"""
Unit tests for analysis_engine.py.

Run with:  pytest backend/tests/test_analysis_engine.py -v

All tests use synthetically generated signals so there are no fixture files
or external dependencies — the test suite is fully self-contained.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from app.services.analysis_engine import (
    LimitSpec,
    PassFailStatus,
    WaveformMetrics,
    analyze_waveform,
    apply_limits,
    compute_duty_cycle,
    compute_fft,
    compute_frequency,
    compute_rise_fall_time,
    compute_v_statistics,
)

# ---------------------------------------------------------------------------
# Fixtures / signal factories
# ---------------------------------------------------------------------------

FS = 100_000          # sample rate [Hz]
N = 10_000            # number of samples
T_END = N / FS        # total capture time [s]


def _make_time() -> np.ndarray:
    return np.linspace(0, T_END, N, endpoint=False)


def _sine(freq_hz: float = 1_000.0, amplitude: float = 1.0, offset: float = 0.0) -> np.ndarray:
    t = _make_time()
    return offset + amplitude * np.sin(2 * np.pi * freq_hz * t)


def _square(
    freq_hz: float = 1_000.0,
    amplitude: float = 1.0,
    duty: float = 0.5,
    noise_std: float = 0.0,
) -> np.ndarray:
    """Ideal square wave with optional Gaussian noise."""
    t = _make_time()
    from scipy import signal as sp_signal
    wave = amplitude * (sp_signal.square(2 * np.pi * freq_hz * t, duty=duty) + 1.0) / 2.0
    if noise_std:
        rng = np.random.default_rng(42)
        wave = wave + rng.normal(0, noise_std, size=wave.shape)
    return wave


def _pwm(duty: float = 0.3, freq_hz: float = 1_000.0) -> np.ndarray:
    return _square(freq_hz=freq_hz, amplitude=3.3, duty=duty)


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


class TestValidation:
    def test_mismatched_shapes_raise(self):
        t = _make_time()
        v = _sine()[: N - 1]
        with pytest.raises(ValueError, match="same shape"):
            analyze_waveform(t, v)

    def test_too_few_samples_raise(self):
        t = np.linspace(0, 1e-3, 4)
        v = np.zeros(4)
        with pytest.raises(ValueError, match="samples"):
            analyze_waveform(t, v)

    def test_nan_in_voltage_raises(self):
        t = _make_time()
        v = _sine()
        v[500] = float("nan")
        with pytest.raises(ValueError, match="NaN"):
            analyze_waveform(t, v)

    def test_nonmonotonic_time_raises(self):
        t = _make_time().copy()
        t[100] = t[50]  # duplicate timestamp
        with pytest.raises(ValueError, match="monotonically"):
            analyze_waveform(t, _sine())


# ---------------------------------------------------------------------------
# Voltage statistics
# ---------------------------------------------------------------------------


class TestVStatistics:
    def test_sine_rms(self):
        """RMS of A·sin = A/√2."""
        A = 2.5
        stats = compute_v_statistics(_sine(amplitude=A))
        expected_rms = A / math.sqrt(2)
        assert abs(stats["v_rms"] - expected_rms) < 1e-3

    def test_sine_peak_to_peak(self):
        A = 1.8
        stats = compute_v_statistics(_sine(amplitude=A))
        assert abs(stats["v_peak_to_peak"] - 2 * A) < 0.01

    def test_dc_offset_captured_in_mean(self):
        offset = 2.5
        stats = compute_v_statistics(_sine(offset=offset))
        assert abs(stats["v_mean"] - offset) < 0.01

    def test_ac_rms_removes_dc(self):
        """AC RMS of A·sin + DC = A/√2 regardless of DC offset."""
        A = 1.0
        offset = 5.0
        v = _sine(amplitude=A, offset=offset)
        stats = compute_v_statistics(v)
        expected_ac_rms = A / math.sqrt(2)
        assert abs(stats["v_rms_ac"] - expected_ac_rms) < 1e-3

    def test_power_calculation(self):
        """P = V_rms² / R."""
        A = 2.0
        R = 50.0
        stats = compute_v_statistics(_sine(amplitude=A), load_resistance_ohms=R)
        expected_power = (A / math.sqrt(2)) ** 2 / R
        assert abs(stats["avg_power_w"] - expected_power) < 1e-4


# ---------------------------------------------------------------------------
# Frequency estimation
# ---------------------------------------------------------------------------


class TestFrequency:
    @pytest.mark.parametrize("freq", [100, 500, 1_000, 5_000, 10_000])
    def test_sine_frequency_accuracy(self, freq):
        """Zero-crossing frequency estimate must be within 1 % of true value."""
        t = _make_time()
        v = np.sin(2 * np.pi * freq * t)
        f_est, _ = compute_frequency(t, v)
        assert abs(f_est - freq) / freq < 0.01, f"Expected ~{freq} Hz, got {f_est:.2f} Hz"

    def test_dc_signal_returns_zero(self):
        t = _make_time()
        v = np.full(N, 3.3)
        f_est, period = compute_frequency(t, v)
        assert f_est == 0.0
        assert period == 0.0

    def test_noisy_sine_within_2pct(self):
        rng = np.random.default_rng(0)
        freq = 1_000.0
        t = _make_time()
        v = np.sin(2 * np.pi * freq * t) + rng.normal(0, 0.15, N)
        f_est, _ = compute_frequency(t, v)
        assert abs(f_est - freq) / freq < 0.02


# ---------------------------------------------------------------------------
# FFT
# ---------------------------------------------------------------------------


class TestFFT:
    def test_dominant_frequency_sine(self):
        freq = 2_500.0
        t = _make_time()
        v = np.sin(2 * np.pi * freq * t)
        freqs, mags, dom_freq = compute_fft(t, v)
        assert abs(dom_freq - freq) / freq < 0.01

    def test_magnitude_at_dominant_bin_close_to_amplitude(self):
        """For a pure sine of amplitude A, the dominant FFT bin should ≈ A."""
        A = 3.0
        freq = 1_000.0
        t = _make_time()
        v = A * np.sin(2 * np.pi * freq * t)
        _, mags, dom_freq = compute_fft(t, v)
        dom_idx = int(np.argmax(mags))
        # Hann window introduces a small amplitude error; allow 5 %
        assert abs(mags[dom_idx] - A) / A < 0.05

    def test_output_array_length(self):
        t = _make_time()
        v = _sine()
        freqs, mags, _ = compute_fft(t, v)
        assert len(freqs) == N // 2 + 1
        assert len(mags) == N // 2 + 1


# ---------------------------------------------------------------------------
# Duty cycle
# ---------------------------------------------------------------------------


class TestDutyCycle:
    @pytest.mark.parametrize("duty", [0.1, 0.25, 0.5, 0.75, 0.9])
    def test_pwm_duty_cycle_accuracy(self, duty):
        """Duty cycle estimate must be within 2 percentage points of true value."""
        v = _pwm(duty=duty)
        dc = compute_duty_cycle(v)
        assert dc is not None
        assert abs(dc - duty * 100.0) < 2.0, f"Expected {duty*100:.0f}%, got {dc:.2f}%"

    def test_dc_signal_returns_none(self):
        v = np.full(N, 1.8)
        dc = compute_duty_cycle(v)
        assert dc is None


# ---------------------------------------------------------------------------
# Rise / fall time
# ---------------------------------------------------------------------------


class TestRiseFallTime:
    def test_square_wave_has_valid_rise_fall(self):
        t = _make_time()
        v = _square(freq_hz=1_000.0, amplitude=3.3, noise_std=0.02)
        rise, fall = compute_rise_fall_time(t, v)
        assert rise is not None and rise > 0
        assert fall is not None and fall > 0

    def test_dc_signal_returns_none(self):
        t = _make_time()
        v = np.full(N, 2.5)
        rise, fall = compute_rise_fall_time(t, v)
        assert rise is None
        assert fall is None

    def test_rise_time_positive_and_less_than_half_period(self):
        freq = 1_000.0
        t = _make_time()
        v = _square(freq_hz=freq, amplitude=1.0)
        rise, _ = compute_rise_fall_time(t, v)
        half_period = 1.0 / (2 * freq)
        assert rise is not None
        assert 0 < rise < half_period


# ---------------------------------------------------------------------------
# Limit checking
# ---------------------------------------------------------------------------


class TestLimitChecking:
    def test_pass_within_bounds(self):
        t = _make_time()
        v = _sine(freq_hz=1_000.0, amplitude=1.0)
        metrics = analyze_waveform(t, v)
        specs = [LimitSpec("frequency_hz", unit="Hz", min_value=990.0, max_value=1_010.0)]
        results = apply_limits(metrics, specs)
        assert results[0].status == PassFailStatus.PASS

    def test_fail_outside_bounds(self):
        t = _make_time()
        v = _sine(freq_hz=1_000.0, amplitude=1.0)
        metrics = analyze_waveform(t, v)
        specs = [LimitSpec("v_rms", unit="V", max_value=0.5)]
        results = apply_limits(metrics, specs)
        assert results[0].status == PassFailStatus.FAIL

    def test_unknown_spec_name_is_not_tested(self):
        t = _make_time()
        v = _sine()
        metrics = analyze_waveform(t, v)
        specs = [LimitSpec("nonexistent_metric")]
        results = apply_limits(metrics, specs)
        assert results[0].status == PassFailStatus.NOT_TESTED

    def test_overall_verdict_fail_when_any_spec_fails(self):
        t = _make_time()
        v = _sine(freq_hz=1_000.0, amplitude=1.0)
        metrics = analyze_waveform(
            t,
            v,
            limit_specs=[
                LimitSpec("frequency_hz", unit="Hz", min_value=990.0, max_value=1_010.0),
                LimitSpec("v_rms", unit="V", max_value=0.5),  # will FAIL
            ],
        )
        assert metrics.overall_verdict == PassFailStatus.FAIL

    def test_overall_verdict_pass_when_all_specs_pass(self):
        t = _make_time()
        A = 1.0
        v = _sine(freq_hz=1_000.0, amplitude=A)
        expected_rms = A / math.sqrt(2)
        metrics = analyze_waveform(
            t,
            v,
            limit_specs=[
                LimitSpec("v_rms", unit="V", min_value=expected_rms * 0.95, max_value=expected_rms * 1.05),
                LimitSpec("frequency_hz", unit="Hz", min_value=990.0, max_value=1_010.0),
            ],
        )
        assert metrics.overall_verdict == PassFailStatus.PASS

    def test_overall_verdict_not_tested_when_no_specs(self):
        t = _make_time()
        v = _sine()
        metrics = analyze_waveform(t, v)
        assert metrics.overall_verdict == PassFailStatus.NOT_TESTED


# ---------------------------------------------------------------------------
# Smoke test — full pipeline
# ---------------------------------------------------------------------------


class TestFullPipeline:
    def test_analyze_waveform_returns_waveform_metrics(self):
        t = _make_time()
        v = _sine(freq_hz=1_000.0, amplitude=2.0)
        result = analyze_waveform(t, v)
        assert isinstance(result, WaveformMetrics)

    def test_summary_dict_is_json_serialisable(self):
        """All values in summary_dict must be Python scalars (not numpy types)."""
        import json
        t = _make_time()
        v = _pwm(duty=0.4)
        metrics = analyze_waveform(t, v)
        # json.dumps will raise TypeError on numpy scalars
        json_str = json.dumps(metrics.summary_dict())
        assert len(json_str) > 0

    def test_pwm_full_analysis(self):
        duty = 0.3
        freq = 2_000.0
        t = _make_time()
        v = _pwm(duty=duty, freq_hz=freq)
        metrics = analyze_waveform(t, v)
        assert abs(metrics.frequency_hz - freq) / freq < 0.02
        assert metrics.duty_cycle_pct is not None
        assert abs(metrics.duty_cycle_pct - duty * 100) < 3.0
