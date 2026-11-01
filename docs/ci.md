# Continuous integration

| Workflow | When | Does |
|---|---|---|
| `build-and-test.yml` | PRs, pushes to `main` that touch code, on demand | `lint`, `build_with_cargo`, `build_with_pip`, `coverage`, `sonar-scan` |
| `benchmarks.yml` | PRs and `main` touching code; `compare` on demand | CodSpeed benchmarks; the starfile/starfile-rs comparison |
| `codeql.yml` | PRs, `main`, Mondays | CodeQL over the workflows, Python and Rust, without a build |
| `release.yml` | packaging changes, `main`, `v*` tags | sdist, abi3 wheels per platform, the `development` prerelease |
| `keep-caches-warm.yml` | every morning, and on a change to itself | reads every Rust cache so none expires |

A second push to the same ref cancels the run in flight.

## build-and-test

| Job | Does |
|---|---|
| `lint` | `ruff check .`, complexipy (≤ 7) and `mypy`, once, from the `lint` group without building the crate |
| `build_with_cargo` | `cargo fmt --check`, clippy at `-D warnings`, `cargo build`, `cargo test`, `--locked`, on Linux, macOS and Windows |
| `build_with_pip` | `pip install .[hdf5] --group test` and `pytest`, three platforms × Python 3.10–3.15 |
| `coverage` | `cargo llvm-cov` over the Rust tests, clippy as JSON, `pytest --cov` over an editable install |
| `sonar-scan` | hands the three reports to SonarQube Cloud |

- One extra cell, Linux on 3.10, installs the **floor** of every range
  (pyarrow, polars, pandas, h5py) instead of the newest.
- 3.15 installs no `hdf5` extra: h5py has no wheel for it.
- `fail-fast` is off. The Rust build is cached per platform, written only by
  `main`; the pip job sets `CARGO_TARGET_DIR` so maturin's build is cached.
- Actions are pinned by digest except the organisation's own, taken from
  `main`. Renovate updates the rest with a 14-day minimum release age and
  turns on auto-merge, which still waits on the checks and a code-owner
  review.
- The Rust toolchain follows stable, so a new clippy can fail an untouched
  build; pin it in `rust-toolchain.toml` if that starts costing more than
  it gives.

## Static analysis

SonarQube Cloud runs from CI (automatic analysis is off: it cannot read Rust
or coverage). `sonar-project.properties` lists the sources, the tests, the
three report paths, `sonar.python.version=3.10`, excludes `scripts/` from
coverage, and turns off Sonar's own clippy run, since `coverage` already
produced it.

Findings accepted in the SonarQube interface rather than fixed: the missing
lock file and the free resolution of `pip install . --group test`. A
library declares ranges; `build_with_pip` builds this crate from source by
design.

## Benchmarks

CodSpeed runs `pytest benchmarks --codspeed` over 100 000 generated rows
under CPU simulation, which leaves out system calls: I/O-heavy benchmarks
are understated, and `scripts/compare.py` is what measures wall time.
`REXLIB_BENCH_ROWS` changes the size locally. The tools install from pinned
wheels and the package from a wheel maturin builds, with `--no-deps`.

`python -m scripts.compare` reads and writes ten million rows here and in
starfile and starfile-rs; `--measure memory` reports peak memory, each
operation in a process of its own; `--svg` redraws the README's charts.

## Release

The sdist is built first and every wheel from it, so the sdist is proven to
build. Wheels are abi3 from 3.10, tested by cibuildwheel on 3.10–3.14. A
push to `main` replaces the `development` prerelease. Publishing to PyPI,
by trusted publishing, waits on the package name
([#40](https://github.com/gigabit-clowns/rexlib-metadata/issues/40)).
