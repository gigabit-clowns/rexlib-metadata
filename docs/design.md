# Design notes

The requirements, the decisions that stand, the interfaces, the engine's
rules and what is still open. A change that contradicts this file updates it
in the same pull request. The canonical columns are in
[canonical.md](canonical.md), what each format demands in
[formats.md](formats.md), progress in [roadmap.md](roadmap.md).

## The requirements

Tables, or groups of related tables, between the field's formats and one
canonical in-memory form. A new format and a new canonical representation are
each an addition, not a rewrite.

1. A reader without its writer, and a writer without its reader.
2. Dependency inversion: readers, writers, conventions and columns injectable
   from the client side.
3. Highly performant: Rust with a Python API.
4. Heuristics pick reader, writer and conventions (`*.star` → STAR reader,
   Relion conventions; `*.xmd` → STAR reader, Xmipp conventions; the content
   where the extension does not settle it). Every heuristic can be overridden.
5. Groups of related tables are first-class.
6. Paginated reading and writing.
7. Single columns can be read, and the rest forwarded on write.
8. Strict column typing.
9. Binary formats: SQLite, HDF5.

The canonical table is a pandas or polars DataFrame, the user's choice; Arrow
sits under both.

## Decisions

- **A library of its own**, part of REX and depending on nothing else in it.
  The name is open until the first PyPI release (`vitrio-metadata` is the
  other candidate).
- **Arrow is the canonical form**: `arrow-rs` in Rust, the C Data Interface
  across the boundary. pandas and polars are extras, imported only by
  `to_pandas()` / `to_polars()`.
- **A reader never infers a type.** STAR and XMD arrive as `Utf8`; SQLite
  and HDF5 are transcribed as they declare. Typing is the schema's, conversion
  the convention's.
- **Read and write are separate pipelines**: separate ABCs, registration and
  lists in a bundle. A canonical column may have several origins and has one
  destination.
- **Matching is by column presence**, never by the raw table's name.
- **Priority is per bundle**, never per column: a bundle wins or loses as one.
- **Missing is null**, an empty value of a typed column included. A token
  that does not parse into the declared type is an error naming the file,
  the canonical table and the value (not the line). Sentinels such as
  Xmipp's `-999` are the format's conventions' to translate, both ways.
  `ColumnDescriptor.default` fills a column the file does not carry.
- **The canonical form normalizes, it does not rename**: fixed units on the
  column, one rotation convention, image references split into path and
  zero-based index, paths as written. No image library is named in the API.
  Details in [canonical.md](canonical.md).
- **One parser.** The state machine in `src/text/` hands each row to a sink
  that appends to Arrow builders and cuts a chunk every so many rows; a whole
  read is every chunk. Another block-shaped text format is a new lexer, not a
  second parser.
- **No memory map**: the crate forbids `unsafe_code`, and a file truncated
  while mapped is a `SIGBUS`. A buffered reader bounds memory instead.
- **No chunk index** until an API asks for chunk *k* without reading the ones
  before it; then a progressive index, never a mandatory first scan.
- **No LTO**: the release profile is cargo's default (see the Phase 10
  measurements in [roadmap.md](roadmap.md)).
- **SQLite is read in Python through `sqlite3`.** Generic reader: every
  table, typed by SQLite's affinity rules, `NUMERIC` and undeclared columns
  as text. A dialect such as Scipion's is a bundle on top, not a reader.
- **HDF5 is read through h5py, the `hdf5` extra**, imported only when an HDF5
  file is opened. A table is a one-dimensional compound dataset (fields are
  columns) or a group of equal-length datasets (each a column), named by its
  path. The writer writes groups.
- **A table the file does not name is named `""`**, a plain `str`. Written to
  STAR it is `data_`.
- **Relations between tables are data on the `Schema`**, not special cases in
  a bundle (see [The schema layer](#the-schema-layer)).

## The canonical representation

`pyo3-arrow` returns `arro3` objects. arro3 is not a dependency: every Rust
entry point returning Arrow goes through `to_pyarrow_table` in `_arrow.py`,
which consumes the Arrow protocol. `_rexlib.pyi` types those entry points as
`ArrowArrayExportable` (one method, `__arrow_c_array__`), never as an arro3
class.

## The schema layer

`python/rexlib_metadata/schema.py`; knows no file format.

| Type | What it is |
|---|---|
| `ColumnDescriptor(name, dtype, unit=None, required=False, default=None)` | One canonical column. Required and defaulted at once raises. |
| `SchemaTrait(name, columns)` | A reusable group (`EulerAngles`), flattened into the table; no run-time identity. |
| `TableSchema(name, *parts)` | One table, composed from traits and columns in order. |
| `Relation(table, related, key)` | Each row of `table` points by `key` at one row of `related`. |
| `Schema(*tables, relations=())` | One or more tables by unique name, and their relations. |

- The same column declared identically twice collapses to the first; declared
  two ways (any field, unit and `required` included) raises at construction.
- A relation's two tables both declare its key and share no other column,
  checked at construction.
- An unknown column raises; nothing is passed through.

## The convention layer

`python/rexlib_metadata/convention.py`.

```python
ArrowColumn = pa.Array | pa.ChunkedArray

class RawSchema:            # table_name: str, column_names: tuple[str, ...]
    def has(self, *names: str) -> bool: ...

class RawTable:             # schema: RawSchema, table: pa.Table
    @classmethod
    def of(cls, name: str, table: pa.Table) -> RawTable: ...

class ReadConvention(ABC):
    source_columns: tuple[str, ...]   # file columns consumed
    target_columns: tuple[str, ...]   # canonical columns produced
    def matches(self, raw: RawSchema) -> bool: ...
    def load(self, table: pa.Table) -> dict[str, ArrowColumn]: ...

class WriteConvention(ABC):
    source_columns: tuple[str, ...]   # canonical columns consumed
    target_columns: tuple[str, ...]   # file columns produced
    def store(self, canonical: dict[str, ArrowColumn]) -> dict[str, ArrowColumn]: ...

class ConventionBundle:
    def __init__(self, name: str,
                 read: Mapping[str, Iterable[ReadConvention]] | None = None,
                 write: Mapping[str, Iterable[WriteConvention]] | None = None): ...
    tables: tuple[str, ...]           # canonical tables it reads into
    def read_conventions(self, table: str) -> tuple[ReadConvention, ...]: ...
    def write_conventions(self, table: str) -> tuple[WriteConvention, ...]: ...
```

A bundle is every convention of one format, keyed by the canonical table each
fills. It is immutable and validates itself when built, raising on:

- two read conventions of one table declaring the same canonical column;
- two write conventions of one table declaring the same file column;
- a convention with no `target_columns`.

The same column in conventions of different tables is no collision
(`optics_group` belongs to both `particles` and `optics`).

`matches()` decides from `source_columns` only, as every shipped convention
does; a narrowed read depends on it.

A reader and a writer (`abc.py`):

```python
class Reader(ABC):
    def read_tables(self, path: str) -> list[RawTable]: ...            # abstract
    def read_schemas(self, path: str) -> list[RawSchema]: ...
    def read_tables_keeping(self, path: str, columns: Set[str]) -> list[RawTable]: ...
    def read_chunks(self, path: str, size: int, columns: Set[str] | None = None
                    ) -> Iterator[tuple[int, RawTable]]: ...

class Writer(ABC):
    def write_tables(self, path: str, tables: Iterable[RawTable]) -> None: ...  # abstract
```

`read_schemas`, `read_tables_keeping` and `read_chunks` default to reading everything and
dropping or slicing; a reader that can do better overrides them, as
`StarReader`, `SqliteReader` and `Hdf5Reader` do. `columns` is raw names and
may name columns the file lacks. Each chunk carries its table's ordinal,
which tells two tables of one name apart; a table of no rows is one empty
chunk.

### The read engine

`read_canonical` in `engine.py`, for one canonical table:

1. If some raw table has a row and no convention of the table, in any
   bundle, matches any raw table, raise, naming the bundles and the columns
   found.
   A partial read is legitimate; an empty file reads as empty.
2. The source is the raw table `assigned` gives it, decided from the
   raw schemas alone, so a chunked read (`read_schemas` first) and a whole
   read choose alike. A raw table can fill a canonical one when its
   matching conventions declare every required column, scoring the columns
   they declare. Best score first, then file order, then schema order, a
   pair is taken when neither side is taken yet; a canonical table left
   without one shares the best raw table it can fill. Only the source is
   read.
3. Bundles in order, then their conventions: a matching convention that adds
   a column not yet covered is loaded. The first to produce a column owns it.
   A losing output is discarded unvalidated.
4. A kept column raises if its convention did not declare it, the table does
   not declare it, or its Arrow type differs from the declared one (a
   convention converts, the engine does not).
5. Columns of different lengths raise; a value from another table is a
   relation's job or the convention's, never a broadcast by the engine.
6. A required column nobody produced raises. A defaulted one is filled with
   its default; any other is absent, not nulls.

A narrowed read (`columns=`) keeps a set of raw names computed from the
conventions alone, before the file is opened (`source_columns` in
`engine.py`): for each canonical table declaring a requested column, the
`source_columns` of every convention producing a requested or required
column. It may name more than the file holds, never less than the read needs.

### The write engine

`write_canonical` in `engine.py` mirrors the read: bundles in order, a write
convention applies when all its `source_columns` are present and it adds a
file column not yet produced, the first to produce a file column owns it, an
undeclared output raises, and a table nothing writes raises.

- The destination's extension chooses writer and bundles, so
  `read("a.star").write("b.xmd")` converts. Canonical names are never written
  as a default; `result.raw.write(path)` writes the file's own names.
- Values are converted with Arrow's cast: a float is the shortest text that
  reads back as the same `float64`. A convention may format its own column.
- A related table the destination's conventions do not write is joined into
  the rows that point at it (XMD has no optics table). `rxm.write` puts a
  table that others point at first.
- **Same format** means the same writer, class and configuration, not the
  same suffix (`.sqlite` and `.db` are one; `.star` and `.xmd` are two). Then
  a column no convention writes, and a block no canonical table covers, are
  carried over in file order. Towards another format both are dropped.
- A column of `updates` no write convention consumes raises. A write that
  would hold nothing raises.
- Every write goes to a temporary file in the destination's directory,
  renamed over it at the end.

### Writing a convention

```python
class MyAngles(ReadConvention):
    source_columns = ("myAngle1", "myAngle2", "myAngle3")
    target_columns = ("angle_rot", "angle_tilt", "angle_psi")

    def matches(self, raw: RawSchema) -> bool:
        return raw.has(*self.source_columns)

    def load(self, table: pa.Table) -> dict[str, ArrowColumn]:
        return {
            target: pc.cast(table.column(source), pa.float64())
            for source, target in zip(self.source_columns, self.target_columns)
        }

bundle = ConventionBundle("mylab", read={"particles": [MyAngles()]})
global_registry.register_bundle(".star", bundle, prepend=True)
```

## The registry, detection and injection

`MetadataRegistry` (`registry.py`) maps a lower-cased extension to a reader,
a writer and an ordered list of bundles (`register_reader`,
`register_writer`, `register_bundle(..., prepend=False)`).
`global_registry` holds what ships; a local instance isolates a test.

Overrides at the call site, each an instance: `reader=` and `bundle=` on
`read`, `writer=` and `bundle=` on `write`; `bundle=` takes one bundle or
several in priority order. With both named the extension need not be
registered. A write rereads its source through the reader it was read with.

## Laziness, projection and forwarding

- `rxm.read()` returns a `ReadResult` and reads no row. Rows are read by
  `to_pandas()`, `to_polars()`, `names` or `chunks()`. No file handle
  outlives the call doing the I/O.
- `result[name]` checks the name against the schema and reads nothing; a
  declared table the file does not fill is an error when its rows are asked
  for.
- `columns=` shows only those canonical columns, and only the tables
  declaring one; an undeclared name raises before any I/O.
- `chunks(size)` needs one canonical table (`result[name]`), yields `Chunk`s
  (`name`, `len()`, `to_arrow()`, `to_pandas()`, `to_polars()`), and stops
  where the filling block ends. Tables a joined view points at are read
  whole first.
- `result.joined(name)` gives each row the columns of the row it points at.
  `updates` through it may not change the related table's columns.
- A view never narrows a write: `write` writes every canonical table the
  source fills, every column, rereading the whole source. The source must
  still be there.
- `updates=` replaces columns of the one table the result shows; it holds a
  row for every row written, in order. `rows=` (positions or a boolean mask)
  keeps only those rows of that table.

Text formats are paginated by the parser; SQLite by a cursor per table, HDF5
by dataset slicing.

## The public API

```python
import rexlib_metadata as rxm

result = rxm.read("particles.star")
result = rxm.read("particles.star", columns=["angle_rot"],
                  bundle=relion4_bundle(), reader=StarReader())
df = result.to_pandas()                      # or .to_polars()
result.names                                 # canonical tables filled
result["particles"].to_pandas()
result.joined("particles").to_polars()       # optics joined per row
for chunk in result["particles"].chunks(10_000):
    chunk.to_pandas()
result.raw["particles"].to_pandas()          # the file's own names
result.write("out.xmd")                      # converts

result = rxm.read("particles.star", columns=["angle_rot"])
df = result.to_pandas()
df["angle_rot"] += 10
result.write("out.star", updates=df)         # every other column forwarded
kept = df[df["angle_rot"] > 0]
result.write("subset.star", rows=kept.index, updates=kept)

rxm.write("new.star", {"particles": frame})  # canonical tables from memory
```

## Formats

| Extension | Reader / writer | Bundle |
|---|---|---|
| `.star` | `StarReader` / `StarWriter` | `relion4` |
| `.xmd` | `StarReader` / `StarWriter(header=HEADER)` | `xmipp` |
| `.sqlite`, `.db` | `SqliteReader` / `SqliteWriter` | — |
| `.h5`, `.hdf5` | `Hdf5Reader` / `Hdf5Writer` | — |

Order: Relion 4/5 STAR, Xmipp XMD, cryoSPARC, then the stored formats.
cryoSPARC `.cs` (a NumPy structured array, one `pose` column feeding three
angles), FREALIGN `.par` and the cryoSPARC CSV are in
[formats.md](formats.md); Relion 3 is deferred.

## Open questions

- **The M:N column relation.** The convention is the unit of mapping, with
  `matches()` deciding; no hard case has tested it yet (cryoSPARC's `pose`
  will).
- **Convention lookup cost.** Every convention of every bundle is walked in
  order, linear in their number; unmeasured at the Relion bundle's full size.
- **Content-based detection.** Which bytes decide, and how far a sniff may
  read.
- **The rotation convention's signs**, unverified against real files (see
  [canonical.md](canonical.md)).
- **A read convention that needs a joined column**, as Relion 3.0's shifts in
  pixels need the optics' pixel size.

## References

- [starfile-rs](https://github.com/hanjinliu/starfile-rs): the STAR reader
  was compared against it.
- [starfile](https://github.com/teamtomo/starfile): Python prior art.
