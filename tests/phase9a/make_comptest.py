"""
Generates drive_c/COMPTEST.COM, the Phase 9A composite-capture test program
(docs/phase9a-composite-capture-design.md, section 9).

The project has no DOS assembler in its toolchain, so the program is
emitted here byte-for-byte by a tiny two-pass label assembler. Behavior:

- Switches to mode 13h (320x200, 256 colors, default VGA palette).
- Draws a 1-pixel frame, each edge in its own color, so the viewport
  boundary can be located in a composite capture:
  top = BORDER_TOP, bottom = BORDER_BOTTOM, left = BORDER_LEFT,
  right = BORDER_RIGHT.
- Draws marker set A (MARKERS_A), then waits for a key. Any key switches
  to marker set B (MARKERS_B), the next key back to A, and so on. ESC
  returns to text mode and exits.

Run directly to (re)write drive_c/COMPTEST.COM:

    python tests/phase9a/make_comptest.py
"""

from pathlib import Path

# Default VGA palette indices and their RGB values (6-bit DAC scaled x4 by
# DOSBox-X's renderer: 0x3F -> 0xFF, 0x15 -> 0x55, 0x2A -> 0xAA).
BORDER_TOP = 0x01      # blue        (0x00, 0x00, 0xAA)
BORDER_BOTTOM = 0x02   # green       (0x00, 0xAA, 0x00)
BORDER_LEFT = 0x0C     # light red   (0xFF, 0x55, 0x55)
BORDER_RIGHT = 0x0E    # yellow      (0xFF, 0xFF, 0x55)
MARKER_1 = 0x0F        # white       (0xFF, 0xFF, 0xFF)
MARKER_2 = 0x0D        # light magenta (0xFF, 0x55, 0xFF)

PALETTE_RGB = {
    0x00: (0x00, 0x00, 0x00),
    0x01: (0x00, 0x00, 0xAA),
    0x02: (0x00, 0xAA, 0x00),
    0x0C: (0xFF, 0x55, 0x55),
    0x0D: (0xFF, 0x55, 0xFF),
    0x0E: (0xFF, 0xFF, 0x55),
    0x0F: (0xFF, 0xFF, 0xFF),
}

# (x, y, w, h, color) in the guest's native 320x200 grid.
MARKERS_A = [(40, 30, 16, 8, MARKER_1), (200, 150, 32, 16, MARKER_2)]
MARKERS_B = [(120, 60, 16, 8, MARKER_1), (240, 40, 32, 16, MARKER_2)]

OUTPUT = Path(__file__).resolve().parents[2] / "drive_c" / "COMPTEST.COM"


class Asm:
    def __init__(self, origin=0x100):
        self.origin = origin
        self.items = []  # ("bytes", b) | ("label", name) | ("rel16", op, name) | ("rel8", op, name)

    def db(self, *bs):
        self.items.append(("bytes", bytes(bs)))

    def label(self, name):
        self.items.append(("label", name))

    def call(self, name):
        self.items.append(("rel16", 0xE8, name))

    def jmp(self, name):
        self.items.append(("rel16", 0xE9, name))

    def jz(self, name):
        self.items.append(("rel8", 0x74, name))

    def jnz(self, name):
        self.items.append(("rel8", 0x75, name))

    def mov_di(self, v):
        self.db(0xBF, v & 0xFF, v >> 8)

    def mov_bx(self, v):
        self.db(0xBB, v & 0xFF, v >> 8)

    def mov_dx(self, v):
        self.db(0xBA, v & 0xFF, v >> 8)

    def mov_al(self, v):
        self.db(0xB0, v)

    @staticmethod
    def _size(item):
        kind = item[0]
        if kind == "bytes":
            return len(item[1])
        if kind == "label":
            return 0
        return 3 if kind == "rel16" else 2

    def assemble(self):
        labels, pc = {}, self.origin
        for item in self.items:
            if item[0] == "label":
                labels[item[1]] = pc
            pc += self._size(item)
        out, pc = bytearray(), self.origin
        for item in self.items:
            size = self._size(item)
            if item[0] == "bytes":
                out += item[1]
            elif item[0] == "rel16":
                rel = (labels[item[2]] - (pc + size)) & 0xFFFF
                out += bytes([item[1], rel & 0xFF, rel >> 8])
            elif item[0] == "rel8":
                rel = labels[item[2]] - (pc + size)
                assert -128 <= rel <= 127, item
                out += bytes([item[1], rel & 0xFF])
            pc += size
        return bytes(out)


def fill(a, x, y, w, h, color):
    a.mov_di(y * 320 + x)
    a.mov_bx(w)
    a.mov_dx(h)
    a.mov_al(color)
    a.call("fill")


def build():
    a = Asm()
    a.db(0xB8, 0x13, 0x00)        # mov ax,0013h
    a.db(0xCD, 0x10)              # int 10h
    a.db(0xB8, 0x00, 0xA0)        # mov ax,A000h
    a.db(0x8E, 0xC0)              # mov es,ax
    a.db(0xFC)                    # cld

    for name, markers, nxt in (("set_a", MARKERS_A, "set_b"), ("set_b", MARKERS_B, "set_a")):
        a.label(name)
        a.call("frame")
        for m in markers:
            fill(a, *m)
        a.db(0xB4, 0x00)          # mov ah,0
        a.db(0xCD, 0x16)          # int 16h
        a.db(0x3C, 0x1B)          # cmp al,1Bh
        a.jz("exit")
        a.jmp(nxt)

    a.label("exit")
    a.db(0xB8, 0x03, 0x00)        # mov ax,0003h
    a.db(0xCD, 0x10)              # int 10h
    a.db(0xCD, 0x20)              # int 20h

    # frame: clear the screen, then draw the four 1-pixel edges.
    a.label("frame")
    fill(a, 0, 0, 320, 200, 0x00)
    fill(a, 0, 0, 320, 1, BORDER_TOP)
    fill(a, 0, 199, 320, 1, BORDER_BOTTOM)
    fill(a, 0, 1, 1, 198, BORDER_LEFT)
    fill(a, 319, 1, 1, 198, BORDER_RIGHT)
    a.db(0xC3)                    # ret

    # fill: DI = start offset, BX = width, DX = rows, AL = color.
    a.label("fill")
    a.label("fill_row")
    a.db(0x57)                    # push di
    a.db(0x89, 0xD9)              # mov cx,bx
    a.db(0xF3, 0xAA)              # rep stosb
    a.db(0x5F)                    # pop di
    a.db(0x81, 0xC7, 0x40, 0x01)  # add di,320
    a.db(0x4A)                    # dec dx
    a.jnz("fill_row")
    a.db(0xC3)                    # ret
    return a.assemble()


if __name__ == "__main__":
    code = build()
    OUTPUT.write_bytes(code)
    print(f"wrote {OUTPUT} ({len(code)} bytes)")
