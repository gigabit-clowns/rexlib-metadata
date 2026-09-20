# Design notes

The design this repository is being built towards, at the level of detail
that does not belong in `AGENTS.md`: the requirements it answers, the
decisions taken and when, the interfaces in code, and what is still open.
`AGENTS.md` states the rules; this file states why they are the rules and
what they look like written out.

Keep it true the same way: a change that contradicts something here updates
it in the same pull request, and a decision taken in a discussion is only
taken once it is written down here.

## The requirements

The library reads and writes tables, or groups of related tables, between the
formats the field uses — Relion STAR, Xmipp XMD, and the binary ones — and a
canonical in-memory representation. It has to be extensible in both
directions at once: a new industry format, and a new canonical
representation, are each supposed to be additions rather than rewrites.

From the original requirements document:

1. A reader can be defined without its writer, and a writer without its
   reader.
2. Dependency inversion throughout. Readers, writers, conventions and columns
   are all injectable from the client side.
3. Highly performant. Rust with a Python API — confirmed, and built.
4. Heuristics decide reader, writer and conventions: `*.star` gives the STAR
   reader with Relion4 conventions, `*.xmd` the STAR reader with Xmipp ones,
   and the content is consulted where the extension does not settle it. Every
   heuristic can be overridden.
5. Groups of related tables are a first-class case, not an afterthought.
6. Loading and writing are paginated.
7. Single columns can be read, and the rest forwarded on write.
8. Column typing is strict.
9. Formats that are not human-readable — SQLite, HDF5 — are supported.

The canonical table is a pandas or a polars DataFrame, the user's choice,
which is why Arrow is what sits underneath both.

## Decisions

**A library of its own.** The "separate library, name TBD" of the original
document is this repository, `rexlib-metadata`. It is part of the REX suite
and depends on nothing else in it.

**Arrow as the canonical form** (Phase 0). One representation that both
pandas and polars are built on, so neither is privileged and neither is a
hard dependency. `arrow-rs` in Rust, the C Data Interface across the
boundary.

**Everything reads as `Utf8`** (Phase 1). Inference in the reader would take
the typing decision away from the schema, silently and per file. A reader
that guesses `1e5` into a float has already decided something the convention
was supposed to decide.

**Read and write are separate pipelines** (2026-07-03). Separate ABCs,
separate registration, separate lists in a bundle. Writing a reader must not
imply writing a writer, and the mapping is not one to one anyway: a canonical
column with several possible origins in Relion still has exactly one
destination we would write it to. A single reversible object would have to
misrepresent one of the two directions.

**Matching by column presence, not by table name** (Phase 2 design). The name
of a data block belongs to whoever wrote the file. The columns are the
evidence.

**Priority at the bundle level** (Phase 2 design). Column-level priority
would make the result depend on registration order in a way nobody can
predict from the outside. A bundle is a coherent unit: it wins or it loses as
one.

## The schema layer

```python
@dataclass
class ColumnDescriptor:
    name: str
    dtype: pa.DataType
    default: Any | None = None  # None means required
```

`SchemaTrait` is a named, reusable group of related columns — `EulerAngles`,
`CartesianPosition`. It is a composition tool only and flattens into the
table.

`TableSchema` is a table's full column set, built by composing traits:

- same name, same type across traits → keep the first, discard silently
- same name, different type → raise at construction

`Schema` is one or more `TableSchema`. A Relion4 file with `data_particles`
and `data_optics` produces a `Schema` with two tables.

## The convention layer

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


class ConventionBundle:
    name: str                               # "relion4"
    read_conventions: list[ReadConvention]
    write_conventions: list[WriteConvention]
```

`register()` validates that no two `ReadConvention`s of the bundle declare
the same element in `target_columns`, and raises on the spot if they do.

### The read engine

```python
covered = {}  # canonical column -> Array

for bundle in registry.bundles_for(extension):   # ordered, highest first
    for raw_table in file.tables:
        for conv in bundle.read_conventions:
            if conv.matches(raw_table.schema):
                if any(t not in covered for t in conv.target_columns):
                    for col, array in conv.load(raw_table.batch).items():
                        covered.setdefault(col, array)   # first write wins

for col in table_schema.required_columns:
    if col.name not in covered and col.default is None:
        raise ValueError(f"Required column '{col.name}' not produced by any convention")
```

The raw table is linked to the canonical table by `matches()` returning true
for its `RawSchema` — no string comparison anywhere in the path.

### Registering a bundle

```python
registry.register_bundle(".star", Relion4Bundle())   # tried first
registry.register_bundle(".star", Relion3Bundle())   # fallback
```

### Writing one

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

## The intended public API

Written out as it is meant to end up. Only the first three lines exist today.

```python
import rexlib_metadata as rm

result = rm.read("particles.star")
result = rm.read("particles.star", columns=["angle_rot"],
                 convention=Relion4(), backend="polars")

df = result.to_pandas()     # I/O happens here
df = result.to_polars()

df_particles = result["particles"].to_pandas()      # multi-table files

for chunk in result.chunks(size=10_000):            # streaming
    chunk.to_pandas()

result.write("output.star")

# write-forwarding: read some columns, modify, write everything back
result = rm.read("particles.star", columns=["angle_rot"])
df = result.to_pandas()
df["angle_rot"] += 10
result.write("output.star", updates=df)
```

## Formats

Implementation order: Relion4/5 STAR, then XMD, then SQLite, then HDF5.

| Extension | Reader | Conventions |
|---|---|---|
| `.star` | `StarReader` | Relion4, Relion3 |
| `.xmd` | `StarReader` | Xmipp |
| `.db`, `.sqlite` | `SqliteReader` | — |
| `.h5`, `.hdf5` | `Hdf5Reader` | — |

XMD is STAR with different column names, which is exactly the split the
convention layer exists for: one reader, two bundles.

## Pagination

Text formats get a progressive lazy index of chunk-level byte offsets over a
memory-mapped file. The index is built as chunks are read rather than by a
mandatory first scan, so sequential access pays nothing and random access
pays only for what it has already passed. SQLite and HDF5 use what they
have — `LIMIT`/`OFFSET`, dataset slicing. The API the user sees is the same
either way.

## Open questions

**The M:N column relation.** A canonical column may come from several file
columns and a file column may feed several canonical ones. The current answer
is the convention as the unit of mapping, with `matches()` deciding
applicability, but it has not met a hard case yet.

**Indexing the convention registry.** A plain key-value lookup is not enough
if choosing a convention means an intelligent selection over the columns
present. The current design walks every convention of every bundle in order
and lets `matches()` decide, which is correct and linear in the number of
conventions; whether that stays acceptable as the Relion bundle grows to its
real size is unmeasured.

**Table groups.** Relation between tables — which optics group a particle
belongs to — is not modelled yet. `Schema` holds several tables; nothing
holds what connects them.

**Content-based detection.** "Look at the content" is stated as a
requirement, but which bytes decide, and how far into the file the sniffing
is allowed to read, is not settled.

**Strict typing at the edges.** Missing values, sentinel values and the
Relion conventions around them have no answer yet. `ColumnDescriptor.default`
covers an absent column, not an absent cell.

## References

- [starfile-rs](https://github.com/hanjinliu/starfile-rs) — the reference
  implementation the STAR reader was compared against.
- [starfile](https://github.com/teamtomo/starfile) — the Python prior art.
- Relion 3.1+ splits optics into their own data block, which is the source of
  the multi-block requirement.
