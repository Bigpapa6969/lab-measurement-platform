/**
 * FftPlot.tsx — FFT magnitude spectrum plot
 *
 * Renders per-channel FFT data from the AnalysisResponse.
 * A vertical dashed annotation marks the dominant frequency bin.
 * Y-axis can be toggled between linear and log scale.
 */

import Plotly from 'plotly.js';
import { useEffect, useRef, useState } from 'react';
import type { ChannelAnalysisResponse } from '../../types';
import { channelColor, fmtSI } from '../../types';
import { DARK_LAYOUT_BASE } from './WaveformPlot';

interface Props {
  channelResults:  ChannelAnalysisResponse[];
  activeChannelIds: string[];
  height?:         number;
}

export default function FftPlot({ channelResults, activeChannelIds, height = 220 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [logScale,   setLogScale]   = useState(false);

  useEffect(() => {
    if (!containerRef.current) return;

    const active = channelResults.filter(ch => activeChannelIds.includes(ch.channel_id));

    const traces: Plotly.Data[] = active.map((ch, i) => ({
      x:    ch.fft_frequencies.map(f => f / 1_000),   // Hz → kHz
      y:    ch.fft_magnitudes,
      type: 'scatter' as const,
      mode: 'lines' as const,
      name: ch.channel_id,
      line: {
        width: 1.5,
        color: channelColor(ch.channel_id, i),
      },
      fill:      'tozeroy' as const,
      fillcolor: `${channelColor(ch.channel_id, i)}18`,   // ~10% opacity fill
      hovertemplate:
        '<b>%{y:.4f} V</b><br>%{x:.4f} kHz<extra>%{fullData.name}</extra>',
    }));

    // Dominant frequency annotations (one per active channel)
    const annotations: Partial<Plotly.Annotations>[] = active.map((ch, i) => ({
      x:          ch.dominant_fft_freq_hz / 1_000,
      y:          1,
      xref:       'x',
      yref:       'paper',
      text:       fmtSI(ch.dominant_fft_freq_hz, 'Hz', 1),
      showarrow:  true,
      arrowhead:  2,
      arrowcolor: channelColor(ch.channel_id, i),
      arrowwidth: 1.5,
      arrowsize:  0.8,
      ax:         0,
      ay:         -24,
      font:       { size: 9, color: channelColor(ch.channel_id, i) },
      bgcolor:    'rgba(0,0,0,0.5)',
      bordercolor: channelColor(ch.channel_id, i),
      borderwidth: 0.5,
      borderpad:   2,
    }));

    const layout: Partial<Plotly.Layout> = {
      ...DARK_LAYOUT_BASE,
      height,
      annotations,
      xaxis: {
        ...DARK_LAYOUT_BASE.xaxis,
        title: { text: 'Frequency (kHz)', font: { size: 10 } },
      },
      yaxis: {
        ...DARK_LAYOUT_BASE.yaxis,
        title: { text: 'Magnitude (V)', font: { size: 10 } },
        type:  logScale ? 'log' : 'linear',
        // Avoid log-scale rendering with zero/negative values
        rangemode: 'tozero',
      },
    };

    const config: Partial<Plotly.Config> = {
      responsive:     true,
      scrollZoom:     true,
      displayModeBar: false,
    };

    Plotly.react(containerRef.current, traces, layout, config);
  }, [channelResults, activeChannelIds, height, logScale]);

  useEffect(() => {
    const el = containerRef.current;
    return () => { if (el) Plotly.purge(el); };
  }, []);

  return (
    <div className="relative">
      {/* Log/Linear toggle */}
      <button
        onClick={() => setLogScale(v => !v)}
        className="absolute top-1 right-2 z-10 text-[10px] font-mono px-1.5 py-0.5
                   bg-scope-hover border border-scope-border rounded text-ink-secondary
                   hover:text-ink-primary transition-colors"
        title="Toggle log/linear Y scale"
      >
        {logScale ? 'LOG' : 'LIN'}
      </button>
      <div
        ref={containerRef}
        style={{ width: '100%', height }}
        className="rounded overflow-hidden"
      />
    </div>
  );
}
