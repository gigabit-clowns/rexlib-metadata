# SPDX-License-Identifier: LGPL-2.1-or-later

"""Time reading and writing a large STAR file here, in starfile and starfile-rs.

    python -m scripts.compare --rows 10000000 --svg

Prints a Markdown table of the best of `--repeat` runs of each and, with
`--svg`, draws both into `docs/assets` as light and dark bar charts for the
README. A write starts from what a read left in memory, and is timed alone,
except where saying so in its name. This is a comparison to write down, not
a gate: their releases move it, and CI's benchmarks watch only our own
numbers.
"""

from __future__ import annotations

import argparse
import datetime
import platform
import tempfile
import time
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

import starfile
import starfile_rs

import rexlib_metadata as rxm
from benchmarks.generate import write
from scripts.chart import DARK, LIGHT, Bar, svg

if TYPE_CHECKING:
    from collections.abc import Callable

    Action = Callable[[], object]


def _read_ours_raw(path: Path) -> object:
    return rxm.read(str(path)).raw["particles"].to_pandas()


def _read_ours_canonical(path: Path) -> object:
    return rxm.read(str(path))["particles"].to_pandas()


def _read_starfile(path: Path) -> object:
    return starfile.read(path)["particles"]


def _read_starfile_rs(path: Path) -> object:
    return starfile_rs.read_star(path)["particles"].to_pandas()


def _reading(read: Callable[[Path], object]) -> Callable[[Path, Path], Action]:
    return lambda path, _: partial(read, path)


def _write_ours_raw(path: Path, out: Path) -> Action:
    raw = rxm.read(str(path)).raw
    raw.tables()
    return lambda: raw.write(str(out))


def _write_ours_canonical(path: Path, out: Path) -> Action:
    result = rxm.read(str(path))
    return lambda: result.write(str(out))


def _write_starfile(path: Path, out: Path) -> Action:
    frames = starfile.read(path)
    return lambda: starfile.write(frames, out)


def _write_starfile_rs_as_read(path: Path, out: Path) -> Action:
    star = starfile_rs.read_star(path)
    return lambda: star.write(out)


def _write_starfile_rs(path: Path, out: Path) -> Action:
    star = starfile_rs.read_star(path)
    frames = {name: star[name].to_pandas() for name in star}
    return lambda: starfile_rs.as_star(frames).write(out)


READS: dict[str, Callable[[Path, Path], Action]] = {
    "rexlib-metadata, raw (all text)": _reading(_read_ours_raw),
    "rexlib-metadata, canonical": _reading(_read_ours_canonical),
    "starfile": _reading(_read_starfile),
    "starfile-rs": _reading(_read_starfile_rs),
}

WRITES: dict[str, Callable[[Path, Path], Action]] = {
    "rexlib-metadata, raw (as read)": _write_ours_raw,
    "rexlib-metadata, canonical (rereads)": _write_ours_canonical,
    "starfile-rs, as read": _write_starfile_rs_as_read,
    "starfile-rs, from pandas": _write_starfile_rs,
    "starfile, from pandas": _write_starfile,
}

ASSETS = Path(__file__).resolve().parent.parent / "docs" / "assets"


def best_of(action: Action, repeat: int) -> float:
    """Return the fastest of `repeat` runs of `action`, in seconds."""
    times = []
    for _ in range(repeat):
        start = time.perf_counter()
        action()
        times.append(time.perf_counter() - start)
    return min(times)


def measure(
    heading: str,
    operations: dict[str, Callable[[Path, Path], Action]],
    path: Path,
    repeat: int,
) -> list[Bar]:
    """Time each operation over `path`, print the table, return the bars."""
    print(f"\n| {heading} | Seconds |\n|---|---|")
    bars = []
    for name, prepare in operations.items():
        seconds = best_of(prepare(path, path.with_name("out.star")), repeat)
        bars.append(Bar(name, seconds, name.startswith("rexlib")))
        print(f"| {name} | {seconds:.2f} |")
    return bars


def main() -> None:
    """Generate the file, time each read and write, print the tables."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rows", type=int, default=10_000_000)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument(
        "--svg", action="store_true", help="draw the charts into docs/assets"
    )
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        path = write(Path(directory) / "particles.star", args.rows)
        size = path.stat().st_size / 2**20
        print(f"{args.rows} rows, {size:.0f} MiB, best of {args.repeat}")
        reads = measure("Read to pandas", READS, path, args.repeat)
        writes = measure("Write a STAR file", WRITES, path, args.repeat)
    if args.svg:
        caption = (
            f"{args.rows:,} rows, {size:.0f} MiB, best of {args.repeat} · "
            f"python -m scripts.compare · {datetime.date.today()} · "
            f"{platform.system()}, Python {platform.python_version()}"
        )
        count = _count(args.rows)
        reading = f"Reading {count} Relion particles to pandas"
        _draw("read", reads, reading, caption)
        _draw("write", writes, f"Writing {count} Relion particles", caption)


def _count(rows: int) -> str:
    """Say a row count as a reader would: 10 million, not 10,000,000."""
    if rows % 1_000_000 == 0:
        return f"{rows // 1_000_000} million"
    return f"{rows:,}"


def _draw(kind: str, bars: list[Bar], title: str, caption: str) -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    for name, theme in (("light", LIGHT), ("dark", DARK)):
        chart = svg(bars, title, caption, theme)
        (ASSETS / f"performance-{kind}-{name}.svg").write_text(
            chart, encoding="utf-8", newline="\n"
        )


if __name__ == "__main__":
    main()
