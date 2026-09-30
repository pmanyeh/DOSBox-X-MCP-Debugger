"""
Phase 9A tests that each launch a one-off DOSBox-X configuration:
unsupported backends (T12) and the opt-in fullscreen geometry case (T3).
"""

import os
import time

import pytest

from conftest import assert_frame_matches_viewport, launch_dosbox
from dosbox_client import DOSBoxCompositeUnsupportedBackend


def assert_unsupported(client, backend):
    with pytest.raises(DOSBoxCompositeUnsupportedBackend) as e:
        client.capture_composite(format="png")
    assert f'"{backend}"' in str(e.value) and "direct3d, surface" in str(e.value)
    # The pre-scaler capture keeps working on the same backend.
    assert client.capture_frame(format="rgba", max_width=16)["width"] == 16


def test_t12_opengl_unsupported_never_falls_back():
    with launch_dosbox("opengl") as client:
        assert_unsupported(client, "opengl")


def test_t12_ttf_unsupported_in_text_mode():
    """output=ttf only renders text modes; in a graphics mode DOSBox-X
    itself presents through a regular backend (direct3d on Windows), so
    the capture is a real composite there. Once COMPTEST exits back to text mode, TTF is
    presenting and the capture must be refused."""
    with launch_dosbox("ttf") as client:
        assert client.capture_composite(format="rgba", max_width=16)["backend"] in ("direct3d", "surface")
        client.key_tap("esc")
        deadline = time.time() + 10
        while client.capture_frame(format="rgba")["height"] == 400 and \
                client.capture_frame(format="rgba")["width"] == 640 and time.time() < deadline:
            time.sleep(0.2)
        time.sleep(0.5)
        assert_unsupported(client, "ttf")


@pytest.mark.skipif(os.environ.get("PHASE9A_FULLSCREEN") != "1", reason="set PHASE9A_FULLSCREEN=1 to run")
def test_t3_fullscreen_geometry():
    with launch_dosbox("direct3d", fullscreen=True) as client:
        r = client.capture_composite(format="png", crop="full")
        assert r["geometry"]["fullscreen"] is True
        assert_frame_matches_viewport(r)
