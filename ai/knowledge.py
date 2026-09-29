"""
Persistent symbol/annotation knowledge store for autonomous reverse
engineering (Phase 8C, item 2).

Lives entirely on the agent side -- DOSBox-X and the native bridge have no
notion of this data and are never asked to store or retrieve it; nothing
here is a native bridge method. Addresses are canonicalized the same way
analysis.py's search_memory()/build_control_flow_graph() are (segment =
linear_address >> 4, offset = linear_address & 0xF) before being used as
keys, so a symbol/comment/xref set through one SEG:OFF representation of
an address is found again through any other representation of the same
linear address. See docs/phase8c-agent-side-analysis-tools-design.md.
"""

import json
from pathlib import Path
from typing import Optional

DEFAULT_STORE_PATH = Path(__file__).resolve().parent / "knowledge.local.json"

VALID_XREF_KINDS = ("call", "jump", "data", "other")


def _canonical_address(address: str) -> str:
    if not isinstance(address, str) or ":" not in address:
        raise ValueError(f"malformed address: {address!r}")
    seg_str, off_str = address.split(":", 1)
    try:
        segment = int(seg_str, 16)
        offset = int(off_str, 16)
    except ValueError:
        raise ValueError(f"malformed address: {address!r}") from None
    if not (0 <= segment <= 0xFFFF) or not (0 <= offset <= 0xFFFF):
        raise ValueError(f"address out of range: {address!r}")
    linear = segment * 16 + offset
    return f"{linear >> 4:04X}:{linear & 0xF:04X}"


class KnowledgeStore:
    """A small, JSON-file-backed database of symbols, comments, and
    cross-references, keyed by canonical address. Not thread-safe --
    matches DOSBoxClient's own "one caller at a time" assumption, since
    both are driven by the same single-threaded MCP server process.
    Every mutating call saves immediately (no explicit flush needed) so a
    crashed session never loses an already-acknowledged write."""

    def __init__(self, path: Optional[str] = None):
        self.path = Path(path) if path else DEFAULT_STORE_PATH
        self._symbols: dict = {}
        self._comments: dict = {}
        self._xrefs: list = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        self._symbols = data.get("symbols", {})
        self._comments = data.get("comments", {})
        self._xrefs = data.get("xrefs", [])

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"symbols": self._symbols, "comments": self._comments, "xrefs": self._xrefs}
        self.path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    def set_symbol(self, address: str, name: str) -> dict:
        if not isinstance(name, str) or not name:
            raise ValueError("name must be a non-empty string")
        canonical = _canonical_address(address)
        self._symbols[canonical] = name
        self.save()
        return {"address": canonical, "name": name}

    def get_symbol(self, address: str) -> dict:
        canonical = _canonical_address(address)
        return {"address": canonical, "name": self._symbols.get(canonical)}

    def delete_symbol(self, address: str) -> dict:
        canonical = _canonical_address(address)
        existed = self._symbols.pop(canonical, None) is not None
        if existed:
            self.save()
        return {"address": canonical, "deleted": existed}

    def list_symbols(self) -> dict:
        return {"symbols": [{"address": a, "name": n} for a, n in sorted(self._symbols.items())]}

    def set_comment(self, address: str, text: str) -> dict:
        if not isinstance(text, str) or not text:
            raise ValueError("text must be a non-empty string")
        canonical = _canonical_address(address)
        self._comments[canonical] = text
        self.save()
        return {"address": canonical, "text": text}

    def get_comment(self, address: str) -> dict:
        canonical = _canonical_address(address)
        return {"address": canonical, "text": self._comments.get(canonical)}

    def add_xref(self, from_address: str, to_address: str, kind: str = "call") -> dict:
        if kind not in VALID_XREF_KINDS:
            raise ValueError(f"kind must be one of {VALID_XREF_KINDS}, got {kind!r}")
        entry = {
            "from": _canonical_address(from_address),
            "to": _canonical_address(to_address),
            "kind": kind,
        }
        if entry not in self._xrefs:
            self._xrefs.append(entry)
            self.save()
        return entry

    def list_xrefs(self, address: str, direction: str = "to") -> dict:
        if direction not in ("to", "from", "both"):
            raise ValueError(f"direction must be 'to', 'from', or 'both', got {direction!r}")
        canonical = _canonical_address(address)
        matches = [
            x
            for x in self._xrefs
            if (direction in ("to", "both") and x["to"] == canonical)
            or (direction in ("from", "both") and x["from"] == canonical)
        ]
        return {"address": canonical, "xrefs": matches}
