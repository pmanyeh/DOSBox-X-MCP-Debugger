"""
Phase 9A acceptance tests for video.composite.capture / capture_composite
(docs/phase9a-composite-capture-design.md, section 9) that share ONE
DOSBox-X instance (output=direct3d, default window) launched by
conftest.launch_dosbox() running drive_c/COMPTEST.COM. Tests that need a
different backend or window size are in test_composite_geometry.py.

T8 (window covered by another window), T10 (resize/fullscreen switch
while running), T11 (pixel shaders) and T15 (zero idle overhead) need a
human at the machine and are manual checks -- see the design doc.
"""

import base64
import time

import pytest

from conftest import (
    SET_A,
    SET_B,
    RGBAImage,
    decode_png,
    markers_in_composite,
    markers_in_source,
)
from dosbox_client import (
    DOSBoxCropOutOfBounds,
    DOSBoxExecutionTimeout,
    DOSBoxFrameTooLarge,
    DOSBoxProtocolError,
)


# ---- T1, T2, T7 --------------------------------------------------------------


def test_t1_png_valid_and_matches_reported_size(d3d):
    r = d3d.capture_composite(format="png")
    blob = base64.b64decode(r["png_base64"])
    assert blob[:8] == b"\x89PNG\r\n\x1a\n"
    w, h, _ = decode_png(blob)
    assert (w, h) == (r["width"], r["height"])
    assert r["pixel_format"] == "rgba8888"
    assert r["layers"] == ["dos_image"]


def test_t2_backend_and_geometry_reported(d3d):
    r = d3d.capture_composite(format="rgba", max_width=64)
    assert r["backend"] == "direct3d"
    g = r["geometry"]
    assert g["render_src"] == {"w": 640, "h": 400}
    assert g["guest_native"] == {"w": 320, "h": 200}
    assert g["pixel_shader"] == "none"
    v = g["viewport"]
    assert g["scale"]["x"] == pytest.approx(v["w"] / 320, rel=1e-4)
    assert g["scale"]["y"] == pytest.approx(v["h"] / 200, rel=1e-4)


def test_t7_static_screen_still_captures(d3d):
    # COMPTEST sits in INT 16h with an unchanging screen; the bridge must
    # force a present rather than wait out the timeout.
    for _ in range(3):
        t = time.time()
        r = d3d.capture_composite(format="rgba", max_width=32)
        assert time.time() - t < 2.0
        assert r["source_frame_match"] is True
        assert r["presented_render_seq"] == r["target_render_seq"]


def test_crop_modes_and_parameter_validation(d3d):
    full = d3d.capture_composite(format="rgba", crop="full")
    bb = full["geometry"]["backbuffer"]
    assert (full["width"], full["height"]) == (bb["w"], bb["h"])
    vp = d3d.capture_composite(format="rgba")
    assert vp["crop_rect"] == full["geometry"]["viewport"]

    r = d3d.capture_composite(format="rgba", rect={"x": 10, "y": 20, "w": 30, "h": 40})
    assert (r["width"], r["height"]) == (30, 40)
    assert r["crop_rect"] == {"x": 10, "y": 20, "w": 30, "h": 40}

    with pytest.raises(DOSBoxCropOutOfBounds):
        d3d.capture_composite(rect={"x": bb["w"] - 5, "y": 0, "w": 10, "h": 10})
    with pytest.raises(DOSBoxCropOutOfBounds):
        d3d.capture_composite(game_rect={"x": 310, "y": 0, "w": 20, "h": 10})
    with pytest.raises(DOSBoxCropOutOfBounds):
        d3d.capture_composite(game_rect={"x": 0, "y": 0, "w": 0, "h": 10})
    for bad in ({"crop": "full", "rect": {"x": 0, "y": 0, "w": 1, "h": 1}},
                {"format": "bmp"},
                {"crop": "middle"},
                {"rect": {"x": 0, "y": 0, "w": 1}}):
        with pytest.raises(DOSBoxProtocolError) as e:
            d3d.capture_composite(**bad)
        assert e.value.code == "INVALID_PARAMETER", bad

    small = d3d.capture_composite(format="rgba", crop="full", max_width=100)
    assert small["width"] <= 100 and small["scaled"] is True


# ---- T6: frame correspondence across a marker switch -----------------------


def test_t6_source_and_composite_from_same_frame(d3d):
    """Capture right after each key press: the frame may even be one the
    guest is halfway through redrawing, but source and composite must
    always agree marker-for-marker -- never a mix of old and new frames."""
    def capture_and_compare():
        r = d3d.capture_composite(format="rgba", crop="full", include_source=True)
        assert r["source_frame_match"] is True
        comp = RGBAImage.from_result(r)
        src = RGBAImage.from_result(r["source"])
        s, c = markers_in_source(src, r), markers_in_composite(comp, r)
        assert s == c, (s, c)
        return c

    settled = set()
    for _ in range(8):
        d3d.key_tap("space")
        capture_and_compare()          # immediately: possibly mid-redraw
        time.sleep(0.3)
        settled.add(capture_and_compare())
    assert SET_A in settled and SET_B in settled, settled


# ---- T9: stopped guest times out, then recovers ----------------------------


def test_t9_breakpoint_times_out_then_recovers(d3d):
    d3d.pause_execution()
    try:
        with pytest.raises(DOSBoxExecutionTimeout):
            d3d.capture_composite(format="rgba", max_width=16)
    finally:
        d3d.continue_execution()
    r = d3d.capture_composite(format="rgba", max_width=16)
    assert r["width"] <= 16


# ---- T13: stability --------------------------------------------------------


def test_t13_fifty_captures_then_status_ok(d3d):
    seqs = []
    for i in range(50):
        r = d3d.capture_composite(format="png" if i % 2 else "rgba", max_width=200)
        seqs.append(r["presented_render_seq"])
    assert seqs == sorted(seqs)
    assert "stopped" in d3d.get_debug_status()


# ---- T14: payload cap ------------------------------------------------------


def test_t14_payload_cap(d3d):
    r = d3d.capture_composite(format="rgba", crop="full", max_width=64)
    bb = r["geometry"]["backbuffer"]
    if bb["w"] * bb["h"] * 4 <= 8 * 1024 * 1024:
        full = d3d.capture_composite(format="rgba", crop="full")
        assert len(base64.b64decode(full["rgba_base64"])) == bb["w"] * bb["h"] * 4
    else:
        with pytest.raises(DOSBoxFrameTooLarge) as e:
            d3d.capture_composite(format="rgba", crop="full")
        assert "suggested_max_width" in str(e.value)


# ---- Phase 7A regression: capture_frame unchanged in shape ------------------


def test_capture_frame_still_matches_composite_source(d3d):
    """capture_frame and include_source come from the same unpacker; on a
    static screen they must be byte-identical."""
    r = d3d.capture_composite(format="rgba", include_source=True)
    f = d3d.capture_frame(format="rgba")
    assert (f["width"], f["height"]) == (r["source"]["width"], r["source"]["height"]) == (640, 400)
    assert f["rgba_base64"] == r["source"]["rgba_base64"]
