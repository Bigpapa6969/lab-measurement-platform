/**
 * useAnalysis.ts — Analysis execution and result state
 *
 * Accepts an AnalysisRequest (built by the UI) and manages the async call
 * to /analysis/run, exposing the result as typed state.
 */

import { useCallback, useState } from 'react';
import api, { ApiError } from '../services/api';
import type { AnalysisRequest, AnalysisResponse } from '../types';

interface AnalysisState {
  analysis:    AnalysisResponse | null;
  loading:     boolean;
  error:       string | null;
  runAnalysis: (req: AnalysisRequest) => Promise<void>;
  clearError:  ()                     => void;
  reset:       ()                     => void;
}

export function useAnalysis(): AnalysisState {
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [loading,  setLoading]  = useState(false);
  const [error,    setError]    = useState<string | null>(null);

  const runAnalysis = useCallback(async (req: AnalysisRequest) => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.runAnalysis(req);
      setAnalysis(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Analysis failed — check the backend logs.');
    } finally {
      setLoading(false);
    }
  }, []);

  const clearError = useCallback(() => setError(null), []);

  const reset = useCallback(() => {
    setAnalysis(null);
    setError(null);
  }, []);

  return { analysis, loading, error, runAnalysis, clearError, reset };
}
