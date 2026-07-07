# rexlib-metadata

Read and write CryoEM metadata formats (STAR, XMD, SQLite, HDF5) as Pandas or Polars DataFrames. Rust core, Python API, extensible by design.

Part of the [REX suite](https://github.com/gigabit-clowns) (gigabit-clowns org).

## Features

- **Read STAR files** to Pandas or Polars DataFrames with a single call
- **All values preserved as strings** — no silent type inference; type conversion is the convention system's job
- **Lazy I/O** — `rm.read()` opens and closes the file immediately; row data is only loaded when you call `to_pandas()` or `to_polars()`
- **Extensible** — plug in custom readers and conventions by subclassing Python ABCs; no Rust required
- **Fast core** — parsing and Arrow serialization in Rust via PyO3 + Maturin

### Roadmap

| Phase | Status |
|-------|--------|
| STAR reader | ✅ Done |
| Schema + Relion4 convention system | Planned |
| STAR writer + roundtrip | Planned |
| Chunked / streaming reads | Planned |
| XMD (Xmipp) | Planned |
| SQLite | Planned |
| HDF5 | Planned |

## Installation

```bash
# With pandas
pip install rexlib-metadata[pandas]

# With polars
pip install rexlib-metadata[polars]

# Both
pip install rexlib-metadata[pandas,polars]
```

Requires Python ≥ 3.9.

## Usage

```python
import rexlib_metadata as rm

result = rm.read("particles.star")

df = result.to_pandas()   # pandas.DataFrame
df = result.to_polars()   # polars.DataFrame
```

All column values come back as strings. Type conversion is intentionally deferred to the convention system (Phase 2).

```python
print(df.columns)
# ['_rlnAngleRot', '_rlnAngleTilt', '_rlnCoordinateX', '_rlnCoordinateY', ...]

print(df.dtypes)
# All object / String — no silent inference
```

### Custom readers

Subclass `Reader` to add support for any format without touching Rust:

```python
from rexlib_metadata.abc import Reader
from rexlib_metadata.result import ReadResult
from rexlib_metadata.registry import global_registry
import pyarrow as pa

class MyFormatReader(Reader):
    def read_all(self, path: str) -> pa.Table:
        # parse your format, return an Arrow Table
        ...

    def read(self, path: str, **kwargs) -> ReadResult:
        return ReadResult(path, self)

global_registry.register_reader([".myext"], MyFormatReader)

# Now rm.read() dispatches to your reader automatically
result = rm.read("data.myext")
```

## Development

### Requirements

- Python ≥ 3.9
- Rust (stable) — install via [rustup](https://rustup.rs)
- [Maturin](https://www.maturin.rs) — `pip install maturin`

### Build and install locally

```bash
pip install maturin
maturin develop
```

### Run tests

```bash
pip install .[test]
pytest
```

### Run Rust unit tests

```bash
cargo test
```
