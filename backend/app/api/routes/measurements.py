"""
routes/measurements.py — Measurement ingestion endpoints
=========================================================

Endpoints
---------
POST /measurements/upload
    Accepts a multipart CSV file upload; auto-detects oscilloscope format.
    Returns WaveformDataResponse with a measurement_id.

POST /measurements/mock
    Generates synthetic waveform data via MockOscilloscope.
    Useful for frontend development and automated testing without hardware.

GET /measurements/{measurement_id}
    Retrieves a previously stored measurement by ID.

GET /measurements
    Lists all stored measurement IDs.
"""
from __future__ import annotations

import logging
from uuid import uuid4

import numpy as np
from fastapi import APIRouter, Depends, File, UploadFile

from app.api.dependencies import get_store
from app.api.store import InMemoryStore
from app.core.config import settings
from app.core.exceptions import CsvParseError, MeasurementNotFoundError
from app.models.waveform import ChannelData, MockRequest, WaveformDataResponse
from app.services.ingestion.csv_parser import parse_csv
from app.services.ingestion.mock_oscilloscope import MockOscilloscope

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _channel_data_from_arrays(
    channel_id: str,
    time_s: "np.ndarray",
    voltage_v: "np.ndarray",
    unit: str = "V",
) -> ChannelData:
    """Convert numpy arrays → ChannelData Pydantic model."""
    dt = float(np.mean(np.diff(time_s))) if len(time_s) > 1 else 1.0
    return ChannelData(
        channel_id=channel_id,
        time_s=time_s.tolist(),
        voltage_v=voltage_v.tolist(),
        sample_rate_hz=round(1.0 / dt, 4),
        unit=unit,
        n_samples=len(time_s),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/upload", response_model=WaveformDataResponse, summary="Upload a CSV waveform file")
async def upload_csv(
    file: UploadFile = File(..., description="Oscilloscope or SPICE CSV export"),
    store: InMemoryStore = Depends(get_store),
) -> WaveformDataResponse:
    """
    Parse and store a waveform from an uploaded CSV file.

    Supported formats (auto-detected):
    - **Rigol** DS/MSO series default export
    - **Tektronix** MSO/DPO series default export
    - **LTspice** XVII tab-separated export
    - **Generic** CSV with a time column (comma or tab separated)

    Returns a ``measurement_id`` to use in subsequent ``/analysis/run`` calls.
    """
    # Guard against huge uploads before reading into memory
    raw: bytes = await file.read()
    if len(raw) > settings.max_upload_size_bytes:
        raise CsvParseError(
            f"File size {len(raw):,} bytes exceeds limit of "
            f"{settings.max_upload_size_bytes:,} bytes."
        )

    filename = file.filename or "upload.csv"
    logger.info("upload_csv: received '%s' (%d bytes)", filename, len(raw))

    try:
        parsed = parse_csv(content=raw, filename=filename)
    except ValueError as exc:
        raise CsvParseError(str(exc)) from exc

    channels = [
        _channel_data_from_arrays(ch.channel_id, ch.time_s, ch.voltage_v, ch.unit)
        for ch in parsed.channels
    ]

    measurement_id = str(uuid4())
    response = WaveformDataResponse(
        measurement_id=measurement_id,
        source="csv",
        channels=channels,
        metadata={**parsed.metadata, "source_format": parsed.source_format, "filename": filename},
    )
    store.save_measurement(measurement_id, response)
    logger.info(
        "upload_csv: stored measurement_id=%s (%d channels, format=%s)",
        measurement_id, len(channels), parsed.source_format,
    )
    return response


@router.post("/mock", response_model=WaveformDataResponse, summary="Generate a mock waveform")
def generate_mock(
    body: MockRequest,
    store: InMemoryStore = Depends(get_store),
) -> WaveformDataResponse:
    """
    Generate synthetic waveform data using the software MockOscilloscope.

    Useful for:
    - Frontend development without physical hardware
    - Automated integration testing with deterministic data
    - Demonstrating analysis capabilities

    Each channel can be independently configured as SINE, SQUARE, PWM,
    TRIANGLE, or DC with custom frequency, amplitude, noise, and duty cycle.
    """
    channel_configs = {
        ch_name: ch_req.to_channel_config()
        for ch_name, ch_req in body.channels.items()
    }

    scope = MockOscilloscope(
        channel_configs=channel_configs,
        sample_rate_hz=body.sample_rate_hz,
        duration_s=body.duration_s,
        seed=body.seed,
    )

    with scope:
        waveforms = scope.get_all_waveforms()

    channels = [
        _channel_data_from_arrays(ch_name, t, v)
        for ch_name, (t, v) in waveforms.items()
    ]

    n_samples = int(body.sample_rate_hz * body.duration_s)
    measurement_id = str(uuid4())
    response = WaveformDataResponse(
        measurement_id=measurement_id,
        source="mock",
        channels=channels,
        metadata={
            "sample_rate_hz": str(body.sample_rate_hz),
            "duration_s": str(body.duration_s),
            "n_samples": str(n_samples),
            "seed": str(body.seed),
        },
    )
    store.save_measurement(measurement_id, response)
    logger.info(
        "generate_mock: stored measurement_id=%s (%d channels, %d samples/ch)",
        measurement_id, len(channels), n_samples,
    )
    return response


@router.get(
    "/{measurement_id}",
    response_model=WaveformDataResponse,
    summary="Retrieve a stored measurement",
)
def get_measurement(
    measurement_id: str,
    store: InMemoryStore = Depends(get_store),
) -> WaveformDataResponse:
    """Retrieve a previously uploaded or generated measurement by its ID."""
    data = store.get_measurement(measurement_id)
    if data is None:
        raise MeasurementNotFoundError(measurement_id)
    return data


@router.get("/", response_model=list[str], summary="List all measurement IDs")
def list_measurements(store: InMemoryStore = Depends(get_store)) -> list[str]:
    """Return all stored measurement IDs."""
    return store.list_measurement_ids()
