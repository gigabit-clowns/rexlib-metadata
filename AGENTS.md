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
- `docs/` holds the design, the plan, continuous integration and the
  dependencies, one subject each. The table at the foot of this file says
  when each is worth opening.

## What is built and what is designed

Most of what follows describes an architecture that is only partly built. The
design is settled and the code is catching up with it, so read every section
knowing which of the two it is talking about:

| Layer | State |
|---|---|
| STAR reader, values as strings, one block | Built, `src/star/` |
| Arrow as the canonical representation | Built |
| `Reader` ABC, `MetadataRegistry`, `ReadResult` | Built, minimal |
| `Convention` ABC in `abc.py` | A placeholder; Phase 2 replaces it |
| Schema layer (`ColumnDescriptor`, `TableSchema`, …) | Designed, not written |
| `ReadConvention` / `WriteConvention`, bundles, engine | Designed, not written |
| Writers, chunking, multi-table, XMD, SQLite, HDF5 | Designed, not written |

`docs/roadmap.md` is the authority on what comes next and in which order.
Nothing here commits to a shape the roadmap has not reached yet, but the
invariants at the end of this file already bind what gets written.

## Layout

| Path | Holds |
|---|---|
| `src/lib.rs` | The PyO3 module `_rexlib`: thin wrappers, error conversion, nothing else |
| `src/star/lexer.rs` | `tokenize_line`, one line to tokens, quoting and comments |
| `src/star/parser.rs` | `parse_blocks`, the state machine from tokens to `StarBlock`s |
| `src/star/builder.rs` | `StarBlock` rows to an Arrow `RecordBatch` |
| `src/star/mod.rs` | `StarError`, `RawSchema`, and the crate-facing `read_schema` / `read_all` |
| `python/rexlib_metadata/` | The public Python package |
| `python/rexlib_metadata/_rexlib.pyi` | Stubs for the compiled module |
| `tests/python/` | pytest suites, with their sample files in `fixtures/` |
| `docs/` | Design notes and roadmap: everything too specific for this file |
| `ruff.toml` | The lint rules of the Python, the authority on its style |
| `CHANGELOG.md` | What a user of the package would notice, newest first |

Rust unit tests live in a `mod tests` at the foot of the file they cover,
which is why there is no `tests/rust/`. `tests/` is the Python side only.

`src/star/` is a directory, not the single `src/star.rs` that older notes
describe, and there is no `src/parser/`, `src/serializer/`, `src/convention/`
or `src/arrow_bridge.rs`. The split by *stage* — lex, parse, build — is the
shape to follow when a second format arrives: a format gets a directory under
`src/`, and inside it the same three stages.

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
to do too.

`src/lib.rs` keeps no logic. It wraps, converts `StarError` into a Python
exception, and returns. Logic that creeps into it is logic Rust's own tests
cannot reach.

## Building and testing

```bash
pip install maturin
maturin develop          # builds the extension into the active environment
pytest tests/python/     # the Python suites
cargo test               # the Rust unit tests

bash scripts/local-gate.sh   # all of it, in CI's order
```

The gate is the one to run before pushing: `cargo fmt --check`, build, test,
clippy at `-D warnings`, then ruff and pytest, stopping at the first failure.
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
| The schema | What a canonical table's columns are: name, type, unit, required or defaulted. Knows no file format | designed, `docs/design.md` |
| The conventions | Which file columns make which canonical ones, per format, read and write kept apart | designed, `docs/design.md` |

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

`_rexlib.pyi` is written by hand. A function added to `_rexlib` gets its stub
in the same pull request, or the Python side is typed against something that
no longer exists.

A class that implements an interface is named after it, with what sets it
apart in front: `StarReader` is a `Reader`, `Relion4Bundle` is a
`ConventionBundle`. The name says what the thing is before the reader has to
open it.

Nothing that comes out of a file may reach a panic. A malformed file is an
error with a line number, so arithmetic over counts and offsets read from one
is checked, and nothing indexes with a number the file supplied. `expect` is
for what the code has just proven about itself, never for what a file
promised.

### Comments

As few as possible, and none at all wherever that is possible. A comment says
**what**, never **why**. The why belongs in the commit message and the pull
request, where it can be read against the change that motivated it instead of
rotting in a file that moved on without it.

And the what only when the code does not already say it. If a reader
understands the line without the comment, the comment does not go in. A
banner announcing that the types come next, a note restating the signature
above it, an explanation of what a well-known macro generates — all of that
is text to be kept true for no gain.

The rule covers every file, not just the Rust and the Python: a workflow step
whose name already says what it runs does not also need a paragraph above it.
What does stay is the thing that is not a comment at all — a docstring, a
`# noqa`, an attribute — and, where a contract has to be written down
somewhere, `docs/` is where it goes.

There is not a single `TODO` in the repository, and there is not meant to be.
Unfinished work is an issue: a comment nobody is assigned to, that no search
finds and that no pull request closes, is a way of forgetting something in
writing. `docs/roadmap.md` keeps the plan — the phases, in order — and
everything else that is missing lives in the tracker.

The package targets Python 3.10, which is what Ubuntu 22.04 ships and what
its users therefore have; the end of 3.10's own support is not the thing
that decides this. Every module that annotates anything opens with
`from __future__ import annotations`, and `X | None` is written only under
it. pandas, polars and even pyarrow go inside `if TYPE_CHECKING:` where
they are used for types alone, and inside the function where they are used at
run time. An optional dependency imported at module scope stops being
optional.

On the Rust side, errors are a `thiserror` enum per format, carrying the path
and the line number where there is one, and `lib.rs` converts them at the
boundary. Nothing panics on bad input: `expect` is for what the code itself
has just proven, and its message names the guard that proves it.

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

**A fixture of a file format comes from a program that writes that format**,
trimmed to a few rows, never typed out from our reading of the specification.
A hand-written STAR file tests that the parser agrees with whoever wrote the
fixture, which is the same person who wrote the parser; only a file Relion,
Xmipp or cryoSPARC actually produced can contradict us. The real ones land in
`tests/files/`, where both suites can reach them, each with a note saying
where it came from and what about it is worth a test. The small invented ones
that predate this rule stay for what they are, cases the format allows that
no file we have happens to contain.

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
  column; it raises at registration.
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
| [docs/roadmap.md](docs/roadmap.md) | picking up work, or finishing a phase: the ordered phases and where they stand |
| [docs/ci.md](docs/ci.md) | touching a workflow, or wondering why a run costs what it costs: the jobs, the cache and what keeps it warm |
| [docs/dependencies.md](docs/dependencies.md) | adding, raising or pinning a dependency: the feature that must stay off, the two crates that move as one, and why two pins are split |
| the issue tracker | looking for what is missing — loose ends are issues, not a list in a file |

A document says what is. The history is in the commits, so nothing here
records what something used to be; a decision worth keeping goes to
`docs/design.md` as a decision, not as a story about how it was reached.

This file holds what a newcomer needs before they can usefully read either of
those. Keep it that way: an architectural rule or an invariant belongs here,
a phase's checklist or a code-level interface belongs in `docs/`.
