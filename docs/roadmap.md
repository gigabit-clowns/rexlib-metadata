# Roadmap and backlog

Ordered phases, the state of the work in flight, and the loose ends that
belong to no phase. Start from the first unchecked item of the first
unfinished phase. A phase is finished when its tests pass and CI is green,
and nothing of the next one starts before that.

Keep this file true: tick the boxes in the pull request that earns them, and
add the items a pull request discovers rather than leaving them in a comment.

## Where the work stands

Phases 0 and 1 are on `main`. Phase 1b, the rewrite of the STAR reader, is
finished on the `parser` branch and is what main is waiting for: the single
`src/star.rs` became `src/star/{lexer,parser,builder,mod}.rs`, and with it
came quoted values, comments, typed `StarError`s carrying path and line,
multi-block parsing, and the Rust half of CI. Both suites are green, 31 tests
in Rust and 15 in Python.

What the STAR parser does not do, and that a real file may yet ask for:

- A data row spread over several lines, which the format allows and no
  writer we target produces.
- More than one `loop_` in a data block, which the `StarBlock` model has
  nowhere to put.
- Blocks of `_name value` pairs with no `loop_`, which Relion writes in its
  optimiser files. The lexer rejects the line, so this is a lexer change
  before it is a parser one.

Each of the three is an error naming the line, never a silent skip.

`read_schema` and `read_all` in `src/star/mod.rs` still take the last block
of the file and drop the rest. Multi-table is the next slice, and it is what
removes that.

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

## Phase 1b — Parser rewrite ✅

- [x] Split into lexer, parser and builder
- [x] `StarError` with path and line, replacing `Result<_, String>`
- [x] `tokenize_line`: quoting, comments, single-token headers
- [x] `parse_blocks`: the state machine over the tokens
- [x] Keep the Python suites green against the rewritten reader
- [x] A fixture of quoted paths and trailing comments, read end to end
- [x] `cargo fmt`, clippy and `cargo test` in CI, on the three platforms

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

- **arrow is capped below 60 until pyo3-arrow can hold it.** `renovate.json`
  caps it and says why; the paragraph on the two of them in `AGENTS.md` says
  what breaks without the cap. The cap is not a thing to delete when this
  clears, it is a bound to move: arrow may never pass the major pyo3-arrow
  pins, so the rule outlives any particular number. When a pyo3-arrow built
  against a newer arrow appears, its own Renovate pull request is the signal,
  and one pull request does all of it — raise pyo3-arrow, raise arrow, move
  the bound, and rewrite the two versions the rule's description names.

  The trail upstream, so that nobody has to find it twice. arrow-rs
  [#10431](https://github.com/apache/arrow-rs/pull/10431) made the FFI struct
  fields private and shipped in arrow 60, which is what broke pyo3-arrow;
  its author answered with
  [#11125](https://github.com/apache/arrow-rs/pull/11125), merged three days
  after 60 went out and therefore still unreleased, due in the minor tracked
  by [#10525](https://github.com/apache/arrow-rs/issues/10525). arro3
  [#513](https://github.com/kylebarron/arro3/pull/513) is the pyo3-arrow side,
  a draft waiting on that release.
  [#11161](https://github.com/apache/arrow-rs/pull/11161) is the other road,
  an `ArrayReader` concept upstream, which would fix the underlying problem
  ([#6586](https://github.com/apache/arrow-rs/issues/6586)) and take longer.
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
