# SPDX-License-Identifier: LGPL-2.1-or-later

"""Draw the comparison of `scripts/compare.py` as a bar chart, in SVG.

One horizontal bar per read, fastest first, its seconds at the tip. Ours
are blue and the others neutral, each named beside its bar, so colour is
never the only thing that says which is which. A light and a dark file,
for the README to pick between through `<picture>`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from html import escape

WIDTH = 760
LABEL_RIGHT = 300
PLOT_LEFT = 312
PLOT_RIGHT = 690
TOP = 92
PITCH = 44
BAR = 24
RADIUS = 4
FONT = "-apple-system, Segoe UI, Helvetica, Arial, sans-serif"


@dataclass(frozen=True)
class Theme:
    """The colours of one mode, from the chart palette's chrome and ink."""

    surface: str
    primary: str
    secondary: str
    muted: str
    grid: str
    ours: str
    others: str


LIGHT = Theme(
    surface="#fcfcfb",
    primary="#0b0b0b",
    secondary="#52514e",
    muted="#898781",
    grid="#e1e0d9",
    ours="#2a78d6",
    others="#8a8880",
)
DARK = Theme(
    surface="#1a1a19",
    primary="#f0efec",
    secondary="#c3c2b7",
    muted="#898781",
    grid="#2c2c2a",
    ours="#3987e5",
    others="#6f6d66",
)


@dataclass(frozen=True)
class Bar:
    """One read: what it is called, how long it took, and whether it is ours."""

    name: str
    seconds: float
    ours: bool


@dataclass(frozen=True)
class _Ink:
    """How a piece of text is set."""

    colour: str
    size: int
    anchor: str = "start"
    weight: int = 400


def svg(bars: list[Bar], title: str, caption: str, theme: Theme) -> str:
    """Return the whole chart as an SVG document."""
    bars = sorted(bars, key=lambda bar: bar.seconds)
    scale = math.ceil(max(bar.seconds for bar in bars))
    height = TOP + PITCH * len(bars) + 56
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" '
        f'height="{height}" viewBox="0 0 {WIDTH} {height}" role="img" '
        f'aria-label="{escape(title)}">',
        f'<rect width="{WIDTH}" height="{height}" rx="8" '
        f'fill="{theme.surface}"/>',
        _text(24, 36, title, _Ink(theme.primary, 17, weight=600)),
        _text(24, 60, "Seconds, lower is better", _Ink(theme.secondary, 13)),
        *_grid(scale, len(bars), theme),
        *(_bar(row, bar, scale, theme) for row, bar in enumerate(bars)),
        _text(24, height - 20, caption, _Ink(theme.muted, 12)),
        "</svg>",
    ]
    return "\n".join(parts) + "\n"


def _x(seconds: float, scale: int) -> float:
    return PLOT_LEFT + (PLOT_RIGHT - PLOT_LEFT) * seconds / scale


def _grid(scale: int, rows: int, theme: Theme) -> list[str]:
    bottom = TOP + PITCH * rows - (PITCH - BAR) / 2
    tick = _Ink(theme.muted, 12, anchor="middle")
    lines = []
    for second in range(scale + 1):
        x = _x(second, scale)
        lines.append(
            f'<line x1="{x:.1f}" y1="{TOP - 6}" x2="{x:.1f}" '
            f'y2="{bottom:.1f}" stroke="{theme.grid}" stroke-width="1"/>'
        )
        lines.append(_text(x, bottom + 18, f"{second}", tick))
    return lines


def _bar(row: int, bar: Bar, scale: int, theme: Theme) -> str:
    top = TOP + PITCH * row
    middle = top + BAR / 2 + 4.5
    tip = _x(bar.seconds, scale)
    name = _Ink(theme.primary, 14, anchor="end")
    if bar.ours:
        name = replace(name, weight=600)
    fill = theme.ours if bar.ours else theme.others
    value = _Ink(theme.secondary, 13)
    return "\n".join(
        [
            _text(LABEL_RIGHT, middle, bar.name, name),
            f'<path d="{_rounded_end(PLOT_LEFT, top, tip)}" fill="{fill}"/>',
            _text(tip + 8, middle, f"{bar.seconds:.2f} s", value),
        ]
    )


def _rounded_end(left: float, top: float, right: float) -> str:
    """Return a bar square at its baseline and rounded at its data end."""
    r = min(RADIUS, (right - left) / 2)
    bottom = top + BAR
    return (
        f"M{left:.1f},{top:.1f} H{right - r:.1f} "
        f"Q{right:.1f},{top:.1f} {right:.1f},{top + r:.1f} "
        f"V{bottom - r:.1f} "
        f"Q{right:.1f},{bottom:.1f} {right - r:.1f},{bottom:.1f} "
        f"H{left:.1f} Z"
    )


def _text(x: float, y: float, content: str, ink: _Ink) -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" fill="{ink.colour}" '
        f'font-size="{ink.size}" font-weight="{ink.weight}" '
        f'text-anchor="{ink.anchor}" font-family="{FONT}">'
        f"{escape(content)}</text>"
    )
