# What the formats demand

Four formats were put on the table, with real files behind them, and the ask
was not to read them all but to be sure the architecture would let us. This
is what each one asks for, taken from its actual bytes rather than from its
documentation, and what in this library already answers and what does not.

The files are EMPIAR depositions, listed under
[the fixtures](#fixtures-from-these-files) at the end. Only the first few
kilobytes of each were read: in every one of these formats the schema is at
the top.

## STAR, and XMD behind it

Named blocks, and inside a block either a `loop_` with a column per `_name`
and a row per line, or a run of `_name value` tags which is a table of one
row. Values are text, with no type anywhere. Built, `src/star/`.

A tag carries exactly one value and a block does not mix tags with a loop.
Neither is in the standard; both are what the real files
in `tests/files/star/` do, and anything else is an error naming the line.

## The CSV that is not a CSV

`final.csv`, a cryoSPARC export, opens like this:

```
_table,images
_header
uid,split,ctf_params.akv,ctf_params.angast_deg,ctf_params.angast_rad,…
_dtypes
int,string,float,float,float,float,float,…
```

Then the rows, comma separated. It is **STAR's shape with commas**: a named
block, a header of column names, rows after it. Two things it has that STAR
does not — a `_dtypes` line that **declares the type of every column**, and
nesting spelled with dots.

What it asks for: a reader whose state machine is the one STAR already has,
with a different lexer. That change is done — the machine lives in
`src/text/parser.rs` and takes the lexer as an argument — so this format is
now a lexer away rather than a parser away.

It is also the first format to arrive with its types stated, which is the
case the invariant was written for: a reader never infers a type, but it
transcribes the ones a format declares.

## `.par`, FREALIGN and cisTEM

```
C           PSI   THETA     PHI       SHX       SHY     MAG  FILM      DF1 …
      1  133.28   21.36  -68.87     -2.29     -5.08   38168     1  15301.1 …
```

One comment line naming the columns, then fixed-width numeric rows and
nothing else: no block, no table name, no types. 18 MB of it in the file we
looked at.

What it asks for: parsing by position rather than by separator, since
fixed-width columns in the wild do run into each other, and a decision about
`RawSchema.table_name` — this file *is* the table, and the convention layer
matches on columns rather than names, so the name can be anything as long as
it is the same anything every time.

## `.cs`, cryoSPARC

A NumPy structured array on disk: the `.npy` header, then rows. The one we
read declares **85 fields** over 3152 rows, and it is the format that bends
the design hardest:

| Field | dtype | What it means here |
|---|---|---|
| `blob/path` | `\|S36` | a path as fixed-width **bytes**, to decode and strip |
| `location/micrograph_path` | `\|S137` | the same, wider |
| `blob/shape` | `<u4 [(2,)]` | a **two-vector** in one field |
| `alignments3D/pose` | `<f4 [(3,)]` | the rotation, as an axis-angle **three-vector** |
| `alignments3D/shift` | `<f4 [(2,)]` | shifts, in pixels |
| `ctf/tetra_A` | `<f4 [(4,)]` | a four-vector |
| `ctf/df_angle_rad` | `<f4` | an angle, in **radians** |
| `ctf/phase_shift_rad` | `<f4` | likewise |
| `blob/psize_A` | `<f4` | the pixel size, **per row** |

What it asks for: a reader that maps NumPy's dtypes onto Arrow, including
`fixed_size_list` for the subarrays and bytes-to-string for the `S` fields.
Nothing in the core changes — `ColumnDescriptor.dtype` is a `pa.DataType` and
can hold a `fixed_size_list` as readily as a `float64`.

And it settles two arguments that were theoretical until the file arrived:

- **M:N is real.** `alignments3D/pose` is one column that produces three
  canonical angles. The read convention that owns it declares one source and
  three targets, which is exactly the shape `ReadConvention` already has.
- **A null has no spelling.** STAR separates values by whitespace, so an
  absent value is written as `""` and reads back as an empty string, not as a
  null. The canonical form's "missing is null" survives a read and does not
  survive a write to a text format, which is the format's limit rather than
  a decision.
- **Units are not decoration.** Radians where we chose degrees, pixels where
  we chose Ångström, and in the CSV both `angast_deg` *and* `angast_rad` as
  separate columns. The unit belongs on the column, as `ColumnDescriptor`
  carries it, and the conversion belongs in the convention that reads it.
  `.cs` is also the easy case for the optics join, since the pixel size is on
  every row rather than in another table.

## What holds, and what has to change

Holds, and the files confirm rather than merely allow it:

- A format is a reader plus a bundle. None of these four touches
  `schema.py`, `convention.py` or `engine.py`.
- A reader never infers a type. STAR and `.par` state none and arrive as
  text; the CSV and `.cs` state theirs and are transcribed.
- `RawSchema` as a table name and column names works for all four, since
  every one of them names its columns somewhere.
- Matching by column presence rather than by table name, which is what lets
  a `.par` with no table name be read at all.

- The state machine takes its tokens from any lexer, so a block-shaped
  delimited file is a lexer rather than a second parser. Done, and the second
  lexer written to prove it found a bug while doing so.

Has to change, in this order:

1. **Reader and bundle have to be choosable at the call site.** `.csv` says
   nothing about who wrote it, and neither will `.db` or `.h5`: the extension
   cannot pick a dialect for a generic container. The design has always said
   every heuristic can be overridden, and this is the format that makes the
   override compulsory rather than polite. It needs named arguments on
   `read`, not the `**kwargs` that were just removed for swallowing mistakes
   in silence. Done: `reader=` and `bundle=` on `read`, `writer=` and
   `bundle=` on `write`.
2. **A NumPy-dtype-to-Arrow mapping**, wherever the `.cs` reader lives.
3. **A rule for a format that has no table name**, which `.par` is the first
   of and SQLite will be the opposite of.

## Fixtures from these files

- `.cs`: `empiar/13345/data/h41_gs/rotated/trna_a-pe_EMD-56849/J114_particles_exported.cs`,
  2 MB, 85 fields, 3152 rows.
- `.par`: `empiar/10076/data/Frealign9Parameter_0_r1.par`, 18 MB.
- `.csv`: `empiar/10255/data/final.csv`, 54 MB.

All three from `ftp.ebi.ac.uk/empiar/world_availability/`. None belongs in
the repository at that size: each has to be trimmed to a handful of rows with
its header intact, which for the `.cs` means rewriting the shape in its
`.npy` header, and each needs its provenance recorded beside it in
`tests/files/`.

[teamtomo](https://teamtomo.org/site/io_packages/) is the other source worth
raiding: a package per format, tests included, and assets we could borrow
with attribution rather than invent. Their formats also bring the shape
[#41](https://github.com/gigabit-clowns/rexlib-metadata/issues/41) settled
for STAR: mdoc's blocks of `key = value` pairs with no loop, which here are
a table of one row.
