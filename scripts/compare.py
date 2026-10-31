# SPDX-License-Identifier: LGPL-2.1-or-later

"""Time one read of a large STAR file here and in starfile and starfile-rs.

    python -m scripts.compare --rows 1000000 --svg docs/assets

Prints a Markdown table of the best of `--repeat` runs of each and, with
`--svg`, draws it as a light and a dark bar chart for the README. This is a
comparison to write down, not a gate: their releases move it, and CI's
benchmarks watch only our own numbers.
"""

from __future__ import annotations

import argparse
import datetime
import platform
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

import starfile
import starfile_rs

import rexlib_metadata as rxm
from benchmarks.generate import write
from scripts.chart import DARK, LIGHT, Bar, svg

if TYPE_CHECKING:
    from collections.abc import Callable


def _ours_raw(path: Path) -> object:
    return rxm.read(str(path)).raw["particles"].to_pandas()


def _ours_canonical(path: Path) -> object:
    return rxm.read(str(path))["particles"].to_pandas()


def _starfile(path: Path) -> object:
    return starfile.read(path)["particles"]


def _starfile_rs(path: Path) -> object:
    return starfile_rs.read_star(path)["particles"].to_pandas()


READS: dict[str, Callable[[Path], object]] = {
    "rexlib-metadata, raw (all text)": _ours_raw,
    "rexlib-metadata, canonical": _ours_canonical,
    "starfile": _starfile,
    "starfile-rs": _starfile_rs,
}

TITLE = "Reading a million-row Relion STAR file to pandas"


def best_of(read: Callable[[Path], object], path: Path, repeat: int) -> float:
    """Return the fastest of `repeat` reads, in seconds."""
    times = []
    for _ in range(repeat):
        start = time.perf_counter()
        read(path)
        times.append(time.perf_counter() - start)
    return min(times)


def main() -> None:
    """Generate the file, time each read, print the table."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rows", type=int, default=1_000_000)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--svg", type=Path, help="directory for the charts")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        path = write(Path(directory) / "particles.star", args.rows)
        size = path.stat().st_size / 2**20
        print(f"{args.rows} rows, {size:.0f} MiB, best of {args.repeat}\n")
        print("| Read to pandas | Seconds |\n|---|---|")
        bars = []
        for name, read in READS.items():
            seconds = best_of(read, path, args.repeat)
            bars.append(Bar(name, seconds, name.startswith("rexlib")))
            print(f"| {name} | {seconds:.2f} |")
    if args.svg:
        caption = (
            f"{args.rows:,} rows, {size:.0f} MiB, best of {args.repeat} · "
            f"python -m scripts.compare · {datetime.date.today()} · "
            f"{platform.system()}, Python {platform.python_version()}"
        )
        _draw(args.svg, bars, caption)


def _draw(directory: Path, bars: list[Bar], caption: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, theme in (("light", LIGHT), ("dark", DARK)):
        chart = svg(bars, TITLE, caption, theme)
        (directory / f"performance-{name}.svg").write_text(
            chart, encoding="utf-8", newline="\n"
        )


if __name__ == "__main__":
    main()
