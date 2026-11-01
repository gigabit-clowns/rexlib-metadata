# What the formats demand

Read off the headers of real EMPIAR files ([below](#fixtures-from-these-files)).

## STAR, and XMD behind it

Named blocks; in each, either a `loop_` (a column per `_name`, a row per
line) or `_name value` tags (a table of one row). Values are untyped text.
Built, `src/star/`.

A tag carries exactly one value and a block does not mix tags with a loop:
not in the standard, but what every file in `tests/files/star/` does.
Anything else is an error naming the line. A null is written `""`; a typed
column reads it back as null, a text column cannot tell it from an empty
string.

## cryoSPARC `.csv`

```
_table,images
_header
uid,split,ctf_params.akv,ctf_params.angast_deg,ctf_params.angast_rad,…
_dtypes
int,string,float,float,float,float,float,…
```

STAR's shape with commas, plus a `_dtypes` line typing every column and
nesting spelled with dots. Needs a comma lexer for the state machine in
`src/text/parser.rs`, which takes the lexer as an argument; the declared
types are transcribed, never inferred. Not read yet.

## FREALIGN / cisTEM `.par`

```
C           PSI   THETA     PHI       SHX       SHY     MAG  FILM      DF1 …
      1  133.28   21.36  -68.87     -2.29     -5.08   38168     1  15301.1 …
```

One comment line naming the columns, then fixed-width numeric rows: no block,
no table name, no types. Needs parsing by position, since fixed-width columns
run into each other. Its table name is `""`, as STAR's bare `data_`. Not read
yet.

## cryoSPARC `.cs`

A NumPy structured array: the `.npy` header, then rows (85 fields in the
fixture).

| Field | dtype | Meaning |
|---|---|---|
| `blob/path` | `\|S36` | path as fixed-width bytes, to decode and strip |
| `location/micrograph_path` | `\|S137` | the same |
| `blob/shape` | `<u4 [(2,)]` | two-vector |
| `alignments3D/pose` | `<f4 [(3,)]` | rotation as an axis-angle three-vector |
| `alignments3D/shift` | `<f4 [(2,)]` | shifts, in pixels |
| `ctf/tetra_A` | `<f4 [(4,)]` | four-vector |
| `ctf/df_angle_rad` | `<f4` | angle in radians |
| `ctf/phase_shift_rad` | `<f4` | likewise |
| `blob/psize_A` | `<f4` | pixel size, per row |

Needs a NumPy-dtype-to-Arrow mapping: `fixed_size_list` for subarrays,
bytes to string for `S` fields. `ColumnDescriptor.dtype` already holds either.
Not read yet.

What it shows:

- **M:N.** `alignments3D/pose` is one source column for three canonical
  angles, which `ReadConvention` already allows.
- **Units.** Radians and pixels where the canonical form has degrees and Å;
  the CSV carries `angast_deg` and `angast_rad` both. The convention that
  reads a column converts it.
- **Optics.** The pixel size is on every row, so no join is needed.

## What the architecture takes

- A format is a reader plus a bundle; none of these touches `schema.py`,
  `convention.py` or `engine.py`.
- A reader never infers a type: STAR and `.par` arrive as text, CSV and `.cs`
  as declared.
- Conventions match on column presence, not table name.
- An extension does not name a dialect (`.csv`, `.db`, `.h5`), so `read`
  takes `reader=` and `bundle=`, and `write` takes `writer=` and `bundle=`.

## Fixtures from these files

From `ftp.ebi.ac.uk/empiar/world_availability/`, trimmed to ten rows with
headers intact; origin and trimming in `tests/files/README.md`.

| Format | EMPIAR file | Original |
|---|---|---|
| `.cs` | `13345/data/h41_gs/rotated/trna_a-pe_EMD-56849/J114_particles_exported.cs` | 2 MB, 85 fields, 3152 rows |
| `.par` | `10076/data/Frealign9Parameter_0_r1.par` | 18 MB |
| `.csv` | `10255/data/final.csv` | 54 MB |

[teamtomo](https://teamtomo.org/site/io_packages/) has a package per format
with tests and assets to borrow with attribution. Its mdoc is blocks of
`key = value` pairs with no loop: a table of one row, as STAR's tags.
