"""
analysis_engine.py — Signal Analysis Engine
============================================

Pure numerical analysis module.  Zero I/O, zero framework dependencies.
All public functions are stateless and accept NumPy arrays.

Primary entry point
-------------------
    metrics = analyze_waveform(time, voltage)

Computed metrics
----------------
    Voltage statistics  : v_min, v_max, v_peak_to_peak, v_mean, v_rms, v_rms_ac
    Power               : avg_power_w  (configurable load resistance)
    Frequency           : zero-crossing method + FFT confirmation
    FFT spectrum        : single-sided magnitude spectrum (for plotting)
    Waveform shape      : duty_cycle_pct, rise_time_s, fall_time_s
    Pass/Fail checking  : apply_limits(metrics, specs) → LimitResult list

Design notes
------------
- All frequency/time calculations assume a uniformly-sampled signal.
  Non-uniform time vectors raise ValueError before analysis begins.
- Noisy signals are handled with Savitzky-Golay smoothing *only* for
  edge-detection purposes; all statistical metrics use the raw signal.
- Functions that cannot produce a meaningful result (e.g., rise time on
  a DC signal) return None rather than raising exceptions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np
import numpy.typing as npt
from scipy import signal as sp_signal
from scipy.fft import rfft, rfftfreq

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

FloatArray = npt.NDArray[np.float64]


# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

_RISE_FALL_LOW_PCT: float = 0.10   # 10 % of swing — start of rise
_RISE_FALL_HIGH_PCT: float = 0.90  # 90 % of swing — end of rise
_MIN_SAMPLES_FOR_ANALYSIS: int = 16
_SAVGOL_WINDOW: int = 11           # Must be odd; used only for edge detection
_SAVGOL_POLY: int = 3


# ---------------------------------------------------------------------------
# Enums & value types
# ---------------------------------------------------------------------------


class PassFailStatus(str, Enum):
    """Tri-state verdict for a single measurement against a specification."""
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_TESTED = "NOT_TESTED"


@dataclass(frozen=True)
class LimitSpec:
    """
    Defines an upper and/or lower bound for one named measurement.

    Either bound may be None (open-ended).  Both None is valid but produces
    a NOT_TESTED result — use it as a placeholder spec.

    Examples
    --------
    >>> ripple_spec = LimitSpec("V_ripple", unit="V", max_value=0.050)
    >>> freq_spec   = LimitSpec("Frequency", unit="Hz", min_value=99.0, max_value=101.0)
    """
    name: str
    unit: str = ""
    min_value: Optional[float] = None
    max_value: Optional[float] = None

    def check(self, measured: float) -> PassFailStatus:
        """Compare *measured* against this spec's bounds."""
        if self.min_value is None and self.max_value is None:
            return PassFailStatus.NOT_TESTED
        if self.min_value is not None and measured < self.min_value:
            return PassFailStatus.FAIL
        if self.max_value is not None and measured > self.max_value:
            return PassFailStatus.FAIL
        return PassFailStatus.PASS


@dataclass
class LimitResult:
    """Pairs a spec with its measured value and the resulting verdict."""
    spec: LimitSpec
    measured_value: float
    status: PassFailStatus

    def __str__(self) -> str:
        bounds = []
        if self.spec.min_value is not None:
            bounds.append(f"min={self.spec.min_value}")
        if self.spec.max_value is not None:
            bounds.append(f"max={self.spec.max_value}")
        bound_str = ", ".join(bounds) or "no bounds"
        return (
            f"{self.spec.name}: {self.measured_value:.6g} {self.spec.unit} "
            f"[{bound_str}] → {self.status.value}"
        )


# ---------------------------------------------------------------------------
# Primary result container
# ---------------------------------------------------------------------------


@dataclass
class WaveformMetrics:
    """
    All computed metrics for a single waveform channel.

    Fields that cannot be determined (e.g., duty cycle on a pure sine,
    rise time on a DC rail) are explicitly set to ``None``.

    The ``fft_frequencies`` and ``fft_magnitudes`` arrays are suitable for
    direct use with Plotly / Matplotlib — single-sided, magnitude in Volts.
    """

    # -- Voltage statistics -------------------------------------------------
    v_min: float
    """Minimum sample value [V]."""

    v_max: float
    """Maximum sample value [V]."""

    v_peak_to_peak: float
    """v_max − v_min [V]."""

    v_mean: float
    """Mean (DC offset) [V]."""

    v_rms: float
    """True (total) RMS [V]."""

    v_rms_ac: float
    """AC-coupled RMS = std(signal) [V]."""

    # -- Power --------------------------------------------------------------
    avg_power_w: float
    """v_rms² / load_resistance_ohms [W]."""

    load_resistance_ohms: float
    """Reference load used for power calculation [Ω]."""

    # -- Frequency ----------------------------------------------------------
    frequency_hz: float
    """Fundamental frequency estimated via zero-crossing method [Hz].
    Returns 0.0 if fewer than two crossings are detected."""

    period_s: float
    """1 / frequency_hz [s].  0.0 when frequency is 0."""

    # -- FFT ----------------------------------------------------------------
    dominant_fft_freq_hz: float
    """Frequency bin with highest magnitude in the FFT [Hz]."""

    fft_frequencies: FloatArray
    """Single-sided frequency axis [Hz], length = N//2 + 1."""

    fft_magnitudes: FloatArray
    """Single-sided magnitude spectrum [V], length = N//2 + 1."""

    # -- Waveform shape -----------------------------------------------------
    duty_cycle_pct: Optional[float]
    """Percentage of period the signal is above its mid-level [%].
    None for non-digital / non-periodic signals."""

    rise_time_s: Optional[float]
    """Mean 10 %→90 % transition time across all detected rising edges [s].
    None if fewer than one clean rising edge is found."""

    fall_time_s: Optional[float]
    """Mean 90 %→10 % transition time across all detected falling edges [s].
    None if fewer than one clean falling edge is found."""

    # -- Limit check results ------------------------------------------------
    limit_results: list[LimitResult] = field(default_factory=list)

    # -- Derived property ---------------------------------------------------
    @property
    def overall_verdict(self) -> PassFailStatus:
        """
        Aggregate pass/fail across all applied limit specs.

        Returns NOT_TESTED when no specs have been applied.
        Returns FAIL as soon as any individual spec fails.
        """
        if not self.limit_results:
            return PassFailStatus.NOT_TESTED
        if any(r.status == PassFailStatus.FAIL for r in self.limit_results):
            return PassFailStatus.FAIL
        return PassFailStatus.PASS

    def summary_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable dict of scalar metrics (excludes arrays)."""
        return {
            "v_min_V": self.v_min,
            "v_max_V": self.v_max,
            "v_peak_to_peak_V": self.v_peak_to_peak,
            "v_mean_V": self.v_mean,
            "v_rms_V": self.v_rms,
            "v_rms_ac_V": self.v_rms_ac,
            "avg_power_W": self.avg_power_w,
            "load_resistance_ohms": self.load_resistance_ohms,
            "frequency_hz": self.frequency_hz,
            "period_s": self.period_s,
            "dominant_fft_freq_hz": self.dominant_fft_freq_hz,
            "duty_cycle_pct": self.duty_cycle_pct,
            "rise_time_s": self.rise_time_s,
            "fall_time_s": self.fall_time_s,
            "overall_verdict": self.overall_verdict.value,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_inputs(time: FloatArray, voltage: FloatArray) -> None:
    """
    Raise ValueError for any input that would corrupt downstream math.

    Checks
    ------
    - Both arrays have the same length.
    - Both arrays have at least ``_MIN_SAMPLES_FOR_ANALYSIS`` samples.
    - No NaN or Inf values in either array.
    - Time vector is monotonically increasing.
    - Sampling interval is uniform to within 1 % tolerance.
    """
    if time.shape != voltage.shape:
        raise ValueError(
            f"time and voltage must have the same shape; "
            f"got time={time.shape}, voltage={voltage.shape}"
        )
    if time.ndim != 1:
        raise ValueError(
            f"Arrays must be 1-D; got ndim={time.ndim}"
        )
    n = len(time)
    if n < _MIN_SAMPLES_FOR_ANALYSIS:
        raise ValueError(
            f"Need at least {_MIN_SAMPLES_FOR_ANALYSIS} samples for analysis; "
            f"got {n}"
        )
    if not np.all(np.isfinite(time)):
        raise ValueError("time array contains NaN or Inf values")
    if not np.all(np.isfinite(voltage)):
        raise ValueError("voltage array contains NaN or Inf values")

    dt = np.diff(time)
    if not np.all(dt > 0):
        raise ValueError("time array must be strictly monotonically increasing")

    dt_mean = dt.mean()
    dt_variation = np.max(np.abs(dt - dt_mean)) / dt_mean
    if dt_variation > 0.01:
        raise ValueError(
            f"Non-uniform sampling detected (max deviation {dt_variation:.1%} "
            f"from mean interval). Resample to a uniform grid before analysis."
        )


def _infer_sample_rate(time: FloatArray) -> float:
    """Return the sample rate in Hz, inferred from the mean time step."""
    return float(1.0 / np.mean(np.diff(time)))


def _smooth_for_edge_detection(voltage: FloatArray) -> FloatArray:
    """
    Apply Savitzky-Golay smoothing to suppress high-frequency noise before
    edge detection.  The raw signal is NOT modified.

    Falls back to the original array if the signal is too short for the
    configured window.
    """
    window = min(_SAVGOL_WINDOW, len(voltage) if len(voltage) % 2 == 1 else len(voltage) - 1)
    if window < 5:
        return voltage.copy()
    return sp_signal.savgol_filter(voltage, window_length=window, polyorder=_SAVGOL_POLY)


def _find_signal_levels(voltage: FloatArray) -> tuple[float, float]:
    """
    Estimate stable HIGH and LOW logic levels via histogram analysis.

    Uses the two tallest histogram peaks (bi-modal assumption, suited for
    square/PWM waveforms).  Falls back to 5th / 95th percentiles for
    sinusoidal or arbitrary signals where the distribution is not bi-modal.

    Returns
    -------
    (low_level, high_level) : tuple[float, float]
        Estimated stable LOW and HIGH voltage levels.
    """
    # Build a voltage histogram. A square/PWM wave spends most of its time
    # sitting at two distinct levels (HIGH and LOW), so its histogram is
    # bi-modal — two tall spikes with a valley between them.
    hist, bin_edges = np.histogram(voltage, bins=min(100, len(voltage) // 4 + 1))
    bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])

    # Find peaks in the histogram that are at least 10 % of the tallest bar
    # and separated by at least 1/10th of the total bin count.
    # These correspond to the voltage levels where the signal dwells the longest.
    peak_indices, _ = sp_signal.find_peaks(
        hist,
        height=np.max(hist) * 0.1,
        distance=max(1, len(hist) // 10),
    )

    if len(peak_indices) >= 2:
        # Take the two tallest peaks — their bin-centre voltages are our
        # estimated LOW and HIGH rail voltages.
        sorted_peaks = peak_indices[np.argsort(hist[peak_indices])[-2:]]
        low_level = float(bin_centers[sorted_peaks.min()])
        high_level = float(bin_centers[sorted_peaks.max()])
    else:
        # Sine waves and other continuous signals produce a smooth histogram
        # with no clear bi-modal peaks. Use robust percentiles instead:
        # 5th percentile ≈ LOW, 95th percentile ≈ HIGH, trimming outliers.
        low_level = float(np.percentile(voltage, 5))
        high_level = float(np.percentile(voltage, 95))

    return low_level, high_level


def _threshold_crossings(
    signal: FloatArray,
    threshold: float,
    direction: str,
) -> npt.NDArray[np.intp]:
    """
    Return indices of samples immediately *before* a threshold crossing.

    Parameters
    ----------
    signal    : 1-D array
    threshold : crossing level
    direction : ``"rising"`` or ``"falling"``

    Returns
    -------
    indices : 1-D int array
        Each value ``i`` means signal[i] is on one side and signal[i+1]
        is on the other.
    """
    # Boolean mask: True where the sample is above the threshold.
    above = signal > threshold

    if direction == "rising":
        # A rising crossing occurs where sample[i] is below AND sample[i+1]
        # is above. Boolean AND of the inverted mask (below) and the shifted
        # mask (above next sample) gives exactly those transition indices.
        return np.where(~above[:-1] & above[1:])[0]
    elif direction == "falling":
        # A falling crossing is the mirror: above now, below next.
        return np.where(above[:-1] & ~above[1:])[0]
    else:
        raise ValueError(f"direction must be 'rising' or 'falling'; got '{direction}'")


# ---------------------------------------------------------------------------
# Individual metric functions (public — usable standalone)
# ---------------------------------------------------------------------------


def compute_v_statistics(
    voltage: FloatArray,
    load_resistance_ohms: float = 50.0,
) -> dict[str, float]:
    """
    Compute basic voltage and power statistics from a raw voltage array.

    Parameters
    ----------
    voltage : 1-D float array
        Voltage samples [V].
    load_resistance_ohms : float
        Reference impedance for average power calculation [Ω].
        Defaults to 50 Ω (standard RF / oscilloscope input).

    Returns
    -------
    dict with keys:
        v_min, v_max, v_peak_to_peak, v_mean, v_rms, v_rms_ac, avg_power_w
    """
    v_min = float(np.min(voltage))
    v_max = float(np.max(voltage))
    v_mean = float(np.mean(voltage))   # arithmetic mean = DC offset

    # True RMS:  V_rms = sqrt( mean(v²) )
    # This includes both the AC and DC components. Equivalent to the heating
    # value of the waveform — a 1 V RMS AC signal delivers the same power to
    # a resistor as 1 V DC.
    v_rms = float(np.sqrt(np.mean(voltage ** 2)))

    # AC RMS = standard deviation of the signal.
    # std(v) = sqrt( mean( (v - mean(v))² ) ) = sqrt( mean(v²) - mean(v)² )
    # Subtracting the mean removes the DC component, leaving only the
    # time-varying (AC) portion. ddof=0 uses the population formula (divide
    # by N, not N-1) which is correct for a complete waveform window.
    v_rms_ac = float(np.std(voltage, ddof=0))

    # Average power dissipated in a resistive load:  P = V_rms² / R
    # This is the electrical equivalent of the RMS definition — it gives the
    # same power as a DC voltage of magnitude V_rms across resistance R.
    avg_power_w = v_rms ** 2 / load_resistance_ohms

    return {
        "v_min": v_min,
        "v_max": v_max,
        "v_peak_to_peak": v_max - v_min,
        "v_mean": v_mean,
        "v_rms": v_rms,
        "v_rms_ac": v_rms_ac,
        "avg_power_w": avg_power_w,
    }


def compute_frequency(
    time: FloatArray,
    voltage: FloatArray,
) -> tuple[float, float]:
    """
    Estimate fundamental frequency using the mean-level zero-crossing method.

    Positive-going crossings through the signal mean are detected on a
    Savitzky-Golay-smoothed copy of the signal to reject high-frequency noise.
    The mean period is computed from consecutive crossing times.

    Parameters
    ----------
    time    : 1-D float array, uniformly sampled [s]
    voltage : 1-D float array [V]

    Returns
    -------
    (frequency_hz, period_s) : tuple[float, float]
        Both are 0.0 when the signal has fewer than two positive crossings
        (DC signal or single half-cycle captured).
    """
    # Smooth first to suppress noise spikes that would otherwise create
    # false crossings and corrupt the period measurement.
    smoothed = _smooth_for_edge_detection(voltage)
    mean_level = float(np.mean(smoothed))

    # Use positive-going (rising) crossings through the signal mean as the
    # reference point. One rising crossing per cycle → crossing spacing = period.
    # The mean is a robust centre-line that works for sine, square, and PWM.
    rising_idx = _threshold_crossings(smoothed, mean_level, "rising")

    if len(rising_idx) < 2:
        logger.debug(
            "compute_frequency: fewer than 2 zero-crossings found; "
            "returning 0 Hz (signal may be DC or too short)."
        )
        return 0.0, 0.0

    # Sub-sample interpolation: the crossing happens somewhere between sample
    # i and i+1, not exactly at an integer index. Linear interpolation gives
    # a fractional position:
    #   frac = (threshold - v[i]) / (v[i+1] - v[i])
    # which we then map back to a time value. This improves frequency accuracy
    # especially when the sample rate is low relative to the signal frequency.
    crossing_times: list[float] = []
    for i in rising_idx:
        frac = (mean_level - smoothed[i]) / (smoothed[i + 1] - smoothed[i])
        crossing_times.append(float(time[i]) + frac * float(time[i + 1] - time[i]))

    # Each consecutive pair of crossing times gives one period estimate.
    periods = np.diff(crossing_times)

    # IQR (interquartile range) outlier rejection:
    # Real signals can have glitches or partial cycles at the capture boundary
    # that produce wildly different period values. Tukey's fence (1.5 × IQR)
    # discards those without assuming a specific noise distribution.
    # This is the same rule used in box-and-whisker plots to identify outliers.
    q25, q75 = np.percentile(periods, [25, 75])
    iqr = q75 - q25
    valid_periods = periods[
        (periods >= q25 - 1.5 * iqr) & (periods <= q75 + 1.5 * iqr)
    ]

    if len(valid_periods) == 0:
        valid_periods = periods   # fallback: use all

    mean_period = float(np.mean(valid_periods))
    if mean_period <= 0:
        return 0.0, 0.0

    # Frequency is the reciprocal of period: f = 1 / T
    return round(1.0 / mean_period, 6), round(mean_period, 12)


def compute_fft(
    time: FloatArray,
    voltage: FloatArray,
) -> tuple[FloatArray, FloatArray, float]:
    """
    Compute a single-sided magnitude FFT spectrum.

    A Hann window is applied to reduce spectral leakage before the transform.
    The DC bin (index 0) is excluded when searching for the dominant frequency
    so that a large DC offset does not mask the signal's fundamental.

    Parameters
    ----------
    time    : 1-D float array, uniformly sampled [s]
    voltage : 1-D float array [V]

    Returns
    -------
    (frequencies, magnitudes, dominant_frequency_hz)
        frequencies    : 1-D array [Hz], length = N//2 + 1
        magnitudes     : 1-D array [V],  length = N//2 + 1
        dominant_freq  : float [Hz]
    """
    n = len(voltage)
    fs = _infer_sample_rate(time)

    # Hann window: multiply the signal by a bell-shaped curve that tapers to
    # zero at both ends. Without windowing, the FFT assumes the captured
    # segment repeats perfectly end-to-end. When it doesn't (which is almost
    # always), the sharp discontinuity at the edges smears energy across many
    # frequency bins — called "spectral leakage". The Hann window reduces this
    # at the cost of a slight reduction in frequency resolution.
    window = np.hanning(n)

    # Coherent amplitude scaling: multiplying by the window reduces the
    # total signal energy. Dividing the final magnitudes by window.sum()
    # (instead of N) corrects for this so the displayed amplitude is accurate.
    windowed = voltage * window

    # rfft: real-input FFT. Since the input is real-valued, the output is
    # symmetric — rfft returns only the non-redundant first half (N//2 + 1 bins).
    # rfftfreq maps each bin index to its corresponding frequency in Hz.
    spectrum = rfft(windowed)
    frequencies = rfftfreq(n, d=1.0 / fs)

    # Convert complex spectrum to real magnitudes and apply amplitude correction:
    #   magnitudes = (2 / sum(window)) * |spectrum|
    # The factor of 2 compensates for discarding the negative-frequency mirror
    # half of the spectrum (single-sided representation doubles the energy of
    # every bin except DC and Nyquist).
    magnitudes = (2.0 / window.sum()) * np.abs(spectrum)

    # The DC bin (index 0) has no mirror image, so it must NOT be doubled.
    # Undo the ×2 applied above by halving it back.
    magnitudes[0] /= 2

    # Find the highest-energy frequency bin, skipping DC (index 0).
    # A large DC offset would otherwise always win and mask the signal's
    # fundamental — we care about the oscillating component.
    if len(magnitudes) > 1:
        dominant_idx = int(np.argmax(magnitudes[1:]) + 1)
    else:
        dominant_idx = 0
    dominant_freq = float(frequencies[dominant_idx])

    return frequencies.astype(np.float64), magnitudes.astype(np.float64), dominant_freq


def compute_duty_cycle(
    voltage: FloatArray,
    threshold: Optional[float] = None,
) -> Optional[float]:
    """
    Compute the duty cycle as the percentage of samples above a threshold.

    Suitable for square waves, PWM signals, and any bi-level waveform.

    Parameters
    ----------
    voltage   : 1-D float array [V]
    threshold : float, optional
        Decision threshold.  If None, the mid-point between the estimated
        HIGH and LOW signal levels is used automatically.

    Returns
    -------
    duty_cycle_pct : float or None
        Percentage of samples above threshold [0–100 %].
        Returns None if the signal appears to have a single level
        (HIGH == LOW within noise tolerance).
    """
    low_level, high_level = _find_signal_levels(voltage)
    swing = high_level - low_level

    # A swing below 1 nV means the signal is effectively DC — duty cycle
    # is undefined (dividing by swing later would cause divide-by-zero).
    if abs(swing) < 1e-9:
        logger.debug("compute_duty_cycle: signal swing is negligible; returning None.")
        return None

    if threshold is None:
        # Decision threshold = midpoint between LOW and HIGH rails.
        # Any sample above this counts as a logical "1" (HIGH).
        threshold = (low_level + high_level) / 2.0

    # Duty cycle = fraction of time spent in the HIGH state × 100 %.
    # Counting samples above the threshold and dividing by total samples
    # is equivalent to integrating a rectangular pulse waveform over one
    # period: D = t_high / T, where T = total capture window.
    above = np.sum(voltage > threshold)
    return float(above / len(voltage) * 100.0)


def compute_rise_fall_time(
    time: FloatArray,
    voltage: FloatArray,
) -> tuple[Optional[float], Optional[float]]:
    """
    Compute mean rise time and mean fall time using the 10 %/90 % convention.

    Algorithm
    ---------
    1. Estimate HIGH/LOW signal levels via histogram analysis.
    2. Compute 10 % and 90 % thresholds relative to the signal swing.
    3. Smooth signal with Savitzky-Golay to suppress noise-induced false edges.
    4. Find all 10 %→90 % crossings (rising) and 90 %→10 % crossings (falling).
    5. For each valid rising edge: record the time between its 10 % and 90 % crossings.
    6. Return the mean of all valid edge measurements, or None if none are found.

    Parameters
    ----------
    time    : 1-D float array, uniformly sampled [s]
    voltage : 1-D float array [V]

    Returns
    -------
    (rise_time_s, fall_time_s) : tuple of float or None
    """
    low_level, high_level = _find_signal_levels(voltage)
    swing = high_level - low_level

    if abs(swing) < 1e-9:
        return None, None

    # IEEE / IEC standard rise-time convention:
    # Rise time is measured from 10 % to 90 % of the signal swing, not from
    # 0 % to 100 %. This avoids including the slow, noisy tails of the
    # transition and gives a reproducible number independent of noise floor.
    #   thresh_10 = LOW + 10 % × (HIGH − LOW)
    #   thresh_90 = LOW + 90 % × (HIGH − LOW)
    thresh_10 = low_level + _RISE_FALL_LOW_PCT * swing
    thresh_90 = low_level + _RISE_FALL_HIGH_PCT * swing

    smoothed = _smooth_for_edge_detection(voltage)

    def _interpolated_crossing_time(idx: int, level: float) -> float:
        """
        Sub-sample interpolated time at which smoothed[idx → idx+1] crosses level.

        Linear interpolation between two adjacent samples:
            frac  = (level - v[i]) / (v[i+1] - v[i])   ← how far between samples
            t_cross = t[i] + frac × (t[i+1] - t[i])    ← map to time axis
        This gives crossing resolution finer than one sample interval.
        """
        dv = float(smoothed[idx + 1] - smoothed[idx])
        if abs(dv) < 1e-15:
            return float(time[idx])
        frac = (level - float(smoothed[idx])) / dv
        return float(time[idx]) + frac * float(time[idx + 1] - time[idx])

    # --- Rising edges ---
    cross_10_up = _threshold_crossings(smoothed, thresh_10, "rising")
    cross_90_up = _threshold_crossings(smoothed, thresh_90, "rising")
    rise_times: list[float] = []

    for i10 in cross_10_up:
        # Find the first 90 % crossing that follows this 10 % crossing
        candidates = cross_90_up[cross_90_up > i10]
        if len(candidates) == 0:
            continue
        i90 = candidates[0]
        # Sanity check: 90 % crossing must come before the next 10 % crossing
        next_10 = cross_10_up[cross_10_up > i10]
        if len(next_10) > 0 and i90 > next_10[0]:
            continue
        t10 = _interpolated_crossing_time(i10, thresh_10)
        t90 = _interpolated_crossing_time(i90, thresh_90)
        dt = t90 - t10
        if dt > 0:
            rise_times.append(dt)

    # --- Falling edges ---
    cross_90_dn = _threshold_crossings(smoothed, thresh_90, "falling")
    cross_10_dn = _threshold_crossings(smoothed, thresh_10, "falling")
    fall_times: list[float] = []

    for i90 in cross_90_dn:
        candidates = cross_10_dn[cross_10_dn > i90]
        if len(candidates) == 0:
            continue
        i10 = candidates[0]
        next_90 = cross_90_dn[cross_90_dn > i90]
        if len(next_90) > 0 and i10 > next_90[0]:
            continue
        t90 = _interpolated_crossing_time(i90, thresh_90)
        t10 = _interpolated_crossing_time(i10, thresh_10)
        dt = t10 - t90
        if dt > 0:
            fall_times.append(dt)

    rise_time_s = float(np.mean(rise_times)) if rise_times else None
    fall_time_s = float(np.mean(fall_times)) if fall_times else None

    return rise_time_s, fall_time_s


# ---------------------------------------------------------------------------
# Limit checking
# ---------------------------------------------------------------------------


def apply_limits(
    metrics: WaveformMetrics,
    specs: list[LimitSpec],
) -> list[LimitResult]:
    """
    Apply a list of LimitSpecs against a computed WaveformMetrics object.

    The spec's ``name`` field is matched (case-insensitive) against a
    predefined mapping of metric attribute names.

    Parameters
    ----------
    metrics : WaveformMetrics
        Previously computed metrics for a channel.
    specs   : list[LimitSpec]
        Specifications to check.  Unknown names are logged and returned
        as NOT_TESTED.

    Returns
    -------
    results : list[LimitResult]
        One result per spec, in the same order as input.
    """
    _NAME_TO_ATTR: dict[str, str] = {
        "v_min":                "v_min",
        "v_max":                "v_max",
        "v_peak_to_peak":       "v_peak_to_peak",
        "v_pp":                 "v_peak_to_peak",
        "v_ripple":             "v_peak_to_peak",
        "v_mean":               "v_mean",
        "v_dc":                 "v_mean",
        "v_rms":                "v_rms",
        "v_rms_ac":             "v_rms_ac",
        "avg_power_w":          "avg_power_w",
        "frequency":            "frequency_hz",
        "frequency_hz":         "frequency_hz",
        "period_s":             "period_s",
        "duty_cycle":           "duty_cycle_pct",
        "duty_cycle_pct":       "duty_cycle_pct",
        "rise_time_s":          "rise_time_s",
        "fall_time_s":          "fall_time_s",
        "dominant_fft_freq_hz": "dominant_fft_freq_hz",
    }

    results: list[LimitResult] = []
    for spec in specs:
        attr = _NAME_TO_ATTR.get(spec.name.lower().replace(" ", "_"))
        if attr is None:
            logger.warning(
                "apply_limits: unknown spec name '%s'; marking NOT_TESTED.", spec.name
            )
            results.append(
                LimitResult(spec=spec, measured_value=float("nan"), status=PassFailStatus.NOT_TESTED)
            )
            continue

        value = getattr(metrics, attr)
        if value is None:
            logger.debug(
                "apply_limits: metric '%s' is None (not computed); marking NOT_TESTED.", attr
            )
            results.append(
                LimitResult(spec=spec, measured_value=float("nan"), status=PassFailStatus.NOT_TESTED)
            )
            continue

        status = spec.check(float(value))
        results.append(LimitResult(spec=spec, measured_value=float(value), status=status))

    return results


# ---------------------------------------------------------------------------
# Primary entry point
# ---------------------------------------------------------------------------


def analyze_waveform(
    time: FloatArray,
    voltage: FloatArray,
    load_resistance_ohms: float = 50.0,
    limit_specs: Optional[list[LimitSpec]] = None,
) -> WaveformMetrics:
    """
    Run the complete analysis pipeline on a single waveform channel.

    This is the primary public API for the analysis engine.  All individual
    compute_* functions are called in order; results are assembled into a
    single WaveformMetrics object.

    Parameters
    ----------
    time : 1-D float64 array
        Uniformly-spaced time vector [s].
    voltage : 1-D float64 array
        Voltage samples, same length as *time* [V].
    load_resistance_ohms : float
        Reference impedance for average power calculation [Ω].  Default 50 Ω.
    limit_specs : list[LimitSpec], optional
        If provided, each spec is evaluated against the computed metrics and
        the results are stored in ``WaveformMetrics.limit_results``.

    Returns
    -------
    WaveformMetrics
        Fully populated metrics container.

    Raises
    ------
    ValueError
        If the input arrays fail validation (see ``_validate_inputs``).

    Examples
    --------
    >>> import numpy as np
    >>> t = np.linspace(0, 1e-3, 10_000)
    >>> v = 3.3 * np.sin(2 * np.pi * 1_000 * t)
    >>> metrics = analyze_waveform(t, v)
    >>> print(f"{metrics.frequency_hz:.1f} Hz, {metrics.v_rms:.4f} V RMS")
    1000.0 Hz, 2.3335 V RMS
    """
    # 1. Validate inputs — raises ValueError on bad data
    _validate_inputs(time, voltage)

    # 2. Voltage statistics
    v_stats = compute_v_statistics(voltage, load_resistance_ohms)

    # 3. Frequency (zero-crossing method)
    frequency_hz, period_s = compute_frequency(time, voltage)

    # 4. FFT spectrum
    fft_freqs, fft_mags, dominant_fft_freq = compute_fft(time, voltage)

    # 5. Duty cycle
    duty_cycle = compute_duty_cycle(voltage)

    # 6. Rise / fall time
    rise_time_s, fall_time_s = compute_rise_fall_time(time, voltage)

    # 7. Assemble result object
    metrics = WaveformMetrics(
        v_min=v_stats["v_min"],
        v_max=v_stats["v_max"],
        v_peak_to_peak=v_stats["v_peak_to_peak"],
        v_mean=v_stats["v_mean"],
        v_rms=v_stats["v_rms"],
        v_rms_ac=v_stats["v_rms_ac"],
        avg_power_w=v_stats["avg_power_w"],
        load_resistance_ohms=load_resistance_ohms,
        frequency_hz=frequency_hz,
        period_s=period_s,
        dominant_fft_freq_hz=dominant_fft_freq,
        fft_frequencies=fft_freqs,
        fft_magnitudes=fft_mags,
        duty_cycle_pct=duty_cycle,
        rise_time_s=rise_time_s,
        fall_time_s=fall_time_s,
    )

    # 8. Apply limit specs (optional)
    if limit_specs:
        metrics.limit_results = apply_limits(metrics, limit_specs)

    logger.info(
        "analyze_waveform: %d samples | %.3f kHz | Vpp=%.4f V | verdict=%s",
        len(voltage),
        frequency_hz / 1e3,
        metrics.v_peak_to_peak,
        metrics.overall_verdict.value,
    )

    return metrics
