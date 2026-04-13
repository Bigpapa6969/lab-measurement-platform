/**
 * WaveformPlot.tsx — Interactive time-domain oscilloscope plot
 *
 * Uses Plotly.js directly via useRef + useEffect to avoid the CommonJS
 * module issues that react-plotly.js can trigger in Vite.
 *
 * Plotly.react() is used instead of Plotly.newPlot() so that zoom/pan
 * state is preserved across re-renders when only the data changes.
 */

import Plotly from 'plotly.js';
import { useEffect, useRef } from 'react';
import type { ChannelData } from '../../types';
import { channelColor } from '../../types';

interface Props {
  channels:         ChannelData[];
  activeChannelIds: string[];
  /**
   * Pixel height of the plot container.
   * Pass undefined to let the div fill its CSS-defined height (flex parent).
   */
  height?:          number;
}

// Shared dark-theme layout base — reused by FftPlot as well
export const DARK_LAYOUT_BASE: Partial<Plotly.Layout> = {
  paper_bgcolor: 'transparent',
  plot_bgcolor:  '#0d1520',
  font:          { family: 'JetBrains Mono, monospace', color: '#8b949e', size: 11 },
  margin:        { t: 8, r: 16, b: 44, l: 60 },
  legend: {
    bgcolor:     'rgba(0,0,0,0)',
    bordercolor: 'transparent',
    font:        { size: 11 },
    x: 0.01, y: 0.99,
    xanchor: 'left', yanchor: 'top',
  },
  xaxis: {
    gridcolor:     '#1a2535',
    zerolinecolor: '#1e2d42',
    tickcolor:     '#484f58',
    linecolor:     '#1e2d42',
    showgrid:      true,
    zeroline:      true,
  },
  yaxis: {
    gridcolor:     '#1a2535',
    zerolinecolor: '#1e2d42',
    tickcolor:     '#484f58',
    linecolor:     '#1e2d42',
    showgrid:      true,
    zeroline:      true,
  },
};

const PLOT_CONFIG: Partial<Plotly.Config> = {
  responsive:           true,
  scrollZoom:           true,
  displayModeBar:       true,
  displaylogo:          false,
  modeBarButtonsToRemove: [
    'sendDataToCloud',
    'editInChartStudio',
    'toImage',
  ] as Plotly.ModeBarDefaultButtons[],
};

export default function WaveformPlot({ channels, activeChannelIds, height = 300 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    // Build one trace per active channel
    const traces: Plotly.Data[] = activeChannelIds
      .flatMap((chId, i) => {
        const ch = channels.find(c => c.channel_id === chId);
        if (!ch) return [];

        // Convert time from seconds → milliseconds for human-readable axis
        const x = ch.time_s.map(t => t * 1_000);

        const trace: Plotly.Data = {
          x,
          y:          ch.voltage_v,
          type:       'scattergl',   // WebGL-accelerated for large arrays
          mode:       'lines',
          name:       chId,
          line: {
            width: 1.5,
            color: channelColor(chId, i),
          },
          hovertemplate: '<b>%{y:.4f} V</b><br>%{x:.4f} ms<extra>%{fullData.name}</extra>',
        };
        return [trace];
      });

    const layout: Partial<Plotly.Layout> = {
      ...DARK_LAYOUT_BASE,
      // When height is undefined Plotly uses autosize (fills the container div)
      ...(height !== undefined ? { height } : {}),
      autosize: height === undefined,
      xaxis: {
        ...DARK_LAYOUT_BASE.xaxis,
        title: { text: 'Time (ms)', font: { size: 10 } },
        rangeslider: { visible: false },
      },
      yaxis: {
        ...DARK_LAYOUT_BASE.yaxis,
        title: { text: 'Voltage (V)', font: { size: 10 } },
      },
    };

    if (traces.length === 0) {
      // Render empty placeholder
      Plotly.react(containerRef.current, [], layout, PLOT_CONFIG);
      return;
    }

    Plotly.react(containerRef.current, traces, layout, PLOT_CONFIG);
  }, [channels, activeChannelIds, height]);

  // Cleanup on unmount
  useEffect(() => {
    const el = containerRef.current;
    return () => { if (el) Plotly.purge(el); };
  }, []);

  return (
    <div
      ref={containerRef}
      style={{ width: '100%', height: height ?? '100%' }}
      className="rounded overflow-hidden"
    />
  );
}
