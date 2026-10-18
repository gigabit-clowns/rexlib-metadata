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

**Missing is null, and nothing else** (2026-10-18). Arrow's null is the only
representation of an absent value in the canonical form. A token that does
not parse into the declared type is an error naming the file and the line,
never a silent null: `_rlnDefocusU` holding `abc` is a broken file and the
caller has to hear about it. Sentinels — Xmipp's `-999` and its kin — are
knowledge about a format, so they are translated by the read convention that
knows them and written back by the write convention, and the core never
learns they exist. `ColumnDescriptor.default` is a different thing: it covers
a column the file does not carry at all.

**Forwarding re-reads the source** (2026-10-18). A projection reads only the
columns asked for. `write(path, updates=df)` streams the source again and
emits the output substituting the columns that changed, so memory is one
chunk rather than the whole file, and a file larger than RAM still works.
The earlier design held every column in memory on every read to make this
possible, which charged the whole file to callers who never write.

Three things follow. The source has to still be there at write time, and the
caller is trusted not to move it from under us — a guard on size and mtime
was considered and dropped as distrust of the user for a mistake only the
user can make; if concurrent writers ever become a real problem, an advisory
lock is the answer, not a heuristic. The rows have to correspond one to one,
so a different row count is an error saying that filtering makes the caller
the owner of every column: there is no sane answer to which source row a
filtered row forwards from. And writing over the source goes through a
temporary file **in the destination directory**, renamed at the end, since
a rename is only atomic within one filesystem and a temporary in the system
temp directory would degrade into a copy.

**The canonical form normalizes, it does not rename** (2026-10-18). A
canonical column whose only merit is dropping the `rln` prefix leaves the
consumer knowing which program wrote the row, which is what the canonical
form exists to spare them. So: units are fixed and declared on the column
rather than spelled in its name, shifts in Ångström because pixels mean
nothing across a change of binning, angles in degrees, one documented
rotation convention that every format converts into. Image references are
split into a path as written and a zero-based index, because the consumer
indexes arrays and because a plain string and a plain integer are usable by
`mrcfile`, by vitrio, or by anything else — this library depends on no image
library and names none in its API. Paths are kept exactly as the file writes
them, since Relion resolves them against a project directory that the file
does not state. The model stays relational, tables and the relations between
them, and the convenience of a flat per-row view with the optics joined in is
served on top of it, with the group kept so that writing can split it again.

## The canonical representation

Apache Arrow is the canonical in-memory form: `arrow-rs` on the Rust side,
the C Data Interface across the boundary. pandas and polars are both built on
Arrow, so one representation serves both without a second copy and without
either becoming a hard dependency — they are extras, imported only where a
`to_pandas()` / `to_polars()` call actually asks for them.

A reader never infers a type. No number is guessed, no date is recognised,
nothing is read out of the look of a token: typing is the schema's job and
conversion is the convention's job, and a reader that types on its own takes
a decision away from the layer allowed to take it. For STAR and XMD, which
state no types, that means every value arrives as `Utf8` and leaves as
`Utf8` until a convention says otherwise. A format that does state its
types — SQLite, HDF5 — is reported as it declares them, which is not
inference but transcription.

`pyo3-arrow` returns an `arro3` object rather than a `pyarrow` one. arro3 is
not a dependency and must not become one: the object is consumed through the
Arrow protocol methods it exposes, which is what `_to_pyarrow_table` in
`conventions/star.py` does. Any new Rust entry point returning Arrow goes
through that same function.

## The schema layer

The schema defines the canonical column structure and knows nothing about any
file format. A `ColumnDescriptor` is one canonical column — name, Arrow type,
and a default whose absence means the column is required. A `SchemaTrait` is
a reusable group of related columns, `EulerAngles` or `CartesianPosition`,
and exists only so that tables can be composed out of them; it flattens into
the table and has no identity at run time. A `TableSchema` is one table's full
column set, and a `Schema` is one or more tables, which is what a multi-block
Relion file needs.

Composition deduplicates: the same name declared identically by two traits
is the same declaration and collapses, and the same name declared two
different ways is an error at construction. Failing there rather than at read
time is the point — a contradictory schema is a programming mistake, not a
data problem.

Validation is strict in the other direction too. An unknown column raises; it
is never passed through quietly.

### In code

Written, in `python/rexlib_metadata/schema.py`.

```python
@dataclass(frozen=True)
class ColumnDescriptor:
    name: str
    dtype: pa.DataType
    unit: str | None = None
    required: bool = False
    default: Any = None
```

A column is optional unless it says otherwise, which is the common case:
`docs/canonical.md` requires almost nothing, since a file from picking has no
pose and one from classification has no class. Required and defaulted at once
is a contradiction and raises — a default is what makes a column optional.
The unit sits here rather than in the name, so that a conversion can read it.

`SchemaTrait` is a named, reusable group of related columns — `EulerAngles`,
`CartesianPosition`. It is a composition tool only and flattens into the
table.

`TableSchema` is a table's full column set, composed from traits and loose
columns in the order given:

- the same name declared identically twice → keep the first, silently
- the same name declared two different ways → raise at construction, naming
  the column and both declarations

The second rule covers every field, not the type alone. Two traits that
disagree about a column's unit, or about whether it is required, disagree
about what the column *is*, and the composer is the one who has to decide.

`Schema` is one or more `TableSchema`, reached by name, and a name may not
repeat. A Relion 4 file with `data_particles` and `data_optics` produces a
`Schema` with two tables.

## The convention layer

A convention maps file columns onto canonical columns. Reading and writing
are separate pipelines — decided on 2026-07-03 — and the separation is total:
separate ABCs, separate registration, separate lists inside a bundle.

Two reasons, and both matter. Writing a reader must not oblige anyone to
write the writer too, then or ever. And the mapping is genuinely not one to
one: a canonical column may have several possible origins in Relion while
there is exactly one place we would write it back to, so a single reversible
object would have to lie about one direction or the other.

A `ReadConvention` declares the file columns it consumes and the canonical
columns it produces, answers `matches()` for a raw schema, and `load()`s. A
`WriteConvention` declares the canonical columns it consumes and the file
columns it produces, and `store()`s. A `ConventionBundle` groups all the
conventions of one format — Relion4, Relion3, Xmipp — under a name.

Matching is by column presence, never by the name of the raw table. A raw
`data_particles` block becomes the canonical `particles` table because a
convention recognised its columns, not because a string matched. Table names
are the format's to choose and often the user's to mistype; the columns are
what can actually be relied on.

Two conventions of one bundle may not produce the same canonical column: that
is an ambiguity inside a unit meant to be coherent, and it is rejected when
the bundle is registered. Across bundles the conflict is legitimate and
priority resolves it — bundles are ordered, the first to produce a canonical
column owns it, and later bundles cannot overwrite what an earlier one
produced. Inside a bundle, every matching convention that adds something not
yet covered applies.

Required canonical columns that no convention produced are an error at the
end of the read, not a column of nulls.

### In code

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
    name: str                                 # "relion4"
    read_conventions: tuple[ReadConvention, ...]
    write_conventions: tuple[WriteConvention, ...]
```

Written, in `python/rexlib_metadata/convention.py`, along with `RawSchema`,
which is a raw table's name and column names and answers `has()` for the
columns a `matches()` is looking for.

A bundle validates itself when it is built, rather than when it is
registered: it is immutable, so that is the first and last moment anything
could be wrong, and the registry has nothing left to check. Three ways to
be wrong:

- two `ReadConvention`s declaring the same canonical column
- two `WriteConvention`s declaring the same file column, which the design
  did not mention and is the same ambiguity seen from the other side
- a convention declaring no `target_columns` at all, which nothing would
  ever ask for

Each raises naming the bundle, the column and both conventions.

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

## The registry, detection and injection

`MetadataRegistry` maps an extension to a reader and, from Phase 2, to an
ordered list of convention bundles. `global_registry` is the default
instance, built at import time with what ships in the box; a local instance
is how a test stays isolated from it.

Detection is a heuristic with an override, always in that order. A `.star`
gives the STAR reader and Relion conventions, a `.xmd` gives the same reader
with Xmipp conventions, and where the extension is not enough the file's
content decides. Every one of those decisions can be overridden at the call
site, and none of them may be the only way to reach a behaviour. Dependency
inversion is the requirement this library exists to satisfy: readers,
writers, conventions and columns all have to be injectable from the user's
side, so that a client can teach the library a format it has never heard of
without changing a line in here.

## Laziness, projection and forwarding

`rm.read()` returns a `ReadResult` and does no row I/O. Materialisation
happens in `to_pandas()` / `to_polars()`, and a `ReadResult` holds no open
file handle once the call that created it has returned: handles exist only
for the duration of actual I/O. A reader that keeps one open breaks every
caller that reads more files than the platform has descriptors.

`columns=` reads what it says and nothing else. Reading two columns of
forty, changing one and writing the file back still has to leave the other
thirty-eight exactly as they were, and the way that works is that the write
re-reads the source and substitutes as it goes, a chunk at a time. Holding
all forty in memory on the chance that a write may come charges the whole
file to every caller who only ever reads, and makes a file larger than RAM
impossible.

What follows from re-reading: the source has to still be there when the
write happens, the rows have to correspond one to one — a `updates` frame of
a different length is an error, because a filtered row forwards from nothing
in particular — and a write over the source goes through a temporary file in
the destination directory, renamed at the end. The destination directory
rather than the system temp one: a rename is atomic only within a
filesystem.

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

Implementation order, settled 2026-10-18: Relion 4 and 5 STAR first and
properly, then Xmipp3 XMD, then cryoSPARC, and the stored formats — SQLite,
PostgreSQL, HDF5 — after that, one at a time. What the early formats owe the
later ones is an architecture that takes them without being rearranged.

| Extension | Reader | Conventions |
|---|---|---|
| `.star` | `StarReader` | Relion 4/5, Relion 3 |
| `.xmd` | `StarReader` | Xmipp3 |
| `.cs` | `CryosparcReader` | cryoSPARC |
| `.db`, `.sqlite` | `SqliteReader` | — |
| `.h5`, `.hdf5` | `Hdf5Reader` | — |

XMD is STAR with different column names, which is exactly the split the
convention layer exists for: one reader, two bundles.

cryoSPARC is not. A `.cs` file is a NumPy structured array on disk, so it
needs a reader of its own, and it is the format that makes the M:N relation
real rather than theoretical: its `alignments3D/pose` is one column holding a
rotation vector that feeds three canonical angles. That is a good reason to
reach it early — the convention layer is only proven once something bends it.

The name of the library is not settled. `vitrio-metadata` is the other
candidate, and the decision is taken before the first PyPI release, which is
also the last moment it is free.

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

**The rotation convention.** Proposed in `docs/canonical.md`: ZYZ intrinsic,
in degrees, taking the reference frame into the particle's. What remains is
not the choice but the proof — the sign of each angle and the direction the
rotation maps are stated there from documentation rather than from a file,
and a round trip through a real Relion file and a real cryoSPARC one is what
settles them. The same goes for whether a shift is added or subtracted.

**Table relations.** The optics group is the case that exists today, and
joining it into a flat view is decided. What is not decided is how a relation
between two canonical tables is declared, so that the join is data rather
than a special case written into the Relion bundle. `docs/canonical.md` names
the four tables; what joins them is still prose.

## References

- [starfile-rs](https://github.com/hanjinliu/starfile-rs) — the reference
  implementation the STAR reader was compared against.
- [starfile](https://github.com/teamtomo/starfile) — the Python prior art.
- Relion 3.1+ splits optics into their own data block, which is the source of
  the multi-block requirement.
