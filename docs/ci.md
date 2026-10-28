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
| `lint` | `ruff check .`, the cognitive complexity check and `mypy`, once |
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
are six entries.

The rule that would drop them is the other one, that an entry goes a week
after its last read. `keep-caches-warm.yml` reads all six every morning
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

SonarQube Cloud watches the repository on its own, outside the workflow:
**automatic analysis**, which the organisation turned on and which scans
`main` and every pull request without a step of ours and without a token. The
badges at the head of `README.md` report what it finds, and the project is
`gigabit-clowns_rexlib-metadata`.

It is configured by `.sonarcloud.properties`, at the root and read from the
default branch. That is the file automatic analysis reads; the
`sonar-project.properties` the rest of the suite carries is for a scanner
invoked from a workflow, and automatic analysis ignores it. The properties it
accepts are a short list — sources, tests, inclusions, exclusions, encoding,
duplication exclusions, and the Python version — and **no value of any of
them may contain a wildcard**.

Ours says three things:

| Property | Why |
|---|---|
| `sonar.sources=src,python,scripts,.github` | everything that is shipped or that runs |
| `sonar.tests=tests` | a statement instead of a heuristic: the Python analyser recognises a test by its `test_*.py` name, and a helper in `tests/` without that name is a test too |
| `sonar.python.version=3.10` | the floor from `pyproject.toml`: a rule that wants newer syntax is wrong here until the floor moves |

The Rust is not analysed. SonarQube Cloud reads Rust through a clippy report
rather than a parser of its own, which needs a scanner step and a token, so
`src/` is listed under sources and no rule reaches it. Clippy in
`build_with_cargo` is what holds that half of the repository, and importing
its report is part of [#39](https://github.com/gigabit-clowns/rexlib-metadata/issues/39).

### What it flags and what stays flagged

Four rules of its default profile fire on this repository and will go on
firing. Three of the four are one rule in three costumes — lock your
dependencies — and a library is the one thing that must not:

- **a lock file is missing** (`uv.lock`, `poetry.lock`, `pylock.toml`), and
  **`pip install .[test]` resolves versions freely**. A library declares
  ranges; an application freezes a tree. Freezing ours would mean CI proving
  that one resolution works, when the claim in `pyproject.toml` is that every
  resolution inside the range does. The floors cell exists for exactly that
  reason.
- **`--only-binary :all:` is missing from `pip install .[test]`**, because a
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

## What is not here

Coverage, CodeQL, and the scanner-based Sonar analysis that would carry
coverage and the clippy report are
[#39](https://github.com/gigabit-clowns/rexlib-metadata/issues/39), scheduled
for after Phase 2. Publishing is
[#40](https://github.com/gigabit-clowns/rexlib-metadata/issues/40). Neither
is an absence to reproduce elsewhere.
