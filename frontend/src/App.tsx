/**
 * App.tsx — Root component
 *
 * Owns all application state:
 *   - measurement   : loaded waveform data
 *   - analysis      : computed metrics + limit results
 *   - activeChannels: which channels are visible in the plots
 *   - limitSpecs    : user-defined pass/fail bounds
 *   - loadResistance: reference impedance for power calculation
 *   - showReport    : whether the PDF config modal is open
 *
 * Passes state and callbacks down to Dashboard, which distributes them
 * to the left/right panels and plots.
 */

import { useCallback, useState } from 'react';
import AnalysisSidebar from './components/AnalysisSidebar/AnalysisSidebar';
import Dashboard from './components/Dashboard/Dashboard';
import ReportModal from './components/ReportModal/ReportModal';
import SourceSelector from './components/SourceSelector/SourceSelector';
import { useAnalysis } from './hooks/useAnalysis';
import { useWaveform } from './hooks/useWaveform';
import api from './services/api';
import type { LimitSpecRequest, MockRequest, ReportConfig } from './types';

export default function App() {
  // ---- Data / analysis state --------------------------------------------
  const {
    measurement, loading: waveLoading, error: waveError,
    loadFromMock, loadFromCsv, clearError: clearWaveError, reset: resetWave,
  } = useWaveform();

  const {
    analysis, loading: analysisLoading, error: analysisError,
    runAnalysis, clearError: clearAnalysisError, reset: resetAnalysis,
  } = useAnalysis();

  // ---- UI state ----------------------------------------------------------
  const [activeChannelIds, setActiveChannelIds] = useState<string[]>(['CH1']);
  const [limitSpecs,       setLimitSpecs]       = useState<LimitSpecRequest[]>([]);
  const [loadResistance]                         = useState(50.0);
  const [showReport,       setShowReport]       = useState(false);
  const [reportLoading,    setReportLoading]    = useState(false);

  // ---- Handlers ----------------------------------------------------------

  // When a new measurement loads, auto-activate all its channels
  const handleMeasurementLoaded = useCallback((allChannelIds: string[]) => {
    setActiveChannelIds(allChannelIds);
    resetAnalysis();
  }, [resetAnalysis]);

  const handleLoadFromMock = useCallback(async (req: MockRequest) => {
    await loadFromMock(req);
    handleMeasurementLoaded(Object.keys(req.channels));
  }, [loadFromMock, handleMeasurementLoaded]);

  const handleLoadFromCsv = useCallback(async (file: File) => {
    await loadFromCsv(file);
    // Channel IDs aren't known until the response arrives; useEffect in Dashboard handles it
  }, [loadFromCsv]);

  const handleToggleChannel = useCallback((id: string) => {
    setActiveChannelIds(prev =>
      prev.includes(id)
        ? prev.length > 1 ? prev.filter(c => c !== id) : prev  // keep ≥1 active
        : [...prev, id]
    );
  }, []);

  const handleRunAnalysis = useCallback(() => {
    if (!measurement) return;
    runAnalysis({
      measurement_id:       measurement.measurement_id,
      channel_ids:          [],             // empty = all channels
      load_resistance_ohms: loadResistance,
      limit_specs:          limitSpecs,
    });
  }, [measurement, loadResistance, limitSpecs, runAnalysis]);

  const handleAddLimit = useCallback((spec: LimitSpecRequest) => {
    setLimitSpecs(prev => [...prev, spec]);
  }, []);

  const handleRemoveLimit = useCallback((index: number) => {
    setLimitSpecs(prev => prev.filter((_, i) => i !== index));
  }, []);

  const handleGenerateReport = useCallback(async (cfg: ReportConfig) => {
    setReportLoading(true);
    try {
      // Ask the backend to render the PDF and store it
      const { report_id, download_url } = await api.generateReport(cfg);

      // Fetch the raw PDF bytes via the download endpoint
      const blob = await api.downloadReport(report_id);

      // Trigger a browser "Save As" dialog using a temporary <a> element
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = objectUrl;
      anchor.download = `report-${report_id.slice(0, 8)}.pdf`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(objectUrl);

      setShowReport(false);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      alert(`Report generation failed: ${message}`);
    } finally {
      setReportLoading(false);
    }
  }, []);

  // ---- Auto-activate channels when CSV measurement arrives ---------------
  // (For mock we know the channel IDs upfront; for CSV we discover them here)
  const channelIds = measurement?.channels.map(c => c.channel_id) ?? [];
  if (measurement && channelIds.length > 0 && activeChannelIds.every(id => !channelIds.includes(id))) {
    setActiveChannelIds(channelIds);
  }

  // ---- Render ------------------------------------------------------------

  const leftPanel = (
    <SourceSelector
      onLoadFromCsv={handleLoadFromCsv}
      onLoadFromMock={handleLoadFromMock}
      loading={waveLoading}
      error={waveError}
      onClearError={clearWaveError}
    />
  );

  const rightPanel = (
    <AnalysisSidebar
      measurement={measurement}
      analysis={analysis}
      activeChannelIds={activeChannelIds}
      loadResistance={loadResistance}
      limitSpecs={limitSpecs}
      onRunAnalysis={handleRunAnalysis}
      onAddLimit={handleAddLimit}
      onRemoveLimit={handleRemoveLimit}
      onOpenReport={() => setShowReport(true)}
      loading={analysisLoading}
      error={analysisError}
    />
  );

  return (
    <>
      <Dashboard
        measurement={measurement}
        analysis={analysis}
        activeChannelIds={activeChannelIds}
        onToggleChannel={handleToggleChannel}
        leftPanel={leftPanel}
        rightPanel={rightPanel}
      />

      {showReport && analysis && (
        <ReportModal
          analysisId={analysis.analysis_id}
          onGenerate={handleGenerateReport}
          onClose={() => setShowReport(false)}
          loading={reportLoading}
        />
      )}
    </>
  );
}
