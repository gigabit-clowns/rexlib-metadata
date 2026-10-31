# The canonical form

The columns this library reads a file into, whatever program wrote it, and
the conventions they obey. A proposal: the names and the tables are settled
enough to build Phase 2 on, and two of the conventions carry a question that
only a real file can answer, marked where they appear.

Canonical is not a renaming. If `_rlnAngleRot` became `angle_rot` and nothing
else happened, whoever reads the table would still have to know which program
wrote the row before they could use the number, and the layer would have
earned nothing. So the names are the small part. The part that matters is
that a value means the same thing in every row of every file:

- **Units are fixed, and declared on the column** rather than spelled in its
  name. `shift_x` is in Ångström because it is always in Ångström, and the
  schema says so in a field a program can read.
- **One rotation convention**, which every format converts into.
- **Optics resolved per row**: the caller gets a flat table, while the group
  survives so that writing can split it again.
- **No dialect in a name**: no `rln`, no `cs`, no `xmipp`.

## Conventions

**Angles** are in degrees. Relion, Xmipp and cryoSPARC all report degrees or
convert to them trivially, and radians would only move the conversion to the
other side of every consumer.

**Rotations** are the three ZYZ Euler angles `angle_rot`, `angle_tilt` and
`angle_psi`, intrinsic, describing the rotation that takes the reference
frame into the particle's. ZYZ because Relion and Xmipp already use it, so
the two formats we implement first convert by doing nothing, and because
cryoSPARC's axis-angle vector converts into it exactly.

> **To verify against real files before Phase 2 ships.** The sign of each
> angle and the direction the rotation maps are stated here from the
> documentation, not from a file. A round trip through a real Relion file and
> a real cryoSPARC file, compared against the same particle's orientation in
> both, is what settles it. The repository's own rule applies: a fixture
> comes from the program, not from our reading of the specification.

**Shifts** are in Ångström. Pixels stop meaning anything the moment a stack
is rescaled, and Relion itself moved to Ångström in 3.1 for that reason.
Reading a 3.0 file therefore multiplies by the pixel size, which the optics
group holds — the first place where the convention layer needs a value from
another table, and a good test of whether the engine's shape is right.

> **To verify against real files.** Whether a shift is added or subtracted to
> centre a particle is a sign convention, and the same round trip settles it.

**Coordinates** are in pixels of the micrograph they refer to, not in
Ångström, because what consumes them is a crop out of that micrograph.
`pixel_size` is on the row for anyone who needs to convert.

**An image reference is two columns**: `image_path`, the string exactly as
the file writes it, and `image_index`, **zero-based**. Relion writes
`000001@Extract/job/mic.mrcs` and counts from one; cryoSPARC writes the path
and the index apart and counts from zero. The canonical form splits and
counts from zero because what reads it next indexes an array — and because a
plain string and a plain integer can be handed to `mrcfile`, to vitrio, or to
anything else, which is how this library stays independent of every image
library.

A reference written without an index — a bare path, which the format allows —
reads as index zero and is written back as `000001@path`. The two mean the
same to Relion, and telling them apart would cost the consumer a nullable
index, which is the thing splitting the reference was for.

**Paths are not resolved.** Relion writes them relative to a project
directory the file does not name, so resolving one here would be guessing.
They are kept as written, and a `root` argument may later be offered to
whoever knows the answer.

**Missing is null**, and a value that does not parse is an error naming the
line. A format's sentinels — Xmipp's `-999` and its kin — are translated by
that format's conventions, never by the core.

**Continuous values are `float64`.** The precision is never the bottleneck,
the parse happens once, and a consumer who wants `float32` can cast. If the
memory of a ten-million-particle table ever argues otherwise, the type is
declared per column and can be narrowed one column at a time.

## The tables

Four, composed from one vocabulary. A file brings the ones it has.

### `optics`

What a microscope and a detector were doing. Relion 3.1 and later keep it in
`data_optics`; cryoSPARC and Xmipp repeat it per particle, and the read puts
it back into a table of its own.

Resolving it per row, which the principles above promise, is not done. A read
of a Relion file gives `particles` and `optics` as two tables, joined by
`optics_group` and nothing more: one raw table fills one canonical table, so
the engine will not reach into the optics block while filling the particles,
and the convention that would do it has no way to ask for a second table yet.
That is the join this file has always said was open, now pinned to the rule
that keeps it honest in the meantime.

| Column | Type | Unit | Required |
|---|---|---|---|
| `optics_group` | `int32` | — | yes |
| `optics_group_name` | `string` | — | |
| `voltage` | `float64` | kV | |
| `spherical_aberration` | `float64` | mm | |
| `amplitude_contrast` | `float64` | fraction | |
| `pixel_size` | `float64` | Å/px | |
| `micrograph_pixel_size` | `float64` | Å/px | |
| `image_size` | `int64` | px | |
| `image_dimensionality` | `int32` | — | |
| `ctf_premultiplied` | `bool` | — | |
| `beam_tilt_x`, `beam_tilt_y` | `float64` | mrad | |

### `particles`

| Column | Type | Unit | Required |
|---|---|---|---|
| `image_path` | `string` | — | yes |
| `image_index` | `int64` | — | yes |
| `micrograph_path` | `string` | — | |
| `coord_x`, `coord_y`, `coord_z` | `float64` | px | |
| `angle_rot`, `angle_tilt`, `angle_psi` | `float64` | degrees | |
| `shift_x`, `shift_y`, `shift_z` | `float64` | Å | |
| `defocus_u`, `defocus_v` | `float64` | Å | |
| `defocus_angle` | `float64` | degrees | |
| `phase_shift` | `float64` | degrees | |
| `ctf_bfactor` | `float64` | Å² | |
| `ctf_scale` | `float64` | — | |
| `ctf_max_resolution` | `float64` | Å | |
| `ctf_figure_of_merit` | `float64` | — | |
| `class_id` | `int32` | — | |
| `random_subset` | `int32` | — | |
| `group_id` | `int32` | — | |
| `norm_correction` | `float64` | — | |
| `log_likelihood` | `float64` | — | |
| `max_probability` | `float64` | — | |
| `optics_group` | `int32` | — | |

Only the image reference is required, and deliberately so: a file from
picking has coordinates and no pose, one from classification has a pose and
no class yet, and a schema that demanded either would refuse to read half the
files in a project.

### `coordinates`

Picking, before extraction. `micrograph_path`, `coord_x` and `coord_y` are
required; `class_id`, `figure_of_merit` and `optics_group` may be there.

### `micrographs`

`micrograph_path` required, and whatever of the optics and CTF vocabulary the
file carries, per micrograph rather than per particle.

## Reading Relion

The mappings that are not a rename, which are the ones worth writing down.

| Canonical | Relion 4 and 5 | Note |
|---|---|---|
| `image_path` + `image_index` | `_rlnImageName` | `index@path`, one-based, split and rebased; written back zero-padded to six digits, which is what Relion writes |
| `shift_x`, `shift_y` | `_rlnOriginXAngst`, `_rlnOriginYAngst` | already Å |
| `shift_x`, `shift_y` | `_rlnOriginX`, `_rlnOriginY` (3.0 and before) | pixels; × `pixel_size` from the optics group |
| `pixel_size` | `_rlnImagePixelSize` | in `data_optics` |
| everything in `optics` | the row of `data_optics` the particle's `_rlnOpticsGroup` points at | joined per row |

cryoSPARC's `alignments3D/pose` is the other shape worth naming: one column
holding a rotation vector that produces three canonical ones, which is the
M:N relation the convention layer exists for and the reason to reach that
format earlier rather than later.

## Not in this version

Helical parameters, tilt-series and tomography columns beyond `coord_z` and
`shift_z`, per-particle priors, Zernike aberration coefficients, and the MTF
file name. Each is a group of columns that one workflow needs and most do
not; they go in when a real file asks and a test can prove the mapping.

## In code

`python/rexlib_metadata/canonical.py` carries the traits and the two tables
that have conventions behind them today — the image reference, the position,
the angles, the shifts, the CTF resolution, the optics key, the microscope
and the sampling. It grows a column when a convention can produce one, not before: a
catalogue that lists what nothing reads is a promise rather than a schema.

## Open

- **The rotation and shift conventions**, as marked above: the sign and the
  direction, settled by a round trip through real files.
- **How a relation between two tables is declared**, so that joining optics
  into particles is data the schema holds rather than a special case written
  into the Relion bundle.
- **Whether `coordinates` and `particles` are two tables or one**, which a
  real picking file and a real extraction file next to each other will make
  obvious.
