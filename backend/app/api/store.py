"""
store.py — In-memory data store
================================
Provides a simple keyed store for measurements and analysis results.
In production this would be replaced by a database (PostgreSQL + SQLAlchemy
or a time-series DB like TimescaleDB).  For the portfolio/demo scope,
an in-memory dict behind a thin class is sufficient and avoids adding
infrastructure dependencies.

The store is created once per application instance during the FastAPI
lifespan and attached to ``app.state.store``.
"""
from __future__ import annotations

from app.models.analysis import AnalysisResponse
from app.models.waveform import WaveformDataResponse


class InMemoryStore:
    """
    Thread-unsafe in-memory store for measurements and analysis results.

    Not safe for concurrent writes — acceptable for a single-process dev
    server.  Upgrade to Redis or a DB-backed store for multi-worker deploys.
    """

    def __init__(self) -> None:
        self._measurements: dict[str, WaveformDataResponse] = {}
        self._analyses: dict[str, AnalysisResponse] = {}
        self._reports: dict[str, bytes] = {}

    # ---- Measurements ------------------------------------------------

    def save_measurement(self, measurement_id: str, data: WaveformDataResponse) -> None:
        self._measurements[measurement_id] = data

    def get_measurement(self, measurement_id: str) -> WaveformDataResponse | None:
        return self._measurements.get(measurement_id)

    def list_measurement_ids(self) -> list[str]:
        return list(self._measurements.keys())

    # ---- Analyses ----------------------------------------------------

    def save_analysis(self, analysis_id: str, result: AnalysisResponse) -> None:
        self._analyses[analysis_id] = result

    def get_analysis(self, analysis_id: str) -> AnalysisResponse | None:
        return self._analyses.get(analysis_id)

    def list_analysis_ids(self) -> list[str]:
        return list(self._analyses.keys())

    # ---- Reports -------------------------------------------------------------

    def save_report(self, report_id: str, pdf_bytes: bytes) -> None:
        self._reports[report_id] = pdf_bytes

    def get_report(self, report_id: str) -> bytes | None:
        return self._reports.get(report_id)
