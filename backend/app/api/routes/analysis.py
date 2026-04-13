"""
routes/analysis.py — Waveform analysis endpoints
==================================================

Endpoints
---------
POST /analysis/run
    Run the signal analysis engine on a stored measurement.
    Accepts channel selection and optional pass/fail limit specs.
    Returns AnalysisResponse with per-channel metrics and a verdict.

GET /analysis/{analysis_id}
    Retrieve a previously computed analysis result.
"""
from __future__ import annotations

import logging
from uuid import uuid4

import numpy as np
from fastapi import APIRouter, Depends

from app.api.dependencies import get_store
from app.api.store import InMemoryStore
from app.core.exceptions import (
    AnalysisError,
    AnalysisNotFoundError,
    ChannelNotFoundError,
    MeasurementNotFoundError,
)
from app.models.analysis import (
    AnalysisRequest,
    AnalysisResponse,
    ChannelAnalysisResponse,
    LimitResultResponse,
)
from app.services.analysis_engine import (
    LimitSpec,
    WaveformMetrics,
    analyze_waveform,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------


def _build_limit_specs(request: AnalysisRequest) -> list[LimitSpec]:
    """Convert Pydantic LimitSpecRequest list → engine LimitSpec list."""
    return [
        LimitSpec(
            name=spec.name,
            unit=spec.unit,
            min_value=spec.min_value,
            max_value=spec.max_value,
        )
        for spec in request.limit_specs
    ]


def _metrics_to_response(
    channel_id: str,
    metrics: WaveformMetrics,
) -> ChannelAnalysisResponse:
    """
    Convert an engine ``WaveformMetrics`` dataclass → API ``ChannelAnalysisResponse``.

    FFT arrays are downsampled to at most 2048 points for efficient JSON
    serialisation; the frontend only needs enough resolution to render a
    readable spectrum.
    """
    # Downsample FFT arrays for the response (keep every N-th bin if too long)
    fft_freqs = metrics.fft_frequencies
    fft_mags = metrics.fft_magnitudes
    max_fft_bins = 2048
    if len(fft_freqs) > max_fft_bins:
        step = len(fft_freqs) // max_fft_bins
        fft_freqs = fft_freqs[::step]
        fft_mags = fft_mags[::step]

    limit_results = [
        LimitResultResponse(
            spec_name=r.spec.name,
            unit=r.spec.unit,
            min_value=r.spec.min_value,
            max_value=r.spec.max_value,
            measured_value=r.measured_value,
            status=r.status.value,
        )
        for r in metrics.limit_results
    ]

    return ChannelAnalysisResponse(
        channel_id=channel_id,
        v_min=metrics.v_min,
        v_max=metrics.v_max,
        v_peak_to_peak=metrics.v_peak_to_peak,
        v_mean=metrics.v_mean,
        v_rms=metrics.v_rms,
        v_rms_ac=metrics.v_rms_ac,
        avg_power_w=metrics.avg_power_w,
        load_resistance_ohms=metrics.load_resistance_ohms,
        frequency_hz=metrics.frequency_hz,
        period_s=metrics.period_s,
        dominant_fft_freq_hz=metrics.dominant_fft_freq_hz,
        duty_cycle_pct=metrics.duty_cycle_pct,
        rise_time_s=metrics.rise_time_s,
        fall_time_s=metrics.fall_time_s,
        fft_frequencies=fft_freqs.tolist(),
        fft_magnitudes=fft_mags.tolist(),
        limit_results=limit_results,
        overall_verdict=metrics.overall_verdict.value,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/run", response_model=AnalysisResponse, summary="Run signal analysis")
def run_analysis(
    body: AnalysisRequest,
    store: InMemoryStore = Depends(get_store),
) -> AnalysisResponse:
    """
    Run the signal analysis engine on a stored measurement.

    **Workflow:**
    1. Fetch the measurement identified by ``measurement_id``.
    2. For each requested channel (or all channels if ``channel_ids`` is empty):
       a. Convert stored lists → NumPy arrays.
       b. Call ``analyze_waveform()`` with the provided load resistance and limit specs.
       c. Convert ``WaveformMetrics`` → ``ChannelAnalysisResponse``.
    3. Persist the result and return it with a new ``analysis_id``.

    **Computed metrics per channel:**
    v_min, v_max, v_peak_to_peak, v_mean, v_rms, v_rms_ac, avg_power_w,
    frequency_hz, period_s, dominant_fft_freq_hz, duty_cycle_pct,
    rise_time_s, fall_time_s, plus a single-sided FFT spectrum.

    **Limit checking:**
    Provide ``limit_specs`` to get a PASS/FAIL verdict on any metric.
    """
    # 1. Resolve the measurement
    measurement = store.get_measurement(body.measurement_id)
    if measurement is None:
        raise MeasurementNotFoundError(body.measurement_id)

    # 2. Determine which channels to analyse
    channel_ids = body.channel_ids if body.channel_ids else measurement.channel_ids

    # 3. Build engine-level limit specs once (shared across all channels)
    limit_specs = _build_limit_specs(body)

    # 4. Analyse each channel
    channel_results: list[ChannelAnalysisResponse] = []

    for ch_id in channel_ids:
        ch_data = measurement.get_channel(ch_id)
        if ch_data is None:
            raise ChannelNotFoundError(ch_id, body.measurement_id)

        time_s = np.array(ch_data.time_s, dtype=np.float64)
        voltage_v = np.array(ch_data.voltage_v, dtype=np.float64)

        try:
            metrics: WaveformMetrics = analyze_waveform(
                time=time_s,
                voltage=voltage_v,
                load_resistance_ohms=body.load_resistance_ohms,
                limit_specs=limit_specs if limit_specs else None,
            )
        except ValueError as exc:
            raise AnalysisError(
                f"Channel '{ch_id}' in measurement '{body.measurement_id}': {exc}"
            ) from exc

        channel_results.append(_metrics_to_response(ch_id, metrics))
        logger.info(
            "run_analysis: %s | freq=%.1f Hz | Vpp=%.4f V | verdict=%s",
            ch_id,
            metrics.frequency_hz,
            metrics.v_peak_to_peak,
            metrics.overall_verdict.value,
        )

    # 5. Persist and return
    analysis_id = str(uuid4())
    response = AnalysisResponse(
        analysis_id=analysis_id,
        measurement_id=body.measurement_id,
        channels=channel_results,
    )
    store.save_analysis(analysis_id, response)
    return response


@router.get(
    "/{analysis_id}",
    response_model=AnalysisResponse,
    summary="Retrieve a stored analysis result",
)
def get_analysis(
    analysis_id: str,
    store: InMemoryStore = Depends(get_store),
) -> AnalysisResponse:
    """Retrieve a previously computed analysis result by its ID."""
    result = store.get_analysis(analysis_id)
    if result is None:
        raise AnalysisNotFoundError(analysis_id)
    return result
