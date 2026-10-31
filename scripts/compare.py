# SPDX-License-Identifier: LGPL-2.1-or-later

"""Time one read of a large STAR file here and in starfile and starfile-rs.

    python -m scripts.compare --rows 1000000

Prints a Markdown table of the best of `--repeat` runs of each. This is a
comparison to write down, not a gate: their releases move it, and CI's
benchmarks watch only our own numbers.
"""

from __future__ import annotations

import argparse
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

import starfile
import starfile_rs

import rexlib_metadata as rxm
from benchmarks.generate import write

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
    "rexlib-metadata, raw": _ours_raw,
    "rexlib-metadata, canonical": _ours_canonical,
    "starfile": _starfile,
    "starfile-rs": _starfile_rs,
}


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
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        path = write(Path(directory) / "particles.star", args.rows)
        size = path.stat().st_size / 2**20
        print(f"{args.rows} rows, {size:.0f} MiB, best of {args.repeat}\n")
        print("| Read to pandas | Seconds |\n|---|---|")
        for name, read in READS.items():
            print(f"| {name} | {best_of(read, path, args.repeat):.2f} |")


if __name__ == "__main__":
    main()
