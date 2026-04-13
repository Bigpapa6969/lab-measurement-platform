"""
mock_oscilloscope.py — Software Mock Oscilloscope
===================================================
Generates realistic, reproducible test waveforms without physical hardware.
Suitable for unit tests, frontend development, and CI pipelines.

Supported waveform types: SINE, SQUARE, PWM, TRIANGLE, DC.
Each channel is configured independently via ``ChannelConfig``.

Usage (instrument interface)::

    config = {
        "CH1": ChannelConfig(waveform_type=WaveformType.SINE, frequency_hz=1000),
        "CH2": ChannelConfig(waveform_type=WaveformType.PWM,  duty_cycle=0.3),
    }
    with MockOscilloscope(channel_configs=config, sample_rate_hz=100_000) as scope:
        t, v = scope.get_waveform("CH1")

Usage (standalone, no connection needed)::

    t, v = MockOscilloscope.generate_waveform(config, sample_rate_hz=100_000,
                                              duration_s=0.01, rng=np.random.default_rng())
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np
import numpy.typing as npt
from scipy import signal as sp_signal

from app.services.ingestion.base_instrument import BaseInstrument, InstrumentError

logger = logging.getLogger(__name__)
FloatArray = npt.NDArray[np.float64]


# ---------------------------------------------------------------------------
# Waveform configuration
# ---------------------------------------------------------------------------


class WaveformType(str, Enum):
    """Signal shape produced by a mock channel."""
    SINE = "sine"
    SQUARE = "square"
    PWM = "pwm"        # Square wave with explicit duty_cycle control
    TRIANGLE = "triangle"
    DC = "dc"


@dataclass
class ChannelConfig:
    """
    Per-channel waveform generation parameters.

    Attributes
    ----------
    waveform_type : WaveformType
    frequency_hz  : Fundamental frequency.  Ignored for DC.
    amplitude_v   : Peak amplitude (half of peak-to-peak swing).
    offset_v      : DC offset added on top of the waveform.
    duty_cycle    : Fraction of period in high state [0–1].
                    Effective only for SQUARE and PWM.
    noise_std     : Std deviation of additive Gaussian noise [V].
                    Models quantisation noise, EMI, amplifier noise.
    phase_deg     : Initial phase offset [degrees].
    """
    waveform_type: WaveformType = WaveformType.SINE
    frequency_hz: float = 1_000.0
    amplitude_v: float = 1.0
    offset_v: float = 0.0
    duty_cycle: float = 0.5     # used for SQUARE / PWM
    noise_std: float = 0.02
    phase_deg: float = 0.0


# ---------------------------------------------------------------------------
# Default channel configs (convenient presets)
# ---------------------------------------------------------------------------

PRESET_POWER_RAIL = ChannelConfig(
    waveform_type=WaveformType.DC,
    amplitude_v=0.0,
    offset_v=3.3,
    noise_std=0.005,
)

PRESET_PWM_SIGNAL = ChannelConfig(
    waveform_type=WaveformType.PWM,
    frequency_hz=20_000.0,
    amplitude_v=3.3,
    duty_cycle=0.4,
    noise_std=0.03,
)

PRESET_SINE_1KHZ = ChannelConfig(
    waveform_type=WaveformType.SINE,
    frequency_hz=1_000.0,
    amplitude_v=1.0,
    noise_std=0.02,
)


# ---------------------------------------------------------------------------
# MockOscilloscope
# ---------------------------------------------------------------------------


class MockOscilloscope(BaseInstrument):
    """
    Software mock of a 4-channel digital storage oscilloscope.

    Generates deterministic waveforms from ``ChannelConfig`` objects.
    The random seed controls noise reproducibility across runs — set it
    to a fixed integer in CI environments.

    Parameters
    ----------
    channel_configs : dict[str, ChannelConfig]
        Maps channel names (``"CH1"`` … ``"CH4"``) to their configurations.
        Channels not in this dict cannot be acquired.
    sample_rate_hz  : float
        Simulated sample rate in Hz.  Default 100 kSa/s.
    duration_s      : float
        Default acquisition window in seconds.
    seed            : int or None
        RNG seed for noise generation.  None → non-deterministic.
    """

    _IDN = "MockInstruments,MockDSO-4CH,SN000001,FW1.0.0"

    def __init__(
        self,
        channel_configs: Optional[dict[str, ChannelConfig]] = None,
        sample_rate_hz: float = 100_000.0,
        duration_s: float = 0.01,
        seed: Optional[int] = 42,
    ) -> None:
        if channel_configs is None:
            channel_configs = {
                "CH1": ChannelConfig(waveform_type=WaveformType.SINE),
                "CH2": ChannelConfig(waveform_type=WaveformType.SQUARE),
            }

        self._channel_configs: dict[str, ChannelConfig] = channel_configs
        self._sample_rate_hz: float = sample_rate_hz
        self._duration_s: float = duration_s
        self._seed: Optional[int] = seed
        self._connected: bool = False

    # ------------------------------------------------------------------
    # BaseInstrument implementation
    # ------------------------------------------------------------------

    def connect(self) -> None:
        self._connected = True
        logger.info("MockOscilloscope: connected (seed=%s)", self._seed)

    def disconnect(self) -> None:
        self._connected = False
        logger.info("MockOscilloscope: disconnected")

    def get_identity(self) -> str:
        return self._IDN

    @property
    def is_connected(self) -> bool:
        return self._connected

    def get_waveform(
        self,
        channel: str,
        n_samples: Optional[int] = None,
    ) -> tuple[FloatArray, FloatArray]:
        """
        Generate and return a waveform for *channel*.

        The returned arrays are always freshly generated (no internal caching)
        but are deterministic for a given seed + channel configuration.

        Parameters
        ----------
        channel   : Channel name, e.g. ``"CH1"``.
        n_samples : Override the number of samples.  None uses the default
                    duration and sample rate set at construction.

        Raises
        ------
        InstrumentError
            If not connected or *channel* is not in ``channel_configs``.
        """
        if not self._connected:
            raise InstrumentError(
                "MockOscilloscope is not connected. "
                "Call connect() or use as a context manager."
            )
        if channel not in self._channel_configs:
            available = ", ".join(sorted(self._channel_configs.keys()))
            raise InstrumentError(
                f"Channel '{channel}' is not configured. "
                f"Available channels: {available}"
            )

        config = self._channel_configs[channel]

        # Per-channel seed: XOR global seed with channel index so CH1/CH2
        # produce independent (but still reproducible) noise patterns.
        channel_index = list(self._channel_configs.keys()).index(channel)
        per_channel_seed = (
            None if self._seed is None else self._seed ^ (channel_index * 0x9E3779B9 & 0xFFFFFFFF)
        )
        rng = np.random.default_rng(per_channel_seed)

        duration = (
            n_samples / self._sample_rate_hz
            if n_samples is not None
            else self._duration_s
        )

        return self.generate_waveform(config, self._sample_rate_hz, duration, rng)

    # ------------------------------------------------------------------
    # Static waveform generator (usable without an instrument instance)
    # ------------------------------------------------------------------

    @staticmethod
    def generate_waveform(
        config: ChannelConfig,
        sample_rate_hz: float,
        duration_s: float,
        rng: np.random.Generator,
    ) -> tuple[FloatArray, FloatArray]:
        """
        Generate a (time, voltage) waveform array pair.

        This is a pure function — all state is passed explicitly.
        Call it in isolation for testing without a MockOscilloscope instance::

            t, v = MockOscilloscope.generate_waveform(
                ChannelConfig(WaveformType.SINE, frequency_hz=1000),
                sample_rate_hz=100_000,
                duration_s=0.01,
                rng=np.random.default_rng(0),
            )

        Parameters
        ----------
        config         : Waveform shape and electrical parameters.
        sample_rate_hz : Samples per second.
        duration_s     : Length of the capture window in seconds.
        rng            : NumPy random Generator for noise (caller-owned).

        Returns
        -------
        (time_s, voltage_v) : tuple[FloatArray, FloatArray]
            Both arrays are 1-D, uniformly spaced, dtype float64.
        """
        n = max(1, int(round(sample_rate_hz * duration_s)))
        time_s: FloatArray = np.linspace(0.0, duration_s, n, endpoint=False, dtype=np.float64)

        phase_rad = np.deg2rad(config.phase_deg)
        omega = 2.0 * np.pi * config.frequency_hz
        wt = omega * time_s + phase_rad

        waveform: WaveformType = config.waveform_type

        if waveform == WaveformType.SINE:
            signal = config.amplitude_v * np.sin(wt)

        elif waveform in (WaveformType.SQUARE, WaveformType.PWM):
            # scipy.signal.square: duty=1.0 → always +1, duty=0.5 → 50%
            raw = sp_signal.square(wt, duty=config.duty_cycle)  # ∈ {-1, +1}
            # Map to [0, amplitude] range (unipolar, like a real PWM rail)
            signal = config.amplitude_v * (raw + 1.0) / 2.0

        elif waveform == WaveformType.TRIANGLE:
            # scipy.signal.sawtooth with width=0.5 → symmetric triangle
            raw = sp_signal.sawtooth(wt, width=0.5)   # ∈ [-1, +1]
            signal = config.amplitude_v * raw

        elif waveform == WaveformType.DC:
            signal = np.zeros(n, dtype=np.float64)

        else:
            raise ValueError(f"Unknown WaveformType: {waveform!r}")

        # Add Gaussian noise, DC offset
        noise = rng.normal(0.0, config.noise_std, size=n) if config.noise_std > 0 else 0.0
        voltage_v: FloatArray = (signal + config.offset_v + noise).astype(np.float64)

        return time_s, voltage_v

    # ------------------------------------------------------------------
    # Convenience: acquire all configured channels at once
    # ------------------------------------------------------------------

    def get_all_waveforms(
        self,
        n_samples: Optional[int] = None,
    ) -> dict[str, tuple[FloatArray, FloatArray]]:
        """
        Acquire waveforms for every configured channel in one call.

        Returns
        -------
        dict[channel_name, (time_s, voltage_v)]
        """
        return {
            ch: self.get_waveform(ch, n_samples=n_samples)
            for ch in self._channel_configs
        }

    @property
    def channel_names(self) -> list[str]:
        """Ordered list of configured channel names."""
        return list(self._channel_configs.keys())
