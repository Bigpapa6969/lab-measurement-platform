"""
Integration tests for the FastAPI application.

Uses FastAPI's TestClient (backed by httpx) — no running server needed.
Tests cover the full HTTP → service → response chain including error paths.

The ``client`` fixture uses ``with TestClient(app)`` to trigger the FastAPI
lifespan handler, which initialises ``app.state.store`` before any request
is made.  Without the context-manager form the store is never set up.
"""
from __future__ import annotations

import textwrap

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    """Module-scoped TestClient that runs the full lifespan."""
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Shared CSV fixtures
# ---------------------------------------------------------------------------

RIGOL_CSV = textwrap.dedent("""\
    X,CH1,CH2
    Second,Volt,Volt
    0.000000e+00,+1.23e-01,+5.67e-02
    1.000000e-05,+1.25e-01,+5.70e-02
    2.000000e-05,+1.27e-01,+5.73e-02
    3.000000e-05,+1.29e-01,+5.76e-02
    4.000000e-05,+1.31e-01,+5.79e-02
""").encode()

GENERIC_CSV = textwrap.dedent("""\
    time,voltage
    0.0,1.5
    0.001,1.6
    0.002,1.7
    0.003,1.8
    0.004,1.9
""").encode()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _create_sine_measurement(client: TestClient, freq: float = 1000.0) -> str:
    """Generate a mock sine measurement and return its measurement_id."""
    body = {
        "channels": {
            "CH1": {
                "waveform_type": "sine",
                "frequency_hz": freq,
                "amplitude_v": 1.0,
                "noise_std": 0.01,
                "offset_v": 0.0,
                "duty_cycle": 0.5,
                "phase_deg": 0.0,
            }
        },
        "sample_rate_hz": 100000.0,
        "duration_s": 0.01,
        "seed": 0,
    }
    return client.post("/measurements/mock", json=body).json()["measurement_id"]


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


def test_root_health_check(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body


# ---------------------------------------------------------------------------
# POST /measurements/mock
# ---------------------------------------------------------------------------


class TestMockEndpoint:

    def _default_mock_body(self) -> dict:
        return {
            "channels": {
                "CH1": {"waveform_type": "sine", "frequency_hz": 1000.0, "amplitude_v": 1.0,
                         "noise_std": 0.01, "offset_v": 0.0, "duty_cycle": 0.5, "phase_deg": 0.0},
                "CH2": {"waveform_type": "square", "frequency_hz": 500.0, "amplitude_v": 3.3,
                         "noise_std": 0.02, "offset_v": 0.0, "duty_cycle": 0.5, "phase_deg": 0.0},
            },
            "sample_rate_hz": 100000.0,
            "duration_s": 0.01,
            "seed": 42,
        }

    def test_returns_200(self, client):
        resp = client.post("/measurements/mock", json=self._default_mock_body())
        assert resp.status_code == 200

    def test_returns_measurement_id(self, client):
        resp = client.post("/measurements/mock", json=self._default_mock_body())
        body = resp.json()
        assert "measurement_id" in body
        assert len(body["measurement_id"]) == 36  # UUID4

    def test_returns_two_channels(self, client):
        resp = client.post("/measurements/mock", json=self._default_mock_body())
        channels = resp.json()["channels"]
        assert len(channels) == 2
        ids = {ch["channel_id"] for ch in channels}
        assert ids == {"CH1", "CH2"}

    def test_channel_array_lengths_match(self, client):
        resp = client.post("/measurements/mock", json=self._default_mock_body())
        for ch in resp.json()["channels"]:
            assert len(ch["time_s"]) == len(ch["voltage_v"])
            assert ch["n_samples"] == len(ch["time_s"])

    def test_correct_number_of_samples(self, client):
        body = self._default_mock_body()
        fs = body["sample_rate_hz"]
        dur = body["duration_s"]
        expected = int(fs * dur)
        resp = client.post("/measurements/mock", json=body)
        for ch in resp.json()["channels"]:
            assert ch["n_samples"] == expected

    def test_source_is_mock(self, client):
        resp = client.post("/measurements/mock", json=self._default_mock_body())
        assert resp.json()["source"] == "mock"

    def test_deterministic_with_same_seed(self, client):
        body = self._default_mock_body()
        r1 = client.post("/measurements/mock", json=body).json()
        r2 = client.post("/measurements/mock", json=body).json()
        ch1_v1 = r1["channels"][0]["voltage_v"]
        ch1_v2 = r2["channels"][0]["voltage_v"]
        assert ch1_v1 == ch1_v2


# ---------------------------------------------------------------------------
# POST /measurements/upload
# ---------------------------------------------------------------------------


class TestUploadEndpoint:

    def test_upload_rigol_returns_200(self, client):
        resp = client.post(
            "/measurements/upload",
            files={"file": ("rigol.csv", RIGOL_CSV, "text/csv")},
        )
        assert resp.status_code == 200

    def test_upload_rigol_two_channels(self, client):
        resp = client.post(
            "/measurements/upload",
            files={"file": ("rigol.csv", RIGOL_CSV, "text/csv")},
        )
        channels = resp.json()["channels"]
        assert len(channels) == 2

    def test_upload_generic_csv(self, client):
        resp = client.post(
            "/measurements/upload",
            files={"file": ("generic.csv", GENERIC_CSV, "text/csv")},
        )
        assert resp.status_code == 200
        assert len(resp.json()["channels"]) == 1

    def test_upload_stores_measurement(self, client):
        resp = client.post(
            "/measurements/upload",
            files={"file": ("rigol.csv", RIGOL_CSV, "text/csv")},
        )
        mid = resp.json()["measurement_id"]
        get_resp = client.get(f"/measurements/{mid}")
        assert get_resp.status_code == 200
        assert get_resp.json()["measurement_id"] == mid

    def test_upload_bad_csv_returns_422(self, client):
        bad = b"this,is,not,waveform,data\nalpha,beta,gamma,delta,epsilon\n"
        resp = client.post(
            "/measurements/upload",
            files={"file": ("bad.csv", bad, "text/csv")},
        )
        assert resp.status_code == 422

    def test_upload_metadata_contains_format(self, client):
        resp = client.post(
            "/measurements/upload",
            files={"file": ("rigol.csv", RIGOL_CSV, "text/csv")},
        )
        assert resp.json()["metadata"]["source_format"] == "rigol"


# ---------------------------------------------------------------------------
# GET /measurements/{id}
# ---------------------------------------------------------------------------


class TestGetMeasurement:

    def test_get_existing_returns_200(self, client):
        post = client.post("/measurements/mock", json={
            "channels": {"CH1": {"waveform_type": "sine"}},
            "sample_rate_hz": 10000.0, "duration_s": 0.01, "seed": 1,
        })
        mid = post.json()["measurement_id"]
        resp = client.get(f"/measurements/{mid}")
        assert resp.status_code == 200

    def test_get_nonexistent_returns_404(self, client):
        resp = client.get("/measurements/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    def test_list_measurements_includes_created(self, client):
        post = client.post("/measurements/mock", json={
            "channels": {"CH1": {"waveform_type": "dc", "offset_v": 3.3}},
            "sample_rate_hz": 10000.0, "duration_s": 0.005, "seed": 7,
        })
        mid = post.json()["measurement_id"]
        list_resp = client.get("/measurements/")
        assert mid in list_resp.json()


# ---------------------------------------------------------------------------
# POST /analysis/run
# ---------------------------------------------------------------------------


class TestAnalysisEndpoint:

    def test_run_analysis_returns_200(self, client):
        mid = _create_sine_measurement(client)
        resp = client.post("/analysis/run", json={"measurement_id": mid})
        assert resp.status_code == 200

    def test_response_contains_analysis_id(self, client):
        mid = _create_sine_measurement(client)
        resp = client.post("/analysis/run", json={"measurement_id": mid})
        assert "analysis_id" in resp.json()

    def test_channel_metrics_present(self, client):
        mid = _create_sine_measurement(client)
        resp = client.post("/analysis/run", json={"measurement_id": mid})
        ch = resp.json()["channels"][0]
        for field in ("v_rms", "v_peak_to_peak", "frequency_hz", "fft_frequencies", "fft_magnitudes"):
            assert field in ch, f"Missing field: {field}"

    def test_frequency_estimate_accurate(self, client):
        freq = 1_000.0
        mid = _create_sine_measurement(client, freq=freq)
        resp = client.post("/analysis/run", json={"measurement_id": mid})
        measured_freq = resp.json()["channels"][0]["frequency_hz"]
        assert abs(measured_freq - freq) / freq < 0.02

    def test_limit_spec_pass(self, client):
        mid = _create_sine_measurement(client, freq=1000.0)
        body = {
            "measurement_id": mid,
            "limit_specs": [
                {"name": "frequency_hz", "unit": "Hz", "min_value": 990.0, "max_value": 1010.0}
            ],
        }
        resp = client.post("/analysis/run", json=body)
        lr = resp.json()["channels"][0]["limit_results"][0]
        assert lr["status"] == "PASS"

    def test_limit_spec_fail(self, client):
        mid = _create_sine_measurement(client)
        body = {
            "measurement_id": mid,
            "limit_specs": [{"name": "v_rms", "unit": "V", "max_value": 0.1}],
        }
        resp = client.post("/analysis/run", json=body)
        lr = resp.json()["channels"][0]["limit_results"][0]
        assert lr["status"] == "FAIL"
        assert resp.json()["channels"][0]["overall_verdict"] == "FAIL"

    def test_no_limits_gives_not_tested_verdict(self, client):
        mid = _create_sine_measurement(client)
        resp = client.post("/analysis/run", json={"measurement_id": mid})
        assert resp.json()["channels"][0]["overall_verdict"] == "NOT_TESTED"

    def test_channel_filter_applies(self, client):
        """Requesting only CH2 should return only CH2 results."""
        body_mock = {
            "channels": {
                "CH1": {"waveform_type": "sine"},
                "CH2": {"waveform_type": "square"},
            },
            "sample_rate_hz": 100000.0,
            "duration_s": 0.01,
            "seed": 5,
        }
        mid = client.post("/measurements/mock", json=body_mock).json()["measurement_id"]
        resp = client.post("/analysis/run", json={"measurement_id": mid, "channel_ids": ["CH2"]})
        channels = resp.json()["channels"]
        assert len(channels) == 1
        assert channels[0]["channel_id"] == "CH2"

    def test_analysis_nonexistent_measurement_returns_404(self, client):
        resp = client.post("/analysis/run", json={
            "measurement_id": "00000000-0000-0000-0000-000000000000"
        })
        assert resp.status_code == 404

    def test_analysis_unknown_channel_returns_422(self, client):
        mid = _create_sine_measurement(client)
        resp = client.post("/analysis/run", json={
            "measurement_id": mid,
            "channel_ids": ["CH99"],
        })
        assert resp.status_code == 422

    def test_get_stored_analysis(self, client):
        mid = _create_sine_measurement(client)
        run_resp = client.post("/analysis/run", json={"measurement_id": mid})
        aid = run_resp.json()["analysis_id"]
        get_resp = client.get(f"/analysis/{aid}")
        assert get_resp.status_code == 200
        assert get_resp.json()["analysis_id"] == aid

    def test_get_nonexistent_analysis_returns_404(self, client):
        resp = client.get("/analysis/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404
