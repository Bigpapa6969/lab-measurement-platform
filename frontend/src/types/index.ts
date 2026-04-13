/**
 * types/index.ts — TypeScript mirrors of backend Pydantic models
 *
 * Keep these in sync with:
 *   backend/app/models/waveform.py
 *   backend/app/models/analysis.py
 *   backend/app/models/report.py
 */

// ---------------------------------------------------------------------------
// Enums
// ---------------------------------------------------------------------------

export type WaveformType = 'sine' | 'square' | 'pwm' | 'triangle' | 'dc';

export type Verdict = 'PASS' | 'FAIL' | 'NOT_TESTED';

// ---------------------------------------------------------------------------
// Waveform / measurement
// ---------------------------------------------------------------------------

export interface ChannelData {
  channel_id: string;
  time_s: number[];
  voltage_v: number[];
  sample_rate_hz: number;
  unit: string;
  n_samples: number;
}

export interface WaveformDataResponse {
  measurement_id: string;
  source: 'csv' | 'mock' | 'visa';
  channels: ChannelData[];
  metadata: Record<string, string>;
  captured_at: string;
}

// ---------------------------------------------------------------------------
// Mock generation request
// ---------------------------------------------------------------------------

export interface MockChannelRequest {
  waveform_type: WaveformType;
  frequency_hz: number;
  amplitude_v: number;
  offset_v: number;
  duty_cycle: number;
  noise_std: number;
  phase_deg: number;
}

export interface MockRequest {
  channels: Record<string, MockChannelRequest>;
  sample_rate_hz: number;
  duration_s: number;
  seed: number | null;
}

// ---------------------------------------------------------------------------
// Analysis
// ---------------------------------------------------------------------------

export interface LimitSpecRequest {
  name: string;
  unit: string;
  min_value: number | null;
  max_value: number | null;
}

export interface AnalysisRequest {
  measurement_id: string;
  channel_ids: string[];
  load_resistance_ohms: number;
  limit_specs: LimitSpecRequest[];
}

export interface LimitResultResponse {
  spec_name: string;
  unit: string;
  min_value: number | null;
  max_value: number | null;
  measured_value: number;
  status: Verdict;
}

export interface ChannelAnalysisResponse {
  channel_id: string;
  v_min: number;
  v_max: number;
  v_peak_to_peak: number;
  v_mean: number;
  v_rms: number;
  v_rms_ac: number;
  avg_power_w: number;
  load_resistance_ohms: number;
  frequency_hz: number;
  period_s: number;
  dominant_fft_freq_hz: number;
  duty_cycle_pct: number | null;
  rise_time_s: number | null;
  fall_time_s: number | null;
  fft_frequencies: number[];
  fft_magnitudes: number[];
  limit_results: LimitResultResponse[];
  overall_verdict: Verdict;
}

export interface AnalysisResponse {
  analysis_id: string;
  measurement_id: string;
  channels: ChannelAnalysisResponse[];
  analyzed_at: string;
}

// ---------------------------------------------------------------------------
// Report (Step 4 stub)
// ---------------------------------------------------------------------------

export interface ReportConfig {
  analysis_id: string;
  title: string;
  engineer_name: string;
  project_ref: string;
  include_fft_plot: boolean;
  include_waveform_plot: boolean;
}

// ---------------------------------------------------------------------------
// UI-only helpers
// ---------------------------------------------------------------------------

/** Per-channel display colour (matches classic oscilloscope convention). */
export const CHANNEL_COLORS: Record<string, string> = {
  CH1: '#f0c040',
  CH2: '#40c8f0',
  CH3: '#f040a8',
  CH4: '#40e878',
};

export function channelColor(channelId: string, index: number): string {
  return (
    CHANNEL_COLORS[channelId] ??
    ['#f0c040', '#40c8f0', '#f040a8', '#40e878'][index % 4]
  );
}

/** Format a SI-scaled number to a readable string with unit. */
export function fmtSI(value: number | null, unit: string, digits = 4): string {
  if (value === null || value === undefined) return 'N/A';
  const abs = Math.abs(value);
  if (abs === 0) return `0 ${unit}`;
  if (abs >= 1e6)  return `${(value / 1e6).toFixed(digits)} M${unit}`;
  if (abs >= 1e3)  return `${(value / 1e3).toFixed(digits)} k${unit}`;
  if (abs >= 1)    return `${value.toFixed(digits)} ${unit}`;
  if (abs >= 1e-3) return `${(value * 1e3).toFixed(digits)} m${unit}`;
  if (abs >= 1e-6) return `${(value * 1e6).toFixed(digits)} µ${unit}`;
  if (abs >= 1e-9) return `${(value * 1e9).toFixed(digits)} n${unit}`;
  return `${(value * 1e12).toFixed(digits)} p${unit}`;
}
