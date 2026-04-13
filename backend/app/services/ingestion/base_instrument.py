"""
base_instrument.py — Abstract Instrument Interface
====================================================
Defines the contract every instrument driver must satisfy, whether it wraps a
real PyVISA resource, a file-based parser, or a software mock.

Concrete subclasses only need to implement the four abstract methods.
Context-manager support comes for free from this base class.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]


class InstrumentError(Exception):
    """Raised for any instrument-level failure (connection, timeout, protocol)."""


class BaseInstrument(ABC):
    """
    Abstract base class for lab instruments.

    Contract
    --------
    - ``connect()``     — open the resource (VISA address, serial port, …)
    - ``disconnect()``  — release the resource cleanly
    - ``get_identity()``— return an *IDN?-style string for logging
    - ``get_waveform()``— acquire one channel, return (time_s, voltage_v) arrays

    Context-manager usage (preferred)::

        with MockOscilloscope(...) as scope:
            t, v = scope.get_waveform("CH1")
    """

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def connect(self) -> None:
        """Open the instrument resource.  Idempotent — safe to call twice."""
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """Release the instrument resource.  Idempotent — safe to call twice."""
        ...

    @abstractmethod
    def get_identity(self) -> str:
        """
        Return a human-readable instrument identification string.

        Equivalent to the IEEE 488.2 ``*IDN?`` query on real hardware.
        Format: ``<Manufacturer>,<Model>,<Serial>,<Firmware>``
        """
        ...

    @abstractmethod
    def get_waveform(
        self,
        channel: str,
        n_samples: Optional[int] = None,
    ) -> tuple[FloatArray, FloatArray]:
        """
        Acquire a waveform from *channel*.

        Parameters
        ----------
        channel   : str
            Channel identifier, e.g. ``"CH1"``, ``"CH2"``.
        n_samples : int, optional
            Number of samples to acquire.  If None, the instrument's
            current record-length setting is used.

        Returns
        -------
        (time_s, voltage_v) : tuple[FloatArray, FloatArray]
            Both arrays are 1-D, uniformly sampled, dtype float64.
            ``time_s``   starts at 0 (or relative to trigger).
            ``voltage_v`` is in Volts.

        Raises
        ------
        InstrumentError
            If the channel is not available or acquisition fails.
        """
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """True when the instrument resource is open and usable."""
        ...

    # ------------------------------------------------------------------
    # Concrete helpers (shared by all subclasses)
    # ------------------------------------------------------------------

    def __enter__(self) -> "BaseInstrument":
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.disconnect()

    def __repr__(self) -> str:
        state = "connected" if self.is_connected else "disconnected"
        return f"<{type(self).__name__} [{state}]>"
