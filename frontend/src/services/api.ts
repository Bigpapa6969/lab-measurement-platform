/**
 * services/api.ts — Typed API client
 *
 * All functions return typed promises and throw ApiError on non-2xx responses.
 * The base URL is read from VITE_API_URL or defaults to '' (uses Vite's proxy).
 *
 * Usage:
 *   const measurement = await api.generateMock(mockRequest);
 *   const analysis    = await api.runAnalysis(analysisRequest);
 */

import type {
  AnalysisRequest,
  AnalysisResponse,
  MockRequest,
  ReportConfig,
  WaveformDataResponse,
} from '../types';

const BASE: string = import.meta.env.VITE_API_URL ?? '';

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

// ---------------------------------------------------------------------------
// Core fetch wrapper
// ---------------------------------------------------------------------------

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      ...(init.body && !(init.body instanceof FormData)
        ? { 'Content-Type': 'application/json' }
        : {}),
      ...init.headers,
    },
  });

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // body wasn't JSON — keep the generic message
    }
    throw new ApiError(res.status, detail);
  }

  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Measurement endpoints
// ---------------------------------------------------------------------------

/** Generate synthetic waveform data via MockOscilloscope. */
export async function generateMock(
  body: MockRequest,
): Promise<WaveformDataResponse> {
  return request<WaveformDataResponse>('/measurements/mock', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/** Upload a CSV/txt file and parse it into a measurement. */
export async function uploadCsv(
  file: File,
): Promise<WaveformDataResponse> {
  const form = new FormData();
  form.append('file', file);
  return request<WaveformDataResponse>('/measurements/upload', {
    method: 'POST',
    body: form,
  });
}

/** Retrieve a stored measurement by ID. */
export async function getMeasurement(
  measurementId: string,
): Promise<WaveformDataResponse> {
  return request<WaveformDataResponse>(`/measurements/${measurementId}`);
}

// ---------------------------------------------------------------------------
// Analysis endpoints
// ---------------------------------------------------------------------------

/** Run the signal analysis engine on a stored measurement. */
export async function runAnalysis(
  body: AnalysisRequest,
): Promise<AnalysisResponse> {
  return request<AnalysisResponse>('/analysis/run', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/** Retrieve a previously computed analysis result. */
export async function getAnalysis(
  analysisId: string,
): Promise<AnalysisResponse> {
  return request<AnalysisResponse>(`/analysis/${analysisId}`);
}

// ---------------------------------------------------------------------------
// Report endpoint (Step 4 — stub)
// ---------------------------------------------------------------------------

/** Generate a PDF report for a completed analysis. */
export async function generateReport(
  body: ReportConfig,
): Promise<{ report_id: string; download_url: string; page_count: number }> {
  return request('/reports/generate', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/** Download the generated PDF as a Blob. */
export async function downloadReport(reportId: string): Promise<Blob> {
  const res = await fetch(`${BASE}/reports/${reportId}/download`);
  if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status}`);
  return res.blob();
}

// ---------------------------------------------------------------------------
// Convenience — bundle into a single named export
// ---------------------------------------------------------------------------

const api = {
  generateMock,
  uploadCsv,
  getMeasurement,
  runAnalysis,
  getAnalysis,
  generateReport,
  downloadReport,
};

export default api;
