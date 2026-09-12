"""Small shims so the bridge runs on the Python that ships with macOS.

Stock macOS has 3.9. Requiring 3.11 would mean installing a Python, which is
the same install-step problem that `pyserial` used to be - and the reason an
earlier design tried to avoid the host entirely by making the deck a keyboard.
Two shims are a cheap price for "copy the folder and run it".
"""

from __future__ import annotations

import enum
import sys

if sys.version_info >= (3, 11):
    StrEnum = enum.StrEnum
else:
    class StrEnum(str, enum.Enum):  # type: ignore[no-redef]
        """enum.StrEnum, which arrived in 3.11.

        Subclassing str keeps `Edge.DOWN == "DOWN"` true, which the protocol
        parsing relies on.
        """

        def __str__(self) -> str:
            return str(self.value)
