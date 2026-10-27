# Continuous integration

What runs on a pull request, what it costs, and why it is arranged this way.
`AGENTS.md` says only that the gate has to be green; this says what the gate
is made of.

One workflow, `build-and-test.yml`, on pull requests, on a push to `main`
that touches something other than documentation, and on demand. A second push
to the same ref cancels the run in flight.

`keep-caches-warm.yml` runs every morning, and on a change to itself.

| Job | Does |
|---|---|
| `lint` | `ruff check .` and the cognitive complexity check, once |
| `build_with_cargo` | `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`, `cargo build`, `cargo test`, on the three platforms |
| `build_with_pip` | `pip install .[test]` and `pytest tests/python/`, three platforms × Python 3.10 to 3.15, and once more on the oldest extras |

One cell of nineteen installs the **oldest** polars and pandas this package
says it supports rather than the newest. The extras declare a range —
`polars>=1.0`, `pandas>=2.2.2` on 3.10 — and a range nobody tests at its floor
is a claim rather than a fact; the pins in `[test]` only ever prove the
ceiling. Testing the floor and the ceiling and not the middle is the usual
compromise, and it is cheap here because polars reaches us through one
function.

That cell is Linux on 3.10 because it has to be: the `<3.0` half of the
pandas extra is declared for 3.10 alone, so 3.10 is the only cell whose floor
2.2.2 is. Its first run moved that floor up from 2.0, pandas before 2.2.2
having been built against numpy 1's headers and dying on import beside
numpy 2. It is added by an
`include` whose `extras` value is outside its dimension, which is what makes
Actions create a cell instead of replacing the one that matches.

The linters run once, in a job of their own, because they read the source and
the source is the same in every cell. Nineteen copies of one answer was the
smaller half of the waste: `complexipy` is a Rust package with no wheel for
3.15 outside Linux, so two cells were building it — 177 crates, two minutes
and ten seconds, more than this library's own build — to ask a question that
had already been answered seventeen times. The job reads the pip cache under
that key and never writes to it, so there is no fourth entry and no race.

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
are six entries.

What would have dropped them is the other rule, that an entry goes a week
after its last read. `keep-caches-warm.yml` reads all six every morning
through the organisation's workflow, which looks each one up by prefix and
downloads nothing — a lookup is a read, and a read is what resets the week.
A quiet fortnight therefore costs nothing, where before it would have cost
the next pull request a cold build on twenty-two cells.

Actions are pinned by digest, and Renovate keeps both the digests and the
dependencies moving, under a 14-day minimum release age that security
advisories skip.

The Rust toolchain is the exception: `dtolnay/rust-toolchain@stable` follows
stable wherever it goes, and clippy's `pedantic` group grows with it. A new
release can therefore fail a build nobody touched — it has happened once,
with `assert_is_empty`, and the lint was right. The tax is small and the
lints have been improvements, so the arrangement stays; pinning the toolchain
in `rust-toolchain.toml` is the alternative, and the moment to take it is the
second time a release costs more than it gave.

## What is not here

Coverage, a SonarQube scan and CodeQL are [#39](https://github.com/gigabit-clowns/rexlib-metadata/issues/39),
scheduled for after Phase 2. Publishing is
[#40](https://github.com/gigabit-clowns/rexlib-metadata/issues/40). None of
the three is an absence to reproduce elsewhere.
