# Continuous integration

What runs on a pull request, what it costs, and why it is arranged this way.
`AGENTS.md` says only that the gate has to be green; this says what the gate
is made of.

One workflow, `build-and-test.yml`, on pull requests, on a push to `main`
that touches something other than documentation, and on demand. A second push
to the same ref cancels the run in flight.

`keep-caches-warm.yml` runs every morning, and on a change to itself.
`release.yml` is described under [Release](#release).

| Job | Does |
|---|---|
| `lint` | `ruff check .`, the cognitive complexity check and `mypy`, once |
| `build_with_cargo` | `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`, `cargo build`, `cargo test`, on the three platforms |
| `build_with_pip` | `pip install .[hdf5] --group test` (no `hdf5` on 3.15, which h5py has no wheel for) and `pytest tests/python/`, three platforms × Python 3.10 to 3.15, and once more on the oldest extras |

One cell of nineteen installs the **oldest** polars, pandas and h5py this
package says it supports rather than the newest. The extras declare a range —
`polars>=1.0`, `pandas>=2.2.2` on 3.10, `h5py>=3.11` — and a range nobody tests at its floor
is a claim rather than a fact; the pins in the `test` group only ever prove the
ceiling. Testing the floor and the ceiling and not the middle is the usual
compromise, and it is cheap here because polars reaches us through one
function.

That cell is Linux on 3.10 because it has to be: the `<3.0` half of the
pandas extra is declared for 3.10 alone, so 3.10 is the only cell whose floor
2.2.2 is — `docs/dependencies.md` says why that is the floor. It is added by
an `include` whose `extras` value is outside its dimension, which is what
makes Actions create a cell instead of replacing the one that matches.

The linters run once, in a job of their own, because they read the source and
the source is the same in every cell.

The job installs through `pip install --group lint`, a PEP 735 group,
which installs the tools without the project: an extra would build this
crate — the Rust and all of arrow — to deliver ruff, so the job needs no Rust
toolchain and no cache. `--only-binary :all:` goes with it, every tool in the
group shipping a wheel for the one platform it runs on.

`mypy` runs there too, reading its settings from `[tool.mypy]`. The group
carries `pyarrow-stubs` and `pandas-stubs`, neither package shipping types,
and `polars`, which does. Without all three the check sees `Any` everywhere
and passes by seeing nothing.

`fail-fast` is off in both matrices, so one broken cell does not hide the
others. The
two jobs run in parallel and neither waits on the other: a Rust warning and a
Python failure are independent pieces of news, and serialising them only
delays one of the two.

`build_with_cargo` compiles and links as well as checking, because clippy
stops at type checking and would not notice a cdylib that fails to link. It
sets Python up for the reason given under [Building and
testing](../AGENTS.md#building-and-testing).

Both jobs cache the Rust build. The dependency tree is the whole cost of a
run — a cold build of arrow and its neighbours is minutes, ours is seconds —
and without a cache it was compiled twenty-two times per run, once per cell.

One key per platform, not per interpreter: nothing under arrow names a
Python, so the six cells of a platform share everything but the final build
of this crate, which pyo3 rebuilds per interpreter anyway. The pip job also
has to set `CARGO_TARGET_DIR`, since maturin otherwise builds in a temporary
directory of its own that nothing can cache and nothing can find afterwards.

Only `main` writes. A pull request restores and saves nothing, so one branch
cannot evict another's, and the cache a pull request reads is the one its
base produced. Nothing evicts them either: GitHub starts at 10 GiB and there
are eight entries.

The rule that would drop them is the other one, that an entry goes a week
after its last read. `keep-caches-warm.yml` reads all eight every morning
through the organisation's workflow, which looks each one up by prefix and
downloads nothing — a lookup is a read, and a read is what resets the week.
A quiet fortnight therefore costs nothing.

Actions are pinned by digest, and Renovate keeps both the digests and the
dependencies moving, under a 14-day minimum release age that security
advisories skip.

Renovate turns GitHub's auto-merge on for its own pull requests rather than
merging them. The merge still waits on the checks and on the code-owner
review the ruleset asks for, which stays a person's. A commit pushed to one
of its branches turns auto-merge off for that pull request.

The organisation's own are not pinned, and `renovate.json` disables
`gigabit-clowns/.github` so that they stay that way. They are taken from
`main` on purpose: a fix to a composite reaches every repository of the suite
the moment it lands, where a digest would need a pull request per repository
to arrive. The trust that gives up is trust in ourselves.

The Rust toolchain is the exception: `dtolnay/rust-toolchain@stable` follows
stable wherever it goes, and clippy's `pedantic` group grows with it, so a
new release can fail a build nobody touched. The lints have been
improvements, so the arrangement stays; pinning the toolchain in
`rust-toolchain.toml` is the alternative, and the moment to take it is the
second time a release costs more than it gave.

## Static analysis

SonarQube Cloud analyses the repository from the workflow, through the
organisation's `sonar-scan` composite and the `SONAR_TOKEN` secret, in a job
of its own, `sonar-scan`, after `coverage`. The badges at the foot of
`README.md` report what it finds, and the project is
`gigabit-clowns_rexlib-metadata`. Its automatic analysis is off: the two
cannot both run, and only the scanner reads Rust and coverage.

`coverage` runs on Ubuntu and measures one cell's worth of tests again:

| Report | Made by |
|---|---|
| `coverage/rust.lcov` | `cargo llvm-cov` over the Rust tests |
| `coverage/clippy.json` | `cargo clippy --message-format=json`, which is how SonarQube reads Rust |
| `coverage/python.xml` | `pytest --cov` against an editable install, so the report names `python/` and not `site-packages`: the `coverage` group, every version pinned and a wheel, then `maturin develop`, so nothing resolves freely |

The Python tests drive the Rust too, but only an instrumented extension
could count that, and the Rust tests already cover the parser on their
own; the Rust number is the Rust tests'.

`sonar-project.properties` says where everything is:

| Property | Why |
|---|---|
| `sonar.sources=src,python,scripts,.github` | everything that is shipped or that runs |
| `sonar.tests=tests` | a statement instead of a heuristic: the Python analyser recognises a test by its `test_*.py` name, and a helper in `tests/` without that name is a test too |
| `sonar.python.version=3.10` | the floor from `pyproject.toml`: a rule that wants newer syntax is wrong here until the floor moves |
| the three report paths | the files `coverage` hands over |
| `sonar.rust.clippy.enable=false` | the scan job has no Rust toolchain, and clippy has already run with the one that builds the crate |

## CodeQL

`codeql.yml` runs GitHub's analysis beside SonarQube's, on every pull
request, on `main` and every Monday, so that a new query reaches code nobody
has touched: the workflows, the Python and the Rust, each without a build.
Its findings are in the repository's Security tab.

### What it flags and what stays flagged

Four rules of its default profile fire on this repository and will go on
firing. Three of the four are one rule in three costumes — lock your
dependencies — and a library is the one thing that must not:

- **a lock file is missing** (`uv.lock`, `poetry.lock`, `pylock.toml`), and
  **`pip install . --group test` resolves versions freely**. A library declares
  ranges; an application freezes a tree. Freezing ours would mean CI proving
  that one resolution works, when the claim in `pyproject.toml` is that every
  resolution inside the range does. The floors cell exists for exactly that
  reason.
- **`--only-binary :all:` is missing from `pip install . --group test`**, because a
  source distribution runs its build script. The distribution being built
  there is *this* one, by maturin, which is the whole point of the step; with
  that flag the job cannot build the crate at all. The other two installs,
  the linters and the pinned polars and pandas of the floors cell, take the
  flag and have it.

Each of those five is accepted in the SonarQube Cloud interface rather than
silenced here, so the reason is attached to the finding and a sixth of the
same shape still arrives red. They hold the security rating at C, which is
what the badge reports.

What the rules were right about, and what changed in the same pull request as
this paragraph: `cargo build`, `cargo test` and `cargo clippy` now pass
`--locked`, so a `Cargo.lock` that no longer matches `Cargo.toml` fails the
run instead of being quietly rewritten inside it; the gate script uses `[[`;
and fourteen `pytest.raises` blocks hold one call each, which is what they
meant to assert.

## Benchmarks

`benchmarks.yml` runs `pytest benchmarks --codspeed` on a pull request or a
push to `main` that touches the code, over a generated Relion-like file of
100 000 rows. CodSpeed runs it under CPU simulation, which counts
instructions, so the noise of a shared runner does not reach the number,
and comments on the pull request how each benchmark moved against `main`.
It authenticates through OIDC, the repository being public, so no token is
kept. `REXLIB_BENCH_ROWS` changes the size for a local run.

CPU simulation leaves system calls out, since they cannot be simulated the
same way twice, so a benchmark that spends its time reading or writing the
file is understated, and CodSpeed says which. That is accepted: what this
phase optimises is CPU — tokens, Arrow, casts — and the walltime instrument
that would count the rest is noise on a shared runner. Time with the I/O in
it is what `scripts/compare.py` measures.

Nothing in it installs from source or resolves freely: the tools come from
wheels, pinned in the `bench` group alongside maturin and pyarrow, maturin
builds this package's wheel, and pip installs that wheel with `--no-deps`.

The comparison with starfile and starfile-rs is not a benchmark: their
releases would move it. `python -m scripts.compare` times one read of a
million rows through each, and the same workflow runs it on demand, writing
the table to the job summary.

## Release

`release.yml` builds the source distribution, and from it a wheel per
platform with cibuildwheel: Linux and macOS on x86_64 and arm64, Windows on
x86_64. Building from the source distribution rather than the checkout proves
the distribution builds. Each wheel is abi3 from 3.10, so one serves every
interpreter, and cibuildwheel runs `pytest` against it on 3.10 to 3.14.

It runs on a pull request that changes packaging, on a push to `main` that
changes what is packaged, on a `v*` tag, and on demand. A push to `main`
replaces the `development` prerelease with what it built. The PyPI job,
through trusted publishing and so without a token, stays off until the
package name is settled in
[#40](https://github.com/gigabit-clowns/rexlib-metadata/issues/40).

None of the organisation's composites fits: they cache C++ builds and set up
MSVC. Its `release.yml` tags from a `VERSION` file, and the version here
lives in `Cargo.toml`; tagging waits on the name as well.

## What is not here

Publishing to PyPI is
[#40](https://github.com/gigabit-clowns/rexlib-metadata/issues/40), and is
not an absence to reproduce elsewhere.
