"""
Unit tests for Module A: Data Ingestion

Covers:
- MockOscilloscope: waveform generation for all types, seeding, context manager
- csv_parser: format detection and parsing for Rigol, LTspice, Tektronix, Generic
"""
from __future__ import annotations

import io
import textwrap

import numpy as np
import pytest

from app.services.ingestion.base_instrument import InstrumentError
from app.services.ingestion.csv_parser import ParsedWaveform, parse_csv
from app.services.ingestion.mock_oscilloscope import (
    ChannelConfig,
    MockOscilloscope,
    WaveformType,
)


# ---------------------------------------------------------------------------
# MockOscilloscope tests
# ---------------------------------------------------------------------------


class TestMockOscilloscope:

    def _default_scope(self, **kwargs) -> MockOscilloscope:
        return MockOscilloscope(
            channel_configs={
                "CH1": ChannelConfig(waveform_type=WaveformType.SINE, frequency_hz=1_000.0),
                "CH2": ChannelConfig(waveform_type=WaveformType.SQUARE),
            },
            sample_rate_hz=100_000.0,
            duration_s=0.01,
            seed=0,
            **kwargs,
        )

    # -- Connection lifecycle ------------------------------------------------

    def test_requires_connect_before_get_waveform(self):
        scope = self._default_scope()
        with pytest.raises(InstrumentError, match="not connected"):
            scope.get_waveform("CH1")

    def test_context_manager_connects_and_disconnects(self):
        scope = self._default_scope()
        assert not scope.is_connected
        with scope:
            assert scope.is_connected
        assert not scope.is_connected

    def test_identity_string(self):
        scope = self._default_scope()
        assert "Mock" in scope.get_identity()

    # -- Waveform output shape -----------------------------------------------

    def test_output_array_length(self):
        fs = 50_000.0
        dur = 0.02
        expected_n = int(fs * dur)
        with MockOscilloscope(sample_rate_hz=fs, duration_s=dur, seed=1) as scope:
            t, v = scope.get_waveform("CH1")
        assert len(t) == expected_n
        assert len(v) == expected_n

    def test_time_array_starts_at_zero(self):
        with self._default_scope() as scope:
            t, _ = scope.get_waveform("CH1")
        assert t[0] == pytest.approx(0.0, abs=1e-9)

    def test_time_array_is_uniformly_spaced(self):
        with self._default_scope() as scope:
            t, _ = scope.get_waveform("CH1")
        diffs = np.diff(t)
        assert np.max(np.abs(diffs - diffs[0])) < 1e-10

    # -- Waveform types ------------------------------------------------------

    @pytest.mark.parametrize("wtype", [
        WaveformType.SINE,
        WaveformType.SQUARE,
        WaveformType.PWM,
        WaveformType.TRIANGLE,
        WaveformType.DC,
    ])
    def test_all_waveform_types_produce_finite_output(self, wtype):
        cfg = {"CH1": ChannelConfig(waveform_type=wtype, frequency_hz=500.0, noise_std=0.0)}
        with MockOscilloscope(channel_configs=cfg, seed=0) as scope:
            _, v = scope.get_waveform("CH1")
        assert np.all(np.isfinite(v)), f"Non-finite values for wtype={wtype}"

    def test_dc_signal_constant_value(self):
        offset = 3.3
        cfg = {"CH1": ChannelConfig(waveform_type=WaveformType.DC, offset_v=offset, noise_std=0.0)}
        with MockOscilloscope(channel_configs=cfg, seed=0) as scope:
            _, v = scope.get_waveform("CH1")
        assert np.allclose(v, offset, atol=1e-9)

    def test_pwm_duty_cycle_approximately_correct(self):
        duty = 0.3
        cfg = {
            "CH1": ChannelConfig(
                waveform_type=WaveformType.PWM,
                frequency_hz=1_000.0,
                amplitude_v=1.0,
                duty_cycle=duty,
                noise_std=0.0,
            )
        }
        with MockOscilloscope(channel_configs=cfg, sample_rate_hz=100_000, duration_s=0.05, seed=0) as scope:
            _, v = scope.get_waveform("CH1")
        high_fraction = np.mean(v > 0.5)
        assert abs(high_fraction - duty) < 0.03, f"Expected duty ~{duty}, got {high_fraction:.3f}"

    # -- Reproducibility and isolation ---------------------------------------

    def test_same_seed_produces_same_waveform(self):
        with MockOscilloscope(seed=99) as s1:
            _, v1 = s1.get_waveform("CH1")
        with MockOscilloscope(seed=99) as s2:
            _, v2 = s2.get_waveform("CH1")
        np.testing.assert_array_equal(v1, v2)

    def test_different_seeds_produce_different_noise(self):
        cfg = {"CH1": ChannelConfig(noise_std=0.1)}
        with MockOscilloscope(channel_configs=cfg, seed=1) as s1:
            _, v1 = s1.get_waveform("CH1")
        with MockOscilloscope(channel_configs=cfg, seed=2) as s2:
            _, v2 = s2.get_waveform("CH1")
        assert not np.array_equal(v1, v2)

    def test_channels_have_independent_noise(self):
        """CH1 and CH2 must not produce identical noise even with same config."""
        cfg = {
            "CH1": ChannelConfig(noise_std=0.5),
            "CH2": ChannelConfig(noise_std=0.5),
        }
        with MockOscilloscope(channel_configs=cfg, seed=0) as scope:
            _, v1 = scope.get_waveform("CH1")
            _, v2 = scope.get_waveform("CH2")
        assert not np.allclose(v1, v2)

    # -- Error handling ------------------------------------------------------

    def test_unknown_channel_raises(self):
        with self._default_scope() as scope:
            with pytest.raises(InstrumentError, match="not configured"):
                scope.get_waveform("CH99")

    # -- get_all_waveforms ---------------------------------------------------

    def test_get_all_waveforms_returns_all_channels(self):
        with self._default_scope() as scope:
            all_waves = scope.get_all_waveforms()
        assert set(all_waves.keys()) == {"CH1", "CH2"}
        for ch, (t, v) in all_waves.items():
            assert len(t) == len(v)

    # -- Static generator (no instrument instance needed) --------------------

    def test_generate_waveform_static(self):
        cfg = ChannelConfig(waveform_type=WaveformType.SINE, frequency_hz=500.0)
        rng = np.random.default_rng(0)
        t, v = MockOscilloscope.generate_waveform(cfg, 100_000.0, 0.01, rng)
        assert len(t) == 1000
        assert np.all(np.isfinite(v))


# ---------------------------------------------------------------------------
# CSV parser tests
# ---------------------------------------------------------------------------


class TestCsvParser:

    # -- Rigol format --------------------------------------------------------

    def test_parse_rigol_two_channels(self):
        csv = textwrap.dedent("""\
            X,CH1,CH2
            Second,Volt,Volt
            -1.000000e-03,+2.48e-01,+1.60e-02
            -9.990000e-04,+2.50e-01,+1.62e-02
            -9.980000e-04,+2.51e-01,+1.63e-02
        """)
        result = parse_csv(content=csv.encode(), filename="rigol.csv")
        assert result.source_format == "rigol"
        assert len(result.channels) == 2
        assert {ch.channel_id for ch in result.channels} == {"CH1", "CH2"}

    def test_parse_rigol_voltage_values_correct(self):
        csv = textwrap.dedent("""\
            X,CH1
            Second,Volt
            0.000000e+00,1.23456e+00
            1.000000e-05,2.34567e+00
        """)
        result = parse_csv(content=csv.encode(), filename="rigol.csv")
        ch1 = result.channels[0]
        assert ch1.voltage_v[0] == pytest.approx(1.23456, rel=1e-4)
        assert ch1.voltage_v[1] == pytest.approx(2.34567, rel=1e-4)

    # -- LTspice format ------------------------------------------------------

    def test_parse_ltspice_tab_separated(self):
        csv = textwrap.dedent("""\
            time\tV(out)\tV(in)
            0.000000e+00\t3.300000e+00\t0.000000e+00
            1.000000e-08\t3.298000e+00\t0.000000e+00
            2.000000e-08\t3.296000e+00\t5.000000e-01
        """)
        result = parse_csv(content=csv.encode(), filename="ltspice.txt")
        assert result.source_format == "ltspice"
        assert len(result.channels) == 2
        ids = {ch.channel_id for ch in result.channels}
        assert "V(out)" in ids and "V(in)" in ids

    def test_parse_ltspice_time_values_correct(self):
        csv = "time\tV(out)\n0.0e+00\t3.3\n1.0e-08\t3.2\n"
        result = parse_csv(content=csv.encode(), filename="spice.txt")
        ch = result.channels[0]
        assert ch.time_s[0] == pytest.approx(0.0)
        assert ch.time_s[1] == pytest.approx(1e-8, rel=1e-4)

    # -- Tektronix format ----------------------------------------------------

    def test_parse_tektronix_with_metadata(self):
        csv = textwrap.dedent("""\
            Model,MSO54B
            Firmware Version,1.24.0
            Record Length,10000,Samples
            Sample Interval,1.0E-08,Seconds
            Time,CH1,CH2
            -5.0E-05,0.12,0.01
            -4.9E-05,0.13,0.02
            -4.8E-05,0.14,0.03
        """)
        result = parse_csv(content=csv.encode(), filename="tek.csv")
        assert result.source_format == "tektronix"
        assert "Model" in result.metadata or len(result.channels) == 2

    # -- Generic format ------------------------------------------------------

    def test_parse_generic_comma_separated(self):
        csv = textwrap.dedent("""\
            time,voltage
            0.0,1.5
            1e-6,1.6
            2e-6,1.7
        """)
        result = parse_csv(content=csv.encode(), filename="generic.csv")
        assert result.source_format == "generic"
        assert len(result.channels) == 1
        assert result.channels[0].voltage_v[0] == pytest.approx(1.5)

    def test_parse_generic_no_header(self):
        """File with no header row: synthesise column names."""
        csv = "0.0,1.5\n1e-6,1.6\n2e-6,1.7\n"
        result = parse_csv(content=csv.encode(), filename="nohdr.csv")
        assert len(result.channels) == 1

    def test_parse_generic_skips_comment_lines(self):
        csv = textwrap.dedent("""\
            # Captured at 2024-01-01
            # Sample rate: 1 MHz
            time,voltage
            0.0,1.0
            1e-6,2.0
        """)
        result = parse_csv(content=csv.encode(), filename="commented.csv")
        assert len(result.channels[0].time_s) == 2

    # -- Error handling ------------------------------------------------------

    def test_empty_file_raises(self):
        with pytest.raises(ValueError, match="empty"):
            parse_csv(content=b"", filename="empty.csv")

    def test_no_numeric_data_raises(self):
        csv = "col1,col2\nalpha,beta\ngamma,delta\n"
        with pytest.raises(ValueError):
            parse_csv(content=csv.encode(), filename="text_only.csv")

    def test_neither_path_nor_content_raises(self):
        with pytest.raises(ValueError, match="neither"):
            parse_csv()

    def test_both_path_and_content_raises(self):
        with pytest.raises(ValueError, match="both"):
            parse_csv(path="some.csv", content=b"data")

    # -- Channel data quality ------------------------------------------------

    def test_parsed_channel_sample_rate(self):
        """Sample rate inferred from parsed time vector should be accurate."""
        fs = 1_000_000.0   # 1 MSa/s
        dt = 1.0 / fs
        times = [i * dt for i in range(100)]
        volts = [float(i) * 0.01 for i in range(100)]
        lines = ["time,voltage"] + [f"{t},{v}" for t, v in zip(times, volts)]
        result = parse_csv(content="\n".join(lines).encode(), filename="sr_test.csv")
        assert abs(result.channels[0].sample_rate_hz - fs) / fs < 0.01
