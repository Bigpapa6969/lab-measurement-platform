"""
models/report.py — Report generation schemas
=============================================
Stub populated in Step 4 (PDF Report Generator).

The ``ReportConfig`` model is referenced by the /reports route so the
import chain is valid before Step 4 is implemented.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ReportConfig(BaseModel):
    """Configuration for a PDF report generation request."""
    analysis_id: str = Field(..., description="ID of a completed analysis to report on")
    title: str = Field(default="Waveform Analysis Report")
    engineer_name: Optional[str] = Field(default=None)
    project_ref: Optional[str] = Field(default=None)
    include_fft_plot: bool = True
    include_waveform_plot: bool = True


class ReportResponse(BaseModel):
    """Returned after successful PDF generation (Step 4)."""
    report_id: str
    download_url: str
    page_count: int
