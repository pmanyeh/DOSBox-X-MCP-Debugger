"""
Shared fixtures for the Phase 9A composite-capture acceptance tests
(docs/phase9a-composite-capture-design.md, section 9).

Unlike the older integration tests, which assume someone already started
DOSBox-X by hand, these tests launch their own DOSBox-X instance running
drive_c/COMPTEST.COM with a specific output backend and window size, and
kill it afterwards -- several tests need different configurations.

Requirements (the tests skip, not fail, when these are missing):
- a built dosbox-src/bin/x64/Release/dosbox-x.exe (Windows),
- nothing else listening on the AI bridge port 127.0.0.1:9876.

Environment knobs:
- PHASE9A_FULLSCREEN=1 also runs the fullscreen geometry case (it takes
  over the display for a few seconds, so it is opt-in).
"""

import base64
import socket
import struct
import subprocess
import sys
import time
import zlib
from contextlib import contextmanager
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "ai"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dosbox_client import DOSBoxClient  # noqa: E402
import make_comptest  # noqa: E402

EXE = REPO / "dosbox-src" / "bin" / "x64" / "Release" / "dosbox-x.exe"
HOST, PORT = "127.0.0.1", 9876


def _port_open() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=0.5):
            return True
    except OSError:
        return False


def pytest_collection_modifyitems(config, items):
    reason = None
    if sys.platform != "win32" or not EXE.exists():
        reason = f"needs a built {EXE}"
    elif _port_open():
        reason = f"something is already listening on {HOST}:{PORT} -- close other DOSBox-X instances first"
    if reason:
        for item in items:
            if "phase9a" in str(item.fspath):
                item.add_marker(pytest.mark.skip(reason=reason))


@contextmanager
def launch_dosbox(output="direct3d", windowresolution=None, fullscreen=False, extra_sets=()):
    """Start DOSBox-X running COMPTEST.COM and yield a connected client
    once the guest has switched to mode 13h. Always kills the process."""

    if _port_open():
        pytest.fail(f"{HOST}:{PORT} is still in use -- another DOSBox-X instance is running")
    make_comptest.OUTPUT.write_bytes(make_comptest.build())
    args =[str(EXE), "-defaultdir", "-set", f"sdl output={output}"]
    if windowresolution:
        args += ["-set", f"sdl windowresolution={windowresolution}"]
    if fullscreen:
        args += ["-set", "sdl fullscreen=true"]
    for s in extra_sets:
        args += ["-set", s]
    args += ["-c", f"mount c {REPO / 'drive_c'}", "-c", "c:", "-c", "COMPTEST.COM"]
    proc = subprocess.Popen(args, cwd=str(REPO))
    client = DOSBoxClient()
    try:
        deadline = time.time() + 20
        while not _port_open():
            if proc.poll() is not None or time.time() > deadline:
                pytest.fail(f"DOSBox-X did not open the AI bridge (exit code {proc.poll()})")
            time.sleep(0.2)
        # Wait until COMPTEST has set mode 13h (render_src 640x400).
        while True:
            try:
                meta = client.capture_frame(format="rgba", max_width=16)
                if meta["width"] == 16 and meta["height"] == 10:
                    break
            except Exception:
                pass
            if time.time() > deadline:
                pytest.fail("COMPTEST.COM never reached mode 13h")
            time.sleep(0.3)
        time.sleep(0.5)  # let the window settle at its final size
        yield client
    finally:
        client.close()
        proc.kill()
        proc.wait(timeout=10)
        deadline = time.time() + 10
        while _port_open() and time.time() < deadline:
            time.sleep(0.2)


@pytest.fixture(scope="module")
def d3d():
    with launch_dosbox("direct3d") as client:
        yield client


# ---- image helpers --------------------------------------------------------


class RGBAImage:
    def __init__(self, width, height, data):
        assert len(data) == width * height * 4
        self.width, self.height, self.data = width, height, data

    @classmethod
    def from_result(cls, result, key_w="width", key_h="height"):
        if "rgba_base64" in result:
            return cls(result[key_w], result[key_h], base64.b64decode(result["rgba_base64"]))
        w, h, data = decode_png(base64.b64decode(result["png_base64"]))
        return cls(w, h, data)

    def px(self, x, y):
        i = (y * self.width + x) * 4
        return tuple(self.data[i:i + 4])


def decode_png(blob):
    """Minimal PNG decoder for the bridge's own output (8-bit RGBA,
    non-interlaced) -- avoids a Pillow dependency."""

    assert blob[:8] == b"\x89PNG\r\n\x1a\n", "bad PNG signature"
    pos, idat, width = 8, b"", None
    while pos < len(blob):
        (length,) = struct.unpack(">I", blob[pos:pos + 4])
        ctype = blob[pos + 4:pos + 8]
        body = blob[pos + 8:pos + 8 + length]
        (crc,) = struct.unpack(">I", blob[pos + 8 + length:pos + 12 + length])
        assert zlib.crc32(ctype + body) & 0xFFFFFFFF == crc, f"bad CRC in {ctype!r}"
        if ctype == b"IHDR":
            width, height, depth, color, _, _, interlace = struct.unpack(">IIBBBBB", body)
            assert (depth, color, interlace) == (8, 6, 0), (depth, color, interlace)
        elif ctype == b"IDAT":
            idat += body
        elif ctype == b"IEND":
            break
        pos += 12 + length
    raw = zlib.decompress(idat)
    stride, bpp = width * 4, 4
    out = bytearray(stride * height)
    prev = bytearray(stride)
    for y in range(height):
        ftype = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if ftype == 1:
                line[i] = (line[i] + a) & 0xFF
            elif ftype == 2:
                line[i] = (line[i] + b) & 0xFF
            elif ftype == 3:
                line[i] = (line[i] + ((a + b) >> 1)) & 0xFF
            elif ftype == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                line[i] = (line[i] + pred) & 0xFF
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return width, height, bytes(out)


def close(c1, c2, tol):
    return all(abs(a - b) <= tol for a, b in zip(c1[:3], c2[:3]))


# ---- geometry helpers ------------------------------------------------------

PAL = make_comptest.PALETTE_RGB
ALL_MARKERS = make_comptest.MARKERS_A + make_comptest.MARKERS_B
SET_A, SET_B = (True, True, False, False), (False, False, True, True)


def viewport(meta):
    v = meta["geometry"]["viewport"]
    return v["x"], v["y"], v["w"], v["h"]


def native_to_output(meta, gx, gy):
    """Center of native pixel (gx, gy) in back-buffer coordinates."""
    vx, vy, vw, vh = viewport(meta)
    n = meta["geometry"]["guest_native"]
    return int(vx + (gx + 0.5) * vw / n["w"]), int(vy + (gy + 0.5) * vh / n["h"])


def find_frame_edges(img, meta, tol=48):
    """Locates COMPTEST's four colored 1-pixel frame edges in a
    crop="full" capture by scanning inward along the viewport's center
    lines. Returns (left, top, right, bottom) in back-buffer pixels."""

    ct = make_comptest
    vx, vy, vw, vh = viewport(meta)
    cx, cy = vx + vw // 2, vy + vh // 2
    top = next(y for y in range(img.height) if close(img.px(cx, y), PAL[ct.BORDER_TOP], tol))
    bottom = next(y for y in reversed(range(img.height)) if close(img.px(cx, y), PAL[ct.BORDER_BOTTOM], tol))
    left = next(x for x in range(img.width) if close(img.px(x, cy), PAL[ct.BORDER_LEFT], tol))
    right = next(x for x in reversed(range(img.width)) if close(img.px(x, cy), PAL[ct.BORDER_RIGHT], tol))
    return left, top, right, bottom


def markers_in_composite(img, meta):
    """Presence of each of COMPTEST's four markers (A1, A2, B1, B2) at its
    center in a crop="full" capture."""
    return tuple(close(img.px(*native_to_output(meta, x + w // 2, y + h // 2)), PAL[c], 48)
                 for x, y, w, h, c in ALL_MARKERS)


def markers_in_source(src, meta):
    """Same as markers_in_composite(), for the pre-scaler source image."""
    n = meta["geometry"]["guest_native"]
    sx, sy = src.width / n["w"], src.height / n["h"]
    return tuple(close(src.px(int((x + w // 2 + 0.5) * sx), int((y + h // 2 + 0.5) * sy)), PAL[c], 0)
                 for x, y, w, h, c in ALL_MARKERS)


def assert_frame_matches_viewport(r):
    img = RGBAImage.from_result(r)
    vx, vy, vw, vh = viewport(r)
    left, top, right, bottom = find_frame_edges(img, r)
    assert abs(left - vx) <= 1, (left, vx)
    assert abs(top - vy) <= 1, (top, vy)
    assert abs(right - (vx + vw - 1)) <= 1, (right, vx + vw - 1)
    assert abs(bottom - (vy + vh - 1)) <= 1, (bottom, vy + vh - 1)
