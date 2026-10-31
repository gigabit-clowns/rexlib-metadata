# Roadmap and backlog

Ordered phases, the state of the work in flight, and the loose ends that
belong to no phase. Start from the first unchecked item of the first
unfinished phase. A phase is finished when its tests pass and CI is green,
and nothing of the next one starts before that.

Keep this file true: tick the boxes in the pull request that earns them, and
add the items a pull request discovers rather than leaving them in a comment.

## Where the work stands

Phases 0 to 5 are on `main`. The single `src/star.rs` became
`src/star/{lexer,mod}.rs` beside `src/text/{parser,builder,mod}.rs`, and with
it came quoted values, comments, a typed `Error` carrying path and line,
multi-block parsing, and the Rust half of CI. Then the schema, the
conventions and the engine, which a read now goes through: `rxm.read(path)`
comes back under canonical names, and `result.raw` is the file under its own.
Then writing, through write conventions, and forwarding: `columns=` narrows
what a read shows, and a write reads the source again and carries every
column of it. Then chunked reading: `result["particles"].chunks(n)` streams
a file in bounded memory. Both suites are green, 68 tests in Rust and 156 in
Python.

What the STAR parser does not do, and that a real file may yet ask for:

- A data row spread over several lines, which the format allows and no
  writer we target produces.
- More than one `loop_` in a data block, which the `Block` model has nowhere
  to put.

Each of the three is an error naming the line, never a silent skip.

Every block of a file is surfaced now, as one `RawTable` each, and a result
of several tables asks which one rather than handing back the last.

## Phase 0 — Skeleton and CI ✅

- [x] `Cargo.toml`: `cdylib`, pyo3, arrow-rs, pyo3-arrow
- [x] `pyproject.toml`: maturin, `python-source`, `module-name`
- [x] `src/lib.rs`: the `_rexlib` module with `version()`
- [x] `python/rexlib_metadata/__init__.py` and `_rexlib.pyi`
- [x] CI across Linux, macOS and Windows

## Phase 1 — STAR reader, no conventions ✅

- [x] `RawSchema` in Python: a table's name and its columns as parsed
- [x] `read_tables()`, every value `Utf8`
- [x] `_rexlib._star_read_tables`
- [x] `Reader` ABC, placeholder `Convention` ABC
- [x] Lazy `ReadResult` with `to_pandas()` and `to_polars()`
- [x] `StarReader` over the Rust entry points
- [x] `MetadataRegistry`, `global_registry`, `.star` pre-registered
- [x] `rxm.read()`
- [x] Fixtures and integration tests
- [x] pytest in CI

## Phase 1b — Parser rewrite ✅

- [x] Split into lexer, parser and builder
- [x] `Error` with path and line, replacing `Result<_, String>`
- [x] `tokenize_line`: quoting, comments, single-token headers
- [x] `parse_blocks`: the state machine over the tokens
- [x] Keep the Python suites green against the rewritten reader
- [x] A fixture of quoted paths and trailing comments, read end to end
- [x] `cargo fmt`, clippy and `cargo test` in CI, on the three platforms

## Phase 2 — Schema, conventions and Relion4

- [x] `ColumnDescriptor`, `SchemaTrait`, `TableSchema`, `Schema` in
      `python/rexlib_metadata/schema.py`, carrying the unit as well as the
      type, against the catalogue in `docs/canonical.md`
- [x] `TableSchema.__init__` flattens traits and deduplicates: an identical
      declaration collapses, a disagreeing one raises
- [x] The catalogue of `docs/canonical.md` as traits and tables, in
      `canonical.py`, for the columns a convention produces today
- [x] `ReadConvention` and `WriteConvention` ABCs in `convention.py`, with
      `RawSchema`, replacing the placeholder `Convention`
- [x] `ConventionBundle`, validating when it is built that no two
      conventions produce the same column and that none produces nothing
- [x] `MetadataRegistry.register_bundle(extensions, bundle, *, prepend=False)`
      and `bundles_for(path)`
- [x] The read engine: bundles in order × raw tables × matching conventions,
      first write per canonical column wins, missing required columns raise,
      and a column of the wrong type or the wrong length raises too
- [x] Relion's conventions, one per column group, matching on column
      presence, in `conventions/relion.py` and tested against real files
- [x] One bundle per format, its conventions grouped by the canonical table
      each fills, registered for `.star` in `global_registry`
- [x] A read comes back canonical: `rxm.read(path)` names the canonical
      tables a file fills and `result[name]` is one of them, with
      `result.raw` the same file under its own names
- [x] Tests: auto-detection, explicit `bundle=`, missing required column,
      overlapping `target_columns` raising when a bundle is built, a file no
      convention understands, and the two views side by side

## Phase 3 — Writing and roundtrip

- [x] `Writer` ABC, `write_tables` and nothing else
- [x] `write_tables` in Rust, `src/star/writer.rs`, a data block per table
- [x] `_rexlib._star_write(path, tables)`
- [x] `StarWriter`, registered for `.star`
- [x] `RawResult.write(path)`, the writer chosen by the destination's
      extension, no forwarding yet
- [x] Tests: read → write → read on five real files, compared as DataFrames
- [x] Relion's `WriteConvention`s, one per column group, the mirror of the
      read conventions in `conventions/relion.py`
- [x] `ReadResult.write(path)`: the canonical columns through the write
      conventions of the destination's extension, or of `bundle=` when given,
      carrying over the columns no convention writes when the destination is
      the format the result was read from

## Phase 4 — Write-forwarding

- [x] `columns=` narrows a result to the canonical columns asked for,
      projected in Python after the reader has parsed every one, and keeps
      none of the rest once the call returns
- [x] `ReadResult.write(path, updates=None)` reads the source again and
      writes every table and every column, the columns of `updates`
      substituted, through a temporary file in the destination directory
- [x] Tests: read 2 of N columns, modify, write, verify all N are intact

## Phase 5 — Chunked reading

- [x] The state machine hands each row to a sink, and the sink appends it
      to the Arrow builders of its block: no `Vec<Vec<String>>`, and a whole
      read is every chunk collected
- [x] The parser it replaces kept as an oracle, the new one agreeing with it
      on every file under `tests/files/star/`, and removed once it does
- [x] The parser steps one line at a time, and the sink cuts a chunk every
      `chunk_size` rows
- [x] `_rexlib._star_read_chunks(path, chunk_size, columns)`, `columns` a
      set of raw names that every block keeps what it holds of, dropping the
      rest as each row is read
- [x] `Reader.read_tables_keeping(path, columns)`, not abstract, falling
      back to `read_tables`; `StarReader` overrides it over the Rust path,
      and `columns=` reaches it as the raw names the engine computes
- [x] `Reader.read_chunks(path, size, columns)`, not abstract, falling back
      to slicing a whole read; `StarReader` overrides it over the Rust
      streaming path. Each chunk carries the ordinal of its block, which is
      what tells two blocks of one name apart
- [x] `ReadResult.chunks(size) -> Iterator[Chunk]`, opening at the start of
      iteration and closing at its end. `Chunk` is rows already read, with
      `name`, `len()`, `to_arrow()`, `to_pandas()` and `to_polars()` and
      nothing a chunk cannot do
- [x] Naming a canonical table reads nothing, so chunking a file reads it
      once and holds no table of it
- [x] Tests: a 100k row file, row count preserved, the chunks reassembling
      into the whole read, and the stream closed when it runs out and when
      it is abandoned

## Phase 6 — Multi-table and CD

- [x] Surface every parsed block instead of the last one
- [x] `ReadResult.names` and `ReadResult.__getitem__`, which took the place
      of the `TableCollection` this once planned
- [x] Tests: a real Relion 3.1 file, its optics in a block of their own
- [x] Continuous deployment: a development release on push to `main`, the
      same pattern as `rexlib-python`, with PyPI waiting on the name (#40)

## Phase 6b — What a second format needs first

Three changes that are cheap now and expensive once a second reader exists,
each argued from a real file in `docs/formats.md`.

- [x] The state machine takes its tokens from any lexer, so that a
      block-shaped delimited file is a lexer rather than a second state
      machine. It moved to `src/text/` with the builder, and the error to
      `src/error.rs`, since neither was ever STAR's, and a line may now declare several columns —
      which only a second lexer could reveal, and did
- [x] `read` grows named arguments for the reader and the bundle, since a
      generic container — `.csv`, `.db`, `.h5` — cannot have its dialect
      guessed from its extension. `write` grew `writer=` with it
- [x] A decision on `RawSchema.table_name` for a format that names no table,
      which `.par` is the first of: `""`, as STAR's bare `data_` already was
- [x] Real STAR files under `tests/files/star/`, with their provenance and
      licence. All eight read: the three that did not were #41, which they
      are what settled
- [x] Real `.cs`, `.par` and block-CSV files, trimmed from the EMPIAR
      depositions `docs/formats.md` names, under `tests/files/`

## Phase 7 — XMD

- [x] Canonical shifts, in Ångström, read and written through Relion's
      `_rlnOrigin{X,Y,Z}Angst`; Relion 3.0's pixels wait on the optics join
- [x] An Xmipp `ConventionBundle`: the image reference and the angles, which
      is what the real files hold
- [x] `.xmd` registered to `StarReader` with that bundle, and to a
      `StarWriter` that writes the `# XMIPP_STAR_1 *` line first
- [x] Tests over real `.xmd` files, from `I2PC/testDataSym`
- [ ] The micrograph, the coordinates, the CTF and the shifts, once a real
      `.xmd` holding them is under `tests/files/xmd/`
- [x] Optics joined per row: a `Relation` on the schema, `result.joined()`,
      and a write to a format with no optics table, as `.xmd`, joining them
      into the particles
- [ ] A read convention that needs a joined column, as Relion 3.0's
      `_rlnOriginX` in pixels needs the optics' pixel size

## Phase 8 — SQLite

- [x] Decide between Rust (`rusqlite`) and Python (`sqlite3`): Python,
      `docs/design.md` says why
- [x] `SqliteReader` and `SqliteWriter`, every table of the file and nothing
      more, typed as the file declares
- [x] Pagination through one cursor per table, `fetchmany`, rather than
      `LIMIT`/`OFFSET`, which rereads every row it skips
- [x] `.db` and `.sqlite` registered
- [x] Tests: read, write, pagination, over databases the tests build
- [ ] Scipion's `.sqlite` — `Objects` with `c01`…, named by `Classes`, and
      `Properties` — over real files, which are on their way

## Phase 9 — HDF5

- [x] `Hdf5Reader` and `Hdf5Writer`, through `h5py` as the `hdf5` extra:
      a compound dataset or a group of column datasets is a table
- [x] Pagination through dataset slicing
- [x] `.h5` and `.hdf5` registered
- [x] Tests: read and write datasets, over files the tests build
- [ ] A real CryoEM HDF5 file under `tests/files/`, when one is offered

## Phase 10 — Performance, measured in CI

"Highly performant" is a requirement with no number behind it. Until a
benchmark gives it one, no optimisation in this repository can be defended,
which is why the release profile is cargo's default.

- [x] A STAR file of about a million rows, generated by the benchmark rather
      than committed: `benchmarks/generate.py`, seeded, Relion-like
- [x] Benchmarks of `read`, `columns=`, `chunks()`, `joined()` and `write`
      over it, in `benchmarks/`, and the same read through `starfile` and
      `starfile-rs` beside ours in `scripts/compare.py`
- [x] Run in CI on a push to `main` and on a pull request that touches `src/`
      or `python/`, through CodSpeed, which counts instructions rather than
      seconds and compares a pull request against `main`
- [ ] CodSpeed's check required by the ruleset, with its regression threshold
      stated in `docs/ci.md`
- [x] The build profile chosen by the numbers, below: cargo's default

A million rows, 243 MiB, read to pandas, best of three, on one Windows
machine with cargo's default release profile (2026-10-31):

| Read | Seconds | Before the plain-line path | Before the tokens borrowed |
|---|---|---|---|
| rexlib-metadata, raw | 1.36 | 1.80 | 3.96 |
| rexlib-metadata, canonical | 2.29 | 2.73 | 4.99 |
| starfile | 6.80 | 6.86 | 6.99 |
| starfile-rs | 2.86 | 2.96 | 2.97 |

Nearly all of a raw read was the Rust parser, at some 60 MB/s: every value
of every row was built a character at a time into a `String`, cloned into a
second one, and copied into Arrow, and every line was a `String` of its own.
Now a token is a slice of the line, the line is one buffer read into again,
and the only copy is the one into Arrow. Pandas and the hop to pyarrow were
never more than a few hundredths of a second.

Then the lexer itself, which still took eight times what splitting the line
on whitespace takes: it decoded and judged every character for a quote. A
line that is ASCII, with no quote and no vertical tab, is now split on
whitespace, which is what the scan would have made of it, and a test holds
the two to the same answer. Every other line is scanned as before.

- [x] The tokens borrow from the line rather than own a copy
- [x] A plain data row is split on whitespace rather than scanned
- [ ] A projected read that skips the columns it drops while tokenising,
      rather than after: two columns of twenty-one still cost 80 % of all
- [ ] The second of a canonical read that the conventions cost, looked at

**The build profile was measured, and stays cargo's default** (2026-10-31).
A million rows, read to pandas, best of five, on one Windows machine; the
build and relink columns are seconds of a whole build and of one after
touching a line:

| Profile | Build | Relink | Wheel | Raw | Canonical | Two columns | Chunks |
|---|---|---|---|---|---|---|---|
| cargo's default, which we ship | 76 | 3 | 3.08 MB | 4.02 | 4.97 | 4.64 | 5.06 |
| `lto = "thin"` | 66 | 24 | 3.22 MB | 3.83 | 4.75 | 4.21 | 4.81 |
| `lto = "thin"`, `codegen-units = 1` | 132 | 51 | 3.10 MB | 3.87 | 4.73 | 4.26 | 4.74 |
| `lto = true`, `codegen-units = 1` | 155 | 78 | 3.09 MB | 3.86 | 4.75 | 4.25 | 4.76 |

The best gains 4 to 9 %, below the 10 % this was to clear, and thin LTO
alone already has all of it. Measured again once the reads themselves are
faster, since the same seconds are then a larger share; when it comes, it
comes as a `dist` profile for the published wheels and the benchmarks, not
for the test cells.

## Phase 11 — Review and clean-up

Once every phase above is done, one deliberate pass over the whole
repository, rather than piecemeal clean-ups along the way.

- [ ] An exhaustive review: code quality, architecture, patterns and
      antipatterns, and the gaps in the tests
- [ ] Every suppression that ties the code to a tool's configuration —
      `# type: ignore[...]`, `# noqa: ...` — replaced by code that needs none
- [ ] The clean-up the review asks for, as code, in pull requests of their own

## What is not here

Loose ends are issues, not a list in this file: an item nobody is assigned to
and no pull request closes is a way of forgetting something in writing. The
tracker holds the licensing scheme and the SPDX headers that follow it (#35),
the arrow cap and what lifts it (#36), the stub that types Arrow as `Any`
(#37), SonarQube and CodeQL (#39), publishing (#40), and a read that matched
nothing coming back empty rather than saying so (#53).

This file keeps the plan: the phases, in the order they are meant to happen.

## Deferred

- `Relion3Bundle`, for legacy files. Low priority, and the bundle mechanism
  is what makes it cheap once wanted.
- A `RexConvention` naming the suite's own canonical spelling, first in
  detection order. Waiting on the team agreeing what that spelling is.
