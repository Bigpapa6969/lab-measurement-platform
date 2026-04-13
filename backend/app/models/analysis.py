"""
models/analysis.py — Analysis request/response schemas
========================================================
These models bridge the HTTP layer and the analysis_engine service.

Data flow:
    HTTP JSON  →  AnalysisRequest (Pydantic)
                  ↓
                  api/routes/analysis.py  converts to engine types
                  ↓
                  analysis_engine.WaveformMetrics (dataclass)
                  ↓
                  _metrics_to_response()  converts back to Pydantic
                  ↓
    HTTP JSON  ←  AnalysisResponse (Pydantic)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class LimitSpecRequest(BaseModel):
    """
    A single pass/fail specification applied to one metric.

    At least one of ``min_value`` / ``max_value`` should be set.
    Both None is valid but results in a NOT_TESTED verdict for that spec.
    """
    name: str = Field(
        ...,
        description=(
            "Metric name to check.  Case-insensitive.  Recognised names: "
            "v_min, v_max, v_peak_to_peak, v_pp, v_ripple, v_mean, v_dc, "
            "v_rms, v_rms_ac, avg_power_w, frequency, frequency_hz, period_s, "
            "duty_cycle, duty_cycle_pct, rise_time_s, fall_time_s, dominant_fft_freq_hz"
        ),
    )
    unit: str = Field(default="", description="Display unit (informational only)")
    min_value: Optional[float] = Field(default=None, description="Lower bound (inclusive)")
    max_value: Optional[float] = Field(default=None, description="Upper bound (inclusive)")


class AnalysisRequest(BaseModel):
    """
    Request body for ``POST /analysis/run``.

    Identifies a previously uploaded measurement and configures what to check.
    """
    measurement_id: str = Field(..., description="ID returned by /measurements/upload or /measurements/mock")
    channel_ids: list[str] = Field(
        default=[],
        description="Channels to analyse.  Empty list = analyse all channels in the measurement.",
    )
    load_resistance_ohms: float = Field(
        default=50.0,
        gt=0,
        description="Reference impedance for average power calculation [Ω]",
    )
    limit_specs: list[LimitSpecRequest] = Field(
        default=[],
        description="Pass/fail limit specifications.  Empty = report metrics only, no verdict.",
    )


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class LimitResultResponse(BaseModel):
    """Result of one limit spec check."""
    spec_name: str
    unit: str
    min_value: Optional[float]
    max_value: Optional[float]
    measured_value: float
    status: str = Field(..., description="'PASS', 'FAIL', or 'NOT_TESTED'")


class ChannelAnalysisResponse(BaseModel):
    """
    Complete analysis output for a single waveform channel.

    All float fields that could not be computed (e.g., rise_time_s on a DC
    signal) are ``null`` / ``None``.
    """
    channel_id: str

    # ---- Voltage statistics ----
    v_min: float = Field(..., description="Minimum sample [V]")
    v_max: float = Field(..., description="Maximum sample [V]")
    v_peak_to_peak: float = Field(..., description="v_max − v_min [V]")
    v_mean: float = Field(..., description="Mean (DC offset) [V]")
    v_rms: float = Field(..., description="True RMS [V]")
    v_rms_ac: float = Field(..., description="AC-coupled RMS [V]")

    # ---- Power ----
    avg_power_w: float = Field(..., description="V_rms² / R [W]")
    load_resistance_ohms: float

    # ---- Frequency ----
    frequency_hz: float = Field(..., description="Zero-crossing frequency estimate [Hz]")
    period_s: float = Field(..., description="1 / frequency_hz [s]")
    dominant_fft_freq_hz: float = Field(..., description="Highest FFT magnitude bin [Hz]")

    # ---- Shape ----
    duty_cycle_pct: Optional[float] = Field(None, description="% time above mid-level")
    rise_time_s: Optional[float] = Field(None, description="10%→90% rise time [s]")
    fall_time_s: Optional[float] = Field(None, description="90%→10% fall time [s]")

    # ---- FFT (for plotting) ----
    fft_frequencies: list[float] = Field(..., description="Frequency axis [Hz]")
    fft_magnitudes: list[float] = Field(..., description="Magnitude spectrum [V]")

    # ---- Limit results ----
    limit_results: list[LimitResultResponse] = Field(default=[])
    overall_verdict: str = Field(..., description="'PASS', 'FAIL', or 'NOT_TESTED'")


class AnalysisResponse(BaseModel):
    """Top-level response from ``POST /analysis/run``."""
    analysis_id: str
    measurement_id: str
    channels: list[ChannelAnalysisResponse]
    analyzed_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
