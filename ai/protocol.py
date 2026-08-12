"""
Shared debugger protocol primitives.

These helpers define the stable data contract between the debugger backend
(FakeDOSBoxDebugger today, the native DOSBox-X bridge later) and the MCP
tool layer: address parsing/formatting and the ok/error response envelope.
"""

from typing import Any


class DebuggerError(Exception):
    """Raised for any invalid request the debugger backend rejects."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def parse_address(address: str) -> tuple[int, int]:
    """Parse a "SEG:OFF" human-friendly address into (segment, offset) ints."""

    if not isinstance(address, str) or ":" not in address:
        raise DebuggerError("INVALID_ADDRESS", f"Malformed address: {address!r}")

    seg_str, off_str = address.split(":", 1)

    try:
        segment = int(seg_str, 16)
        offset = int(off_str, 16)
    except ValueError:
        raise DebuggerError("INVALID_ADDRESS", f"Malformed address: {address!r}")

    if not (0 <= segment <= 0xFFFF) or not (0 <= offset <= 0xFFFF):
        raise DebuggerError("INVALID_ADDRESS", f"Address out of range: {address!r}")

    return segment, offset


def format_address(segment: int, offset: int) -> str:
    return f"{segment:04X}:{offset:04X}"


def linear_address(segment: int, offset: int) -> int:
    """Real-mode style linear address: segment * 16 + offset."""

    return segment * 16 + offset


def ok(result: Any) -> dict:
    return {"ok": True, "result": result}


def error(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}
