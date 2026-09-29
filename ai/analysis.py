"""
Agent-side analysis helpers for autonomous reverse engineering (Phase 8C).

These are deliberately NOT native bridge methods. Everything here is built
by composing the existing native protocol (DOSBoxClient's memory.read,
code.disassemble, cpu.get -- see docs/dosbox-ai-bridge.md) from the Python
side, matching this project's stated design principle of never adding a
second CPU/disassembler/memory-reading mechanism (see
docs/phase8c-agent-side-analysis-tools-design.md for the full rationale).

search_memory() is the first piece implemented (Phase 8C, priority 1).
get_call_stack() and build_control_flow_graph() follow the same principle
-- see each function's docstring for its own scope and limitations.
"""

import re
from typing import Optional, Union

from dosbox_client import DOSBoxMemoryError

PatternElement = Union[int, str, None]

# 0x1000 paragraphs * 16 bytes/paragraph == 0x10000 bytes -- stepping the
# segment forward by this amount between full chunks advances the linear
# address by exactly one chunk with no gap and no overlap, regardless of
# where within a segment the scan started (see
# docs/phase8c-agent-side-analysis-tools-design.md, "Crossing segment
# boundaries without duplicating a linear-address model").
_SEGMENT_PARAGRAPH_STEP = 0x1000
_CHUNK_BYTES = 0x10000  # matches memory.read's own per-call cap
_MAX_SEARCH_LENGTH = 0x100000  # the entire real-mode address space (1 MiB)


def _parse_seg_off(address: str) -> tuple[int, int]:
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
    return segment, offset


def _compile_pattern(pattern: list) -> list:
    """Compile a byte-spec list (ints 0-255, 2-digit hex strings, or
    "??"/"?"/None wildcards) into a list of int | None, one per byte."""

    if not pattern:
        raise ValueError("pattern must be a non-empty list")

    compiled = []
    for element in pattern:
        if element is None:
            compiled.append(None)
        elif isinstance(element, bool):
            raise TypeError(f"pattern element must be int, str, or None, got {type(element).__name__}")
        elif isinstance(element, str):
            if element in ("??", "?"):
                compiled.append(None)
            else:
                try:
                    value = int(element, 16)
                except ValueError:
                    raise ValueError(f"invalid pattern byte: {element!r}") from None
                if not (0 <= value <= 0xFF):
                    raise ValueError(f"pattern byte out of range: {element!r}")
                compiled.append(value)
        elif isinstance(element, int):
            if not (0 <= element <= 0xFF):
                raise ValueError(f"pattern byte out of range: {element!r}")
            compiled.append(element)
        else:
            raise TypeError(f"pattern element must be int, str, or None, got {type(element).__name__}")
    return compiled


def _compile_text_pattern(text: str, case_sensitive: bool) -> list:
    if not isinstance(text, str) or not text:
        raise ValueError("text must be a non-empty string")
    try:
        raw = text.encode("ascii")
    except UnicodeEncodeError:
        raise ValueError(
            "text must be ASCII -- DOS guest memory holds 8-bit text, not Unicode"
        ) from None

    if case_sensitive:
        return list(raw)

    compiled = []
    for b in raw:
        ch = chr(b)
        if ch.isalpha():
            compiled.append(frozenset({ord(ch.lower()), ord(ch.upper())}))
        else:
            compiled.append(b)
    return compiled


def _find_all(buffer: bytes, compiled_pattern: list) -> list:
    """Return every start index in `buffer` where compiled_pattern matches."""

    n = len(buffer)
    m = len(compiled_pattern)
    if m == 0 or m > n:
        return []

    if all(isinstance(e, int) for e in compiled_pattern):
        needle = bytes(compiled_pattern)
        matches = []
        start = 0
        while True:
            idx = buffer.find(needle, start)
            if idx == -1:
                return matches
            matches.append(idx)
            start = idx + 1

    matches = []
    for i in range(n - m + 1):
        ok = True
        for j, element in enumerate(compiled_pattern):
            b = buffer[i + j]
            if element is None:
                continue
            if isinstance(element, int):
                if b != element:
                    ok = False
                    break
            elif b not in element:
                ok = False
                break
        if ok:
            matches.append(i)
    return matches


def search_memory(
    client,
    start_address: str,
    length: int,
    pattern: Optional[list] = None,
    text: Optional[str] = None,
    case_sensitive: bool = True,
    max_matches: int = 1000,
) -> dict:
    """Scan real-mode guest memory for a byte pattern (with optional "??"
    wildcards) or an ASCII string, starting at `start_address` ("SEG:OFF")
    over `length` bytes (1..0x100000, the whole real-mode address space).
    Built entirely out of repeated calls to `client.read_memory()` -- no
    new native bridge method, no second memory-reading mechanism.

    Give exactly one of `pattern` (a list of byte specs -- each an int
    0-255, a 2-digit hex string, or "??"/"?"/None for "match any byte",
    e.g. ["B8", "??", "12"]) or `text` (matched as raw ASCII bytes;
    `case_sensitive=False` matches either case per letter).

    Crosses segment boundaries by always reading up to the end of the
    current segment first, then stepping the segment forward by 0x1000
    (one full 0x10000-byte chunk) per subsequent full chunk -- this can
    never trigger the native bridge's own 16-bit offset wraparound within
    a single memory.read call (see docs/dosbox-ai-bridge.md,
    code.disassemble's "16-bit wraparound" note), and covers the scanned
    range with no gap and no overlap regardless of `start_address`'s
    initial offset.

    A chunk the native bridge reports MEMORY_ERROR for (unmapped/
    inaccessible guest memory) is skipped, not treated as a failure or as
    zero bytes -- see "unreadable_regions" in the result. This matches
    this project's "no fake data" rule: a skipped range is reported,
    never silently invented as a match or a non-match.

    Result: {"matches": ["SEG:OFF", ...], "scanned_bytes": int,
    "unreadable_regions": [{"address": "SEG:OFF", "length": int}],
    "truncated": bool}. Match addresses are canonicalized
    (`linear_address >> 4 : linear_address & 0xF`) so that every match,
    including one whose true segment:offset pair would need an offset
    above 0xFFFF, is still expressible in "SEG:OFF" form.
    `truncated` is true if `max_matches` cut scanning short before
    `length` bytes were covered.
    """

    if (pattern is None) == (text is None):
        raise ValueError("exactly one of pattern or text must be given")

    compiled = _compile_pattern(pattern) if pattern is not None else _compile_text_pattern(text, case_sensitive)
    pattern_len = len(compiled)

    if not isinstance(length, int) or length <= 0:
        raise ValueError(f"length must be a positive int, got {length!r}")
    if length > _MAX_SEARCH_LENGTH:
        raise ValueError(f"length exceeds the {_MAX_SEARCH_LENGTH:#x}-byte real-mode address space cap")
    if not isinstance(max_matches, int) or max_matches <= 0:
        raise ValueError(f"max_matches must be a positive int, got {max_matches!r}")

    segment, offset = _parse_seg_off(start_address)

    matches: list = []
    unreadable_regions: list = []
    scanned_bytes = 0
    truncated = False

    carry = b""
    carry_linear_start: Optional[int] = None

    remaining = length
    while remaining > 0 and not truncated:
        chunk_linear_start = segment * 16 + offset
        chunk_len = min(remaining, _CHUNK_BYTES - offset)

        try:
            result = client.read_memory(f"{segment:04X}:{offset:04X}", chunk_len)
            chunk = bytes(int(b, 16) for b in result["bytes"])
        except DOSBoxMemoryError:
            unreadable_regions.append({"address": f"{segment:04X}:{offset:04X}", "length": chunk_len})
            carry = b""
            carry_linear_start = None
        else:
            if carry:
                haystack = carry + chunk
                haystack_linear_start = carry_linear_start
            else:
                haystack = chunk
                haystack_linear_start = chunk_linear_start

            for idx in _find_all(haystack, compiled):
                match_linear = haystack_linear_start + idx
                matches.append(f"{match_linear >> 4:04X}:{match_linear & 0xF:04X}")
                if len(matches) >= max_matches:
                    truncated = True
                    break

            if pattern_len > 1 and not truncated:
                keep = min(pattern_len - 1, len(haystack))
                carry = haystack[-keep:] if keep else b""
                carry_linear_start = haystack_linear_start + len(haystack) - keep if keep else None
            else:
                carry = b""
                carry_linear_start = None

        scanned_bytes += chunk_len
        remaining -= chunk_len
        offset += chunk_len
        if offset >= _CHUNK_BYTES:
            offset -= _CHUNK_BYTES
            segment += _SEGMENT_PARAGRAPH_STEP

    return {
        "matches": matches,
        "scanned_bytes": scanned_bytes,
        "unreadable_regions": unreadable_regions,
        "truncated": truncated,
    }


def _canonicalize_seg_off(segment: int, offset: int) -> str:
    linear = segment * 16 + offset
    return f"{linear >> 4:04X}:{linear & 0xF:04X}"


def get_call_stack(client, max_frames: int = 32) -> dict:
    """Walk the real-mode SS:BP frame-pointer chain from the debugger's
    current stopped position -- the same manual technique a human doing
    real-mode stack unwinding already uses. Built entirely out of one
    cpu.get call (for the starting SS/CS/BP) plus repeated memory.read
    calls (to follow each frame) -- no new native bridge method.

    Scope limitation, stated rather than silently guessed around: each
    frame's saved BP is read from [BP], and its return OFFSET from
    [BP+2], assuming a standard PUSH BP / MOV BP,SP prologue and a NEAR
    (same-segment) CALL -- this is the calling convention this project's
    own DOS test programs use (see e.g. drive_c/STEP.COM). A FAR call's
    4-byte return address (segment:offset) would be misread as two
    unrelated 2-byte fields by this implementation; there is no formal
    frame-pointer metadata in 16-bit real-mode code this tool could
    consult instead to tell the two cases apart.

    The walk stops (rather than guessing further) once a saved BP is not
    strictly greater than the current frame's BP -- real-mode stacks
    grow downward, so a genuine parent frame's BP must sit at a
    numerically greater offset than its child's; this also naturally
    halts on a zero/uninitialized BP chain (e.g. before a program's first
    PUSH BP / MOV BP,SP), and on unmapped/inaccessible stack memory
    (native MEMORY_ERROR).

    Result: {"frames": [{"bp": "SS:BP", "return_address": "CS:offset"},
    ...], "truncated": bool}. `return_address`'s segment is always the
    CURRENT CS (a near return address carries no segment of its own) --
    NOT necessarily the segment the caller actually called from; see the
    near-call limitation above. `truncated` is true if `max_frames` was
    reached before an invalid/implausible BP ended the walk.
    """

    if not isinstance(max_frames, int) or max_frames <= 0:
        raise ValueError(f"max_frames must be a positive int, got {max_frames!r}")

    cpu = client.get_cpu_state()
    ss = int(cpu["ss"], 16)
    cs = int(cpu["cs"], 16)
    bp = int(cpu["ebp"], 16) & 0xFFFF

    frames: list = []
    truncated = False

    while bp != 0:
        if len(frames) >= max_frames:
            truncated = True
            break
        try:
            result = client.read_memory(f"{ss:04X}:{bp:04X}", 4)
            raw = bytes(int(b, 16) for b in result["bytes"])
        except DOSBoxMemoryError:
            break

        saved_bp = raw[0] | (raw[1] << 8)
        return_offset = raw[2] | (raw[3] << 8)
        frames.append({
            "bp": f"{ss:04X}:{bp:04X}",
            "return_address": f"{cs:04X}:{return_offset:04X}",
        })

        if saved_bp <= bp:
            break
        bp = saved_bp

    return {"frames": frames, "truncated": truncated}


# Matches a DasmI386-rendered near JMP/Jcc/CALL/LOOP*/JCXZ instruction's
# resolvable relative operand: dosbox-src/src/debug/debug_disasm.cpp's
# case 'J' renders it as an 8-hex-digit value (addr_to_hex(..., splitup=0)
# -> "%08X"), optionally preceded by "short "/"near "/"far " (from a %K
# prefix -- only the near JMP-short opcode 0xEB actually emits "short ";
# the others never emit a prefix here, but this tolerates one either way).
# A far JMP/CALL (%Ap) or an indirect JMP/CALL through a register/memory
# operand (%Ev/%Ep) renders a register name or bracketed memory operand
# instead of a bare 8-hex-digit token, so this deliberately does not match
# those -- see build_control_flow_graph()'s "Scope limitation".
_NEAR_BRANCH_RE = re.compile(r"^(j\w*|call|loop\w*)\s+(?:short|near|far)?\s*([0-9a-f]{8})$")
_RETURN_MNEMONICS = {"ret", "retf", "retn", "iret"}


def _extract_near_branch_target(instruction_text: str) -> Optional[int]:
    """Return the target OFFSET (within the same segment as the
    instruction) of a resolvable near JMP/Jcc/CALL/LOOP*/JCXZ, or None for
    anything this cannot confidently resolve (far/indirect transfer,
    RET/IRET/INT, or any non-branch instruction) -- never a guess."""

    match = _NEAR_BRANCH_RE.match(instruction_text.strip().lower())
    if not match:
        return None
    return int(match.group(2), 16) & 0xFFFF


def build_control_flow_graph(
    client,
    start_address: str,
    max_blocks: int = 64,
    max_instructions_per_block: int = 64,
) -> dict:
    """Build a control-flow graph by recursively walking `code.disassemble`
    from `start_address`, splitting a new block at every resolvable near
    branch and following its target(s) -- entirely reusing the native
    bridge's own disassembler output. No second disassembler is added
    (this was an explicit architecture decision -- see
    docs/phase8c-agent-side-analysis-tools-design.md, "Architecture
    decision"): a jump table or an offline .EXE/.COM parser was
    considered and rejected in favor of this live, same-disassembler
    walk.

    Scope limitation, stated rather than silently guessed around: only
    NEAR, same-segment control flow (JMP/Jcc/CALL/LOOP*/JCXZ with a
    directly-encoded relative target) is followed. A block ending in a
    far JMP/CALL, an indirect JMP/CALL through a register or memory
    operand, or RET/IRET/INT has NO followed successor -- its
    "unresolved_transfer" field names which kind of transfer stopped the
    walk there ("return", "software_interrupt", or
    "indirect_or_far_transfer") rather than fabricating a guessed target.
    A CALL's target block is explored like any other successor, but --
    unlike a strict textbook basic-block CFG -- does not by itself
    prevent the calling block from also continuing past the CALL (both
    the call target and the post-CALL fallthrough address are recorded
    as this block's successors), since the call is expected to return
    under normal (non-crashing) execution. This can under-explore a
    real program's actual reachable code (e.g. a jump table, or an
    INT 21h call that itself transfers elsewhere) -- callers needing
    that coverage must supply additional `start_address` values from
    other evidence (`memory_search`, manual investigation, or
    single-stepping).

    Only explores code already loaded into guest memory -- the debugger
    must be stopped, and `start_address` must be a real, currently
    readable address; this does not load or execute anything, and never
    changes execution state.

    Result: {"blocks": {"SEG:OFF": {"instructions": [...],
    "successors": ["SEG:OFF", ...], "unresolved_transfer": str|None},
    ...}, "truncated": bool}. Each block's `instructions` is the same
    shape `disassemble()` returns. Every address (block keys and
    successors alike) is canonicalized (segment = linear_address >> 4,
    offset = linear_address & 0xF), matching search_memory()'s
    convention, so the same linear address is never split across two
    different block entries. `truncated` is true if `max_blocks` was
    reached before the walk ran out of new addresses to visit.
    """

    if not isinstance(max_blocks, int) or max_blocks <= 0:
        raise ValueError(f"max_blocks must be a positive int, got {max_blocks!r}")
    if not isinstance(max_instructions_per_block, int) or max_instructions_per_block <= 0:
        raise ValueError(
            f"max_instructions_per_block must be a positive int, got {max_instructions_per_block!r}"
        )

    start_segment, start_offset = _parse_seg_off(start_address)
    start_key = _canonicalize_seg_off(start_segment, start_offset)

    blocks: dict = {}
    queue = [start_key]
    queued = {start_key}

    while queue and len(blocks) < max_blocks:
        address = queue.pop(0)
        if address in blocks:
            continue

        block_segment, _ = _parse_seg_off(address)
        batch = client.disassemble(address, max_instructions_per_block)

        instructions: list = []
        successors: list = []
        unresolved_transfer = None
        ended = False

        for i, instr in enumerate(batch):
            instructions.append(instr)
            text = instr.get("instruction", "")
            stripped = text.strip()
            mnemonic = stripped.split()[0].lower() if stripped else ""

            target_offset = _extract_near_branch_target(text)
            if target_offset is not None:
                successors.append(_canonicalize_seg_off(block_segment, target_offset))
                if mnemonic != "jmp":
                    fallthrough = _instruction_after(batch, i, block_segment)
                    if fallthrough is not None:
                        successors.append(fallthrough)
                ended = True
                break

            if mnemonic in _RETURN_MNEMONICS:
                unresolved_transfer = "return"
                ended = True
                break
            if mnemonic == "int":
                unresolved_transfer = "software_interrupt"
                ended = True
                break
            if mnemonic in ("jmp", "call"):
                unresolved_transfer = "indirect_or_far_transfer"
                ended = True
                break

        if not ended and batch:
            fallthrough = _instruction_after(batch, len(batch) - 1, block_segment)
            if fallthrough is not None:
                successors.append(fallthrough)

        blocks[address] = {
            "instructions": instructions,
            "successors": successors,
            "unresolved_transfer": unresolved_transfer,
        }

        for successor in successors:
            if successor not in blocks and successor not in queued:
                queue.append(successor)
                queued.add(successor)

    return {"blocks": blocks, "truncated": bool(queue)}


def _instruction_after(batch: list, index: int, segment: int) -> Optional[str]:
    """The canonicalized address of the instruction immediately following
    batch[index] -- the next batch entry's own address if there is one,
    else computed from batch[index]'s address plus its decoded length."""

    if index + 1 < len(batch):
        seg, off = _parse_seg_off(batch[index + 1]["address"])
        return _canonicalize_seg_off(seg, off)

    instr = batch[index]
    _, off = _parse_seg_off(instr["address"])
    length = len(instr["bytes"].split())
    return _canonicalize_seg_off(segment, off + length)
