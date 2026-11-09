"""
LyraAuth image challenge: a freshly drawn, distorted code that a person reads at a glance.

Why this is harder for bots than the text questions:
  * Every image is generated on the spot from random strokes, so there is no fixed bank to memorise
    or look up. The text questions came from ~100 fixed prompts that any language model answers.
  * The characters are drawn as warped vector paths, not text. There is no <text> element, font or
    alt text in the SVG, so scraping the markup gives coordinates, not letters.
  * Decoy characters in a pale colour overlap the real ones and the person is asked for the dark
    ones only, which defeats plain OCR. Noise strokes use the same ink and width as the letters.
  * Reading it needs a vision model call per attempt, on top of the proof of work in shield.py.

What it is not: proof against every AI. Strong vision models can read most distorted text, so
the score in shield.py (timing, proof of work, automation signals, failure back-off) still matters.

No image libraries are needed: the output is an SVG string the widget shows as an <img>.
"""
import base64
import math
import random
import secrets
from typing import List, Tuple

# Characters people don't confuse with each other (no 0/O, 1/I/L, 2/Z, 5/S, 8/B, 6/G).
ALPHABET = "ACDEFHJKMNPRTUVWXY3479"

# A small stroke font on a 4 x 6 grid. Each glyph is a list of polylines.
_G = {
    "A": [[(0, 6), (2, 0), (4, 6)], [(0.8, 3.9), (3.2, 3.9)]],
    "C": [[(4, 1), (3, 0), (1, 0), (0, 1.5), (0, 4.5), (1, 6), (3, 6), (4, 5)]],
    "D": [[(0, 0), (0, 6), (2.5, 6), (4, 4.5), (4, 1.5), (2.5, 0), (0, 0)]],
    "E": [[(4, 0), (0, 0), (0, 6), (4, 6)], [(0, 3), (3, 3)]],
    "F": [[(4, 0), (0, 0), (0, 6)], [(0, 3), (3, 3)]],
    "H": [[(0, 0), (0, 6)], [(4, 0), (4, 6)], [(0, 3), (4, 3)]],
    "J": [[(4, 0), (4, 4.5), (3, 6), (1, 6), (0, 4.8)]],
    "K": [[(0, 0), (0, 6)], [(4, 0), (0, 3.6)], [(1.4, 2.6), (4, 6)]],
    "M": [[(0, 6), (0, 0), (2, 3.6), (4, 0), (4, 6)]],
    "N": [[(0, 6), (0, 0), (4, 6), (4, 0)]],
    "P": [[(0, 6), (0, 0), (3, 0), (4, 1), (4, 2.2), (3, 3.2), (0, 3.2)]],
    "R": [[(0, 6), (0, 0), (3, 0), (4, 1), (4, 2.2), (3, 3.2), (0, 3.2)], [(1.8, 3.2), (4, 6)]],
    "T": [[(0, 0), (4, 0)], [(2, 0), (2, 6)]],
    "U": [[(0, 0), (0, 4.8), (1, 6), (3, 6), (4, 4.8), (4, 0)]],
    "V": [[(0, 0), (2, 6), (4, 0)]],
    "W": [[(0, 0), (1, 6), (2, 2.4), (3, 6), (4, 0)]],
    "X": [[(0, 0), (4, 6)], [(4, 0), (0, 6)]],
    "Y": [[(0, 0), (2, 3), (4, 0)], [(2, 3), (2, 6)]],
    "3": [[(0, 0.6), (1, 0), (3, 0), (4, 1), (4, 2), (3, 3), (1.5, 3)], [(3, 3), (4, 4), (4, 5), (3, 6), (1, 6), (0, 5.4)]],
    "4": [[(3, 6), (3, 0), (0, 4), (4, 4)]],
    "7": [[(0, 0), (4, 0), (1.5, 6)]],
    "9": [[(4, 3), (3, 3.6), (1, 3.6), (0, 2.6), (0, 1), (1, 0), (3, 0), (4, 1), (4, 4.6), (3, 6), (1, 6), (0, 5.2)]],
}

W, H = 280, 96
INKS = ["#1c1915", "#2a211b", "#1f2a2e", "#2b1d2a"]          # dark: the characters to type
DECOYS = ["#e2b9a3", "#d9c3a5", "#c9d3d6", "#e5c8bd"]        # pale: characters to ignore

Point = Tuple[float, float]


def _rng() -> random.Random:
    return random.Random(secrets.randbits(64))


def _smooth(points: List[Point]) -> str:
    """A path through the points with rounded joins (quadratic curves via midpoints)."""
    if len(points) == 2:
        (x0, y0), (x1, y1) = points
        return f"M{x0:.1f} {y0:.1f}L{x1:.1f} {y1:.1f}"
    d = f"M{points[0][0]:.1f} {points[0][1]:.1f}"
    for i in range(1, len(points) - 1):
        cx, cy = points[i]
        mx, my = (cx + points[i + 1][0]) / 2, (cy + points[i + 1][1]) / 2
        d += f"Q{cx:.1f} {cy:.1f} {mx:.1f} {my:.1f}"
    d += f"L{points[-1][0]:.1f} {points[-1][1]:.1f}"
    return d


def _subdivide(line: List[Point], step: float = 0.7) -> List[Point]:
    """More points along each stroke, so the warp bends lines instead of moving corners."""
    out = [line[0]]
    for (x0, y0), (x1, y1) in zip(line, line[1:]):
        n = max(1, int(math.hypot(x1 - x0, y1 - y0) / step))
        out += [(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n) for k in range(1, n + 1)]
    return out


def _glyph_paths(ch: str, cx: float, cy: float, size: float, r: random.Random, warp) -> List[str]:
    angle = math.radians(r.uniform(-24, 24))
    shear = r.uniform(-0.35, 0.35)
    sx = size / 6 * r.uniform(0.85, 1.15)
    sy = size / 6 * r.uniform(0.9, 1.1)
    ca, sa = math.cos(angle), math.sin(angle)
    paths = []
    for line in _G[ch]:
        pts = []
        for gx, gy in _subdivide(line):
            x, y = (gx - 2) * sx, (gy - 3) * sy
            x += shear * y
            x, y = x * ca - y * sa, x * sa + y * ca
            x, y = warp(cx + x + r.uniform(-0.9, 0.9), cy + y + r.uniform(-0.9, 0.9))
            pts.append((x, y))
        paths.append(_smooth(pts))
    return paths


def generate(length: int = 5, decoys: int = 3, hard: bool = False) -> Tuple[str, str]:
    """Returns (answer, svg). The answer is the dark characters, left to right."""
    r = _rng()
    if hard:
        length, decoys = length + 1, decoys + 1
    answer = "".join(r.choice(ALPHABET) for _ in range(length))

    # One smooth wave across the whole image, plus a gentle second harmonic.
    a1, l1, p1 = r.uniform(5, 9), r.uniform(70, 120), r.uniform(0, 6.28)
    a2, l2, p2 = r.uniform(2, 4), r.uniform(25, 45), r.uniform(0, 6.28)
    def warp(x: float, y: float) -> Point:
        return (x + a2 * math.sin(y / l2 + p2), y + a1 * math.sin(x / l1 + p1))

    parts: List[str] = []
    bg1, bg2 = r.choice(["#f7f2ea", "#f4efe6", "#f2ece3"]), r.choice(["#efe4d4", "#ece4d8", "#f3e8e0"])
    parts.append(f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{bg1}"/>'
                 f'<stop offset="1" stop-color="{bg2}"/></linearGradient></defs><rect width="{W}" height="{H}" fill="url(#g)"/>')

    # Background speckle and faint grid, so edges aren't clean for thresholding.
    for _ in range(70):
        parts.append(f'<circle cx="{r.uniform(0, W):.1f}" cy="{r.uniform(0, H):.1f}" r="{r.uniform(0.6, 1.8):.1f}" '
                     f'fill="{r.choice(DECOYS + INKS[:1])}" opacity="{r.uniform(0.15, 0.5):.2f}"/>')

    # Decoy characters: pale, smaller, scattered behind and between the real ones.
    for _ in range(decoys):
        ch = r.choice(ALPHABET)
        for d in _glyph_paths(ch, r.uniform(20, W - 20), r.uniform(26, H - 26), r.uniform(26, 36), r, warp):
            parts.append(f'<path d="{d}" fill="none" stroke="{r.choice(DECOYS)}" stroke-width="{r.uniform(3, 4.5):.1f}" '
                         f'stroke-linecap="round" stroke-linejoin="round"/>')

    # The real characters, overlapping a little, with uneven spacing and baseline.
    ink = r.choice(INKS)
    span = W - 50
    x = 25 + r.uniform(0, 10)
    step = span / length
    for ch in answer:
        size = r.uniform(42, 54)
        for d in _glyph_paths(ch, x + step * 0.42, H / 2 + r.uniform(-8, 8), size, r, warp):
            parts.append(f'<path d="{d}" fill="none" stroke="{ink}" stroke-width="{r.uniform(3.4, 4.6):.1f}" '
                         f'stroke-linecap="round" stroke-linejoin="round"/>')
        x += step * r.uniform(0.95, 1.05)

    # Noise strokes in the same ink and width as the letters, crossing them.
    for _ in range(3 if not hard else 4):
        y0, y1 = r.uniform(15, H - 15), r.uniform(15, H - 15)
        c1 = (r.uniform(40, W - 40), r.uniform(-10, H + 10))
        c2 = (r.uniform(40, W - 40), r.uniform(-10, H + 10))
        parts.append(f'<path d="M{r.uniform(-5, 30):.1f} {y0:.1f}C{c1[0]:.1f} {c1[1]:.1f} {c2[0]:.1f} {c2[1]:.1f} '
                     f'{r.uniform(W - 30, W + 5):.1f} {y1:.1f}" fill="none" stroke="{ink}" '
                     f'stroke-width="{r.uniform(1.6, 2.6):.1f}" stroke-linecap="round" opacity="{r.uniform(0.7, 0.95):.2f}"/>')

    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
           + "".join(parts) + "</svg>")
    return answer, svg


def data_url(svg: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def normalise(text: str) -> str:
    """People type in any case and sometimes add spaces; compare letters only."""
    t = "".join(ch for ch in (text or "").upper() if ch.isalnum())
    # Forgive the look-alikes we never draw.
    return t.translate(str.maketrans({"O": "D", "0": "D"}))


def matches(typed: str, answer: str) -> bool:
    return secrets.compare_digest(normalise(typed), answer)
