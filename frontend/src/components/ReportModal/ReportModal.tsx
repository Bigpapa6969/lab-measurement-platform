/**
 * ReportModal.tsx — PDF report configuration dialog
 *
 * Step 4 stub: The form captures config and hands it to the parent.
 * When Step 4 is complete the parent's onGenerate callback will POST
 * to /reports/generate and trigger a blob download.
 */

import { useState } from 'react';
import type { ReportConfig } from '../../types';

interface Props {
  analysisId: string;
  onGenerate: (cfg: ReportConfig) => void;
  onClose:    () => void;
  loading:    boolean;
}

export default function ReportModal({ analysisId, onGenerate, onClose, loading }: Props) {
  const [title,         setTitle]         = useState('Waveform Analysis Report');
  const [engineerName,  setEngineerName]  = useState('');
  const [projectRef,    setProjectRef]    = useState('');
  const [includeWave,   setIncludeWave]   = useState(true);
  const [includeFft,    setIncludeFft]    = useState(true);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onGenerate({
      analysis_id:           analysisId,
      title,
      engineer_name:         engineerName,
      project_ref:           projectRef,
      include_waveform_plot: includeWave,
      include_fft_plot:      includeFft,
    });
  };

  return (
    /* Backdrop */
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-scope-bg/80 backdrop-blur-sm"
      onClick={e => e.target === e.currentTarget && onClose()}
    >
      <div className="panel w-full max-w-md mx-4 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-scope-border">
          <h2 className="text-sm font-semibold text-ink-primary">Generate PDF Report</h2>
          <button onClick={onClose} className="text-ink-secondary hover:text-ink-primary">✕</button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-4 space-y-3">
          <div>
            <label className="text-xs text-ink-secondary block mb-1">Report Title</label>
            <input
              className="input"
              value={title}
              onChange={e => setTitle(e.target.value)}
              required
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-ink-secondary block mb-1">Engineer Name</label>
              <input
                className="input"
                placeholder="Optional"
                value={engineerName}
                onChange={e => setEngineerName(e.target.value)}
              />
            </div>
            <div>
              <label className="text-xs text-ink-secondary block mb-1">Project / Ref</label>
              <input
                className="input"
                placeholder="Optional"
                value={projectRef}
                onChange={e => setProjectRef(e.target.value)}
              />
            </div>
          </div>

          {/* Plot toggles */}
          <div className="flex gap-4 pt-1">
            {[
              { id: 'wave', label: 'Waveform plot', val: includeWave, set: setIncludeWave },
              { id: 'fft',  label: 'FFT spectrum',  val: includeFft,  set: setIncludeFft  },
            ].map(({ id, label, val, set }) => (
              <label key={id} className="flex items-center gap-1.5 cursor-pointer text-xs text-ink-secondary">
                <input
                  type="checkbox"
                  checked={val}
                  onChange={e => set(e.target.checked)}
                  className="accent-accent"
                />
                {label}
              </label>
            ))}
          </div>

          {/* Analysis ID (read-only info) */}
          <div className="bg-scope-surface rounded p-2">
            <p className="text-[10px] text-ink-muted">Analysis ID</p>
            <p className="text-[11px] font-mono text-ink-secondary truncate">{analysisId}</p>
          </div>

          {/* Actions */}
          <div className="flex gap-2 pt-1">
            <button type="button" className="btn-secondary flex-1" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn-primary flex-1" disabled={loading}>
              {loading ? (
                <span className="flex items-center gap-1.5 justify-center">
                  <span className="inline-block w-3 h-3 border-2 border-scope-bg/40 border-t-scope-bg rounded-full animate-spin" />
                  Generating…
                </span>
              ) : '↓  Generate PDF'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
