"""
Phase 9A acceptance tests that need their own DOSBox-X configuration
(docs/phase9a-composite-capture-design.md, section 9): viewport geometry
(T3), game_rect conversion (T4) and composite/source agreement (T5) across
backends and window sizes. Unsupported backends (T12) and fullscreen are
in test_composite_backends.py, so their instances never overlap the
module-scoped one here.
"""

import pytest

import make_comptest as ct
from conftest import (
    assert_frame_matches_viewport,
    PAL,
    RGBAImage,
    SET_A,
    close,
    launch_dosbox,
    markers_in_composite,
)

GEOMETRY_CASES = [
    pytest.param(("direct3d", None), id="d3d-original"),
    pytest.param(("direct3d", "1280x800"), id="d3d-1280x800"),
    pytest.param(("direct3d", "1000x700"), id="d3d-1000x700"),
    pytest.param(("surface", None), id="surface-original"),
    pytest.param(("surface", "1000x700"), id="surface-1000x700"),
]


@pytest.fixture(scope="module", params=GEOMETRY_CASES)
def configured(request):
    output, res = request.param
    with launch_dosbox(output, windowresolution=res) as client:
        yield output, client


def test_t3_viewport_matches_detected_frame(configured):
    output, client = configured
    r = client.capture_composite(format="rgba", crop="full")
    assert r["backend"] == output
    assert_frame_matches_viewport(r)


def test_t4_game_rect_crops_marker(configured):
    """The interior of a game_rect crop around a marker is >= 95% marker
    color. A 2-pixel band along the crop's edges is excluded: that is
    where floor/ceil rounding and bilinear filtering legitimately mix in
    the surrounding black (design doc T4)."""
    _, client = configured
    full = client.capture_composite(format="rgba", crop="full")
    found = markers_in_composite(RGBAImage.from_result(full), full)
    markers = ct.MARKERS_A if found == SET_A else ct.MARKERS_B
    for x, y, w, h, color in markers:
        r = client.capture_composite(format="rgba", game_rect={"x": x, "y": y, "w": w, "h": h})
        img = RGBAImage.from_result(r)
        interior = [(px, py) for py in range(2, img.height - 2) for px in range(2, img.width - 2)]
        hits = sum(close(img.px(px, py), PAL[color], 48) for px, py in interior)
        assert hits / len(interior) >= 0.95, (hits, len(interior), r["crop_rect"])


def test_t5_composite_matches_source(configured):
    """Every source pixel whose 3x3 neighborhood is one flat color must
    appear with that color (within 8/255 -- bilinear filtering of a flat
    area is exact up to rounding) at the center of its block in the
    composite viewport."""
    _, client = configured
    r = client.capture_composite(format="rgba", include_source=True)
    assert r["source_frame_match"] is True
    comp = RGBAImage.from_result(r)
    src = RGBAImage.from_result(r["source"])
    sw, sh = src.width, src.height
    checked = 0
    for sy in range(1, sh - 1, 3):
        for sx in range(1, sw - 1, 3):
            c = src.px(sx, sy)
            if any(src.px(sx + dx, sy + dy) != c for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
                continue
            ox = int((sx + 0.5) * comp.width / sw)
            oy = int((sy + 0.5) * comp.height / sh)
            assert close(comp.px(ox, oy), c, 8), ((sx, sy), c, (ox, oy), comp.px(ox, oy))
            checked += 1
    assert checked > 1000
