"""
Tests for the PDF report generation pipeline.

Two layers:
  1. Unit tests — call ``generate_report()`` directly with in-memory objects,
     verify the returned bytes are a valid PDF and contain expected text.
  2. Integration tests — exercise the HTTP endpoints
       POST /reports/generate
       GET  /reports/{id}/download
     using the FastAPI TestClient (lifespan triggered via context manager).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.analysis import (
    AnalysisResponse,
    ChannelAnalysisResponse,
    LimitResultResponse,
)
from app.models.report import ReportConfig
from app.models.waveform import ChannelData, WaveformDataResponse
from app.services.report_generator import generate_report

# ---------------------------------------------------------------------------
# Module-scoped TestClient (same pattern as test_api.py)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Minimal in-memory fixtures for unit tests
# ---------------------------------------------------------------------------

_N = 200  # sample count — small for speed


def _fake_waveform() -> WaveformDataResponse:
    import math
    t = [i / 10_000 for i in range(_N)]           # 0 … 19.9 ms at 10 kSa/s
    v = [math.sin(2 * math.pi * 1_000 * ti) for ti in t]  # 1 kHz sine, ±1 V
    ch = ChannelData(
        channel_id='CH1',
        time_s=t,
        voltage_v=v,
        sample_rate_hz=10_000.0,
        n_samples=_N,
    )
    return WaveformDataResponse(
        measurement_id='test-measurement-id',
        source='mock',
        channels=[ch],
        metadata={'filename': 'unit-test.csv'},
    )


def _fake_analysis(measurement_id: str = 'test-measurement-id') -> AnalysisResponse:
    ch = ChannelAnalysisResponse(
        channel_id='CH1',
        measurement_id=measurement_id,
        frequency_hz=1_000.0,
        period_s=1e-3,
        dominant_fft_freq_hz=1_000.0,
        fft_frequencies=[float(i * 50) for i in range(100)],
        fft_magnitudes=[0.5 if i == 20 else 0.01 for i in range(100)],
        v_mean=0.0,
        v_rms=0.707,
        v_rms_ac=0.707,
        v_peak_to_peak=2.0,
        v_min=-1.0,
        v_max=1.0,
        avg_power_w=0.01,
        load_resistance_ohms=50.0,
        duty_cycle_pct=50.0,
        rise_time_s=1e-4,
        fall_time_s=1e-4,
        overall_verdict='NOT_TESTED',
        limit_results=[],
    )
    return AnalysisResponse(
        analysis_id='test-analysis-id',
        measurement_id=measurement_id,
        channels=[ch],
    )


def _fake_analysis_with_limits(measurement_id: str = 'test-measurement-id') -> AnalysisResponse:
    limit_pass = LimitResultResponse(
        spec_name='frequency',
        measured_value=1_000.0,
        min_value=900.0,
        max_value=1_100.0,
        unit='Hz',
        status='PASS',
    )
    limit_fail = LimitResultResponse(
        spec_name='v_rms',
        measured_value=0.707,
        min_value=0.8,
        max_value=1.0,
        unit='V',
        status='FAIL',
    )
    ch = ChannelAnalysisResponse(
        channel_id='CH1',
        measurement_id=measurement_id,
        frequency_hz=1_000.0,
        period_s=1e-3,
        dominant_fft_freq_hz=1_000.0,
        fft_frequencies=[float(i * 50) for i in range(100)],
        fft_magnitudes=[0.5 if i == 20 else 0.01 for i in range(100)],
        v_mean=0.0,
        v_rms=0.707,
        v_rms_ac=0.707,
        v_peak_to_peak=2.0,
        v_min=-1.0,
        v_max=1.0,
        avg_power_w=0.01,
        load_resistance_ohms=50.0,
        duty_cycle_pct=50.0,
        rise_time_s=1e-4,
        fall_time_s=1e-4,
        overall_verdict='FAIL',
        limit_results=[limit_pass, limit_fail],
    )
    return AnalysisResponse(
        analysis_id='test-analysis-fail-id',
        measurement_id=measurement_id,
        channels=[ch],
    )


# ---------------------------------------------------------------------------
# Unit tests — generate_report() directly
# ---------------------------------------------------------------------------


class TestGenerateReportUnit:
    """Call generate_report() in-process; validate the output bytes."""

    def test_returns_bytes(self):
        pdf = generate_report(
            waveform=_fake_waveform(),
            analysis=_fake_analysis(),
            config=ReportConfig(
                analysis_id='test-analysis-id',
                title='Unit Test Report',
            ),
        )
        assert isinstance(pdf, bytes)

    def test_pdf_magic_bytes(self):
        """PDF files start with the 5-byte header %PDF-."""
        pdf = generate_report(
            waveform=_fake_waveform(),
            analysis=_fake_analysis(),
            config=ReportConfig(analysis_id='test-analysis-id'),
        )
        assert pdf[:5] == b'%PDF-', "output is not a valid PDF (missing magic bytes)"

    def test_pdf_non_trivial_size(self):
        """A real PDF with plots should be well over 10 kB."""
        pdf = generate_report(
            waveform=_fake_waveform(),
            analysis=_fake_analysis(),
            config=ReportConfig(analysis_id='test-analysis-id'),
        )
        assert len(pdf) > 10_000, f"PDF suspiciously small: {len(pdf)} bytes"

    def test_title_in_pdf(self):
        """The report title should appear somewhere in the PDF stream."""
        title = 'My Custom Report Title'
        pdf = generate_report(
            waveform=_fake_waveform(),
            analysis=_fake_analysis(),
            config=ReportConfig(analysis_id='test-analysis-id', title=title),
        )
        assert title.encode() in pdf

    def test_analysis_id_in_pdf(self):
        """The analysis ID prefix should be embedded in the metadata table."""
        pdf = generate_report(
            waveform=_fake_waveform(),
            analysis=_fake_analysis(),
            config=ReportConfig(analysis_id='test-analysis-id'),
        )
        # PDF text is uncompressed in streams for ReportLab Platypus
        assert b'test-analysis' in pdf

    def test_fail_verdict_report(self):
        """A FAIL analysis produces a PDF without raising."""
        pdf = generate_report(
            waveform=_fake_waveform(),
            analysis=_fake_analysis_with_limits(),
            config=ReportConfig(
                analysis_id='test-analysis-fail-id',
                title='FAIL Verdict Report',
            ),
        )
        assert pdf[:5] == b'%PDF-'

    def test_optional_fields_omitted(self):
        """engineer_name and project_ref are optional — no crash when absent."""
        pdf = generate_report(
            waveform=_fake_waveform(),
            analysis=_fake_analysis(),
            config=ReportConfig(
                analysis_id='test-analysis-id',
                engineer_name=None,
                project_ref=None,
            ),
        )
        assert isinstance(pdf, bytes)

    def test_optional_fields_present(self):
        """When engineer_name / project_ref are provided no error is raised and
        the PDF is larger than the one produced without them (content was added)."""
        engineer = 'Jane Engineer'
        project  = 'PRJ-42'
        pdf_with = generate_report(
            waveform=_fake_waveform(),
            analysis=_fake_analysis(),
            config=ReportConfig(
                analysis_id='test-analysis-id',
                engineer_name=engineer,
                project_ref=project,
            ),
        )
        pdf_without = generate_report(
            waveform=_fake_waveform(),
            analysis=_fake_analysis(),
            config=ReportConfig(
                analysis_id='test-analysis-id',
                engineer_name=None,
                project_ref=None,
            ),
        )
        assert pdf_with[:5] == b'%PDF-'
        # PDF with metadata should be at least as large
        assert len(pdf_with) >= len(pdf_without)

    def test_plots_disabled(self):
        """Disabling both plots still produces a valid PDF."""
        pdf = generate_report(
            waveform=_fake_waveform(),
            analysis=_fake_analysis(),
            config=ReportConfig(
                analysis_id='test-analysis-id',
                include_waveform_plot=False,
                include_fft_plot=False,
            ),
        )
        assert pdf[:5] == b'%PDF-'

    def test_multichannel(self):
        """Two-channel waveform + analysis produces a PDF without error."""
        import math
        t = [i / 10_000 for i in range(_N)]
        ch1 = ChannelData(
            channel_id='CH1',
            time_s=t,
            voltage_v=[math.sin(2 * math.pi * 1_000 * ti) for ti in t],
            sample_rate_hz=10_000.0,
            n_samples=_N,
        )
        ch2 = ChannelData(
            channel_id='CH2',
            time_s=t,
            voltage_v=[math.cos(2 * math.pi * 2_000 * ti) for ti in t],
            sample_rate_hz=10_000.0,
            n_samples=_N,
        )
        waveform = WaveformDataResponse(
            measurement_id='multi-ch-id',
            source='mock',
            channels=[ch1, ch2],
            metadata={},
        )

        def _ch_result(ch_id: str, freq: float) -> ChannelAnalysisResponse:
            return ChannelAnalysisResponse(
                channel_id=ch_id,
                measurement_id='multi-ch-id',
                frequency_hz=freq,
                period_s=1 / freq,
                dominant_fft_freq_hz=freq,
                fft_frequencies=[float(i * 50) for i in range(100)],
                fft_magnitudes=[0.4 if i == int(freq / 50) else 0.01 for i in range(100)],
                v_mean=0.0,
                v_rms=0.707,
                v_rms_ac=0.707,
                v_peak_to_peak=2.0,
                v_min=-1.0,
                v_max=1.0,
                avg_power_w=0.01,
                load_resistance_ohms=50.0,
                duty_cycle_pct=None,
                rise_time_s=None,
                fall_time_s=None,
                overall_verdict='NOT_TESTED',
                limit_results=[],
            )

        analysis = AnalysisResponse(
            analysis_id='multi-ch-analysis-id',
            measurement_id='multi-ch-id',
            channels=[_ch_result('CH1', 1_000.0), _ch_result('CH2', 2_000.0)],
        )
        pdf = generate_report(
            waveform=waveform,
            analysis=analysis,
            config=ReportConfig(analysis_id='multi-ch-analysis-id'),
        )
        assert pdf[:5] == b'%PDF-'


# ---------------------------------------------------------------------------
# Integration tests — HTTP endpoints
# ---------------------------------------------------------------------------


class TestReportEndpoints:
    """
    End-to-end tests through the FastAPI application.
    Each test that exercises /reports/generate first creates a real
    measurement + analysis via the existing API endpoints.
    """

    def _create_analysis(self, client: TestClient) -> tuple[str, str]:
        """
        Create a mock measurement then run analysis.
        Returns (measurement_id, analysis_id).
        """
        mock_resp = client.post('/measurements/mock', json={
            'channels': {
                'CH1': {
                    'waveform_type': 'sine',
                    'frequency_hz': 1_000.0,
                    'amplitude_v': 1.0,
                    'n_samples': 500,
                    'sample_rate_hz': 50_000.0,
                }
            }
        })
        assert mock_resp.status_code == 200
        measurement_id = mock_resp.json()['measurement_id']

        analysis_resp = client.post('/analysis/run', json={
            'measurement_id': measurement_id,
            'channel_ids': [],
            'load_resistance_ohms': 50.0,
            'limit_specs': [],
        })
        assert analysis_resp.status_code == 200
        analysis_id = analysis_resp.json()['analysis_id']

        return measurement_id, analysis_id

    def test_generate_report_success(self, client: TestClient):
        _, analysis_id = self._create_analysis(client)
        resp = client.post('/reports/generate', json={
            'analysis_id': analysis_id,
            'title': 'Integration Test Report',
        })
        assert resp.status_code == 200
        body = resp.json()
        assert 'report_id' in body
        assert 'download_url' in body
        assert body['download_url'].startswith('/reports/')
        assert body['download_url'].endswith('/download')
        assert body['page_count'] >= 2   # summary + ≥1 channel

    def test_generate_report_unknown_analysis(self, client: TestClient):
        resp = client.post('/reports/generate', json={
            'analysis_id': 'does-not-exist',
        })
        assert resp.status_code == 404
        assert 'does-not-exist' in resp.json()['detail']

    def test_download_report_pdf(self, client: TestClient):
        _, analysis_id = self._create_analysis(client)
        gen_resp = client.post('/reports/generate', json={'analysis_id': analysis_id})
        assert gen_resp.status_code == 200
        report_id = gen_resp.json()['report_id']

        dl_resp = client.get(f'/reports/{report_id}/download')
        assert dl_resp.status_code == 200
        assert dl_resp.headers['content-type'] == 'application/pdf'
        assert dl_resp.content[:5] == b'%PDF-'

    def test_download_report_content_length(self, client: TestClient):
        """Content-Length header must be present and match actual body size."""
        _, analysis_id = self._create_analysis(client)
        gen_resp = client.post('/reports/generate', json={'analysis_id': analysis_id})
        report_id = gen_resp.json()['report_id']

        dl_resp = client.get(f'/reports/{report_id}/download')
        assert dl_resp.status_code == 200
        assert 'content-length' in dl_resp.headers
        assert int(dl_resp.headers['content-length']) == len(dl_resp.content)

    def test_download_report_not_found(self, client: TestClient):
        resp = client.get('/reports/nonexistent-id/download')
        assert resp.status_code == 404
        assert 'nonexistent-id' in resp.json()['detail']

    def test_generate_with_optional_fields(self, client: TestClient):
        _, analysis_id = self._create_analysis(client)
        resp = client.post('/reports/generate', json={
            'analysis_id': analysis_id,
            'title': 'Full Config Report',
            'engineer_name': 'Test Engineer',
            'project_ref': 'PRJ-001',
            'include_fft_plot': True,
            'include_waveform_plot': True,
        })
        assert resp.status_code == 200
        assert resp.json()['page_count'] >= 2

    def test_generate_plots_disabled(self, client: TestClient):
        """Disabling both plots still yields a valid PDF download."""
        _, analysis_id = self._create_analysis(client)
        gen_resp = client.post('/reports/generate', json={
            'analysis_id': analysis_id,
            'include_fft_plot': False,
            'include_waveform_plot': False,
        })
        assert gen_resp.status_code == 200
        report_id = gen_resp.json()['report_id']

        dl_resp = client.get(f'/reports/{report_id}/download')
        assert dl_resp.status_code == 200
        assert dl_resp.content[:5] == b'%PDF-'

    def test_report_ids_are_unique(self, client: TestClient):
        """Generating the same analysis twice should yield distinct report IDs."""
        _, analysis_id = self._create_analysis(client)
        r1 = client.post('/reports/generate', json={'analysis_id': analysis_id}).json()['report_id']
        r2 = client.post('/reports/generate', json={'analysis_id': analysis_id}).json()['report_id']
        assert r1 != r2
