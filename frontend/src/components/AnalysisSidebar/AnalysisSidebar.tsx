/**
 * AnalysisSidebar.tsx — Metrics display, limit spec management, and verdict
 *
 * Sections
 * --------
 * 1. Run Analysis button  — triggers backend analysis call
 * 2. Metrics table        — all computed values for the selected channel tab
 * 3. Limit Specs          — add/remove pass-fail bounds
 * 4. Overall verdict      — PASS / FAIL / NOT_TESTED badge
 * 5. Generate PDF         — opens ReportModal (Step 4)
 */

import { useState } from 'react';
import type {
  AnalysisResponse,
  ChannelAnalysisResponse,
  LimitResultResponse,
  LimitSpecRequest,
  Verdict,
  WaveformDataResponse,
} from '../../types';
import { fmtSI } from '../../types';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Props {
  measurement:     WaveformDataResponse | null;
  analysis:        AnalysisResponse | null;
  activeChannelIds: string[];
  loadResistance:  number;
  limitSpecs:      LimitSpecRequest[];
  onRunAnalysis:   () => void;
  onAddLimit:      (spec: LimitSpecRequest) => void;
  onRemoveLimit:   (index: number) => void;
  onOpenReport:    () => void;
  loading:         boolean;
  error:           string | null;
}

// ---------------------------------------------------------------------------
// Metric definitions
// ---------------------------------------------------------------------------

interface MetricDef {
  label: string;
  key:   keyof ChannelAnalysisResponse;
  unit:  string;
  fmt?:  (v: number) => string;
}

const METRICS: MetricDef[] = [
  { label: 'Frequency',    key: 'frequency_hz',      unit: 'Hz' },
  { label: 'Period',       key: 'period_s',           unit: 's' },
  { label: 'FFT Peak',     key: 'dominant_fft_freq_hz', unit: 'Hz' },
  { label: 'V peak-peak',  key: 'v_peak_to_peak',     unit: 'V' },
  { label: 'V RMS',        key: 'v_rms',              unit: 'V' },
  { label: 'V RMS (AC)',   key: 'v_rms_ac',           unit: 'V' },
  { label: 'V mean',       key: 'v_mean',             unit: 'V' },
  { label: 'V min',        key: 'v_min',              unit: 'V' },
  { label: 'V max',        key: 'v_max',              unit: 'V' },
  { label: 'Avg Power',    key: 'avg_power_w',        unit: 'W' },
  { label: 'Duty Cycle',   key: 'duty_cycle_pct',     unit: '%', fmt: v => `${v.toFixed(2)} %` },
  { label: 'Rise Time',    key: 'rise_time_s',        unit: 's' },
  { label: 'Fall Time',    key: 'fall_time_s',        unit: 's' },
];

const LIMIT_METRIC_OPTIONS = [
  { value: 'frequency_hz',        label: 'Frequency (Hz)' },
  { value: 'v_peak_to_peak',      label: 'V peak-to-peak' },
  { value: 'v_ripple',            label: 'V ripple (alias for Vpp)' },
  { value: 'v_rms',               label: 'V RMS' },
  { value: 'v_rms_ac',            label: 'V RMS AC' },
  { value: 'v_mean',              label: 'V mean / DC' },
  { value: 'duty_cycle_pct',      label: 'Duty Cycle (%)' },
  { value: 'rise_time_s',         label: 'Rise Time (s)' },
  { value: 'fall_time_s',         label: 'Fall Time (s)' },
  { value: 'avg_power_w',         label: 'Avg Power (W)' },
  { value: 'dominant_fft_freq_hz', label: 'FFT Dominant Freq (Hz)' },
];

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function VerdictBadge({ verdict }: { verdict: Verdict }) {
  const map: Record<Verdict, { cls: string; icon: string; label: string }> = {
    PASS:       { cls: 'bg-pass/15 border-pass/40 text-pass',         icon: '✓', label: 'PASS' },
    FAIL:       { cls: 'bg-fail/15 border-fail/40 text-fail',         icon: '✗', label: 'FAIL' },
    NOT_TESTED: { cls: 'bg-scope-hover border-scope-border text-ink-secondary', icon: '○', label: 'NOT TESTED' },
  };
  const s = map[verdict];
  return (
    <div className={`flex items-center justify-center gap-2 rounded border py-2 font-mono font-bold text-sm ${s.cls}`}>
      <span className="text-base leading-none">{s.icon}</span>
      <span>{s.label}</span>
    </div>
  );
}

function LimitResultRow({ r }: { r: LimitResultResponse }) {
  const cls =
    r.status === 'PASS'  ? 'badge-pass' :
    r.status === 'FAIL'  ? 'badge-fail' :
                           'badge-not-tested';
  const bounds: string[] = [];
  if (r.min_value !== null) bounds.push(`≥ ${r.min_value}`);
  if (r.max_value !== null) bounds.push(`≤ ${r.max_value}`);

  return (
    <div className="metric-row text-[11px]">
      <div>
        <span className="metric-label">{r.spec_name}</span>
        {bounds.length > 0 && (
          <span className="text-ink-muted ml-1.5">[{bounds.join(', ')} {r.unit}]</span>
        )}
      </div>
      <div className="flex items-center gap-1.5">
        <span className="metric-value">{fmtSI(r.measured_value, r.unit)}</span>
        <span className={cls}>{r.status}</span>
      </div>
    </div>
  );
}

function AddLimitForm({ onAdd }: { onAdd: (s: LimitSpecRequest) => void }) {
  const [name, setName] = useState(LIMIT_METRIC_OPTIONS[0].value);
  const [unit, setUnit] = useState('');
  const [min,  setMin]  = useState('');
  const [max,  setMax]  = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onAdd({
      name,
      unit:      unit || '',
      min_value: min !== '' ? parseFloat(min) : null,
      max_value: max !== '' ? parseFloat(max) : null,
    });
    setMin(''); setMax('');
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-1.5 pt-2 border-t border-scope-border">
      <p className="text-[10px] font-mono text-ink-secondary uppercase tracking-widest">Add Limit</p>
      <select
        className="select text-xs py-1"
        value={name}
        onChange={e => setName(e.target.value)}
      >
        {LIMIT_METRIC_OPTIONS.map(o => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
      <div className="grid grid-cols-3 gap-1">
        <input
          type="number" placeholder="Min"
          className="input text-xs py-1" step="any"
          value={min} onChange={e => setMin(e.target.value)}
        />
        <input
          type="number" placeholder="Max"
          className="input text-xs py-1" step="any"
          value={max} onChange={e => setMax(e.target.value)}
        />
        <input
          type="text" placeholder="Unit"
          className="input text-xs py-1"
          value={unit} onChange={e => setUnit(e.target.value)}
        />
      </div>
      <button type="submit" className="btn-secondary w-full text-xs py-1">
        + Add Spec
      </button>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function AnalysisSidebar({
  measurement,
  analysis,
  activeChannelIds,
  loadResistance,
  limitSpecs,
  onRunAnalysis,
  onAddLimit,
  onRemoveLimit,
  onOpenReport,
  loading,
  error,
}: Props) {
  // Which channel's results to display when multiple are active
  const [selectedChId, setSelectedChId] = useState<string | null>(null);

  const chResult =
    analysis?.channels.find(
      c => c.channel_id === (selectedChId ?? activeChannelIds[0])
    ) ?? analysis?.channels[0];

  const canAnalyse = !!measurement && !loading;

  return (
    <div className="flex flex-col h-full overflow-y-auto gap-2">

      {/* ── Run Analysis ───────────────────────────────────────────────── */}
      <div className="panel">
        <div className="panel-header">Analysis</div>
        <div className="p-2 space-y-2">
          <button
            className="btn-primary w-full"
            onClick={onRunAnalysis}
            disabled={!canAnalyse}
          >
            {loading ? (
              <span className="flex items-center gap-1.5">
                <span className="inline-block w-3 h-3 border-2 border-scope-bg/40
                                 border-t-scope-bg rounded-full animate-spin" />
                Running…
              </span>
            ) : '▶  Run Analysis'}
          </button>

          {/* Load resistance input */}
          <div className="flex items-center gap-2">
            <label className="text-[10px] text-ink-secondary whitespace-nowrap">R load (Ω)</label>
            <span className="text-xs font-mono text-ink-primary">{loadResistance}</span>
          </div>

          {error && (
            <p className="text-[11px] text-fail font-mono break-all">{error}</p>
          )}
        </div>
      </div>

      {/* ── Active limit specs ─────────────────────────────────────────── */}
      <div className="panel">
        <div className="panel-header">Limit Specs ({limitSpecs.length})</div>
        <div className="px-2 pb-2">
          {limitSpecs.length === 0 && (
            <p className="text-[11px] text-ink-muted py-1.5">No limits defined — all metrics pass unchecked.</p>
          )}
          {limitSpecs.map((s, i) => (
            <div key={i} className="metric-row">
              <span className="text-[11px] font-mono text-ink-secondary">{s.name}</span>
              <div className="flex items-center gap-1">
                <span className="text-[10px] text-ink-muted">
                  {s.min_value != null ? `≥${s.min_value}` : ''}
                  {s.min_value != null && s.max_value != null ? ' ' : ''}
                  {s.max_value != null ? `≤${s.max_value}` : ''}
                  {s.unit ? ` ${s.unit}` : ''}
                </span>
                <button
                  onClick={() => onRemoveLimit(i)}
                  className="text-ink-muted hover:text-fail text-xs ml-1"
                  title="Remove spec"
                >✕</button>
              </div>
            </div>
          ))}
          <AddLimitForm onAdd={onAddLimit} />
        </div>
      </div>

      {/* ── Metrics table ─────────────────────────────────────────────── */}
      {analysis && chResult && (
        <div className="panel">
          {/* Channel selector tabs (only if >1 channel) */}
          {analysis.channels.length > 1 && (
            <div className="flex gap-0.5 p-1 border-b border-scope-border">
              {analysis.channels.map(ch => (
                <button
                  key={ch.channel_id}
                  onClick={() => setSelectedChId(ch.channel_id)}
                  className={`flex-1 rounded py-0.5 text-xs font-mono transition-colors ${
                    (selectedChId ?? analysis.channels[0].channel_id) === ch.channel_id
                      ? 'bg-scope-hover text-ink-primary'
                      : 'text-ink-secondary hover:text-ink-primary'
                  }`}
                >
                  {ch.channel_id}
                </button>
              ))}
            </div>
          )}
          {analysis.channels.length === 1 && (
            <div className="panel-header">
              Metrics ��� {chResult.channel_id}
            </div>
          )}

          <div className="px-2 py-1">
            {METRICS.map(m => {
              const raw = chResult[m.key] as number | null;
              const val = raw === null || raw === undefined
                ? 'N/A'
                : m.fmt
                  ? m.fmt(raw)
                  : fmtSI(raw, m.unit);
              return (
                <div key={m.key} className="metric-row">
                  <span className="metric-label">{m.label}</span>
                  <span className="metric-value">{val}</span>
                </div>
              );
            })}
          </div>

          {/* Limit check results */}
          {chResult.limit_results.length > 0 && (
            <div className="px-2 pb-1 border-t border-scope-border mt-1">
              <p className="text-[10px] font-mono text-ink-secondary uppercase tracking-widest py-1.5">
                Limit Results
              </p>
              {chResult.limit_results.map((r, i) => (
                <LimitResultRow key={i} r={r} />
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Verdict ───────────────────────────────────────────────────── */}
      {chResult && (
        <div className="panel p-2">
          <VerdictBadge verdict={chResult.overall_verdict} />
        </div>
      )}

      {/* ── Generate Report ────────────────────────────────────────────── */}
      <div className="panel p-2">
        <button
          className="btn-secondary w-full"
          disabled={!analysis}
          onClick={onOpenReport}
          title={!analysis ? 'Run analysis first' : 'Generate PDF report'}
        >
          ↓  Generate PDF Report
        </button>
      </div>
    </div>
  );
}
