# Working on rexlib-metadata

rexlib-metadata reads and writes the metadata formats of CryoEM — Relion
STAR, Xmipp XMD, and later SQLite and HDF5 — into one canonical in-memory
table that Python hands over as a pandas or polars DataFrame. It is part of
the REX suite (gigabit-clowns), but unlike the rest of it this repository
stands alone: it depends on no other project of the suite, and nothing of the
suite is needed to build it.

Keep this file true. When a change makes something here wrong or missing — a
moved directory, a new convention, a dependency, a workflow, an invariant
that stopped holding — update it in the same pull request that causes it. The
rule covers `README.md` and everything under `docs/` just as much: a change
that makes a document wrong is not finished until the document is right
again, and a pull request that leaves documentation stale is an incomplete
pull request. When in doubt about which document something belongs in, see
[the last section](#where-the-rest-lives).

## In short

- Rust parses and produces Arrow; Python decides everything else. The public
  extension surface is the Python ABCs, and `_rexlib` is private.
- `bash scripts/local-gate.sh` runs what CI runs. Green before pushing.
- Docs, code, comments, commits and pull requests are in English, whatever
  language the conversation is in. A squash merge turns a pull request's
  title and body into a commit message.
- A document this change makes wrong is part of the change. Unfinished work
  is an issue, never a `TODO`.
- `docs/` holds the design, the canonical vocabulary, the formats, the plan,
  continuous integration and the dependencies, one subject each. The table at the foot of this file says
  when each is worth opening.

## What is built and what is designed

Most of what follows describes an architecture that is only partly built. The
design is settled and the code is catching up with it, so read every section
knowing which of the two it is talking about:

| Layer | State |
|---|---|
| STAR reader, values as strings, every block | Built, `src/star/` |
| Arrow as the canonical representation | Built |
| `Reader` ABC, `MetadataRegistry`, `RawResult`, `ReadResult` | Built |
| Convention layer (`ReadConvention`, `WriteConvention`, `ConventionBundle`) | Built, `python/rexlib_metadata/convention.py` |
| Schema layer (`ColumnDescriptor`, `TableSchema`, …) | Built, `python/rexlib_metadata/schema.py`, carrying the catalogue of `docs/canonical.md` |
| The read engine | Built, `python/rexlib_metadata/engine.py`, and driving every read |
| The Relion 4 bundle, and a read that comes back canonical | Built, `python/rexlib_metadata/conventions/relion.py` |
| Writers, chunking, XMD, SQLite, HDF5 | Designed, not written |

`docs/roadmap.md` is the authority on what comes next and in which order.
Nothing here commits to a shape the roadmap has not reached yet, but the
invariants at the end of this file already bind what gets written.

## Layout

| Path | Holds |
|---|---|
| `src/lib.rs` | The PyO3 module `_rexlib`: thin wrappers, error conversion, nothing else |
| `src/error.rs` | `Error`, one for the crate, carrying the path and the line |
| `src/text/mod.rs` | `Token`, what every lexer of a text table produces |
| `src/text/parser.rs` | `parse_blocks`, the state machine from tokens to `Block`s, over any lexer |
| `src/text/builder.rs` | `Block` rows to an Arrow `RecordBatch` of `Utf8` |
| `src/star/lexer.rs` | `tokenize_line`, one line of STAR to tokens, quoting and comments |
| `src/star/mod.rs` | `read_tables`, the crate-facing STAR entry point |
| `python/rexlib_metadata/` | The public Python package |
| `python/rexlib_metadata/schema.py` | The canonical columns and the tables they compose |
| `python/rexlib_metadata/convention.py` | The convention interfaces and the bundles that group them |
| `python/rexlib_metadata/canonical.py` | The canonical columns as traits and tables, from `docs/canonical.md` |
| `python/rexlib_metadata/conventions/` | One module per format: its reader, and what its names mean |
| `python/rexlib_metadata/result.py` | `ReadResult`, a file in canonical terms, and `RawResult`, the same file in its own |
| `python/rexlib_metadata/_rexlib.pyi` | Stubs for the compiled module |
| `tests/python/` | pytest suites, with their sample files in `fixtures/` |
| `docs/` | Design notes and roadmap: everything too specific for this file |
| `ruff.toml` | The lint rules of the Python, the authority on its style |
| `clippy.toml` | The complexity threshold clippy holds the Rust to |
| `.sonarcloud.properties` | What SonarQube Cloud calls a source and what it calls a test |
| `CHANGELOG.md` | What a user of the package would notice, newest first |

Rust unit tests live in a `mod tests` at the foot of the file they cover,
which is why there is no `tests/rust/`. `tests/` is the Python side only.

The split is by *stage* — lex, parse, build — and by whether a stage knows
one format. `src/star/` holds the only thing that is STAR's: a lexer that
turns a line into tokens. The state machine that assembles those tokens into
blocks, and the builder that turns a block into Arrow, know nothing about any
format and live under `src/text/`, where the next delimited format reaches
them by handing `parse_blocks` its own lexer.

That is the shape to follow when a second format arrives: write a lexer, not
a parser.

## The two sides

Rust does the file I/O and the parsing, and produces Arrow. Python does the
policy: which reader, which convention, what the canonical table looks like,
what the user's call means. The boundary is drawn there on purpose.

The public extension surface is the Python ABCs, and only those. A user adds
a format by subclassing `Reader` in pure Python and registering it; nothing
on that path requires Rust, a rebuild, or a fork. The Rust types and traits
are implementation details and may change without notice, and the compiled
module `_rexlib` is private — the underscore is the contract. Outside this
repository, only `rexlib_metadata` is ever imported.

A Rust-backed reader such as `StarReader` is therefore an ordinary Python
class satisfying the `Reader` ABC that happens to call `_rexlib` inside. To
the registry it is indistinguishable from a reader a user wrote, and it has
to stay that way: whatever `StarReader` can do, a user's reader must be able
to do too. It is registered where a user would register theirs, in the
package's `__init__`, which is the only module that knows both the registry
and what ships in the box; `registry.py` names no format.

A reader implements `read_tables` and nothing else, returning one `RawTable`
per table the file holds, because a file holding several is the ordinary case
and not the exception. `Reader.read` is concrete and returns the lazy result,
because there is exactly one correct body for it and a second copy of that
line is a chance to break the rule that a read opens no file.

`src/lib.rs` keeps no logic. It wraps, turns `Error` into the Python
exception that answers it — a missing file into `FileNotFoundError`, a
malformed one into `ValueError`, an arrow failure into `RuntimeError`, since
only the last of those is our bug — and releases the interpreter while Rust
reads, so a thread that wants to do something else can. Logic that creeps
into it is logic Rust's own tests cannot reach.

## Building and testing

```bash
pip install maturin
maturin develop            # builds the extension into the active environment
pip install .[test]        # the suites
pip install --group lint   # the linters and the type checker the gate runs
pytest tests/python/       # the Python suites
cargo test                 # the Rust unit tests

bash scripts/local-gate.sh   # all of it, in CI's order
```

`lint` is a dependency group rather than an extra, because a group installs
without the project: the linters read the source and have no use for the
compiled module, and asking pip for an extra would have built the whole crate
to deliver ruff. CI runs them once rather than in every cell, the source
being the same source nineteen times over. A development environment wants
both lines.

The gate is the one to run before pushing: `cargo fmt --check`, build, test,
clippy at `-D warnings`, then ruff, the complexity check and pytest,
stopping at the first failure.
It rebuilds the extension before pytest, so that the suite is not run against
yesterday's build, and it reaches for `.venv` or whichever environment is
active and calls the tools through its interpreter rather than through the
launchers beside it, which are not reliable everywhere.

`maturin develop` puts the compiled `_rexlib` next to the sources, inside
`python/rexlib_metadata/`, where `.gitignore` expects it. `pip install .[test]`
does the same build and brings pandas, polars and pytest with it, which is
what CI runs.

PyO3's `extension-module` feature is enabled by maturin, through
`[tool.maturin] features` in `pyproject.toml`, and is deliberately not on in
`Cargo.toml`. Do not put it back there. The feature drops the link against
libpython, which is right for a wheel loaded by an interpreter that already
holds those symbols and fatal for anything else: a `cargo test` binary built
with it resolves no Python symbol and does not link. Off by default, a plain
`cargo build` or `cargo test` links against whichever interpreter the build
script finds, which is why the Rust CI job sets Python up even though it runs
none.

## The architecture in short

Four layers, and the whole design is in which of them a decision belongs to.

| Layer | Holds | Written down in |
|---|---|---|
| The reader | A file of one format, read into Arrow with no type guessed | `src/star/`, and the `Reader` ABC |
| The canonical form | Apache Arrow, which both pandas and polars are built on, so neither is privileged and neither is a hard dependency | `docs/design.md` |
| The schema | What a canonical table's columns are: name, type, unit, required or defaulted. Knows no file format | built, `schema.py`, designed in `docs/design.md` |
| The conventions | Which file columns make which canonical ones, per format, read and write kept apart | built, `convention.py`, designed in `docs/design.md` |

Around them, the registry, which picks a reader and a set of conventions
from the file's extension and, where that is not enough, its content — and
lets the caller override either. Dependency inversion is the requirement
this library exists to satisfy, so every one of those four layers takes
something the user wrote as readily as something that ships.

The invariants at the foot of this file are what none of it may violate.
`docs/design.md` is the layer-by-layer version, with the interfaces in code,
the read engine and the questions still open; read it before touching the
schema or the conventions.

## Code conventions

Python is four spaces, Rust is four spaces, YAML is two, and lines stay
within 80 columns. `.vscode/settings.json` says as much for the files it
names; for the ones it does not, Python among them, it defaults to tabs and
the code does not follow it. Four spaces is what the code does and what to
keep doing.

`rustfmt` is the authority on the Rust and `ruff.toml` on the Python, and CI
enforces both: `cargo fmt --check` and clippy at `-D warnings` on one side,
`ruff check .` on the other. Run them before pushing and leave nothing
behind. The ruff rules are the ones rexlib-python settled on, minus what only
a repository indenting with tabs needs.

An example imports the package as `rxm`, three letters out of its own name
the way vitrio takes `vio`. Not `rm`, which is the command that deletes
things and which no documentation of a library that writes files should put
in front of a reader.

Every source file opens with its licence, on the first line, as vitrio does
it: `# SPDX-License-Identifier: LGPL-2.1-or-later` in the Python and the
shell, `// ` in the Rust, and in a shell script on the line after the
shebang. Tests included — a file that travels on its own says what it is. A
new file without that line is an incomplete file.

`_rexlib.pyi` is written by hand. A function added to `_rexlib` gets its stub
in the same pull request, or the Python side is typed against something that
no longer exists.

mypy is what keeps that stub, and every annotation beside it, honest: it runs
in the `lint` job and in the local gate, at its default strictness against
the floor in `requires-python`. `pyarrow-stubs` is installed with it on
purpose — pyarrow ships no types of its own, and without them every Arrow
call in this package is `Any` and the check is theatre. An annotation that
the checker cannot prove is narrowed with `cast` at the one line that knows
why, never with a blanket ignore.

A class that implements an interface is named after it, with what sets it
apart in front: `StarReader` is a `Reader`, `Relion4Bundle` is a
`ConventionBundle`. The name says what the thing is before the reader has to
open it.

Nothing that comes out of a file may reach a panic. A malformed file is an
error with a line number, so arithmetic over counts and offsets read from one
is checked, and nothing indexes with a number the file supplied. `expect` is
for what the code has just proven about itself, never for what a file
promised.

### Complexity

Cognitive complexity, counted the way Sonar counts it: an `if`, a loop, a
`try` or a boolean chain is one, plus one more for every level of nesting it
sits inside. Three nested loops are 1 + 2 + 3, not 3.

**Five per function is the aim. Seven is the ceiling**, for the particular
case that earns it, and `complexipy` fails the gate above it.

The nesting weight is why flattening pays more than it looks: the same three
loops written as a generator expression score three where the nested form
scores six, for identical behaviour and, measured, identical speed.

On the Rust side `clippy::cognitive_complexity` is on at the same number,
through `[lints]` in `Cargo.toml` so that it covers the tests too. Clippy
counts by its own approximation rather than Sonar's, so the figure means less
there — it is a tripwire, not a measurement.

The gate is only as current as the toolchain running it. CI installs stable,
which moves, so a local toolchain left behind runs a clippy that CI does not
have and reports green on code CI will reject — `rustup update` before
trusting a green gate on a day when Rust has released. Pinning the toolchain
would settle it by construction, and is the answer if this happens twice.

`[lints]` carries the rest of what this crate is held to: `unsafe_code` is
forbidden, `indexing_slicing` and `unwrap_used` are warnings that CI turns
fatal, and `pedantic` is on. The first two are the AGENTS rule about files
made mechanical — nothing may index with a number a file supplied — and they
are allowed inside `mod tests`, where indexing a fixture is the point.

### Comments

As few as possible, and none at all wherever that is possible. A comment says
**what**, never **why**: the why belongs in the commit message, where it is
read against the change that motivated it instead of rotting in a file that
moved on without it.

And the what only when the code does not already say it. A banner announcing
that the types come next, a note restating the signature above it, an
explanation of what a well-known macro generates — all of that is text to be
kept true for no gain. The rule covers every file, a workflow step included.
What stays is the thing that is not a comment at all: a docstring, a
`# noqa`, an attribute. A contract that has to be written down somewhere goes
in `docs/`.

Unfinished work is an issue, never a `TODO`: `docs/roadmap.md` keeps the
phases in order and the tracker keeps everything else.

### Typing and errors

The package targets Python 3.10, which is what Ubuntu 22.04 ships. Every
module that annotates anything opens with
`from __future__ import annotations`, and `X | None` is written only under
it. pandas, polars and even pyarrow go inside `if TYPE_CHECKING:` where
they are used for types alone, and inside the function where they are used at
run time. An optional dependency imported at module scope stops being
optional.

On the Rust side, errors are a `thiserror` enum per format, carrying the path
and the line number where there is one, and `lib.rs` converts them at the
boundary. Nothing panics on bad input: `expect` is for what the code itself
has just proven, and its message names the guard that proves it.

### Tests and fixtures

Tests come first and they stay small. A Rust module keeps its tests at its
own foot in `mod tests`; the Python suites live under `tests/python/`, with
fixtures as small as they can be while still showing what they are about.

A test that writes names its file through `tempfile` in Rust or `tmp_path` in
pytest, never a fixed path. Cases run at once, and two of them agreeing on a
name is a failure that only shows up on somebody else's machine.

A Python test file is named after the source file it exercises and sits where
that file sits, so that `conventions/star.py` is answered by
`test_star_reader.py` and a reader of either can find the other. A
parametrized case carries a short `id` through `pytest.param`, because a
failure reported as `[case3]` says nothing. A fixture only one file uses
starts with an underscore.

**An assertion about a file comes from the file.** Open it, read the value,
paste it. A remembered number is a guess, and a test built on one fails for
the wrong reason or, worse, passes.

**A fixture of a file format comes from a program that writes that format**,
trimmed to a few rows, never typed out from a reading of the specification. A
hand-written STAR file tests that the parser agrees with whoever wrote the
fixture, which is the same person who wrote the parser; only a file Relion,
Xmipp or cryoSPARC actually produced can contradict it. The real ones live in
`tests/files/`, each with a note saying where it came from and what it is
there for, and the licence of whoever wrote it where that applies. The
invented ones that remain cover cases the format allows and no real file
happens to contain.

## Working here

Docs, code, comments, commits and pull requests are written in English,
whatever language the conversation that produced them was in. A squash merge
turns a pull request's title and body into a commit message, which is why
they are held to the same standard as one.

**The smallest complete change.** Read the code the change touches first, and
list every place it has to reach — this repository has two sides, so a new
entry point in Rust is also a stub in `_rexlib.pyi`, a wrapper on the Python
side, a test in each suite and a line in whichever document described the old
behaviour. Then take the first option that fully works: nothing at all, then
what the repository already has, then the standard library, then a dependency
already installed, then the least new code. No option, no wrapper, no
configuration and no "for later" that nobody asked for; this library's whole
pitch is that the user injects what they need, and every knob added here is
one they did not get to choose. What is never cut to make a change smaller:
what was actually asked for, validation of what came out of a file, and the
error handling that keeps a write from destroying the file it replaces.

**Say what was left out.** A change that skipped something, assumed
something, or was not run against a real file says so in a line, rather than
being presented as finished.

**Bounded output.** A test run, a log or a CI result is narrowed before it
enters the conversation — the line that says how many passed, not the
thousand that say which. The same for `git log` and for anything that greps
a whole tree.

**Explore through subagents.** A search that sweeps many files or several
repositories, and whose output only matters as a conclusion, goes to a
subagent. Read directly when the file and the place in it are already known.

**Say when to start fresh.** When the next task shares nothing with the
current conversation, or the conversation has grown long, propose a new one
and hand over a prompt to paste into it: the goal, the branch, where things
stand, what is left, and which files and documents to read first.

## Pull requests

Whoever opens one assigns it to themselves and gives it the label, among the
repository's own, that matches what it changes: `bug` for a fix,
`enhancement` for something new, `documentation` when only documentation
changes.

A change a user would notice adds its line to `CHANGELOG.md` in the same
pull request. A refactor, a test or a workflow does not: the changelog is
read by people who install the package, not by people who work on it.

The file holds the next release and nothing else, already in the shape of
its notes: a sentence of summary, then `### New`, `### Changed` and
`### Fixed`, one short line each and no commit hashes. Releasing publishes
it and empties it, and the versions before it live in their own releases.

## Design invariants — do not violate

- The public extension surface is the Python ABCs. Rust traits are internal,
  and `_rexlib` is private.
- A reader never infers a type. It reports the types the format states, and
  for a format that states none, as STAR does, that means `Utf8` for
  everything and the typing left to the schema.
- Missing is Arrow's null and nothing else. A value that does not parse is
  an error naming the line, not a null; a format's sentinels are translated
  by its conventions, never by the core.
- A `ReadResult` holds no open file handle once `read()` has returned.
- `columns=` reads only the columns asked for. Forwarding the rest on write
  re-reads the source rather than holding it in memory, and writes through a
  temporary file in the destination directory.
- Read and write are separate pipelines with separate conventions. Neither
  may be written as the inverse of the other.
- A raw table is matched to a canonical table by column presence, through
  `matches()`. Never by the raw table's name.
- No two `ReadConvention`s of one bundle may produce the same canonical
  column; it raises when the bundle is built.
- Priority lives at the bundle level, not the column level. The first bundle
  to produce a canonical column owns it.
- Schema validation is strict: unknown columns raise, and required columns
  that no convention produced raise.
- Every heuristic has an override, and every built-in has an injectable
  counterpart.

## Where the rest lives

| File | Read it when |
|---|---|
| [docs/design.md](docs/design.md) | touching the schema, the conventions or the reading model, or taking a decision that outlives the change: the requirements, the decisions and when they were taken, the interfaces in code, the read engine, and what is still open |
| [docs/formats.md](docs/formats.md) | adding a format, or deciding whether one fits: what each of them asks for, read off real files, and what in here answers it |
| [docs/canonical.md](docs/canonical.md) | touching a convention, a column or a unit: the canonical vocabulary, the tables it composes, and the conventions every format converts into |
| [docs/roadmap.md](docs/roadmap.md) | picking up work, or finishing a phase: the ordered phases and where they stand |
| [docs/ci.md](docs/ci.md) | touching a workflow or `.sonarcloud.properties`, or wondering why a run costs what it costs: the jobs, the cache, what keeps it warm, and what SonarQube Cloud reads |
| [docs/dependencies.md](docs/dependencies.md) | adding, raising or pinning a dependency: the feature that must stay off, the two crates that move as one, and why two pins are split |
| the issue tracker | looking for what is missing — loose ends are issues, not a list in a file |

A document says what is. The history is in the commits, so nothing here
records what something used to be; a decision worth keeping goes to
`docs/design.md` as a decision, not as a story about how it was reached.

This file holds what a newcomer needs before they can usefully read either of
those. Keep it that way: an architectural rule or an invariant belongs here,
a phase's checklist or a code-level interface belongs in `docs/`.
