# rexlib-metadata

Highly performant reader and writer of CryoEM metadata formats (STAR, XMD, SQLite, HDF5), to and from Pandas or Polars DataFrames. Rust core, Python API, extensible by design.

[![Build and Test](https://github.com/gigabit-clowns/rexlib-metadata/actions/workflows/build-and-test.yml/badge.svg)](https://github.com/gigabit-clowns/rexlib-metadata/actions/workflows/build-and-test.yml)
[![CodSpeed](https://img.shields.io/endpoint?url=https://codspeed.io/badge.json)](https://codspeed.io/gigabit-clowns/rexlib-metadata)

## Features

- **One vocabulary, whatever the file** — columns come back under canonical names, typed: `_rlnCoordinateX` and Xmipp's equivalent both arrive as `coord_x`
- **The file's own names too** — `result.raw` is the same read as the format wrote it, every value a string
- **Lazy I/O** — `rxm.read()` returns immediately with no file I/O, and so does naming a table; data is only loaded when you call `to_pandas()`, `to_polars()` or `chunks()`, and nothing of the file is kept once the frame is handed back
- **Bounded memory** — `chunks()` streams a file larger than memory, parsing only the columns asked for
- **Lossless writes** — columns no convention covers are carried over; a conversion is a change of extension
- **Extensible** — custom readers and conventions by subclassing Python ABCs; no Rust required

STAR works through Relion's conventions. XMD reads and writes its image reference and angles; SQLite and HDF5 every table as the file declares it. More of XMD and Scipion's SQLite: see the [roadmap](docs/roadmap.md).

## Performance

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/performance-read-dark.svg">
  <img alt="Reading 10 million Relion particles to pandas, best of three: rexlib-metadata raw 13.15 s, canonical 18.40 s, starfile-rs 29.00 s, starfile 67.70 s" src="docs/assets/performance-read-light.svg">
</picture>

The canonical read hands back numbers, as starfile and
[starfile-rs](https://github.com/hanjinliu/starfile-rs) do, 3.7× and 1.6×
faster: 49 s and 11 s less per read of ten million particles. The raw read
keeps every value as text, so part of its lead is work it skips.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/performance-write-dark.svg">
  <img alt="Writing 10 million Relion particles, best of three: rexlib-metadata raw as read 3.86 s, starfile-rs as read 15.39 s, rexlib-metadata canonical rereading the source 29.65 s, starfile-rs from pandas 180.96 s, starfile from pandas 247.69 s" src="docs/assets/performance-write-light.svg">
</picture>

Each write starts from what its library's read left in memory. Written as
read, the raw write is 4× faster than starfile-rs's. From typed columns, the
canonical write is 6× faster than starfile-rs and 8× faster than starfile,
and rereads the source so that every column reaches the destination.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/performance-read-memory-dark.svg">
  <img alt="Peak memory reading 10 million Relion particles to pandas: rexlib-metadata in chunks of 100k 0.19 GiB, raw 4.53 GiB, canonical 4.93 GiB, starfile-rs 8.60 GiB, starfile 18.74 GiB" src="docs/assets/performance-read-memory-light.svg">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/performance-write-memory-dark.svg">
  <img alt="Peak memory writing 10 million Relion particles: rexlib-metadata raw as read 2.97 GiB, canonical rereading the source 5.87 GiB, starfile-rs as read 9.60 GiB, starfile-rs from pandas 11.33 GiB, starfile from pandas 18.61 GiB" src="docs/assets/performance-write-memory-light.svg">
</picture>

A canonical read holds 3.8× less than starfile and 1.7× less than
starfile-rs. Read in chunks, the same ten million particles take 0.19 GiB in
about the time of a whole read. A write's peak includes the read it starts
from.

Measured with `python -m scripts.compare --rows 10000000 --svg`, and with
`--measure memory`, each operation in its own process. Every pull request is
also benchmarked against `main` on
[CodSpeed](https://codspeed.io/gigabit-clowns/rexlib-metadata).

## Installation

```bash
pip install rexlib-metadata[pandas]   # or [polars], [pandas,polars]
pip install rexlib-metadata[hdf5]     # HDF5 files, through h5py
```

Requires Python ≥ 3.10.

## Usage

```python
import rexlib_metadata as rxm

result = rxm.read("particles.star")   # reader and conventions chosen by extension
df = result.to_pandas()               # or result.to_polars()

df.columns          # ['image_path', 'image_index', 'micrograph_path', 'coord_x', 'coord_y', ...]
df["coord_x"].dtype # float64
```

A file of several tables names them by what they hold, and asks for one
rather than picking:

```python
result = rxm.read("run_it025_data.star")
result.names                             # ('particles', 'optics')
result["particles"].to_pandas()
result.joined("particles").to_pandas()   # ..., optics_group, voltage, pixel_size, ...
```

### Chunks

```python
for chunk in rxm.read("run_data.star")["particles"].chunks(10_000):
    df = chunk.to_pandas()
```

A chunk has `name`, `len()`, `to_arrow()`, `to_pandas()` and `to_polars()`.
Combined with `columns=`, only the projected columns are parsed.

### Raw view

`result.raw` holds the blocks and columns under the file's own names, every
value a string, and is the answer when no convention recognises a file:

```python
result = rxm.read("run_it025_optimiser_3D.star")
result.names               # () -- nothing canonical in an optimiser file
result.raw.names           # ('optimiser_general',)
result.raw.to_pandas()     # _rlnOutputRootName, _rlnModelStarFile, ...
```

### Writing

```python
result = rxm.read("run_data.star")
result.write("copy.star")                  # canonical, spelled as Relion does
result.raw.write("verbatim.star")          # the file's own names, untouched
result.raw["particles"].write("one.star")  # just that block

rxm.read("particles.star").write("particles.xmd")   # conversion
rxm.write("picked.star", {"particles": df})          # tables built in memory: pandas, polars or Arrow
```

Change some columns and the write carries the rest; `rows=` keeps only some
particles, by position or mask:

```python
result = rxm.read("particles.star", columns=["angle_rot"])
df = result.to_pandas()
df["angle_rot"] += 10
result.write("rotated.star", updates=df)

particles = rxm.read("run_data.star")["particles"]
df = particles.to_pandas()
good = df[df["ctf_max_resolution"] < 4].copy()
good["angle_rot"] += 10
particles.write("good.star", rows=good.index, updates=good[["angle_rot"]])
```

- A write rereads the source, so the source must still be where it was. It
  writes every table of the file, whatever the result shows.
- Columns and blocks no convention covers are carried over when the
  destination has the source's format. Converting to XMD, which has no
  optics table, joins the optics into each particle.
- A joined view writes back its particles' columns; a changed optics column
  is refused — write it through `result["optics"]`.
- Writes go through a temporary file, so writing over the source is safe and
  a failed write leaves the old file intact. A write that would hold nothing
  raises.

## Extending

A `ConventionBundle` groups a format's conventions by canonical table.
`bundle=` takes one or several in priority order; `reader=` and `writer=`
cover a file whose extension says nothing of its format:

```python
from rexlib_metadata.convention import ConventionBundle
from rexlib_metadata.conventions.relion import relion4_bundle
from rexlib_metadata.conventions.star import StarReader, StarWriter

mylab = ConventionBundle("mylab", read={"particles": [MyAngleRot()]})
rxm.read("particles.star", bundle=[mylab, relion4_bundle()]).to_pandas()

relion = relion4_bundle()
result = rxm.read("particles.txt", reader=StarReader(), bundle=relion)
result.write("out.txt", writer=StarWriter(), bundle=relion)
```

Registering applies to every file of an extension; the first bundle to
produce a canonical column owns it:

```python
from rexlib_metadata.registry import global_registry

global_registry.register_bundle([".star"], mylab, prepend=True)
```

A new format needs only `read_tables` (and `write_tables` for a `Writer`);
overriding `read_tables_keeping(path, columns)` lets `columns=` skip columns
while parsing:

```python
from rexlib_metadata.abc import Reader
from rexlib_metadata.convention import RawTable

class MyFormatReader(Reader):
    def read_tables(self, path: str) -> list[RawTable]:
        ...  # one RawTable per table the file holds

global_registry.register_reader([".myext"], MyFormatReader())
result = rxm.read("data.myext")
```

## Contributing

Start with [AGENTS.md](AGENTS.md).

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
