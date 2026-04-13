/**
 * useWaveform.ts — Measurement state and loading logic
 *
 * Encapsulates all API calls that produce a WaveformDataResponse, exposing
 * a consistent loading/error/data triple regardless of the source.
 */

import { useCallback, useState } from 'react';
import api, { ApiError } from '../services/api';
import type { MockRequest, WaveformDataResponse } from '../types';

interface WaveformState {
  measurement:   WaveformDataResponse | null;
  loading:       boolean;
  error:         string | null;
  loadFromMock:  (req: MockRequest)     => Promise<void>;
  loadFromCsv:   (file: File)           => Promise<void>;
  clearError:    ()                     => void;
  reset:         ()                     => void;
}

export function useWaveform(): WaveformState {
  const [measurement, setMeasurement] = useState<WaveformDataResponse | null>(null);
  const [loading,     setLoading]     = useState(false);
  const [error,       setError]       = useState<string | null>(null);

  const _wrap = useCallback(async (fn: () => Promise<WaveformDataResponse>) => {
    setLoading(true);
    setError(null);
    try {
      const data = await fn();
      setMeasurement(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Unexpected error — is the backend running?');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadFromMock = useCallback(
    (req: MockRequest) => _wrap(() => api.generateMock(req)),
    [_wrap],
  );

  const loadFromCsv = useCallback(
    (file: File) => _wrap(() => api.uploadCsv(file)),
    [_wrap],
  );

  const clearError = useCallback(() => setError(null), []);

  const reset = useCallback(() => {
    setMeasurement(null);
    setError(null);
  }, []);

  return { measurement, loading, error, loadFromMock, loadFromCsv, clearError, reset };
}
