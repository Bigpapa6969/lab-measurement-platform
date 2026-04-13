"""
csv_parser.py — Oscilloscope & SPICE CSV Parser
=================================================
Parses waveform data from files exported by common lab instruments and
simulation tools.  Supports four formats via auto-detection:

    RIGOL     — DS/MSO series default CSV export
    TEKTRONIX — MSO/DPO series default CSV export
    LTSPICE   — LTspice XVII tab-separated output
    GENERIC   — Any single-header CSV with a time column

Returned dataclass
------------------
    ParsedWaveform
        .channels : list[ParsedChannel]  — name, time array, voltage array
        .metadata : dict[str, str]       — capture parameters, format tag
        .source_format : str

Usage
-----
    from app.services.ingestion.csv_parser import parse_csv

    # From a file path:
    waveform = parse_csv(path="capture.csv")

    # From bytes (e.g., FastAPI UploadFile):
    waveform = parse_csv(content=await upload.read(), filename="capture.csv")
"""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import numpy.typing as npt
import pandas as pd

logger = logging.getLogger(__name__)
FloatArray = npt.NDArray[np.float64]

# Maximum lines to read when sniffing the format
_SNIFF_LINES = 30
# Channels whose column headers we recognise automatically
_CHANNEL_ALIASES = re.compile(
    r"^(ch\d+|channel\s*\d+|v\(.*\)|i\(.*\)|volt.*|current.*|trace\s*\d+)$",
    re.IGNORECASE,
)
_TIME_ALIASES = re.compile(r"^(time|x|t|seconds?|sec|s)$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------


@dataclass
class ParsedChannel:
    """Holds the time and voltage arrays for a single waveform channel."""
    channel_id: str
    time_s: FloatArray
    voltage_v: FloatArray
    unit: str = "V"

    @property
    def sample_rate_hz(self) -> float:
        """Inferred sample rate from the mean time step [Hz]."""
        if len(self.time_s) < 2:
            return 0.0
        return float(1.0 / np.mean(np.diff(self.time_s)))

    @property
    def n_samples(self) -> int:
        return len(self.time_s)


@dataclass
class ParsedWaveform:
    """Top-level result of a parse operation."""
    channels: list[ParsedChannel]
    metadata: dict[str, str] = field(default_factory=dict)
    source_format: str = "generic"

    @property
    def channel_ids(self) -> list[str]:
        return [ch.channel_id for ch in self.channels]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def parse_csv(
    *,
    path: Optional[str] = None,
    content: Optional[bytes] = None,
    filename: str = "upload.csv",
) -> ParsedWaveform:
    """
    Parse oscilloscope or SPICE CSV data into a ``ParsedWaveform``.

    Supply exactly one of ``path`` or ``content``.

    Parameters
    ----------
    path     : Path to a CSV file on disk.
    content  : Raw bytes (e.g., from an HTTP upload).
    filename : Original filename; used only to improve error messages.

    Returns
    -------
    ParsedWaveform

    Raises
    ------
    ValueError
        If neither or both sources are provided, or the file cannot be parsed.
    """
    if path is None and content is None:
        raise ValueError("Supply either 'path' or 'content', not neither.")
    if path is not None and content is not None:
        raise ValueError("Supply either 'path' or 'content', not both.")

    if path is not None:
        with open(path, "rb") as fh:
            content = fh.read()

    assert content is not None  # mypy

    # Decode — try UTF-8 then latin-1 (most instrument exports)
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    lines = text.splitlines()
    if not lines:
        raise ValueError(f"'{filename}' appears to be empty.")

    fmt = _detect_format(lines[:_SNIFF_LINES])
    logger.info("csv_parser: detected format='%s' for file '%s'", fmt, filename)

    parsers = {
        "rigol":     _parse_rigol,
        "tektronix": _parse_tektronix,
        "ltspice":   _parse_ltspice,
        "generic":   _parse_generic,
    }
    try:
        result = parsers[fmt](lines, filename)
    except Exception as exc:
        # Re-raise with format context for cleaner error messages upstream
        raise ValueError(
            f"Failed to parse '{filename}' as {fmt} format: {exc}"
        ) from exc

    if not result.channels:
        raise ValueError(
            f"'{filename}' was parsed as {fmt} format but contained no data channels."
        )

    result.source_format = fmt
    return result


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------


def _detect_format(lines: list[str]) -> str:
    """
    Identify the CSV dialect from the first ``_SNIFF_LINES`` lines.

    Detection priority:
        1. Rigol   — second non-empty line contains "Second" and/or "Volt"
        2. LTspice — first data line is tab-separated and starts with "time"
        3. Tektronix — metadata keys like "Record Length" present
        4. Generic — fallback
    """
    non_empty = [l.strip() for l in lines if l.strip()]

    if len(non_empty) >= 2:
        first_lower = non_empty[0].lower()
        second_lower = non_empty[1].lower()
        if (first_lower.startswith("x,") or ",ch" in first_lower) and (
            "second" in second_lower or "volt" in second_lower
        ):
            return "rigol"

    if non_empty:
        first_lower = non_empty[0].lower()
        if "\t" in first_lower and first_lower.split("\t")[0].strip() in ("time", "t"):
            return "ltspice"

    for line in non_empty[:_SNIFF_LINES]:
        low = line.lower()
        if "record length" in low or "sample interval" in low or "tektronix" in low:
            return "tektronix"

    return "generic"


# ---------------------------------------------------------------------------
# Format-specific parsers
# ---------------------------------------------------------------------------


def _parse_rigol(lines: list[str], filename: str) -> ParsedWaveform:
    """
    Parse Rigol DS/MSO series CSV export.

    Expected structure::

        X,CH1,CH2,...
        Second,Volt,Volt,...
        -1.000000e-03,2.48e-01,1.60e-02,...
    """
    metadata: dict[str, str] = {"instrument_family": "Rigol"}

    # Find the first line that looks like the column-header row (starts with X or time)
    header_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip().lower()
        if stripped.startswith("x,") or re.match(r"^(time|x)\s*[,\t]", stripped):
            header_idx = i
            break

    if header_idx is None:
        raise ValueError("Could not find column header row (expected 'X,CH1,...').")

    col_headers = [c.strip() for c in lines[header_idx].split(",")]

    # Row immediately after headers is the units row — skip it in data
    units_idx = header_idx + 1
    data_start = units_idx + 1

    df = pd.read_csv(
        io.StringIO("\n".join(lines[data_start:])),
        header=None,
        names=col_headers,
        dtype=np.float64,
        on_bad_lines="skip",
    )

    time_col = col_headers[0]
    time_s = df[time_col].to_numpy(dtype=np.float64)

    channels: list[ParsedChannel] = []
    for col in col_headers[1:]:
        if col.strip() == "":
            continue
        if col not in df.columns:
            continue
        v = df[col].to_numpy(dtype=np.float64)
        channels.append(ParsedChannel(channel_id=col, time_s=time_s.copy(), voltage_v=v))

    return ParsedWaveform(channels=channels, metadata=metadata, source_format="rigol")


def _parse_tektronix(lines: list[str], filename: str) -> ParsedWaveform:
    """
    Parse Tektronix MSO/DPO series CSV export.

    These files start with several metadata key-value rows before the
    actual column headers appear.  We scan forward to find the first row
    whose left-most cell matches a time-like name.

    Example structure::

        Model,MSO54B
        Firmware Version,1.24.0
        ...
        Record Length,10000,Samples
        Sample Interval,1.0E-08,Seconds
        ...
        Time,CH1,MATH1
        -5.0E-05,0.1234,0.0001
    """
    metadata: dict[str, str] = {"instrument_family": "Tektronix"}

    # Extract metadata key-value pairs
    header_idx = None
    for i, line in enumerate(lines):
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2:
            key_lower = parts[0].lower()
            if key_lower in ("model", "firmware version", "record length",
                             "sample interval", "trigger point", "source"):
                if len(parts) >= 2:
                    metadata[parts[0]] = parts[1]
            if _TIME_ALIASES.match(key_lower):
                header_idx = i
                break

    if header_idx is None:
        raise ValueError("Could not find 'Time' column header row in Tektronix file.")

    col_headers = [c.strip() for c in lines[header_idx].split(",")]
    df = pd.read_csv(
        io.StringIO("\n".join(lines[header_idx + 1:])),
        header=None,
        names=col_headers,
        dtype=np.float64,
        on_bad_lines="skip",
    )

    time_col = col_headers[0]
    time_s = df[time_col].to_numpy(dtype=np.float64)

    channels: list[ParsedChannel] = []
    for col in col_headers[1:]:
        if col.strip() == "" or col not in df.columns:
            continue
        v = df[col].to_numpy(dtype=np.float64)
        channels.append(ParsedChannel(channel_id=col, time_s=time_s.copy(), voltage_v=v))

    return ParsedWaveform(channels=channels, metadata=metadata, source_format="tektronix")


def _parse_ltspice(lines: list[str], filename: str) -> ParsedWaveform:
    """
    Parse LTspice XVII tab-separated waveform output.

    Structure::

        time\\tV(out)\\tV(in)\\tI(R1)
        0.000000e+00\\t3.3\\t0.0\\t6.6e-04
        ...

    Voltage nets are kept as-is; current nets are prefixed with ``I_``.
    """
    metadata: dict[str, str] = {"instrument_family": "LTspice"}

    # First non-empty line is the header
    header_line = next((l for l in lines if l.strip()), None)
    if header_line is None:
        raise ValueError("LTspice file has no header line.")

    col_headers = [h.strip() for h in header_line.split("\t")]
    df = pd.read_csv(
        io.StringIO("\n".join(lines[1:])),
        sep="\t",
        header=None,
        names=col_headers,
        dtype=np.float64,
        on_bad_lines="skip",
    )

    time_col = col_headers[0]
    time_s = df[time_col].to_numpy(dtype=np.float64)

    channels: list[ParsedChannel] = []
    for col in col_headers[1:]:
        if col.strip() == "" or col not in df.columns:
            continue
        unit = "A" if col.upper().startswith("I(") else "V"
        v = df[col].to_numpy(dtype=np.float64)
        channels.append(
            ParsedChannel(channel_id=col, time_s=time_s.copy(), voltage_v=v, unit=unit)
        )

    return ParsedWaveform(channels=channels, metadata=metadata, source_format="ltspice")


def _parse_generic(lines: list[str], filename: str) -> ParsedWaveform:
    """
    Flexible fallback parser for any well-formed CSV.

    Strategy
    --------
    1. Skip leading comment lines (start with ``#``).
    2. Scan rows from the top until one that is *entirely numeric* is found.
    3. The row immediately before the first numeric row is treated as headers.
    4. If no header row can be identified, synthesise column names.

    Handles comma and tab separators.  Unit rows (rows with non-numeric cells
    after the header) are automatically skipped.
    """
    metadata: dict[str, str] = {"instrument_family": "generic"}

    # Strip comments
    data_lines = [l for l in lines if not l.strip().startswith("#")]

    # Detect separator (comma vs tab)
    sep = "\t" if "\t" in (data_lines[0] if data_lines else "") else ","

    def _is_numeric_row(line: str) -> bool:
        try:
            parts = line.strip().split(sep)
            [float(p) for p in parts if p.strip()]
            return True
        except ValueError:
            return False

    header_idx: Optional[int] = None
    first_data_idx: Optional[int] = None

    for i, line in enumerate(data_lines):
        if _is_numeric_row(line):
            first_data_idx = i
            header_idx = i - 1 if i > 0 and not _is_numeric_row(data_lines[i - 1]) else None
            break

    if first_data_idx is None:
        raise ValueError("No numeric data rows found in the file.")

    # Build column names
    if header_idx is not None:
        raw_headers = [h.strip() for h in data_lines[header_idx].split(sep)]
    else:
        n_cols = len(data_lines[first_data_idx].split(sep))
        raw_headers = ["time"] + [f"CH{i}" for i in range(1, n_cols)]

    # Re-parse with pandas from first_data_idx onwards
    # Skip any non-numeric rows that may follow the header (unit rows)
    numeric_lines = [l for l in data_lines[first_data_idx:] if _is_numeric_row(l)]

    df = pd.read_csv(
        io.StringIO("\n".join(numeric_lines)),
        header=None,
        names=raw_headers[: len(numeric_lines[0].split(sep))],
        sep=sep,
        dtype=np.float64,
        on_bad_lines="skip",
    )

    # Identify time column
    time_col_name = next(
        (col for col in df.columns if _TIME_ALIASES.match(str(col))),
        df.columns[0],
    )
    time_s = df[time_col_name].to_numpy(dtype=np.float64)

    channels: list[ParsedChannel] = []
    for col in df.columns:
        if col == time_col_name:
            continue
        v = df[col].to_numpy(dtype=np.float64)
        channels.append(
            ParsedChannel(channel_id=str(col), time_s=time_s.copy(), voltage_v=v)
        )

    return ParsedWaveform(channels=channels, metadata=metadata, source_format="generic")
