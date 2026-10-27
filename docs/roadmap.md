# Roadmap and backlog

Ordered phases, the state of the work in flight, and the loose ends that
belong to no phase. Start from the first unchecked item of the first
unfinished phase. A phase is finished when its tests pass and CI is green,
and nothing of the next one starts before that.

Keep this file true: tick the boxes in the pull request that earns them, and
add the items a pull request discovers rather than leaving them in a comment.

## Where the work stands

Phases 0, 1 and 1b are on `main`. The single `src/star.rs` became
`src/star/{lexer,mod}.rs` beside `src/text/{parser,builder,mod}.rs`, and with
it came quoted values, comments, a typed `Error` carrying path and line,
multi-block parsing, and the Rust half of CI. Both suites are green, 36 tests
in Rust and 75 in Python.

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
- [ ] Register them for `.star` and have a read apply them, which is the
      decision of what `to_pandas()` means on a file that has conventions
- [ ] Register it for `.star` in `global_registry`
- [ ] Tests: auto-detection, explicit `bundle=`, missing required column,
      overlapping `target_columns` raising when a bundle is built

## Phase 3 — Writing and roundtrip

- [ ] `Writer` ABC
- [ ] `StarSerializer` in Rust: `write(path, record_batch)`
- [ ] `_rexlib._star_write(path, batch)`
- [ ] `StarWriter`, registered for `.star`
- [ ] `ReadResult.write(path)`, no forwarding yet
- [ ] Tests: read → write → read, compared as DataFrames

## Phase 4 — Write-forwarding

- [ ] `ReadResult` always holds the full batch; `columns=` becomes a view
- [ ] `ReadResult.write(path, updates=None)` merges and writes every column
- [ ] Tests: read 2 of N columns, modify, write, verify all N are intact

## Phase 5 — Chunked reading

- [ ] Progressive chunk index in the STAR parser, offsets recorded as chunks
      are read
- [ ] Memory-mapped file access
- [ ] `_rexlib._star_read_chunks(path, chunk_size, columns)`
- [ ] `StarReader.read_chunks()` over the Rust streaming path
- [ ] `ReadResult.chunks(size) -> Iterator[ReadResult]`, opening at the start
      of iteration and closing at its end
- [ ] Tests: a ≥100k row file, row count preserved, handle closed afterwards

## Phase 6 — Multi-table and CD

- [x] Surface every parsed block instead of the last one
- [x] `ReadResult.names` and `ReadResult.__getitem__`, which took the place
      of the `TableCollection` this once planned
- [x] Tests: a real Relion 3.1 file, its optics in a block of their own
- [ ] Continuous deployment: a development release on push to `main`, the
      same pattern as `rexlib-python`

## Phase 6b — What a second format needs first

Three changes that are cheap now and expensive once a second reader exists,
each argued from a real file in `docs/formats.md`.

- [x] The state machine takes its tokens from any lexer, so that a
      block-shaped delimited file is a lexer rather than a second state
      machine. It moved to `src/text/` with the builder, and the error to
      `src/error.rs`, since neither was ever STAR's, and a line may now declare several columns —
      which only a second lexer could reveal, and did
- [ ] `read` grows named arguments for the reader and the bundle, since a
      generic container — `.csv`, `.db`, `.h5` — cannot have its dialect
      guessed from its extension
- [ ] A decision on `RawSchema.table_name` for a format that names no table,
      which `.par` is the first of
- [x] Real STAR files under `tests/files/star/`, with their provenance and
      licence. All eight read: the three that did not were #41, which they
      are what settled
- [ ] Real `.cs`, `.par` and block-CSV files, trimmed from the EMPIAR
      depositions `docs/formats.md` names

## Phase 7 — XMD

- [ ] An Xmipp `ConventionBundle`
- [ ] `.xmd` registered to `StarReader` with that bundle
- [ ] Tests over real `.xmd` files

## Phase 8 — SQLite

- [ ] Decide between Rust (`rusqlite`) and Python (`sqlite3`)
- [ ] `SqliteReader` and `SqliteWriter`
- [ ] Pagination through `LIMIT`/`OFFSET`
- [ ] `.db` and `.sqlite` registered
- [ ] Tests: read, write, pagination

## Phase 9 — HDF5

- [ ] `Hdf5Reader` and `Hdf5Writer`, crate `hdf5` or `h5py`
- [ ] Pagination through dataset slicing
- [ ] `.h5` and `.hdf5` registered
- [ ] Tests: read and write datasets

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
