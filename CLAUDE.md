# rexlib-metadata

CryoEM metadata I/O library. Reads and writes industry-standard formats (Relion STAR, Xmipp XMD, SQLite, HDF5) to a canonical in-memory representation, exposed to Python as Pandas or Polars DataFrames. Part of the REX suite (gigabit-clowns org).

## Architecture

Rust core (via PyO3 + Maturin) with a Python API. The boundary is intentional:

- **Rust**: performance-critical I/O and parsing. Internal traits (`Parse`, `Serialize`, `ApplyConvention`) are implementation details — not part of the public API.
- **Python ABCs** (`Reader`, `Writer`, `Convention`): the public extension surface. Users inject custom readers/conventions by subclassing these.
- **Apache Arrow** (`arrow-rs` + `pyo3-arrow`): the canonical in-memory format at the Rust level. Python receives Arrow data and converts to Pandas or Polars without duplication.

Rust-backed readers (e.g., `StarReader`) are Python classes that satisfy the `Reader` ABC and call into Rust via PyO3. A user implementing a custom reader in pure Python follows the same ABC — no Rust required.

## Public Python API

```python
import rexlib_metadata as rm

# read() is lazy: opens file, reads header/schema, closes file. No row I/O yet.
result = rm.read("particles.star")
result = rm.read("particles.star", columns=["angle_rot"], convention=Relion4(), backend="polars")

# Materialize — I/O happens here
df = result.to_pandas()
df = result.to_polars()

# Multi-table files (e.g., multi-block STAR)
df_particles = result["particles"].to_pandas()

# Streaming — file opened at iteration start, closed when iterator exhausted
for chunk in result.chunks(size=10_000):
    chunk.to_pandas()

# Write
result.write("output.star")

# Write-forwarding: read some columns, modify, write back all columns intact
result = rm.read("particles.star", columns=["angle_rot"])
df = result.to_pandas()
df["angle_rot"] += 10
result.write("output.star", updates=df)
```

`ReadResult` never holds a file handle. File handles are only open during active I/O.

`ReadResult` internally holds a full Arrow `RecordBatch` (all columns). `columns=` is a view/projection, not a memory optimization — all columns are always loaded to support write-forwarding. Selected columns are exposed; the rest are carried silently for pass-through on write.

## Convention system

Conventions map file-specific column names to canonical names and enforce types. Schema validation is strict: unknown columns raise an error.

**Detection order (short-circuit, first match wins):**
1. Explicit `convention=` argument — applied directly, error if schema doesn't match
2. Built-in conventions checked in priority order (most common first):
   - `RexConvention` (once defined — users of this software use it most)
   - `Relion4Convention`
   - `XmdConvention`
   - `Relion3Convention` (future)
3. No match → `GenericStarConvention` (passthrough, no renaming)

Each convention implements `matches(raw: RawSchema) -> bool`. The registry checks them in registration order; the first `True` wins. Registration order = priority.

**Defining a custom convention:**
```python
class MyConvention(Convention):
    def matches(self, raw: RawSchema) -> bool:
        return "myLabParticleId" in raw.column_names

    def apply(self, raw: RawSchema) -> Schema: ...
    def to_file_name(self, canonical: str) -> str: ...
    def to_canonical_name(self, file_col: str) -> str: ...

global_registry.register_convention(MyConvention(), extensions=[".star"])
```

## Registry

Global registry (`global_registry`) is the default. A local `MetadataRegistry` instance is available for test isolation. In tests, patch `global_registry` via `unittest.mock.patch` or pass an explicit registry instance.

## Pagination

- **Text formats (STAR, XMD)**: progressive lazy index of chunk-level byte offsets + memory-mapped file. Index built as chunks are read; enables efficient sequential and random access without a mandatory first scan.
- **SQLite / HDF5**: native `LIMIT`/`OFFSET` and dataset slicing.
- The pagination API is uniform for users; format-specific under the hood.

## Format priority

Implementation order: Relion4/5 STAR → XMD → SQLite → HDF5.

Supported extensions and their default readers:
- `.star` → `StarReader` (also used for `.xmd` with `XmdConvention`)
- `.db` / `.sqlite` → `SqliteReader`
- `.h5` / `.hdf5` → `Hdf5Reader`

## Project structure

```
rexlib-metadata/
├── Cargo.toml                        # cdylib crate for PyO3
├── pyproject.toml                    # Maturin build backend
├── src/                              # Rust source
│   ├── lib.rs                        # PyO3 module entry point (_rexlib)
│   ├── parser/
│   │   ├── star.rs                   # StarParser: implements Parse
│   │   └── xmd.rs
│   ├── serializer/
│   │   └── star.rs
│   ├── convention/
│   │   └── relion4.rs
│   └── arrow_bridge.rs               # RecordBatch <-> pyo3-arrow
├── python/
│   └── rexlib_metadata/              # public Python package
│       ├── __init__.py               # exposes read(), write()
│       ├── _rexlib.pyi               # type stubs for compiled Rust module
│       ├── abc.py                    # Reader, Writer, Convention ABCs
│       ├── registry.py               # MetadataRegistry, global_registry
│       ├── result.py                 # ReadResult, TableCollection
│       └── conventions/
│           └── relion4.py            # StarReader, Relion4Convention
└── tests/
    ├── rust/                         # unit tests (cargo test)
    └── python/                       # integration + e2e tests (pytest)
```

## Build and test

```bash
# Development install
pip install maturin
maturin develop

# Run Rust unit tests
cargo test

# Run Python tests
pytest tests/python/
```

## Key dependencies

- `pyo3` — Rust/Python bindings
- `arrow-rs` — Apache Arrow implementation in Rust
- `pyo3-arrow` — Arrow C Data Interface bridge (RecordBatch → Python)
- `pyarrow` (Python, transitive) — required by pyo3-arrow for the Python side

## Implementation roadmap

Ordered checklist. Start from the first unchecked item. Each phase must be complete (tests passing, CI green) before starting the next.

### Phase 0 — Project skeleton + CI build
- [ ] `Cargo.toml`: `[lib] crate-type = ["cdylib"]`, deps `pyo3` + `arrow-rs` + `pyo3-arrow`
- [ ] `pyproject.toml`: Maturin build backend, `python-source = "python"`, `module-name = "rexlib_metadata._rexlib"`
- [ ] `src/lib.rs`: minimal PyO3 module `_rexlib` with one smoke-test function (e.g. `version() -> &str`)
- [ ] `python/rexlib_metadata/__init__.py`: imports `_rexlib`, re-exports smoke function
- [ ] `python/rexlib_metadata/_rexlib.pyi`: stub for the smoke function
- [ ] CI workflow: build matrix Linux/Mac/Windows, `python -c "import rexlib_metadata"` as smoke test
- [ ] Verify locally: `maturin develop && python -c "import rexlib_metadata"`

### Phase 1 — STAR reader (no convention) + CI tests
- [ ] Define `RawSchema` in Rust: column names + Arrow `DataType`s as parsed from file
- [ ] Implement `StarParser` in Rust: `read_schema() -> RawSchema`, `read_all() -> RecordBatch`
- [ ] Expose to Python via PyO3: `_rexlib._star_read_schema(path)`, `_rexlib._star_read(path, columns)`
- [ ] Create `Reader` ABC in `python/rexlib_metadata/abc.py`
- [ ] Create `Convention` ABC in `abc.py` (stubs for `matches`, `apply`, `to_file_name`, `to_canonical_name`)
- [ ] Create `ReadResult` in `result.py`: lazy (stores path + config, no file handle), `to_pandas()`, `to_polars()`
- [ ] Create `GenericStarConvention` (passthrough, `matches()` always False, `apply()` identity)
- [ ] Create `StarReader` Python class satisfying `Reader` ABC, calling Rust under the hood
- [ ] Create `MetadataRegistry` in `registry.py`: `register_reader(extensions, cls)`, detection by extension
- [ ] Create `global_registry`, pre-register `StarReader` for `.star`
- [ ] Implement `rm.read()` in `__init__.py`
- [ ] Add test fixtures (small real `.star` files) under `tests/python/fixtures/`
- [ ] Write integration tests: `rm.read("test.star").to_pandas()` — check shape, column names, values
- [ ] Add `pytest` to CI (runs on every PR)

### Phase 2 — Convention system + Relion4
- [ ] Implement `Convention.matches(raw: RawSchema) -> bool` and `Convention.apply(raw) -> Schema`
- [ ] Add `Schema` type (canonical column names + validated Arrow `DataType`s)
- [ ] Implement `Relion4Convention`: define required columns, `matches()`, `apply()` with type validation
- [ ] `apply()` raises on unknown columns; raises on type mismatch
- [ ] Add `register_convention(convention, extensions)` to `MetadataRegistry`; registration order = detection priority
- [ ] Wire short-circuit detection into `rm.read()`: iterate registered conventions in order, first `True` wins, fallback to `GenericStarConvention`
- [ ] Register `Relion4Convention` in `global_registry` for `.star`
- [ ] Tests: auto-detect Relion4, check canonical column names; explicit `convention=`; unknown column raises; type mismatch raises

### Phase 3 — Write + roundtrip
- [ ] Create `Writer` ABC in `abc.py`
- [ ] Implement `StarSerializer` in Rust: `write(path, record_batch)`
- [ ] Expose to Python: `_rexlib._star_write(path, batch)`
- [ ] Create `StarWriter` Python class satisfying `Writer` ABC
- [ ] Register `StarWriter` in `global_registry` for `.star`
- [ ] Implement `ReadResult.write(path)` (no forwarding yet)
- [ ] Tests: roundtrip read → write → read, compare DataFrames

### Phase 4 — Write-forwarding
- [ ] Modify `ReadResult`: always load full `RecordBatch` internally; `columns=` is a projection (view only)
- [ ] Implement `ReadResult.write(path, updates=None)`: merge `updates` DataFrame into full batch, write all columns
- [ ] Tests: read 2 of N columns, modify, write, verify all N columns present and correct in output

### Phase 5 — Chunked reading
- [ ] Implement progressive chunk index in `StarParser`: record byte offset at each chunk boundary while reading
- [ ] Implement mmap-based file access in `StarParser`
- [ ] Expose to Python: `_rexlib._star_read_chunks(path, chunk_size, columns)` → yields `RecordBatch`
- [ ] Override `read_chunks()` in `StarReader` to use Rust streaming (not the default in-memory split)
- [ ] Implement `ReadResult.chunks(size) -> Iterator[ReadResult]`: opens file at iteration start, closes on exhaustion or GC
- [ ] Tests: chunk a ≥100k row `.star` file; verify row count matches; verify file handle closed after iteration

### Phase 6 — Multi-table + TableCollection + CD
- [ ] Extend `StarParser` to detect and parse multiple data blocks in one `.star` file
- [ ] Create `TableCollection` in `result.py`: dict-like, `__getitem__` returns `ReadResult`
- [ ] Wire `TableCollection` into `ReadResult` for multi-block files
- [ ] Tests: multi-block `.star` (e.g. Relion4 with `data_particles` + `data_optics`)
- [ ] Set up CD: development release on push to `main` (same pattern as `xmipp4-binding-python`)

### Phase 7 — XMD support
- [ ] Implement `XmdConvention` (Convention ABC, Xmipp column name mapping)
- [ ] Register `.xmd` → `StarReader` + `XmdConvention` in `global_registry`
- [ ] Tests: read `.xmd` files, check canonical column names

### Phase 8 — SQLite
- [ ] Decide: Rust (`rusqlite`) or Python (`sqlite3`) for the parser
- [ ] Implement `SqliteParser` / `SqliteReader`, `SqliteWriter`
- [ ] Native pagination via `LIMIT`/`OFFSET`
- [ ] Register `.db` / `.sqlite` extensions in `global_registry`
- [ ] Tests: read/write SQLite, pagination correctness

### Phase 9 — HDF5
- [ ] Implement `Hdf5Reader`, `Hdf5Writer` (crate `hdf5` or Python `h5py`)
- [ ] Dataset slicing for pagination
- [ ] Register `.h5` / `.hdf5` extensions in `global_registry`
- [ ] Tests: read/write HDF5 datasets

### Deferred (no phase assigned yet)
- `Relion3Convention` (legacy support, low priority)
- `RexConvention` (define once the team agrees on the internal standard; goes first in detection order)

---

## Design invariants — do not violate

- `ReadResult` must never hold an open file handle after `rm.read()` returns.
- Column selection (`columns=`) is always a view, never a load optimization. All columns are loaded internally to support write-forwarding.
- Schema validation is always strict: unknown columns raise, never silently pass through.
- Convention detection is always short-circuit: first `matches()` True wins, no scoring or ranking.
- The public extension surface is Python ABCs only. Rust traits are internal implementation details.
- The `_rexlib` module (compiled Rust artifact) is private. Users import only `rexlib_metadata`.
