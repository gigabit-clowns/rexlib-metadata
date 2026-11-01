# Working on rexlib-metadata

Reads and writes CryoEM metadata — Relion STAR, Xmipp XMD, SQLite, HDF5 —
into one canonical Arrow table, handed to Python as pandas or polars. Part of
the REX suite (gigabit-clowns), but depends on nothing else in it.

## In short

- Rust parses and produces Arrow; Python decides everything else. The public
  extension surface is the Python ABCs; `_rexlib` is private.
- `bash scripts/local-gate.sh` runs what CI runs. Green before pushing.
- Everything written down — docs, code, comments, commits, pull requests —
  is in English.
- A change that makes a document here wrong updates it in the same pull
  request. Unfinished work is an issue, never a `TODO`.
- What is built and what comes next: `docs/roadmap.md`.

## Layout

| Path | Holds |
|---|---|
| `src/lib.rs` | The PyO3 module `_rexlib`: wrappers and error conversion only |
| `src/error.rs` | `Error`, carrying the path and the line |
| `src/text/` | Format-agnostic: `Token`, the line-at-a-time `Parser`, `ArrowSink` (rows ↔ `Utf8` batches) |
| `src/star/` | STAR's lexer and writer, and `read_tables` / `Chunks` |
| `python/rexlib_metadata/abc.py` | `Reader` and `Writer` |
| `…/registry.py` | `MetadataRegistry`: picks reader, writer and bundles |
| `…/schema.py`, `canonical.py` | The canonical columns and tables, from `docs/canonical.md` |
| `…/convention.py` | Convention interfaces and `ConventionBundle` |
| `…/formats/` | One reader and writer per file format |
| `…/conventions/` | One module of conventions per dialect: Relion, Xmipp |
| `…/engine.py` | The read and write engine |
| `…/result.py` | `ReadResult`, `RawResult`, `Chunk` |
| `…/writing.py`, `join.py`, `_arrow.py` | Writing frames, the optics join, Arrow conversions |
| `…/_rexlib.pyi` | Hand-written stubs for the compiled module |
| `tests/python/`, `tests/files/` | pytest suites; real files, each with its origin |
| `benchmarks/`, `scripts/` | CodSpeed benchmarks; gate, comparison, charts |

Rust unit tests live in `mod tests` at the foot of each file. A new delimited
format adds a lexer and a speller under `src/<format>/`, not a parser.

## The two sides

Rust does file I/O and parsing and produces Arrow. Python does the policy:
which reader, which convention, what a canonical table is.

A user adds a format by subclassing `Reader` / `Writer` in pure Python and
registering it. `StarReader` is an ordinary such class that calls `_rexlib`;
whatever it can do, a user's reader must be able to do. Built-ins are
registered in `__init__.py`; `registry.py` names no format.

A reader implements `read_tables`, returning one `RawTable` per table, and
may override `read_tables_keeping` to skip columns while parsing and
`read_schemas` to name tables and columns without reading rows. A writer
implements `write_tables`. Neither knows the registry.

`lib.rs` keeps no logic: it wraps, releases the GIL while Rust reads, and maps
`Error` to `FileNotFoundError` (missing), `ValueError` (malformed) or
`RuntimeError` (Arrow, i.e. our bug).

## Building and testing

```bash
pip install --group develop    # maturin and pyarrow
maturin develop                # the extension, into python/rexlib_metadata/
pip install --group test --group lint
pytest tests/python/
cargo test
bash scripts/local-gate.sh     # all of it, in CI's order
```

Groups install without the project, so they do not rebuild the crate. The
gate runs `cargo fmt --check`, build, test, clippy `-D warnings`, ruff,
complexipy, mypy and pytest, rebuilding the extension first.

PyO3's `extension-module` feature is enabled through `[tool.maturin]` and
must stay off in `Cargo.toml`: with it, `cargo test` does not link.

## Code conventions

- Four spaces in Python and Rust, two in YAML, 80 columns. `rustfmt` and
  `ruff.toml` are the authority; CI enforces both.
- Examples import the package as `rxm`.
- Every source file, tests included, opens with
  `# SPDX-License-Identifier: LGPL-2.1-or-later` (`// ` in Rust; after the
  shebang in shell).
- A function added to `_rexlib` gets its stub in `_rexlib.pyi` in the same
  pull request. mypy runs with `pyarrow-stubs`; narrow with `cast`, never a
  blanket ignore.
- A class is named after the interface it implements, distinguishing part
  first: `StarReader`, `Relion4Bundle`.
- Nothing from a file may reach a panic: checked arithmetic, no indexing with
  a number the file supplied, `expect` only for what the code just proved.
  Clippy's `indexing_slicing` and `unwrap_used` enforce it outside tests;
  `unsafe_code` is forbidden.
- Python targets 3.10: `from __future__ import annotations` in every module
  that annotates; pandas, polars and pyarrow imported under `TYPE_CHECKING`
  for types and inside functions at run time.
- Rust errors are a `thiserror` enum carrying path and line, converted in
  `lib.rs`.

### Complexity

Cognitive complexity as Sonar counts it. Aim for five per function; seven is
the ceiling, enforced by `complexipy` and by `clippy::cognitive_complexity`
(`[lints]` in `Cargo.toml`). Flattening nested loops into generator
expressions is the cheapest fix. CI uses stable Rust; `rustup update` before
trusting a local green.

### Comments

Only where the code cannot say it, in every file including workflows. A
comment says what, never why — the why goes in the commit message, a
contract in `docs/`.

### Documentation

Every word here is read by every agent on every task, so:

- Say only what the code, the manifests and the workflows cannot. Link
  rather than restate.
- State a rule once ("the floor is what the code needs, the ceiling the
  newest CI passed"), never the reason behind each version number.
- Describe what is, not how it got there: no history, no "used to", no
  "what changed in this pull request".
- A table or a bullet over a paragraph; one sentence over three.
- Reread the diff before committing and cut what only explains, narrates or
  repeats.

### Tests and fixtures

- Small, and first. A Python test file is named after the source file it
  exercises; a parametrized case has an `id`; a fixture one file uses starts
  with `_`.
- Files written by tests go to `tmp_path` / `tempfile`, never a fixed path.
- An assertion about a file uses the value read from the file, not a
  remembered one.
- A format fixture comes from a program that writes that format, trimmed,
  and lives in `tests/files/` with a note on its origin and licence.
  Hand-written ones only cover what no real file contains.

## Working here

- **The smallest complete change.** List every place it reaches — a Rust
  entry point is also a stub, a wrapper, a test per side and a doc line. Then
  take the first option that works: nothing, what exists, the standard
  library, an installed dependency, new code. No unrequested options. Never
  cut what was asked for, validation of file input, or the safety of a write.
- **Say what was left out**, assumed, or not run against a real file.
- **Bounded output.** Narrow test runs, logs and greps before reading them.
- **Explore through subagents** when only the conclusion matters.
- **Say when to start fresh**, with a prompt to paste: goal, branch, state,
  what is left, what to read.

## Pull requests

- Assign yourself; label `bug`, `enhancement` or `documentation`.
- A change a user would notice adds a line to `CHANGELOG.md`; refactors,
  tests and workflows do not. The changelog holds the next release only, in
  the shape of its notes: a summary sentence, then `### New`, `### Changed`,
  `### Fixed`, one short line each. Before the first release, only `### New`.

## Design invariants — do not violate

- The public extension surface is the Python ABCs. Rust traits are internal,
  and `_rexlib` is private.
- A reader never infers a type: it reports what the format states, `Utf8`
  for STAR, and typing is the schema's.
- Missing is Arrow's null. A value that does not parse is an error naming
  the line; a format's sentinels are translated by its conventions.
- A `ReadResult` holds no open file handle once `read()` has returned.
- `columns=` reads only the columns asked for. A write forwarding the rest
  re-reads the source, and writes through a temporary file beside the
  destination.
- Read and write are separate pipelines with separate conventions, neither
  written as the inverse of the other.
- A raw table matches a canonical one by column presence through
  `matches()`, never by name.
- No two `ReadConvention`s of one bundle produce the same canonical column.
- Priority is per bundle: the first bundle to produce a column owns it.
- Validation is strict: unknown columns and missing required ones raise.
- Every heuristic has an override, every built-in an injectable counterpart.

## Where the rest lives

| File | Open it when |
|---|---|
| [docs/design.md](docs/design.md) | touching the schema, conventions or engine, or taking a lasting decision |
| [docs/formats.md](docs/formats.md) | adding or assessing a format |
| [docs/canonical.md](docs/canonical.md) | touching a column, unit or convention |
| [docs/roadmap.md](docs/roadmap.md) | picking up or finishing work |
| [docs/ci.md](docs/ci.md) | touching a workflow or the Sonar configuration |
| [docs/dependencies.md](docs/dependencies.md) | adding, raising or pinning a dependency |
| the issue tracker | everything missing that is not a phase |
