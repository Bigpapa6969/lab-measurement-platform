"""
routes/reports.py — PDF report generation endpoints
=====================================================

POST /reports/generate
    Body : ReportConfig JSON
    Returns : { report_id, download_url, page_count }

GET  /reports/{report_id}/download
    Returns : StreamingResponse (application/pdf)

The PDF bytes are stored in the InMemoryStore keyed by a UUID.
The ``download_url`` in the generate response is the path a client
should fetch to retrieve the binary.
"""
from __future__ import annotations

import io
import logging
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.api.dependencies import get_store
from app.core.exceptions import AnalysisNotFoundError, MeasurementNotFoundError, ReportNotFoundError
from app.models.report import ReportConfig, ReportResponse
from app.services.report_generator import generate_report

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    '/generate',
    response_model=ReportResponse,
    summary='Generate a PDF test report',
    description=(
        'Renders a multi-page A4 PDF containing waveform plots, FFT spectra, '
        'metrics tables, and pass/fail limit results.  Returns a ``report_id`` '
        'and ``download_url`` for the binary download.'
    ),
)
def generate(body: ReportConfig, request: Request) -> ReportResponse:
    store = get_store(request)

    # Resolve the analysis record
    analysis = store.get_analysis(body.analysis_id)
    if analysis is None:
        raise AnalysisNotFoundError(body.analysis_id)

    # Resolve the originating measurement (needed for waveform plots)
    waveform = store.get_measurement(analysis.measurement_id)
    if waveform is None:
        raise MeasurementNotFoundError(analysis.measurement_id)

    logger.info(
        "Generating PDF report for analysis_id=%s (%d channel(s))",
        body.analysis_id,
        len(analysis.channels),
    )

    pdf_bytes = generate_report(waveform=waveform, analysis=analysis, config=body)

    # Estimate page count: 1 summary + 1 per channel
    page_count = 1 + len(analysis.channels)

    report_id = str(uuid.uuid4())
    store.save_report(report_id, pdf_bytes)

    download_url = f'/reports/{report_id}/download'
    logger.info(
        "Report stored: report_id=%s  size=%d bytes  pages=%d",
        report_id,
        len(pdf_bytes),
        page_count,
    )

    return ReportResponse(
        report_id=report_id,
        download_url=download_url,
        page_count=page_count,
    )


@router.get(
    '/{report_id}/download',
    summary='Download a generated PDF report',
    description='Streams the raw PDF bytes with Content-Disposition: attachment.',
    response_class=StreamingResponse,
)
def download(report_id: str, request: Request) -> StreamingResponse:
    store = get_store(request)

    pdf_bytes = store.get_report(report_id)
    if pdf_bytes is None:
        raise ReportNotFoundError(report_id)

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type='application/pdf',
        headers={
            'Content-Disposition': f'attachment; filename="report-{report_id[:8]}.pdf"',
            'Content-Length': str(len(pdf_bytes)),
        },
    )
