/**
 * SourceSelector.tsx — Data source panel
 *
 * Provides two acquisition modes:
 *   UPLOAD — drag-and-drop / browse for a CSV file
 *   MOCK   — configure a MockOscilloscope waveform in the browser
 *
 * On successful acquisition the parent receives the WaveformDataResponse
 * via the onMeasurementLoaded callback.
 */

import { useCallback, useRef, useState } from 'react';
import type { MockChannelRequest, MockRequest, WaveformType } from '../../types';

interface Props {
  onLoadFromCsv:  (file: File)       => void;
  onLoadFromMock: (req: MockRequest) => void;
  loading:        boolean;
  error:          string | null;
  onClearError:   ()                 => void;
}

type Tab = 'upload' | 'mock';

// ---- Mock form defaults --------------------------------------------------

const DEFAULT_CH: MockChannelRequest = {
  waveform_type: 'sine',
  frequency_hz:  1_000,
  amplitude_v:   1.0,
  offset_v:      0.0,
  duty_cycle:    0.5,
  noise_std:     0.02,
  phase_deg:     0.0,
};

const WAVEFORM_OPTIONS: { value: WaveformType; label: string }[] = [
  { value: 'sine',     label: 'Sine' },
  { value: 'square',   label: 'Square' },
  { value: 'pwm',      label: 'PWM' },
  { value: 'triangle', label: 'Triangle' },
  { value: 'dc',       label: 'DC Rail' },
];

// ---- Sub-components -------------------------------------------------------

function ChannelFields({
  id,
  cfg,
  onChange,
}: {
  id: string;
  cfg: MockChannelRequest;
  onChange: (patch: Partial<MockChannelRequest>) => void;
}) {
  const showDuty = cfg.waveform_type === 'square' || cfg.waveform_type === 'pwm';

  return (
    <div className="space-y-1.5">
      <p className="text-[10px] font-mono font-semibold text-ink-secondary uppercase tracking-widest">
        {id}
      </p>
      <div className="grid grid-cols-2 gap-1.5">
        <div>
          <label className="text-[10px] text-ink-secondary block mb-0.5">Type</label>
          <select
            className="select text-xs py-1"
            value={cfg.waveform_type}
            onChange={e => onChange({ waveform_type: e.target.value as WaveformType })}
          >
            {WAVEFORM_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-[10px] text-ink-secondary block mb-0.5">Frequency (Hz)</label>
          <input
            type="number"
            className="input text-xs py-1"
            value={cfg.frequency_hz}
            min={1}
            step={100}
            disabled={cfg.waveform_type === 'dc'}
            onChange={e => onChange({ frequency_hz: parseFloat(e.target.value) || 1000 })}
          />
        </div>
        <div>
          <label className="text-[10px] text-ink-secondary block mb-0.5">Amplitude (V)</label>
          <input
            type="number"
            className="input text-xs py-1"
            value={cfg.amplitude_v}
            min={0}
            step={0.1}
            onChange={e => onChange({ amplitude_v: parseFloat(e.target.value) || 1 })}
          />
        </div>
        <div>
          <label className="text-[10px] text-ink-secondary block mb-0.5">Offset (V)</label>
          <input
            type="number"
            className="input text-xs py-1"
            value={cfg.offset_v}
            step={0.1}
            onChange={e => onChange({ offset_v: parseFloat(e.target.value) || 0 })}
          />
        </div>
        {showDuty && (
          <div className="col-span-2">
            <label className="text-[10px] text-ink-secondary block mb-0.5">
              Duty Cycle: {Math.round(cfg.duty_cycle * 100)}%
            </label>
            <input
              type="range"
              min={0.05} max={0.95} step={0.05}
              value={cfg.duty_cycle}
              onChange={e => onChange({ duty_cycle: parseFloat(e.target.value) })}
              className="w-full accent-accent h-1.5"
            />
          </div>
        )}
        <div>
          <label className="text-[10px] text-ink-secondary block mb-0.5">Noise σ (V)</label>
          <input
            type="number"
            className="input text-xs py-1"
            value={cfg.noise_std}
            min={0}
            step={0.005}
            onChange={e => onChange({ noise_std: parseFloat(e.target.value) || 0 })}
          />
        </div>
      </div>
    </div>
  );
}

// ---- Main component -------------------------------------------------------

export default function SourceSelector({
  onLoadFromCsv,
  onLoadFromMock,
  loading,
  error,
  onClearError,
}: Props) {
  const [tab,       setTab]       = useState<Tab>('mock');
  const [dragging,  setDragging]  = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  // Mock form state
  const [ch1, setCh1] = useState<MockChannelRequest>({ ...DEFAULT_CH });
  const [ch2, setCh2] = useState<MockChannelRequest>({
    ...DEFAULT_CH,
    waveform_type: 'square',
    frequency_hz:  500,
    amplitude_v:   3.3,
  });
  const [enableCh2,  setEnableCh2]  = useState(true);
  const [sampleRate, setSampleRate] = useState(100_000);
  const [duration,   setDuration]   = useState(0.01);

  // -- Drag-and-drop handlers ----------------------------------------------
  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) onLoadFromCsv(file);
  }, [onLoadFromCsv]);

  const onFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) onLoadFromCsv(file);
    e.target.value = '';
  }, [onLoadFromCsv]);

  // -- Mock acquire --------------------------------------------------------
  const handleAcquire = useCallback(() => {
    const channels: Record<string, MockChannelRequest> = { CH1: ch1 };
    if (enableCh2) channels['CH2'] = ch2;
    onLoadFromMock({
      channels,
      sample_rate_hz: sampleRate,
      duration_s:     duration,
      seed:           42,
    });
  }, [ch1, ch2, enableCh2, sampleRate, duration, onLoadFromMock]);

  return (
    <div className="space-y-2">
      {/* Tabs */}
      <div className="flex gap-0.5 bg-scope-surface rounded p-0.5 border border-scope-border">
        {(['upload', 'mock'] as Tab[]).map(t => (
          <button
            key={t}
            onClick={() => { setTab(t); onClearError(); }}
            className={`flex-1 rounded py-1 text-xs font-medium transition-colors ${
              tab === t
                ? 'bg-accent text-scope-bg'
                : 'text-ink-secondary hover:text-ink-primary'
            }`}
          >
            {t === 'upload' ? '↑ Upload CSV' : '⚙ Mock Gen'}
          </button>
        ))}
      </div>

      {/* Error banner */}
      {error && (
        <div className="flex items-start gap-2 bg-fail/10 border border-fail/30 rounded p-2">
          <span className="text-fail text-[11px] flex-1 font-mono break-all">{error}</span>
          <button onClick={onClearError} className="text-fail hover:text-fail/70 text-sm leading-none shrink-0">✕</button>
        </div>
      )}

      {/* Upload tab */}
      {tab === 'upload' && (
        <div
          onDragOver={e => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          onClick={() => fileRef.current?.click()}
          className={`
            flex flex-col items-center justify-center gap-2 rounded border-2 border-dashed
            cursor-pointer transition-colors p-6 text-center
            ${dragging
              ? 'border-accent bg-accent/5 text-accent'
              : 'border-scope-border text-ink-secondary hover:border-accent/50 hover:text-ink-primary'}
          `}
        >
          <span className="text-2xl">📂</span>
          <p className="text-xs">
            Drop a CSV file here<br />
            <span className="text-[10px] text-ink-muted">
              Rigol · Tektronix · LTspice · Generic
            </span>
          </p>
          <button className="btn-secondary text-xs px-3 py-1 mt-1">Browse…</button>
          <input
            ref={fileRef}
            type="file"
            accept=".csv,.txt,.tsv"
            className="hidden"
            onChange={onFileChange}
          />
        </div>
      )}

      {/* Mock generator tab */}
      {tab === 'mock' && (
        <div className="space-y-3">
          <ChannelFields id="CH1" cfg={ch1} onChange={p => setCh1(c => ({ ...c, ...p }))} />

          {/* CH2 toggle */}
          <div className="flex items-center gap-2">
            <input
              id="ch2-toggle"
              type="checkbox"
              checked={enableCh2}
              onChange={e => setEnableCh2(e.target.checked)}
              className="accent-accent"
            />
            <label htmlFor="ch2-toggle" className="text-[10px] font-mono text-ink-secondary cursor-pointer">
              Enable CH2
            </label>
          </div>

          {enableCh2 && (
            <ChannelFields id="CH2" cfg={ch2} onChange={p => setCh2(c => ({ ...c, ...p }))} />
          )}

          {/* Acquisition parameters */}
          <div className="grid grid-cols-2 gap-1.5 pt-1 border-t border-scope-border">
            <div>
              <label className="text-[10px] text-ink-secondary block mb-0.5">Sample Rate (Sa/s)</label>
              <input
                type="number"
                className="input text-xs py-1"
                value={sampleRate}
                min={1000}
                step={10000}
                onChange={e => setSampleRate(parseInt(e.target.value) || 100_000)}
              />
            </div>
            <div>
              <label className="text-[10px] text-ink-secondary block mb-0.5">Duration (s)</label>
              <input
                type="number"
                className="input text-xs py-1"
                value={duration}
                min={0.001}
                step={0.001}
                onChange={e => setDuration(parseFloat(e.target.value) || 0.01)}
              />
            </div>
          </div>

          <button
            className="btn-primary w-full"
            onClick={handleAcquire}
            disabled={loading}
          >
            {loading ? (
              <span className="flex items-center gap-1.5">
                <span className="inline-block w-3 h-3 border-2 border-scope-bg/40
                                 border-t-scope-bg rounded-full animate-spin" />
                Acquiring…
              </span>
            ) : '▶  Acquire'}
          </button>
        </div>
      )}
    </div>
  );
}
