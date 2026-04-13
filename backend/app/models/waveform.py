"""
models/waveform.py — Waveform data schemas
===========================================
Pydantic models for the waveform data layer.
These are the request/response contracts for the /measurements endpoints.

Import path for the WaveformType enum:
    from app.models.waveform import WaveformType
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, field_validator

# Re-export WaveformType from where it lives so the rest of the app has
# a single stable import location.
from app.services.ingestion.mock_oscilloscope import ChannelConfig, WaveformType

__all__ = [
    "WaveformType",
    "ChannelData",
    "WaveformDataResponse",
    "MockChannelRequest",
    "MockRequest",
]


# ---------------------------------------------------------------------------
# Wire-format models (what flows over HTTP)
# ---------------------------------------------------------------------------


class ChannelData(BaseModel):
    """
    A single channel's time-series data as serialisable lists.

    ``time_s`` and ``voltage_v`` are parallel arrays of equal length.
    """
    channel_id: str = Field(..., examples=["CH1"])
    time_s: list[float] = Field(..., description="Time vector [s]")
    voltage_v: list[float] = Field(..., description="Voltage samples [V]")
    sample_rate_hz: float = Field(..., description="Inferred sample rate [Hz]")
    unit: str = Field(default="V", description="Voltage unit (V or A for current probes)")
    n_samples: int = Field(..., description="Number of samples (len of arrays)")

    @field_validator("voltage_v")
    @classmethod
    def arrays_must_match_time(cls, v: list[float], info: object) -> list[float]:
        # Pydantic v2 info object; access other fields via info.data
        data = getattr(info, "data", {})
        time_s = data.get("time_s")
        if time_s is not None and len(v) != len(time_s):
            raise ValueError(
                f"time_s (len={len(time_s)}) and voltage_v (len={len(v)}) must have equal length."
            )
        return v


class WaveformDataResponse(BaseModel):
    """
    Complete measurement record returned by /measurements/upload and /measurements/mock.

    The ``measurement_id`` is used as a key for subsequent /analysis/run calls.
    """
    measurement_id: str
    source: str = Field(..., description="'csv', 'mock', or 'visa'")
    channels: list[ChannelData]
    metadata: dict[str, str] = Field(default_factory=dict)
    captured_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )

    @property
    def channel_ids(self) -> list[str]:
        return [ch.channel_id for ch in self.channels]

    def get_channel(self, channel_id: str) -> Optional[ChannelData]:
        for ch in self.channels:
            if ch.channel_id == channel_id:
                return ch
        return None


# ---------------------------------------------------------------------------
# Mock generation request
# ---------------------------------------------------------------------------


class MockChannelRequest(BaseModel):
    """
    Configuration for a single mock channel.

    Maps directly onto ``ChannelConfig`` in the mock oscilloscope service.
    """
    waveform_type: WaveformType = WaveformType.SINE
    frequency_hz: float = Field(default=1_000.0, gt=0, description="Fundamental frequency [Hz]")
    amplitude_v: float = Field(default=1.0, ge=0, description="Peak amplitude [V]")
    offset_v: float = Field(default=0.0, description="DC offset [V]")
    duty_cycle: float = Field(default=0.5, ge=0.0, le=1.0, description="Duty cycle [0–1]; SQUARE/PWM only")
    noise_std: float = Field(default=0.02, ge=0.0, description="Noise std deviation [V]")
    phase_deg: float = Field(default=0.0, description="Initial phase [degrees]")

    def to_channel_config(self) -> ChannelConfig:
        """Convert this request model to the service-layer ChannelConfig dataclass."""
        return ChannelConfig(
            waveform_type=self.waveform_type,
            frequency_hz=self.frequency_hz,
            amplitude_v=self.amplitude_v,
            offset_v=self.offset_v,
            duty_cycle=self.duty_cycle,
            noise_std=self.noise_std,
            phase_deg=self.phase_deg,
        )


class MockRequest(BaseModel):
    """
    Request body for ``POST /measurements/mock``.

    Provide one ``MockChannelRequest`` per channel you want generated.
    """
    channels: dict[str, MockChannelRequest] = Field(
        default={
            "CH1": MockChannelRequest(waveform_type=WaveformType.SINE, frequency_hz=1_000.0),
            "CH2": MockChannelRequest(waveform_type=WaveformType.SQUARE, frequency_hz=500.0, amplitude_v=3.3),
        },
        description="Map of channel name → channel config",
    )
    sample_rate_hz: float = Field(default=100_000.0, gt=0, description="Sample rate [Hz]")
    duration_s: float = Field(default=0.01, gt=0, description="Acquisition window [s]")
    seed: Optional[int] = Field(default=42, description="RNG seed for noise (null = non-deterministic)")
