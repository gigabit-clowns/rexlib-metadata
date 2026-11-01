# The canonical form

The columns a file is read into, whatever wrote it. Code:
`python/rexlib_metadata/canonical.py`. A value means the same in every row of
every file: the unit is fixed and declared on the column, not in its name, and
no name carries a dialect (`rln`, `cs`, `xmipp`).

## Conventions

| What | Canonical |
|---|---|
| Angles | degrees |
| Rotation | ZYZ Euler `angle_rot`, `angle_tilt`, `angle_psi`, intrinsic, reference frame into the particle's |
| Shifts | Ångström |
| Coordinates | pixels of the micrograph they refer to |
| Image reference | `image_path` as written, plus `image_index` zero-based; a bare path is index zero |
| Paths | kept as written, never resolved |
| Missing | null, an empty value of a typed column included |
| Unparseable value | an error naming the file and the table |
| Format sentinels (Xmipp's `-999`) | translated by that format's conventions, never by the core |
| Continuous values | `float64` |

> **Unverified.** The sign of each angle, the direction the rotation maps,
> and whether a shift is added or subtracted are taken from documentation.
> A round trip through a real Relion and a real cryoSPARC file of the same
> particles settles them.

## Tables

`particles` points at `optics` through
`Relation("particles", "optics", "optics_group")`.
`result.joined("particles")` gives each particle its group's columns; a write
to a format without an optics table (XMD) joins them before its conventions
run.

### `particles`

| Column | Type | Unit | Required |
|---|---|---|---|
| `image_path` | `string` | | yes |
| `image_index` | `int64` | | yes |
| `micrograph_path` | `string` | | |
| `coord_x`, `coord_y`, `coord_z` | `float64` | `px` | |
| `angle_rot`, `angle_tilt`, `angle_psi` | `float64` | `degrees` | |
| `shift_x`, `shift_y`, `shift_z` | `float64` | `A` | |
| `ctf_max_resolution` | `float64` | `A` | |
| `optics_group` | `int32` | | |

### `optics`

| Column | Type | Unit | Required |
|---|---|---|---|
| `optics_group` | `int32` | | yes |
| `voltage` | `float64` | `kV` | |
| `spherical_aberration` | `float64` | `mm` | |
| `amplitude_contrast` | `float64` | `fraction` | |
| `pixel_size` | `float64` | `A/px` | |
| `image_size` | `int64` | `px` | |
| `image_dimensionality` | `int32` | | |

A column is added when a convention produces it. Names reserved for then:

- `particles`: `defocus_u`, `defocus_v` (Å), `defocus_angle`, `phase_shift`
  (degrees), `ctf_bfactor` (Å²), `ctf_scale`, `ctf_figure_of_merit`,
  `class_id`, `random_subset`, `group_id`, `norm_correction`,
  `log_likelihood`, `max_probability`.
- `optics`: `optics_group_name`, `micrograph_pixel_size` (Å/px),
  `ctf_premultiplied`, `beam_tilt_x`, `beam_tilt_y` (mrad).
- `coordinates`: `micrograph_path`, `coord_x`, `coord_y` required;
  `class_id`, `figure_of_merit`, `optics_group`.
- `micrographs`: `micrograph_path` required, plus optics and CTF columns per
  micrograph.

Out of scope until a real file asks: helical parameters, tomography columns
beyond `coord_z` and `shift_z`, priors, Zernike coefficients, the MTF file.

## Relion 4 and 5

The mappings that are not a rename (`conventions/relion.py`).

| Canonical | Relion | Note |
|---|---|---|
| `image_path` + `image_index` | `_rlnImageName` | `index@path`, one-based; written back zero-padded to six digits |
| `shift_x`, `shift_y`, `shift_z` | `_rlnOriginXAngst`, `…YAngst`, `…ZAngst` | already Å; 3.0's pixel `_rlnOriginX` is not read |
| `optics` columns | `data_optics`, row named by `_rlnOpticsGroup` | joined per row on request |

## Xmipp

`conventions/xmipp.py` reads and writes `_image` (`index@path`, one-based, as
Relion) and `_angleRot`, `_angleTilt`, `_anglePsi` (the same ZYZ angles).
`_shiftX`, `_shiftY` are pixels with no pixel size in the file, and are not
read.

## Open

- The rotation and shift signs, above.
- Whether `coordinates` and `particles` are one table or two.
