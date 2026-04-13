"""
report_generator.py — Multi-page PDF Report Generator
=======================================================
Produces a professional A4 PDF test report combining waveform plots
(rendered with matplotlib) and tabular analysis data (laid out with
ReportLab Platypus).

Document structure
------------------
  Page 1 — Summary
    Title block   : report title, date, engineer, project ref, analysis ID
    Metadata      : source, channels, sample rate, capture window
    Summary table : one row per channel — key metrics + PASS/FAIL verdict
    Verdict box   : large overall PASS / FAIL / NOT TESTED badge

  Page 2+ — Per-channel detail (one page per analysed channel)
    Header         : channel ID, sample rate
    Waveform plot  : time-domain, rendered by matplotlib
    FFT spectrum   : single-sided magnitude, rendered by matplotlib
    Metrics table  : all computed scalar values
    Limit results  : spec name | measured | bounds | status

Public API
----------
    pdf_bytes = generate_report(waveform, analysis, config)

The function returns raw bytes suitable for streaming or file storage.
"""
from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from typing import Optional

# ── matplotlib (non-interactive, must be set before importing pyplot) ──────
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

# ── ReportLab ──────────────────────────────────────────────────────────────
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    HRFlowable,
    Image as RLImage,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.models.analysis import AnalysisResponse, ChannelAnalysisResponse
from app.models.report import ReportConfig
from app.models.waveform import ChannelData, WaveformDataResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------

PAGE_W, PAGE_H = A4                    # 595 × 842 pt
MARGIN         = 1.5 * cm
USABLE_W       = PAGE_W - 2 * MARGIN  # ~18 cm

PLOT_WAVE_H    = 7.0 * cm
PLOT_FFT_H     = 5.0 * cm

# ---------------------------------------------------------------------------
# Color palette (professional light theme, print-friendly)
# ---------------------------------------------------------------------------

C_NAVY    = HexColor('#0d1b2e')
C_BLUE    = HexColor('#1e40af')
C_PASS    = HexColor('#166534')
C_FAIL    = HexColor('#991b1b')
C_NT      = HexColor('#374151')
C_PASS_BG = HexColor('#dcfce7')
C_FAIL_BG = HexColor('#fee2e2')
C_NT_BG   = HexColor('#f3f4f6')
C_LGRAY   = HexColor('#e5e7eb')
C_MGRAY   = HexColor('#9ca3af')
C_DGRAY   = HexColor('#374151')
C_STRIPE  = HexColor('#f9fafb')

# Matplotlib channel colors (colorblind-safe, print-friendly)
_MPL_CH_COLORS: dict[str, str] = {
    'CH1': '#1d4ed8',
    'CH2': '#c2410c',
    'CH3': '#7c3aed',
    'CH4': '#047857',
}
_MPL_CH_DEFAULT = ['#1d4ed8', '#c2410c', '#7c3aed', '#047857']


def _mpl_color(channel_id: str, index: int) -> str:
    return _MPL_CH_COLORS.get(channel_id, _MPL_CH_DEFAULT[index % 4])


# ---------------------------------------------------------------------------
# ReportLab styles
# ---------------------------------------------------------------------------

def _build_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        'title': ParagraphStyle(
            'RptTitle', parent=base['Title'],
            fontSize=18, textColor=C_NAVY, spaceAfter=2,
            fontName='Helvetica-Bold', alignment=TA_LEFT,
        ),
        'subtitle': ParagraphStyle(
            'RptSubtitle', fontSize=9, textColor=C_MGRAY,
            spaceAfter=0, fontName='Helvetica', alignment=TA_LEFT,
        ),
        'h1': ParagraphStyle(
            'RptH1', fontSize=11, textColor=C_NAVY, spaceAfter=4,
            spaceBefore=10, fontName='Helvetica-Bold',
        ),
        'h2': ParagraphStyle(
            'RptH2', fontSize=9, textColor=C_BLUE, spaceAfter=3,
            spaceBefore=6, fontName='Helvetica-Bold',
        ),
        'body': ParagraphStyle(
            'RptBody', fontSize=8, textColor=C_DGRAY, spaceAfter=2,
            fontName='Helvetica', leading=12,
        ),
        'mono': ParagraphStyle(
            'RptMono', fontSize=7, textColor=C_DGRAY,
            fontName='Courier', leading=10,
        ),
        'verdict_pass': ParagraphStyle(
            'VerdictPass', fontSize=24, textColor=C_PASS,
            fontName='Helvetica-Bold', alignment=TA_CENTER,
        ),
        'verdict_fail': ParagraphStyle(
            'VerdictFail', fontSize=24, textColor=C_FAIL,
            fontName='Helvetica-Bold', alignment=TA_CENTER,
        ),
        'verdict_nt': ParagraphStyle(
            'VerdictNT', fontSize=24, textColor=C_NT,
            fontName='Helvetica-Bold', alignment=TA_CENTER,
        ),
    }


# ---------------------------------------------------------------------------
# SI unit formatter
# ---------------------------------------------------------------------------

def _si(value: float | None, unit: str, digits: int = 4) -> str:
    """Format a scalar value with SI prefix scaling."""
    if value is None:
        return 'N/A'
    if value == 0:
        return f'0 {unit}'
    abs_v = abs(value)
    if abs_v >= 1e6:
        return f'{value / 1e6:.{digits}f} M{unit}'
    if abs_v >= 1e3:
        return f'{value / 1e3:.{digits}f} k{unit}'
    if abs_v >= 1:
        return f'{value:.{digits}f} {unit}'
    if abs_v >= 1e-3:
        return f'{value * 1e3:.{digits}f} m{unit}'
    if abs_v >= 1e-6:
        return f'{value * 1e6:.{digits}f} µ{unit}'
    if abs_v >= 1e-9:
        return f'{value * 1e9:.{digits}f} n{unit}'
    return f'{value * 1e12:.{digits}f} p{unit}'


# ---------------------------------------------------------------------------
# Matplotlib plot renderers
# ---------------------------------------------------------------------------

_MAX_PLOT_POINTS = 5_000   # downsample threshold for PDF clarity


def _downsample(data: list[float], n: int) -> list[float]:
    if len(data) <= n:
        return data
    step = max(1, len(data) // n)
    return data[::step]


def _render_waveform_plot(
    waveform: WaveformDataResponse,
    channel_ids: Optional[list[str]] = None,
) -> io.BytesIO:
    """
    Render a time-domain waveform plot for the given channels.

    Parameters
    ----------
    waveform    : Full measurement record.
    channel_ids : Which channels to include.  None → all channels.

    Returns
    -------
    PNG image as a BytesIO buffer (position reset to 0).
    """
    channels = [
        ch for ch in waveform.channels
        if channel_ids is None or ch.channel_id in channel_ids
    ]

    fig, ax = plt.subplots(figsize=(USABLE_W / cm, PLOT_WAVE_H / cm), dpi=130)
    fig.patch.set_facecolor('white')
    ax.set_facecolor('#f8fafc')

    for i, ch in enumerate(channels):
        t_ms = _downsample([t * 1_000 for t in ch.time_s], _MAX_PLOT_POINTS)
        v    = _downsample(ch.voltage_v, _MAX_PLOT_POINTS)
        ax.plot(t_ms, v, linewidth=0.9, label=ch.channel_id,
                color=_mpl_color(ch.channel_id, i), alpha=0.92)

    ax.set_xlabel('Time (ms)', fontsize=8)
    ax.set_ylabel('Voltage (V)', fontsize=8)
    ax.tick_params(labelsize=7)
    ax.grid(True, linewidth=0.4, alpha=0.35)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    if len(channels) > 1:
        ax.legend(fontsize=7, loc='upper right', framealpha=0.7)

    buf = io.BytesIO()
    try:
        fig.tight_layout()
        fig.savefig(buf, format='png', dpi=130, bbox_inches='tight',
                    facecolor='white')
    finally:
        plt.close(fig)

    buf.seek(0)
    return buf


def _render_fft_plot(
    ch_result: ChannelAnalysisResponse,
    channel_index: int = 0,
) -> io.BytesIO:
    """
    Render a single-sided FFT magnitude spectrum for one channel.

    Returns
    -------
    PNG image as a BytesIO buffer (position reset to 0).
    """
    freqs_khz = [f / 1_000 for f in ch_result.fft_frequencies]
    mags      = ch_result.fft_magnitudes
    dom_khz   = ch_result.dominant_fft_freq_hz / 1_000
    color     = _mpl_color(ch_result.channel_id, channel_index)

    fig, ax = plt.subplots(figsize=(USABLE_W / cm, PLOT_FFT_H / cm), dpi=130)
    fig.patch.set_facecolor('white')
    ax.set_facecolor('#f8fafc')

    ax.plot(freqs_khz, mags, linewidth=0.9, color=color)
    ax.fill_between(freqs_khz, mags, alpha=0.12, color=color)
    ax.axvline(
        x=dom_khz, color='#dc2626', linewidth=0.8, linestyle='--',
        label=f'f₀ = {_si(ch_result.dominant_fft_freq_hz, "Hz", 2)}',
    )

    ax.set_xlabel('Frequency (kHz)', fontsize=8)
    ax.set_ylabel('Magnitude (V)', fontsize=8)
    ax.tick_params(labelsize=7)
    ax.grid(True, linewidth=0.4, alpha=0.35)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.legend(fontsize=7, framealpha=0.7)
    ax.set_xlim(left=0)
    ax.yaxis.set_minor_locator(mticker.AutoMinorLocator())

    buf = io.BytesIO()
    try:
        fig.tight_layout()
        fig.savefig(buf, format='png', dpi=130, bbox_inches='tight',
                    facecolor='white')
    finally:
        plt.close(fig)

    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# ReportLab table helpers
# ---------------------------------------------------------------------------

def _tbl_style(
    *,
    row_stripe: bool = True,
    verdict_col: Optional[int] = None,
    verdict_rows: Optional[list[tuple[int, str]]] = None,
) -> TableStyle:
    """
    Build a standard TableStyle.  Optionally colour a verdict column.

    Parameters
    ----------
    row_stripe     : Alternate row background.
    verdict_col    : Column index that contains verdict text (0-based).
    verdict_rows   : List of (row_index, verdict) to individually colour.
    """
    cmds: list = [
        ('BACKGROUND',    (0, 0), (-1, 0),  C_NAVY),
        ('TEXTCOLOR',     (0, 0), (-1, 0),  colors.white),
        ('FONTNAME',      (0, 0), (-1, 0),  'Helvetica-Bold'),
        ('FONTSIZE',      (0, 0), (-1, 0),  8),
        ('FONTNAME',      (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE',      (0, 1), (-1, -1), 8),
        ('GRID',          (0, 0), (-1, -1), 0.4, C_LGRAY),
        ('LEFTPADDING',   (0, 0), (-1, -1), 7),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 7),
        ('TOPPADDING',    (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
    ]
    if row_stripe:
        cmds.append(('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, C_STRIPE]))

    if verdict_rows:
        for row_i, verdict in verdict_rows:
            col = verdict_col if verdict_col is not None else -1
            bg  = C_PASS_BG if verdict == 'PASS' else (C_FAIL_BG if verdict == 'FAIL' else C_NT_BG)
            fg  = C_PASS    if verdict == 'PASS' else (C_FAIL    if verdict == 'FAIL' else C_NT)
            cmds += [
                ('BACKGROUND', (col, row_i), (col, row_i), bg),
                ('TEXTCOLOR',  (col, row_i), (col, row_i), fg),
                ('FONTNAME',   (col, row_i), (col, row_i), 'Helvetica-Bold'),
            ]

    return TableStyle(cmds)


# ---------------------------------------------------------------------------
# Flowable builders
# ---------------------------------------------------------------------------

def _divider(width: float = USABLE_W) -> HRFlowable:
    return HRFlowable(width=width, thickness=0.5, color=C_LGRAY, spaceAfter=6, spaceBefore=2)


def _verdict_block(
    verdict: str,
    styles: dict[str, ParagraphStyle],
) -> Table:
    """
    Render a large coloured verdict box as a 1-cell Table.
    """
    symbol  = '✓' if verdict == 'PASS' else ('✗' if verdict == 'FAIL' else '○')
    label   = verdict
    bg      = C_PASS_BG if verdict == 'PASS' else (C_FAIL_BG if verdict == 'FAIL' else C_NT_BG)
    fg      = C_PASS    if verdict == 'PASS' else (C_FAIL    if verdict == 'FAIL' else C_NT)

    style_key = 'verdict_pass' if verdict == 'PASS' else ('verdict_fail' if verdict == 'FAIL' else 'verdict_nt')
    text = Paragraph(f'{symbol}  {label}', styles[style_key])

    tbl = Table([[text]], colWidths=[USABLE_W])
    tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), bg),
        ('TOPPADDING',    (0, 0), (-1, -1), 14),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 14),
        ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
        ('BOX',           (0, 0), (-1, -1), 1.5, fg),
        ('ROUNDEDCORNERS', [4]),
    ]))
    return tbl


def _summary_table(
    analysis: AnalysisResponse,
    styles: dict[str, ParagraphStyle],
) -> Table:
    """Per-channel summary — Frequency, Vpp, Vrms, Verdict."""
    header = ['Channel', 'Frequency', 'V peak-peak', 'V RMS', 'Verdict']
    rows: list[list[str]] = [header]

    verdict_rows: list[tuple[int, str]] = []
    for i, ch in enumerate(analysis.channels, start=1):
        verdict_rows.append((i, ch.overall_verdict))
        rows.append([
            ch.channel_id,
            _si(ch.frequency_hz,    'Hz'),
            _si(ch.v_peak_to_peak,  'V'),
            _si(ch.v_rms,           'V'),
            ch.overall_verdict,
        ])

    col_w = [3 * cm, 4 * cm, 4 * cm, 4 * cm, 3.2 * cm]
    tbl = Table(rows, colWidths=col_w)
    tbl.setStyle(_tbl_style(verdict_col=4, verdict_rows=verdict_rows))
    return tbl


def _metrics_table(
    ch: ChannelAnalysisResponse,
    styles: dict[str, ParagraphStyle],
) -> Table:
    """Full metrics table for one channel."""
    defs = [
        ('Frequency',        _si(ch.frequency_hz,         'Hz')),
        ('Period',           _si(ch.period_s,             's')),
        ('FFT dominant freq',_si(ch.dominant_fft_freq_hz, 'Hz')),
        ('V peak-to-peak',   _si(ch.v_peak_to_peak,       'V')),
        ('V RMS (total)',     _si(ch.v_rms,               'V')),
        ('V RMS (AC)',        _si(ch.v_rms_ac,            'V')),
        ('V mean (DC)',       _si(ch.v_mean,              'V')),
        ('V min',            _si(ch.v_min,               'V')),
        ('V max',            _si(ch.v_max,               'V')),
        ('Avg Power',        _si(ch.avg_power_w,         'W')  + f'  (R={ch.load_resistance_ohms} Ω)'),
        ('Duty Cycle',       f'{ch.duty_cycle_pct:.2f} %' if ch.duty_cycle_pct is not None else 'N/A'),
        ('Rise Time',        _si(ch.rise_time_s,         's') if ch.rise_time_s is not None else 'N/A'),
        ('Fall Time',        _si(ch.fall_time_s,         's') if ch.fall_time_s is not None else 'N/A'),
    ]

    header = ['Parameter', 'Measured Value']
    rows   = [header] + [[label, val] for label, val in defs]
    col_w  = [USABLE_W * 0.48, USABLE_W * 0.52]

    tbl = Table(rows, colWidths=col_w)
    tbl.setStyle(_tbl_style())
    return tbl


def _limits_table(
    ch: ChannelAnalysisResponse,
    styles: dict[str, ParagraphStyle],
) -> Optional[Table]:
    """
    Limit-check results table, or None if no limits were applied.
    """
    if not ch.limit_results:
        return None

    header = ['Spec', 'Measured', 'Min', 'Max', 'Unit', 'Status']
    rows: list[list[str]] = [header]
    verdict_rows: list[tuple[int, str]] = []

    for i, r in enumerate(ch.limit_results, start=1):
        verdict_rows.append((i, r.status))
        rows.append([
            r.spec_name,
            f'{r.measured_value:.5g}',
            f'{r.min_value}' if r.min_value is not None else '—',
            f'{r.max_value}' if r.max_value is not None else '—',
            r.unit or '—',
            r.status,
        ])

    col_w = [3.5*cm, 3*cm, 2.5*cm, 2.5*cm, 2*cm, 2.8*cm]
    tbl = Table(rows, colWidths=col_w)
    tbl.setStyle(_tbl_style(verdict_col=5, verdict_rows=verdict_rows))
    return tbl


# ---------------------------------------------------------------------------
# Page builders
# ---------------------------------------------------------------------------

def _build_summary_page(
    waveform:  WaveformDataResponse,
    analysis:  AnalysisResponse,
    config:    ReportConfig,
    styles:    dict[str, ParagraphStyle],
    ts:        str,
) -> list:
    """Build all flowables for Page 1 (summary / cover)."""
    S = styles
    elems: list = []

    # ── Title block ────────────────────────────────────────────────────────
    elems.append(Paragraph(config.title, S['title']))
    elems.append(Spacer(1, 2 * mm))
    elems.append(_divider())

    # Metadata grid
    meta_rows = [
        ['Date / Time',  ts,                                  'Analysis ID', analysis.analysis_id[:18] + '…'],
        ['Engineer',     config.engineer_name or '—',         'Project Ref', config.project_ref or '—'],
        ['Source',       waveform.source.upper(),             'Filename',    waveform.metadata.get('filename', '—')],
        ['Channels',     ', '.join(ch.channel_id for ch in waveform.channels),
         'Sample Rate',  waveform.metadata.get('sample_rate_hz', '—') + ' Sa/s'
                         if 'sample_rate_hz' in waveform.metadata else '—'],
        ['Capture Time', waveform.metadata.get('duration_s', '—') + ' s'
                         if 'duration_s' in waveform.metadata else '—',
         'N Samples',    waveform.metadata.get('n_samples', '—')],
    ]
    meta_style = TableStyle([
        ('FONTNAME',      (0, 0), (0, -1),  'Helvetica-Bold'),
        ('FONTNAME',      (2, 0), (2, -1),  'Helvetica-Bold'),
        ('FONTSIZE',      (0, 0), (-1, -1), 8),
        ('TEXTCOLOR',     (0, 0), (0, -1),  C_DGRAY),
        ('TEXTCOLOR',     (2, 0), (2, -1),  C_DGRAY),
        ('TEXTCOLOR',     (1, 0), (1, -1),  C_NAVY),
        ('TEXTCOLOR',     (3, 0), (3, -1),  C_NAVY),
        ('GRID',          (0, 0), (-1, -1), 0.3, C_LGRAY),
        ('LEFTPADDING',   (0, 0), (-1, -1), 6),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 6),
        ('TOPPADDING',    (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('ROWBACKGROUNDS',(0, 0), (-1, -1), [colors.white, C_STRIPE]),
    ])
    meta_tbl = Table(meta_rows, colWidths=[3.5*cm, 5*cm, 3.5*cm, 6.2*cm])
    meta_tbl.setStyle(meta_style)
    elems.append(meta_tbl)

    # ── Channel summary table ───────────────────────────────────────────────
    elems.append(Spacer(1, 4 * mm))
    elems.append(Paragraph('Channel Summary', S['h1']))
    elems.append(_summary_table(analysis, styles))

    # ── Overall verdict ─────────────────────────────────────────────────────
    verdicts = [ch.overall_verdict for ch in analysis.channels]
    overall = (
        'FAIL'       if 'FAIL'       in verdicts else
        'PASS'       if all(v == 'PASS' for v in verdicts) else
        'NOT_TESTED'
    )
    elems.append(Spacer(1, 4 * mm))
    elems.append(Paragraph('Overall Test Verdict', S['h1']))
    elems.append(_verdict_block(overall, styles))

    return elems


def _build_channel_page(
    waveform:       WaveformDataResponse,
    ch_result:      ChannelAnalysisResponse,
    channel_index:  int,
    config:         ReportConfig,
    styles:         dict[str, ParagraphStyle],
) -> list:
    """Build all flowables for one channel detail page."""
    S = styles
    elems: list = []

    # Header
    elems.append(Paragraph(f'Channel {ch_result.channel_id} — Detailed Analysis', S['h1']))

    # Sample-rate subtitle
    ch_data = next(
        (c for c in waveform.channels if c.channel_id == ch_result.channel_id),
        None,
    )
    if ch_data:
        elems.append(Paragraph(
            f'{ch_data.n_samples:,} samples  ·  '
            f'{_si(ch_data.sample_rate_hz, "Sa/s", 3)}  ·  '
            f'{_si(len(ch_data.time_s) / ch_data.sample_rate_hz, "s", 4)} capture',
            S['subtitle'],
        ))
    elems.append(_divider())

    # Waveform plot
    if config.include_waveform_plot and ch_data:
        elems.append(Paragraph('Time-Domain Waveform', S['h2']))
        buf = _render_waveform_plot(waveform, channel_ids=[ch_result.channel_id])
        elems.append(RLImage(buf, width=USABLE_W, height=PLOT_WAVE_H))
        elems.append(Spacer(1, 3 * mm))

    # FFT plot
    if config.include_fft_plot:
        elems.append(Paragraph('FFT Magnitude Spectrum', S['h2']))
        fft_buf = _render_fft_plot(ch_result, channel_index=channel_index)
        elems.append(RLImage(fft_buf, width=USABLE_W, height=PLOT_FFT_H))
        elems.append(Spacer(1, 3 * mm))

    # Metrics table
    elems.append(Paragraph('Measurements', S['h2']))
    elems.append(_metrics_table(ch_result, styles))

    # Limit results (optional)
    limit_tbl = _limits_table(ch_result, styles)
    if limit_tbl:
        elems.append(Spacer(1, 3 * mm))
        elems.append(Paragraph('Limit Check Results', S['h2']))
        elems.append(limit_tbl)

        # Per-channel verdict
        elems.append(Spacer(1, 3 * mm))
        elems.append(_verdict_block(ch_result.overall_verdict, styles))

    return elems


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_report(
    waveform:  WaveformDataResponse,
    analysis:  AnalysisResponse,
    config:    ReportConfig,
) -> bytes:
    """
    Generate a complete multi-page A4 PDF report.

    Parameters
    ----------
    waveform  : Raw measurement data (needed for waveform plots).
    analysis  : Computed metrics and limit results.
    config    : User-supplied title, engineer name, plot flags, etc.

    Returns
    -------
    bytes
        Raw PDF data ready for streaming or file storage.
    """
    ts = datetime.now(tz=timezone.utc).strftime('%Y-%m-%d  %H:%M UTC')
    styles = _build_styles()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
        title=config.title,
        author=config.engineer_name or 'Lab Measurement Platform',
        subject=f'Analysis ID: {analysis.analysis_id}',
    )

    story: list = []

    # Page 1 — Summary
    story.extend(_build_summary_page(waveform, analysis, config, styles, ts))

    # Pages 2+ — Per-channel detail
    for idx, ch_result in enumerate(analysis.channels):
        story.append(PageBreak())
        story.extend(
            _build_channel_page(waveform, ch_result, idx, config, styles)
        )

    doc.build(story)
    pdf_bytes = buf.getvalue()
    logger.info(
        "generate_report: produced %d-byte PDF for analysis_id=%s (%d channels)",
        len(pdf_bytes),
        analysis.analysis_id,
        len(analysis.channels),
    )
    return pdf_bytes
