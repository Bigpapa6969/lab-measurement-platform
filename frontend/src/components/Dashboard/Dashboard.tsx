/**
 * Dashboard.tsx — Primary application layout
 *
 * Three-column layout:
 *   Left (260px)  : source selector + channel toggles
 *   Center (flex) : waveform plot + FFT spectrum (stacked)
 *   Right (280px) : analysis sidebar + report button
 *
 * This component is a pure layout shell — no business logic lives here.
 * All state is owned by App.tsx and passed down via props.
 */

import type { ReactNode } from 'react';
import type { AnalysisResponse, ChannelData, WaveformDataResponse } from '../../types';
import { channelColor } from '../../types';
import FftPlot from '../Plot/FftPlot';
import WaveformPlot from '../Plot/WaveformPlot';

interface Props {
  measurement:      WaveformDataResponse | null;
  analysis:         AnalysisResponse | null;
  activeChannelIds: string[];
  onToggleChannel:  (id: string) => void;
  leftPanel:        ReactNode;
  rightPanel:       ReactNode;
}

// ---- Channel toggle pill --------------------------------------------------

function ChannelPill({
  channel,
  active,
  onToggle,
}: {
  channel: ChannelData;
  active:  boolean;
  onToggle: () => void;
}) {
  const color = channelColor(channel.channel_id, 0);
  return (
    <button
      onClick={onToggle}
      className={`
        flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-mono font-semibold
        border transition-all duration-150
        ${active
          ? 'border-transparent text-scope-bg'
          : 'border-scope-border text-ink-secondary hover:text-ink-primary hover:border-scope-hover'}
      `}
      style={active ? { backgroundColor: color, boxShadow: `0 0 8px ${color}55` } : {}}
    >
      ● {channel.channel_id}
      <span className="font-normal opacity-70">
        {(channel.sample_rate_hz / 1_000).toFixed(0)} kSa/s
      </span>
    </button>
  );
}

// ---- Empty state placeholder ----------------------------------------------

function EmptyPlot({ label }: { label: string }) {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-2 text-ink-muted">
      <span className="text-3xl opacity-30">〰</span>
      <p className="text-xs font-mono">{label}</p>
    </div>
  );
}

// ---- Main layout ----------------------------------------------------------

export default function Dashboard({
  measurement,
  analysis,
  activeChannelIds,
  onToggleChannel,
  leftPanel,
  rightPanel,
}: Props) {
  const activeChannels = measurement?.channels.filter(
    ch => activeChannelIds.includes(ch.channel_id),
  ) ?? [];

  const activeAnalysisChannels =
    analysis?.channels.filter(ch => activeChannelIds.includes(ch.channel_id)) ?? [];

  return (
    <div className="flex flex-col h-screen select-none">

      {/* ── Header ─────────────────────────────────────────────────────── */}
      <header className="flex items-center justify-between px-4 py-2
                         bg-scope-panel border-b border-scope-border shrink-0">
        {/* Brand */}
        <div className="flex items-center gap-2">
          <span className="text-accent font-mono font-bold tracking-tight text-sm">
            LAB<span className="text-ink-secondary">·</span>MSR
          </span>
          <span className="text-[10px] text-ink-muted font-mono hidden sm:block">
            Automated Lab Measurement Platform
          </span>
        </div>

        {/* Channel toggles (only when data is loaded) */}
        <div className="flex items-center gap-2">
          {measurement?.channels.map(ch => (
            <ChannelPill
              key={ch.channel_id}
              channel={ch}
              active={activeChannelIds.includes(ch.channel_id)}
              onToggle={() => onToggleChannel(ch.channel_id)}
            />
          ))}
        </div>

        {/* Status indicator */}
        <div className="flex items-center gap-1.5 text-[10px] font-mono">
          {measurement ? (
            <>
              <span className="w-1.5 h-1.5 rounded-full bg-pass animate-pulse" />
              <span className="text-pass">
                {measurement.source.toUpperCase()} · {measurement.channels.length}CH
              </span>
            </>
          ) : (
            <>
              <span className="w-1.5 h-1.5 rounded-full bg-ink-muted" />
              <span className="text-ink-muted">NO DATA</span>
            </>
          )}
        </div>
      </header>

      {/* ── Body ───────────────────────────────────────────────────────── */}
      <div className="flex flex-1 min-h-0">

        {/* Left panel */}
        <aside className="w-64 shrink-0 bg-scope-surface border-r border-scope-border
                          overflow-y-auto p-3 space-y-2">
          <p className="panel-header -mx-3 -mt-3 px-3 pt-3 mb-2">Data Source</p>
          {leftPanel}
        </aside>

        {/* Center — plots */}
        <main className="flex-1 flex flex-col min-w-0 bg-scope-bg">

          {/* Waveform plot */}
          <div className="flex-1 min-h-0 border-b border-scope-border relative">
            <div className="absolute top-2 left-3 z-10 flex items-center gap-1.5">
              <span className="text-[10px] font-mono text-ink-muted uppercase tracking-widest">
                Time Domain
              </span>
              {measurement && (
                <span className="text-[10px] font-mono text-ink-muted">
                  · {measurement.channels[0]?.n_samples.toLocaleString()} Sa
                </span>
              )}
            </div>

            {measurement && activeChannels.length > 0 ? (
              <WaveformPlot
                channels={activeChannels}
                activeChannelIds={activeChannelIds}
                height={undefined}   // fills container via CSS
              />
            ) : (
              <EmptyPlot label="Acquire data to display waveform" />
            )}
          </div>

          {/* FFT plot */}
          <div className="h-52 shrink-0 relative">
            <div className="absolute top-2 left-3 z-10">
              <span className="text-[10px] font-mono text-ink-muted uppercase tracking-widest">
                FFT Spectrum
              </span>
            </div>

            {activeAnalysisChannels.length > 0 ? (
              <FftPlot
                channelResults={activeAnalysisChannels}
                activeChannelIds={activeChannelIds}
                height={208}
              />
            ) : (
              <EmptyPlot label="Run analysis to display FFT" />
            )}
          </div>
        </main>

        {/* Right panel */}
        <aside className="w-72 shrink-0 bg-scope-surface border-l border-scope-border
                          overflow-y-auto p-2">
          {rightPanel}
        </aside>
      </div>
    </div>
  );
}
