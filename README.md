# rexlib-metadata

Read and write CryoEM metadata formats (STAR, XMD, SQLite, HDF5) as Pandas or Polars DataFrames. Rust core, Python API, extensible by design.

Part of the [REX suite](https://github.com/gigabit-clowns) (gigabit-clowns org).

[![Build and Test](https://github.com/gigabit-clowns/rexlib-metadata/actions/workflows/build-and-test.yml/badge.svg)](https://github.com/gigabit-clowns/rexlib-metadata/actions/workflows/build-and-test.yml)

## SonarCloud status
[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=gigabit-clowns_rexlib-metadata&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=gigabit-clowns_rexlib-metadata)

### Ratings
[![Maintainability Rating](https://sonarcloud.io/api/project_badges/measure?project=gigabit-clowns_rexlib-metadata&metric=sqale_rating)](https://sonarcloud.io/summary/new_code?id=gigabit-clowns_rexlib-metadata)
[![Reliability Rating](https://sonarcloud.io/api/project_badges/measure?project=gigabit-clowns_rexlib-metadata&metric=reliability_rating)](https://sonarcloud.io/summary/new_code?id=gigabit-clowns_rexlib-metadata)
[![Security Rating](https://sonarcloud.io/api/project_badges/measure?project=gigabit-clowns_rexlib-metadata&metric=security_rating)](https://sonarcloud.io/summary/new_code?id=gigabit-clowns_rexlib-metadata)
[![Technical Debt](https://sonarcloud.io/api/project_badges/measure?project=gigabit-clowns_rexlib-metadata&metric=sqale_index)](https://sonarcloud.io/summary/new_code?id=gigabit-clowns_rexlib-metadata)

### Specific metrics
[![Bugs](https://sonarcloud.io/api/project_badges/measure?project=gigabit-clowns_rexlib-metadata&metric=bugs)](https://sonarcloud.io/summary/new_code?id=gigabit-clowns_rexlib-metadata)
[![Code Smells](https://sonarcloud.io/api/project_badges/measure?project=gigabit-clowns_rexlib-metadata&metric=code_smells)](https://sonarcloud.io/summary/new_code?id=gigabit-clowns_rexlib-metadata)
[![Vulnerabilities](https://sonarcloud.io/api/project_badges/measure?project=gigabit-clowns_rexlib-metadata&metric=vulnerabilities)](https://sonarcloud.io/summary/new_code?id=gigabit-clowns_rexlib-metadata)
[![Duplicated Lines (%)](https://sonarcloud.io/api/project_badges/measure?project=gigabit-clowns_rexlib-metadata&metric=duplicated_lines_density)](https://sonarcloud.io/summary/new_code?id=gigabit-clowns_rexlib-metadata)
[![Lines of Code](https://sonarcloud.io/api/project_badges/measure?project=gigabit-clowns_rexlib-metadata&metric=ncloc)](https://sonarcloud.io/summary/new_code?id=gigabit-clowns_rexlib-metadata)

## Features

- **Read STAR files** to Pandas or Polars DataFrames with a single call
- **All values preserved as strings** — no silent type inference; type conversion is the convention system's job
- **Lazy I/O** — `rxm.read()` returns immediately with no file I/O; data is only loaded when you call `to_pandas()` or `to_polars()`
- **Extensible** — plug in custom readers and conventions by subclassing Python ABCs; no Rust required
- **Fast core** — parsing and Arrow serialization in Rust via PyO3 + Maturin

Reading STAR files is what works today. Writing, the conventions themselves, chunked reads, XMD, SQLite and HDF5 are on their way — see the [roadmap](docs/roadmap.md).

## Installation

```bash
# With pandas
pip install rexlib-metadata[pandas]

# With polars
pip install rexlib-metadata[polars]

# Both
pip install rexlib-metadata[pandas,polars]
```

Requires Python ≥ 3.10.

## Usage

```python
import rexlib_metadata as rxm

result = rxm.read("particles.star")

df = result.to_pandas()   # pandas.DataFrame
df = result.to_polars()   # polars.DataFrame
```

A STAR file may hold several data blocks, and a Relion one usually does —
its optics live in a block of their own. Name the one you mean:

```python
result = rxm.read("run_it025_data.star")

result.names               # ('optics', 'particles')
result["particles"].to_pandas()
```

A file of one table needs no name. A file of several asks for one rather
than picking.

All column values come back as strings. Type conversion is intentionally deferred to the [convention system](docs/design.md#the-convention-layer).

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
from rexlib_metadata.convention import RawTable
from rexlib_metadata.registry import global_registry

class MyFormatReader(Reader):
    def read_tables(self, path: str) -> list[RawTable]:
        # parse your format, one RawTable per table the file holds
        ...

global_registry.register_reader([".myext"], MyFormatReader())

# Now rxm.read() dispatches to your reader automatically
result = rxm.read("data.myext")
```

`read_tables` is all a reader has to write: `Reader.read` already returns the
lazy result, and leaving it alone is what keeps the file closed until
somebody asks for rows.

## Development

### Requirements

- Python ≥ 3.10
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

### Contributing

[AGENTS.md](AGENTS.md) is the place to start: the architecture, the conventions of the codebase and the design invariants, everything needed before writing a line here. [docs/design.md](docs/design.md) goes deeper into the schema and convention layers and the questions still open, and [docs/roadmap.md](docs/roadmap.md) says what comes next.
