# SPDX-License-Identifier: LGPL-2.1-or-later

"""Time reading and writing a large STAR file here, in starfile and starfile-rs.

    python -m scripts.compare --rows 10000000 --svg
    python -m scripts.compare --svg --measure memory

Prints a Markdown table of the best of `--repeat` runs of each, or with
`--measure memory` the peak memory of each in a process of its own, and
with `--svg` draws them into `docs/assets` as light and dark bar charts for
the README. A write starts from what a read left in memory: it is timed
alone, but its peak is the read's and the write's together. This is a
comparison to write down, not a gate: their releases move it, and CI's
benchmarks watch only our own numbers.
"""

from __future__ import annotations

import argparse
import datetime
import importlib
import platform
import subprocess
import sys
import tempfile
import time
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

import starfile
import starfile_rs

import rexlib_metadata as rxm
from benchmarks.generate import write
from scripts.chart import DARK, GIB, LIGHT, SECONDS, Bar, Measure, svg
from scripts.memory import peak_bytes

if TYPE_CHECKING:
    from collections.abc import Callable

    Action = Callable[[], object]


def _read_ours_raw(path: Path) -> object:
    return rxm.read(str(path)).raw["particles"].to_pandas()


def _read_ours_canonical(path: Path) -> object:
    return rxm.read(str(path))["particles"].to_pandas()


def _read_ours_chunks(path: Path) -> object:
    for chunk in rxm.read(str(path))["particles"].chunks(100_000):
        chunk.to_pandas()
    return None


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
    "rexlib-metadata, chunks of 100k": _reading(_read_ours_chunks),
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

OPERATIONS = {"read": READS, "write": WRITES}
HEADINGS = {"read": "Read to pandas", "write": "Write a STAR file"}
ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "docs" / "assets"


def best_of(action: Action, repeat: int) -> float:
    """Return the fastest of `repeat` runs of `action`, in seconds."""
    times = []
    for _ in range(repeat):
        start = time.perf_counter()
        action()
        times.append(time.perf_counter() - start)
    return min(times)


def time_each(kind: str, path: Path, repeat: int) -> list[Bar]:
    """Time each operation of `kind` over `path`, print the table."""
    print(f"\n| {HEADINGS[kind]} | Seconds |\n|---|---|")
    bars = []
    for name, prepare in OPERATIONS[kind].items():
        seconds = best_of(prepare(path, path.with_name("out.star")), repeat)
        bars.append(Bar(name, seconds, name.startswith("rexlib")))
        print(f"| {name} | {seconds:.2f} |")
    return bars


def peak_of_each(kind: str, path: Path, _: int) -> list[Bar]:
    """Measure each operation's peak memory in a process of its own."""
    print(f"\n| {HEADINGS[kind]} | Peak GiB |\n|---|---|")
    bars = []
    for name in OPERATIONS[kind]:
        command = [sys.executable, "-m", "scripts.compare", "--child", kind]
        child = subprocess.run(
            [*command, name, str(path)],
            capture_output=True,
            text=True,
            check=True,
            cwd=ROOT,
        )
        gib = int(child.stdout) / 2**30
        bars.append(Bar(name, gib, name.startswith("rexlib")))
        print(f"| {name} | {gib:.2f} |")
    return bars


def child(kind: str, name: str, path: Path) -> None:
    """Run one operation and print how far it raised this process's peak."""
    importlib.import_module("pandas")
    before = peak_bytes()
    OPERATIONS[kind][name](path, path.with_name(f"out-{kind}.star"))()
    print(peak_bytes() - before)


MEASURES = {
    "time": (time_each, SECONDS, "", "best of {repeat}"),
    "memory": (peak_of_each, GIB, "-memory", "peak memory, a process each"),
}


def main() -> None:
    """Generate the file, measure each read and write, print the tables."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rows", type=int, default=10_000_000)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--measure", choices=MEASURES, default="time")
    parser.add_argument(
        "--svg", action="store_true", help="draw the charts into docs/assets"
    )
    parser.add_argument("--child", nargs=3, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        kind, name, path = args.child
        child(kind, name, Path(path))
        return
    run, unit, suffix, how = MEASURES[args.measure]
    with tempfile.TemporaryDirectory() as directory:
        path = write(Path(directory) / "particles.star", args.rows)
        size = path.stat().st_size / 2**20
        how = how.format(repeat=args.repeat)
        print(f"{args.rows} rows, {size:.0f} MiB, {how}")
        bars = {kind: run(kind, path, args.repeat) for kind in OPERATIONS}
    if args.svg:
        caption = (
            f"{args.rows:,} rows, {size:.0f} MiB, {how} · "
            f"python -m scripts.compare · {datetime.date.today()} · "
            f"{platform.system()}, Python {platform.python_version()}"
        )
        _draw_both(bars, _count(args.rows), caption, unit, suffix)


def _draw_both(
    bars: dict[str, list[Bar]],
    count: str,
    caption: str,
    unit: Measure,
    suffix: str,
) -> None:
    titles = {
        "read": f"Reading {count} Relion particles to pandas",
        "write": f"Writing {count} Relion particles",
    }
    for kind, title in titles.items():
        _draw(f"{kind}{suffix}", bars[kind], title, caption, unit)


def _count(rows: int) -> str:
    """Say a row count as a reader would: 10 million, not 10,000,000."""
    if rows % 1_000_000 == 0:
        return f"{rows // 1_000_000} million"
    return f"{rows:,}"


def _draw(
    kind: str, bars: list[Bar], title: str, caption: str, unit: Measure
) -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    for name, theme in (("light", LIGHT), ("dark", DARK)):
        chart = svg(bars, title, caption, theme, unit)
        (ASSETS / f"performance-{kind}-{name}.svg").write_text(
            chart, encoding="utf-8", newline="\n"
        )


if __name__ == "__main__":
    main()
