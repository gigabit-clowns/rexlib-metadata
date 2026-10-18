# Working on rexlib-metadata

rexlib-metadata reads and writes CryoEM metadata formats (Relion STAR, Xmipp
XMD, SQLite, HDF5) into a canonical in-memory representation, exposed to
Python as Pandas or Polars DataFrames. Its core is Rust, through PyO3 and
Maturin, behind a Python API. It is part of the REX suite.

Keep this file true. When a change makes something here wrong or missing —
a moved directory, a new convention, a dependency, a workflow — update it in
the same pull request that causes it.

## What exists today

Phase 1 of the roadmap below is done: a STAR reader with no convention.

| Path | Holds |
|---|---|
| `src/lib.rs` | The PyO3 module `_rexlib`: `version`, `_star_read_schema`, `_star_read` |
| `src/star.rs` | The STAR parser: `read_schema` and `read_all`, every value as `Utf8` |
| `python/rexlib_metadata/__init__.py` | `read()`, `ReadResult`, `__version__` |
| `python/rexlib_metadata/abc.py` | The `Reader` and `Convention` ABCs |
| `python/rexlib_metadata/registry.py` | `MetadataRegistry` and `global_registry`, which registers `StarReader` for `.star` |
| `python/rexlib_metadata/result.py` | `ReadResult`: lazy, `to_pandas()` and `to_polars()` |
| `python/rexlib_metadata/conventions/star.py` | `StarReader` and `GenericStarConvention`, a passthrough |
| `python/rexlib_metadata/_rexlib.pyi` | The stubs of the compiled module, written by hand |
| `tests/python/` | The pytest suite and its fixtures |

The parser reads the last `data_` block that holds a `loop_`; multi-block
files are Phase 6. The `Convention` ABC still has the Phase 1 shape
(`matches`, `apply`, `to_file_name`, `to_canonical_name`); Phase 2 replaces it
with the `ReadConvention` and `WriteConvention` described below.

## Building and testing

```
pip install maturin
maturin develop          # builds _rexlib into python/rexlib_metadata
pip install .[test]
pytest                   # tests/python, per pyproject.toml
cargo test               # the Rust unit tests in src/star.rs
```

`[tool.maturin]` builds `rexlib_metadata._rexlib` from the crate and takes the
Python sources from `python/`. The compiled module is private: users import
`rexlib_metadata` only.

## Architecture

Rust core with a Python API. The boundary is intentional:

- **Rust**: performance-critical I/O and parsing. Internal traits (`Parse`,
  `Serialize`, `ApplyConvention`) are implementation details, not part of the
  public API.
- **Python ABCs** (`Reader`, `Writer`, `Convention`): the public extension
  surface. Users plug in custom readers and conventions by subclassing them.
- **Apache Arrow** (`arrow` + `pyo3-arrow`): the canonical in-memory format at
  the Rust level. Python receives Arrow data and converts to Pandas or Polars
  without duplication.

Rust-backed readers such as `StarReader` are Python classes that satisfy the
`Reader` ABC and call into Rust. A custom reader in pure Python follows the
same ABC, with no Rust.

## The design being built towards

Everything in this section is the target of the phases still open. What is
already built is described above.

### Public Python API

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

`ReadResult` never holds a file handle. File handles are only open during
active I/O.

`ReadResult` internally holds a full Arrow `RecordBatch`, all columns.
`columns=` is a view, not a memory optimisation: all columns are always loaded,
to support write-forwarding. Selected columns are exposed; the rest are
carried silently for pass-through on write.

### Schema

The schema is the WHAT layer: the canonical column structure, independent of
any file format.

**`ColumnDescriptor`** — one canonical column: name, Arrow type and an
optional default.

```python
@dataclass
class ColumnDescriptor:
    name: str
    dtype: pa.DataType
    default: Any | None = None  # None = column is required; any value = optional with that default
```

**`SchemaTrait`** — a named, reusable group of related columns (e.g.
`EulerAngles`, `CartesianPosition`). Traits are a composition tool only; they
flatten into `TableSchema`.

**`TableSchema`** — a table's full column set, built by composing traits:

- Same name and same type across traits: keep the first, discard the duplicate
  silently.
- Same name and a different type: error at construction time.

**`Schema`** — one or more `TableSchema`. Multi-table formats (e.g. Relion4
STAR with `data_particles` and `data_optics`) produce a `Schema` with several
tables.

### Conventions

Conventions are the HOW layer: they map file columns to canonical columns,
entirely apart from the schema.

```python
class ReadConvention(ABC):
    source_columns: list[str]   # file columns consumed
    target_columns: list[str]   # canonical columns produced

    def matches(self, raw: RawSchema) -> bool: ...
    def load(self, raw: RecordBatch) -> dict[str, Array]: ...

class WriteConvention(ABC):
    source_columns: list[str]   # canonical columns consumed
    target_columns: list[str]   # file columns produced

    def store(self, canonical: dict[str, Array]) -> dict[str, Array]: ...
```

A `ConventionBundle` groups all the conventions of one file format, e.g.
Relion4. No two `ReadConvention`s in a bundle may declare the same element in
`target_columns`; `register()` enforces it and raises on violation.

```python
class ConventionBundle:
    name: str                               # e.g. "relion4"
    read_conventions: list[ReadConvention]
    write_conventions: list[WriteConvention]
```

Raw tables are matched to canonical tables by column presence through
`matches()`, never by the raw table's name: `data_particles` becomes the
canonical `particles` table because the Relion4 euler convention's `matches()`
accepts its `RawSchema`.

The read engine, simplified:

```python
covered = {}  # canonical_col → Array

for bundle in registry.bundles_for(extension):   # ordered: higher-priority first
    for raw_table in file.tables:
        for conv in bundle.read_conventions:
            if conv.matches(raw_table.schema):
                if any(t not in covered for t in conv.target_columns):
                    result = conv.load(raw_table.batch)
                    for col, array in result.items():
                        covered.setdefault(col, array)  # first write wins

for col in table_schema.required_columns:
    if col.name not in covered and col.default is None:
        raise ValueError(f"Required column '{col.name}' not produced by any convention")
```

Bundles are registered in priority order, highest first. The first bundle
whose convention produces a canonical column owns it, and later bundles cannot
overwrite it. Within a bundle, every non-overlapping matching convention
applies.

```python
registry.register_bundle(".star", Relion4Bundle())  # tried first
registry.register_bundle(".star", Relion3Bundle())  # fallback
```

A custom bundle:

```python
class MyEulerConvention(ReadConvention):
    source_columns = ["myAngle1", "myAngle2", "myAngle3"]
    target_columns = ["euler_rot", "euler_tilt", "euler_psi"]

    def matches(self, raw: RawSchema) -> bool:
        return all(c in raw.column_names for c in self.source_columns)

    def load(self, raw: RecordBatch) -> dict[str, Array]:
        return {
            "euler_rot":  raw.column("myAngle1"),
            "euler_tilt": raw.column("myAngle2"),
            "euler_psi":  raw.column("myAngle3"),
        }

bundle = ConventionBundle("mylab", read_conventions=[MyEulerConvention()])
global_registry.register_bundle(".star", bundle, prepend=True)
```

### Registry

`global_registry` is the default. A local `MetadataRegistry` is available for
test isolation: patch `global_registry` with `unittest.mock.patch`, or pass an
explicit registry.

### Pagination

- **Text formats (STAR, XMD)**: a progressive lazy index of chunk-level byte
  offsets over a memory-mapped file, built as chunks are read, so that both
  sequential and random access need no first scan.
- **SQLite and HDF5**: native `LIMIT`/`OFFSET` and dataset slicing.

The pagination API is the same for every format; what is under it is not.

### Formats

In order of implementation: Relion4/5 STAR, XMD, SQLite, HDF5.

| Extension | Reader |
|---|---|
| `.star` | `StarReader` |
| `.xmd` | `StarReader` with `XmdConvention` |
| `.db`, `.sqlite` | `SqliteReader` |
| `.h5`, `.hdf5` | `Hdf5Reader` |

## Design invariants — do not violate

- `ReadResult` never holds an open file handle after `rm.read()` returns.
- Column selection (`columns=`) is always a view, never a load optimisation.
  All columns are loaded internally to support write-forwarding.
- Schema validation is always strict: unknown columns raise, never silently
  pass through.
- Raw tables are matched to canonical tables by column presence through
  `matches()`, never by the raw table's name, which is format-specific and not
  under our control.
- Within a `ConventionBundle`, no two `ReadConvention`s declare the same
  element in `target_columns`. Validated at registration, which raises.
- Convention priority is per bundle, not per column. The first bundle whose
  convention produces a canonical column owns it.
- The public extension surface is Python ABCs only. Rust traits are internal.
- `_rexlib` is private. Users import only `rexlib_metadata`.

## Roadmap

Start from the first unchecked item. Each phase is complete — tests passing,
CI green — before the next starts.

### Phase 0 — Project skeleton and CI build ✅

- [x] `Cargo.toml`: `[lib] crate-type = ["cdylib"]`, dependencies `pyo3`, `arrow` and `pyo3-arrow`
- [x] `pyproject.toml`: Maturin build backend, `python-source = "python"`, `module-name = "rexlib_metadata._rexlib"`
- [x] `src/lib.rs`: minimal PyO3 module `_rexlib` with a smoke-test function, `version()`
- [x] `python/rexlib_metadata/__init__.py`: imports `_rexlib`, re-exports the smoke function
- [x] `python/rexlib_metadata/_rexlib.pyi`: stub for the smoke function
- [x] CI workflow: build matrix Linux, macOS and Windows, `import rexlib_metadata` as smoke test
- [x] Verify locally: `maturin develop && python -c "import rexlib_metadata"`

### Phase 1 — STAR reader with no convention, and CI tests ✅

- [x] `RawSchema` in Rust: column names as parsed from the file
- [x] STAR parsing in Rust: `read_schema() -> RawSchema`, `read_all() -> RecordBatch`, all values as `Utf8`
- [x] Exposed to Python: `_rexlib._star_read_schema(path)`, `_rexlib._star_read(path)`
- [x] `Reader` ABC in `abc.py`
- [x] `Convention` ABC in `abc.py`, with `matches`, `apply`, `to_file_name`, `to_canonical_name`
- [x] `ReadResult` in `result.py`: lazy, holding the path and the reader and no file handle; `to_pandas()`, `to_polars()`
- [x] `GenericStarConvention`: passthrough, `matches()` always False, `apply()` identity
- [x] `StarReader`, satisfying `Reader`, calling Rust underneath
- [x] `MetadataRegistry` in `registry.py`: `register_reader(extensions, cls)`, detection by extension
- [x] `global_registry`, with `StarReader` registered for `.star`
- [x] `rm.read()` in `__init__.py`
- [x] Small real `.star` fixtures under `tests/python/fixtures/`
- [x] Integration tests: `rm.read("test.star").to_pandas()`, checking shape, column names and values
- [x] `pytest` in CI, on every pull request

### Phase 2 — Schema, convention system and Relion4

- [ ] `ColumnDescriptor`, `SchemaTrait`, `TableSchema`, `Schema` in `python/rexlib_metadata/schema.py`
- [ ] `TableSchema.__init__` flattens traits and deduplicates by name: same type keeps the first, a different type is an error
- [ ] `ReadConvention` and `WriteConvention` ABCs in `abc.py`: `source_columns`, `target_columns`, `matches()`, `load()` / `store()`
- [ ] `ConventionBundle` in `abc.py`: `name`, `read_conventions`, `write_conventions`; `register()` refuses overlapping `target_columns` within the bundle
- [ ] `register_bundle(extension, bundle, *, prepend=False)` on `MetadataRegistry`
- [ ] The read engine: for each bundle in order and each raw table, apply every matching convention; the first write per canonical column wins; a missing required column raises
- [ ] `Relion4Bundle`: a `ReadConvention` for every Relion4 column group, `matches()` checking column presence, not the table name
- [ ] `Relion4Bundle` registered in `global_registry` for `.star`
- [ ] Tests: Relion4 detected on its own, with canonical column names; an explicit `bundle=`; a missing required column raises; duplicate `target_columns` in a bundle raise at registration

### Phase 3 — Write and roundtrip

- [ ] `Writer` ABC in `abc.py`
- [ ] A STAR serializer in Rust: `write(path, record_batch)`
- [ ] Exposed to Python: `_rexlib._star_write(path, batch)`
- [ ] `StarWriter`, satisfying `Writer`
- [ ] `StarWriter` registered in `global_registry` for `.star`
- [ ] `ReadResult.write(path)`, with no forwarding yet
- [ ] Tests: read, write, read again, and compare the DataFrames

### Phase 4 — Write-forwarding

- [ ] `ReadResult` always loads the full `RecordBatch`; `columns=` is a projection
- [ ] `ReadResult.write(path, updates=None)`: merges `updates` into the full batch and writes every column
- [ ] Tests: read 2 of N columns, modify, write, and check that all N columns are present and correct

### Phase 5 — Chunked reading

- [ ] A progressive chunk index in the STAR parser, recording the byte offset of each chunk boundary while reading
- [ ] Memory-mapped file access in the STAR parser
- [ ] Exposed to Python: `_rexlib._star_read_chunks(path, chunk_size, columns)`, yielding `RecordBatch`es
- [ ] `StarReader.read_chunks()` streaming from Rust rather than splitting in memory
- [ ] `ReadResult.chunks(size) -> Iterator[ReadResult]`: opens the file when iteration starts, closes it when exhausted or collected
- [ ] Tests: chunk a `.star` file of 100k rows or more; check the row count and that the file handle is closed afterwards

### Phase 6 — Multi-table, TableCollection and CD

- [ ] Several data blocks in one `.star` file
- [ ] `TableCollection` in `result.py`: dict-like, `__getitem__` returns a `ReadResult`
- [ ] `TableCollection` wired into `ReadResult` for multi-block files
- [ ] Tests: a multi-block `.star`, e.g. Relion4 with `data_particles` and `data_optics`
- [ ] CD: a development release on every push to `main`, as the other REX repositories do

### Phase 7 — XMD

- [ ] `XmdConvention`, mapping Xmipp column names
- [ ] `.xmd` registered to `StarReader` with `XmdConvention` in `global_registry`
- [ ] Tests: read `.xmd` files and check the canonical column names

### Phase 8 — SQLite

- [ ] Decide: Rust (`rusqlite`) or Python (`sqlite3`) for the parser
- [ ] `SqliteReader`, `SqliteWriter`
- [ ] Native pagination through `LIMIT`/`OFFSET`
- [ ] `.db` and `.sqlite` registered in `global_registry`
- [ ] Tests: read and write SQLite, pagination correctness

### Phase 9 — HDF5

- [ ] `Hdf5Reader`, `Hdf5Writer` (the `hdf5` crate or Python's `h5py`)
- [ ] Dataset slicing for pagination
- [ ] `.h5` and `.hdf5` registered in `global_registry`
- [ ] Tests: read and write HDF5 datasets

### Deferred, no phase yet

- `Relion3Convention`, legacy support, low priority
- `RexConvention`, once the team agrees on the internal standard; it goes first in detection order

## Dependencies

| Dependency | Role |
|---|---|
| `pyo3` | The Rust–Python binding |
| `arrow` | Apache Arrow in Rust, the canonical in-memory format |
| `pyo3-arrow` | The Arrow C Data Interface bridge that hands a `RecordBatch` to Python |
| `pyarrow` | The Python side of that bridge, and the only runtime dependency of the package |
| Pandas, Polars | Optional extras, `[pandas]` and `[polars]` |

Do not enable arrow's `pyarrow` feature. It pulls in `arrow-pyarrow`, which
pins an older pyo3 than `pyo3-arrow` needs, and `pyo3-arrow` is the only bridge
needed.

`arrow` and `pyo3-arrow` move together. `pyo3-arrow` exports no arrow of its
own, so the `RecordBatch` the parser builds and the one `PyRecordBatch::new`
takes are one type only while both come from the same arrow major. Renovate
caps `arrow` at what the newest `pyo3-arrow` holds; the cap is lifted in the
pull request that raises `pyo3-arrow`.

The test requirements and the Pandas extra carry one pin per range of Python
versions, split with PEP 508 markers, because recent releases of pyarrow,
pytest, Pandas and Polars dropped older Pythons. `renovate.json` keeps each old
pin on the releases that still support its Python; its rules say how.

## Conventions

Rust and Python are indented with four spaces. The `.vscode` settings default
to tabs for files they do not name, Python among them, which the code does not
follow.

Python modules that annotate start with `from __future__ import annotations`
and import what they only annotate with under `TYPE_CHECKING`.

`_rexlib.pyi` is written by hand. A function added to `_rexlib` gets its stub
in the same pull request.

## Pull requests

Whoever opens a pull request assigns it to themselves and gives it the label,
among the repository's own, that matches what it changes: `bug` for a fix,
`enhancement` for something new, `documentation` when only documentation
changes, and so on.

## Continuous integration

`build-and-test.yml` runs on pull requests and by hand, not on pushes to
`main`. It installs the package with its test extras on Linux, macOS and
Windows, on Python 3.9 through 3.14, and runs pytest. It runs neither
`cargo test` nor a linter, and there is no deployment yet; that is Phase 6.
