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
```

`maturin develop` puts the compiled `_rexlib` next to the sources, inside
`python/rexlib_metadata/`, where `.gitignore` expects it. `pip install .[test]`
does the same build and brings pandas, polars and pytest with it, which is
what CI runs.

`cargo test` builds a test binary linking the whole crate, PyO3 included. It
works locally on Windows; CI does not run it, and `extension-module` being on
by default in `Cargo.toml` is the reason to verify before assuming it works
on the other platforms — see `docs/roadmap.md`.

## The canonical representation

Apache Arrow is the canonical in-memory form: `arrow-rs` on the Rust side,
the C Data Interface across the boundary. pandas and polars are both built on
Arrow, so one representation serves both without a second copy and without
either becoming a hard dependency — they are extras, imported only where a
`to_pandas()` / `to_polars()` call actually asks for them.

The reader produces every value as `Utf8`. No number is guessed, no date is
recognised, nothing is inferred from the look of a token. Typing is the
schema's job and conversion is the convention's job; a reader that types on
its own takes a decision away from the layer allowed to take it. Strings go
in and strings come out, until a convention says otherwise.

`pyo3-arrow` returns an `arro3` object rather than a `pyarrow` one. arro3 is
not a dependency and must not become one: the object is consumed through the
Arrow protocol methods it exposes, which is what `_to_pyarrow_table` in
`conventions/star.py` does. Any new Rust entry point returning Arrow goes
through that same function.

## Schema: the WHAT

The schema defines the canonical column structure and knows nothing about any
file format. A `ColumnDescriptor` is one canonical column — name, Arrow type,
and a default whose absence means the column is required. A `SchemaTrait` is
a reusable group of related columns, `EulerAngles` or `CartesianPosition`,
and exists only so that tables can be composed out of them; it flattens into
the table and has no identity at run time. A `TableSchema` is one table's full
column set, and a `Schema` is one or more tables, which is what a multi-block
Relion file needs.

Composition deduplicates: the same name with the same type across two traits
keeps the first silently, the same name with a different type is an error at
construction. Failing there rather than at read time is the point — a
contradictory schema is a programming mistake, not a data problem.

Validation is strict in the other direction too. An unknown column raises; it
is never passed through quietly.

## Conventions: the HOW

A convention maps file columns onto canonical columns. Reading and writing
are separate pipelines — decided on 2026-07-03 — and the separation is total:
separate ABCs, separate registration, separate lists inside a bundle.

Two reasons, and both matter. Writing a reader must not oblige anyone to
write the writer too, then or ever. And the mapping is genuinely not one to
one: a canonical column may have several possible origins in Relion while
there is exactly one place we would write it back to, so a single reversible
object would have to lie about one direction or the other.

A `ReadConvention` declares the file columns it consumes and the canonical
columns it produces, answers `matches()` for a raw schema, and `load()`s. A
`WriteConvention` declares the canonical columns it consumes and the file
columns it produces, and `store()`s. A `ConventionBundle` groups all the
conventions of one format — Relion4, Relion3, Xmipp — under a name.

Matching is by column presence, never by the name of the raw table. A raw
`data_particles` block becomes the canonical `particles` table because a
convention recognised its columns, not because a string matched. Table names
are the format's to choose and often the user's to mistype; the columns are
what can actually be relied on.

Two conventions of one bundle may not produce the same canonical column: that
is an ambiguity inside a unit meant to be coherent, and it is rejected when
the bundle is registered. Across bundles the conflict is legitimate and
priority resolves it — bundles are ordered, the first to produce a canonical
column owns it, and later bundles cannot overwrite what an earlier one
produced. Inside a bundle, every matching convention that adds something not
yet covered applies.

Required canonical columns that no convention produced are an error at the
end of the read, not a column of nulls.

`docs/design.md` carries the interfaces, the engine and worked examples.

## Registry, detection and injection

`MetadataRegistry` maps an extension to a reader and, from Phase 2, to an
ordered list of convention bundles. `global_registry` is the default
instance, built at import time with what ships in the box; a local instance
is how a test stays isolated from it.

Detection is a heuristic with an override, always in that order. A `.star`
gives the STAR reader and Relion conventions, a `.xmd` gives the same reader
with Xmipp conventions, and where the extension is not enough the file's
content decides. Every one of those decisions can be overridden at the call
site, and none of them may be the only way to reach a behaviour. Dependency
inversion is the requirement this library exists to satisfy: readers,
writers, conventions and columns all have to be injectable from the user's
side, so that a client can teach the library a format it has never heard of
without changing a line in here.

## Laziness, projection and forwarding

`rm.read()` returns a `ReadResult` and does no row I/O. Materialisation
happens in `to_pandas()` / `to_polars()`, and a `ReadResult` holds no open
file handle once the call that created it has returned: handles exist only
for the duration of actual I/O. A reader that keeps one open breaks every
caller that reads more files than the platform has descriptors.

`columns=` is a projection, never a load optimisation. The full batch is
always read, the selected columns are what the user sees, and the rest are
carried along silently so that a write can forward them untouched. Reading
two columns of forty, changing one and writing the file back has to leave the
other thirty-eight exactly as they were, and that only works if they were
never dropped.

## Pagination

Uniform for the user, format-specific underneath. Text formats get a
progressive index of chunk byte offsets, built as the chunks are read, over a
memory-mapped file — so neither sequential nor random access needs a
mandatory first full scan. SQLite and HDF5 get what they already have,
`LIMIT`/`OFFSET` and dataset slicing.

## Code conventions

Python is four spaces, Rust is four spaces, YAML is two, and lines stay
within 80 columns; `.vscode/settings.json` is set up for exactly that and is
the authority. No linter is configured yet, unlike the sibling repositories —
`docs/roadmap.md` tracks it.

The package targets Python 3.9. Every module that annotates anything opens
with `from __future__ import annotations`, and `X | None` is written only
under it. pandas, polars and even pyarrow go inside `if TYPE_CHECKING:` where
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

## Dependencies

| Crate / package | Why |
|---|---|
| `pyo3` | The Rust/Python binding |
| `arrow` (`arrow-rs`) | Arrow on the Rust side |
| `pyo3-arrow` | The C Data Interface bridge to Python |
| `thiserror` | The error enums |
| `tempfile` (dev) | Files for the parser tests |
| `pyarrow` (Python) | The Python half of the bridge; the only hard runtime dependency |
| `pandas`, `polars` | Extras, one per output backend |

Do not enable arrow's `pyarrow` feature. It pulls in `arrow-pyarrow`, which
pins an older pyo3 and conflicts with `pyo3-arrow`; `pyo3-arrow` is the only
bridge needed, and the two together do not build.

Supporting Python 3.9 is what makes the pins in `pyproject.toml` look
strange: pyarrow, pytest, pandas and polars each raised their floor above 3.9
at some release, so each is pinned twice behind a PEP 508 marker. Renovate
does not see the marker, so `renovate.json` tells the two halves apart with
`matchCurrentVersion` and caps only the old one. The `>=` ranges of the
`pandas` and `polars` extras are excluded from updates entirely: widening
them declares wider support, which is a decision for a person to take.

## Continuous integration

One workflow, `build-and-test.yml`, on pull requests and on demand. It builds
with `pip install .[test]` and runs `pytest tests/python/` across Linux,
macOS and Windows on Python 3.9 through 3.14, with `fail-fast` off so that
one broken cell does not hide the others. Actions are pinned by digest, and
Renovate keeps both the digests and the dependencies moving, under a 14-day
minimum release age that security advisories skip.

There is no Rust test job, no lint job, no coverage, no SonarQube scan and no
deployment. All five are known gaps, all five are in `docs/roadmap.md`, and
none of them is an absence to reproduce elsewhere.

## Design invariants — do not violate

- The public extension surface is the Python ABCs. Rust traits are internal,
  and `_rexlib` is private.
- Readers produce `Utf8` for everything. No type inference in a reader.
- A `ReadResult` holds no open file handle once `read()` has returned.
- `columns=` is a view. The full batch is always loaded, so that a write can
  forward the columns the user never asked for.
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

`docs/design.md` holds the design itself: the requirements this library was
written to satisfy, the decisions taken and when, the schema and convention
interfaces in code, the read engine, and the questions still open. Read it
before touching either layer.

`docs/roadmap.md` holds the ordered phases, what the current branch is in the
middle of, and the loose ends belonging to no phase.

This file holds what a newcomer needs before they can usefully read either of
those. Keep it that way: an architectural rule or an invariant belongs here,
a phase's checklist or a code-level interface belongs in `docs/`.
