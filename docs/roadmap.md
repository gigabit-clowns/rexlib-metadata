# Roadmap and backlog

Ordered phases, the state of the work in flight, and the loose ends that
belong to no phase. Start from the first unchecked item of the first
unfinished phase. A phase is finished when its tests pass and CI is green,
and nothing of the next one starts before that.

Keep this file true: tick the boxes in the pull request that earns them, and
add the items a pull request discovers rather than leaving them in a comment.

## Where the work stands

Phases 0 and 1 are done and on `main`. The STAR reader reads one block of one
file into an Arrow `RecordBatch` of `Utf8` columns, and `rm.read(...)`
returns a lazy `ReadResult` that materialises into pandas or polars.

The `parser` branch is a rewrite of that reader, not new surface. It replaces
the single `src/star.rs` with `src/star/{lexer,parser,builder,mod}.rs`, adds
quoted values, comments, typed `StarError`s carrying path and line, and
multi-block parsing. `tokenize_line` and `build_record_batch` are finished
and tested; `parse_blocks` in `src/star/parser.rs` is a `todo!()` with its
six tests already written and failing, which is the next thing to write. Its
contract is spelled out in the comment above it: use the lexer, zero blocks
is not an error at that level, a block with columns and no rows is valid, a
`data_` token in `ReadingData` closes the block and opens the next, and a row
whose value count disagrees with the column count is a `StarError::Parse`
naming the line.

`read_schema` and `read_all` in `src/star/mod.rs` still take the last block
of the file and drop the rest. That stays until Phase 6 gives the Python side
somewhere to put the others.

CI is red on this branch on purpose, and knowing why saves reading the log:
clippy runs at `-D warnings`, and with `parse_blocks` unwritten nothing calls
the lexer, so every one of its functions is reported as dead code. The ten
warnings are all that shape and all of them go away with the function. The
`build_with_pip` job is unaffected, since `todo!()` compiles.

## Phase 0 — Skeleton and CI ✅

- [x] `Cargo.toml`: `cdylib`, pyo3, arrow-rs, pyo3-arrow
- [x] `pyproject.toml`: maturin, `python-source`, `module-name`
- [x] `src/lib.rs`: the `_rexlib` module with `version()`
- [x] `python/rexlib_metadata/__init__.py` and `_rexlib.pyi`
- [x] CI across Linux, macOS and Windows

## Phase 1 — STAR reader, no conventions ✅

- [x] `RawSchema` in Rust
- [x] `read_schema()` and `read_all()`, every value `Utf8`
- [x] `_rexlib._star_read_schema` and `_rexlib._star_read`
- [x] `Reader` ABC, placeholder `Convention` ABC
- [x] Lazy `ReadResult` with `to_pandas()` and `to_polars()`
- [x] `GenericStarConvention` passthrough
- [x] `StarReader` over the Rust entry points
- [x] `MetadataRegistry`, `global_registry`, `.star` pre-registered
- [x] `rm.read()`
- [x] Fixtures and integration tests
- [x] pytest in CI

## Phase 1b — Parser rewrite (in progress, branch `parser`)

- [x] Split into lexer, parser and builder
- [x] `StarError` with path and line, replacing `Result<_, String>`
- [x] `tokenize_line`: quoting, comments, single-token headers
- [ ] `parse_blocks`: the state machine over the tokens
- [ ] Keep the Python suites green against the rewritten reader
- [ ] Fixtures for quoted values and for a multi-block file

## Phase 2 — Schema, conventions and Relion4

- [ ] `ColumnDescriptor`, `SchemaTrait`, `TableSchema`, `Schema` in
      `python/rexlib_metadata/schema.py`
- [ ] `TableSchema.__init__` flattens traits and deduplicates: same type
      keeps the first, different type raises
- [ ] `ReadConvention` and `WriteConvention` ABCs in `abc.py`, replacing the
      placeholder `Convention`
- [ ] `ConventionBundle`, validating `target_columns` do not overlap within
      the bundle at `register()`
- [ ] `MetadataRegistry.register_bundle(extension, bundle, *, prepend=False)`
- [ ] The read engine: bundles in order × raw tables × matching conventions,
      first write per canonical column wins, missing required columns raise
- [ ] `Relion4Bundle`, one `ReadConvention` per column group, matching on
      column presence
- [ ] Register it for `.star` in `global_registry`
- [ ] Tests: auto-detection, explicit `bundle=`, missing required column,
      overlapping `target_columns` raising at registration

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

- [ ] Surface every parsed block instead of the last one
- [ ] `TableCollection` in `result.py`, dict-like, `__getitem__` gives a
      `ReadResult`
- [ ] Wire it into `ReadResult` for multi-block files
- [ ] Tests: a Relion4 file with `data_optics` and `data_particles`
- [ ] Continuous deployment: a development release on push to `main`, the
      same pattern as `rexlib-python`

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

## Backlog

Not attached to a phase. Roughly in the order they hurt.

- **No linter on the Python side.** `rexlib-python` lints with ruff in CI and
  this repository lints only its Rust. Its `ruff.toml` is the one to copy
  from, minus the tab-indentation ignore.
- **`_rexlib.pyi` references `arro3.core`**, which is not a dependency and
  cannot be imported by a type checker here. The stub should describe what
  the caller is allowed to assume — an object exposing the Arrow protocol —
  rather than name a package that is not installed.
- **No SonarQube scan and no coverage**, unlike the sibling repositories.
- **No CD.** Nothing is published, not even a development pre-release.
  Phase 6 carries it, and it does not have to wait for Phase 6.
- **The `Convention` ABC in `abc.py` is dead weight**, with its
  `matches`/`apply`/`to_file_name`/`to_canonical_name` shape that Phase 2
  discards. So is `GenericStarConvention`. Neither is referenced by anything
  that runs; both go when Phase 2 lands.
- **`registry.py` imports `StarReader` at the bottom of the module** to break
  a cycle. It works, but the cycle is the thing to remove — registration
  belongs somewhere that does not force an import order.
- **Teaching comments in `src/star/`.** The comment block in `mod.rs`
  explaining what `thiserror` generates, and the exercise brief above
  `parse_blocks`, are notes to the author rather than documentation of the
  code. Decide whether they stay before the branch merges.
- **No `CHANGELOG.md`**, which every other repository of the suite keeps.

## Deferred

- `Relion3Bundle`, for legacy files. Low priority, and the bundle mechanism
  is what makes it cheap once wanted.
- A `RexConvention` naming the suite's own canonical spelling, first in
  detection order. Waiting on the team agreeing what that spelling is.
