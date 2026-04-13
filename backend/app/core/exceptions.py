"""
exceptions.py — Domain-specific HTTP exceptions
=================================================
These wrap FastAPI's HTTPException so call-sites don't need to know
status codes and callers get consistent JSON error bodies.

Response shape (FastAPI default):
    {"detail": "<message>"}
"""
from fastapi import HTTPException, status


class MeasurementNotFoundError(HTTPException):
    """Raised when a measurement_id does not exist in the in-memory store."""
    def __init__(self, measurement_id: str) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Measurement '{measurement_id}' not found.",
        )


class AnalysisNotFoundError(HTTPException):
    """Raised when an analysis_id does not exist in the in-memory store."""
    def __init__(self, analysis_id: str) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Analysis result '{analysis_id}' not found.",
        )


class ReportNotFoundError(HTTPException):
    """Raised when a report_id does not exist in the in-memory store."""
    def __init__(self, report_id: str) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report '{report_id}' not found.",
        )


class CsvParseError(HTTPException):
    """Raised when the uploaded CSV cannot be interpreted as waveform data."""
    def __init__(self, detail: str) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"CSV parse error: {detail}",
        )


class AnalysisError(HTTPException):
    """Raised when the analysis engine rejects the input data."""
    def __init__(self, detail: str) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Analysis error: {detail}",
        )


class ChannelNotFoundError(HTTPException):
    """Raised when a requested channel does not exist in the measurement."""
    def __init__(self, channel_id: str, measurement_id: str) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Channel '{channel_id}' not found in measurement '{measurement_id}'. "
                f"Use GET /measurements/{{id}} to list available channels."
            ),
        )
