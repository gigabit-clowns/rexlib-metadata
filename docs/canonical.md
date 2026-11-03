# The canonical form

The columns a file is read into, whatever wrote it. Code:
`python/rexlib_metadata/canonical.py`. A value means the same in every row of
every file: the unit is fixed and declared on the column, not in its name, and
no name carries a dialect (`rln`, `cs`, `xmipp`).

## Conventions

| What | Canonical |
|---|---|
| Angles | degrees |
| Pose | `transform`, below |
| Shifts | Ångström |
| Coordinates | pixels of the micrograph they refer to |
| Image reference | `image_path` as written, plus `image_index` zero-based; a bare path is index zero |
| Paths | kept as written, never resolved |
| Missing | null, an empty value of a typed column included; in a pose, no turn and no shift |
| Unparseable value | an error naming the file and the table |
| Format sentinels (Xmipp's `-999`) | translated by that format's conventions, never by the core |
| Continuous values | `float64`; the transform `float32` |

## The pose

`transform` is the 3x4 matrix `[R | t]`, row by row, taking a point of the
particle's frame into the reference's: Scipion's projection alignment, with
`t` in Ångström rather than pixels. `R` is the transpose of the matrix `A`
Relion builds from its ZYZ angles, and `t = R · origin`. A 2D alignment is a
turn about z with no z shift. pandas holds it as `pd.ArrowDtype`, not as
one object per row. `rexlib_metadata.pose` converts it:

| Function | Gives |
|---|---|
| `matrices(column)` | `(n, 3, 4)` doubles, from Arrow, pandas or polars |
| `euler(column)` | Relion's rot, tilt, psi in degrees |
| `relion(column)` | Relion's `A` and origin in Å |
| `transforms(a, origin)`, `euler_matrix(rot, tilt, psi)` | the column, from Relion's terms |

A write to Euler angles refuses a transform that scales, shears or mirrors.
Angles and origins are written at the transform's single precision.

> **Unverified.** cryoSPARC's rotation is taken as Relion's `A`; a real
> cryoSPARC and Relion file of the same particles settles it.

## Tables

`particles` and `micrographs` point at `optics` through
`Relation(..., "optics", "optics_group")`.
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
| `transform` | `fixed_size_list<float32>[12]` | `A` (of `t`) | |
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

### `micrographs`

| Column | Type | Unit | Required |
|---|---|---|---|
| `micrograph_path` | `string` | | yes |
| `defocus_u`, `defocus_v` | `float64` | `A` | |
| `defocus_angle` | `float64` | `degrees` | |
| `ctf_max_resolution` | `float64` | `A` | |
| `optics_group` | `int32` | | |

A column is added when a convention produces it. Names reserved for then:

- `particles`: `defocus_u`, `defocus_v` (Å), `defocus_angle`, `phase_shift`
  (degrees), `ctf_bfactor` (Å²), `ctf_scale`, `ctf_figure_of_merit`,
  `class_id`, `random_subset`, `group_id`, `norm_correction`,
  `log_likelihood`, `max_probability`.
- `optics`: `optics_group_name`, `micrograph_pixel_size` (Å/px),
  `ctf_premultiplied`, `beam_tilt_x`, `beam_tilt_y` (mrad).
- `coordinates`: `micrograph_path`, `coord_x`, `coord_y` required;
  `class_id`, `figure_of_merit`, `optics_group`.

Out of scope until a real file asks: helical parameters, tomography columns
beyond `coord_z` and a z shift, priors, Zernike coefficients, the MTF file.

## Relion 4 and 5

The mappings that are not a rename (`conventions/relion.py`).

| Canonical | Relion | Note |
|---|---|---|
| `image_path` + `image_index` | `_rlnImageName` | `index@path`, one-based; written back zero-padded to six digits |
| `transform` | `_rlnAngleRot`, `…Tilt`, `…Psi`, `_rlnOriginXAngst`, `…YAngst`, `…ZAngst` | any may be missing; all six written |
| `optics` columns | `data_optics`, row named by `_rlnOpticsGroup` | joined per row on request |
| `micrographs` | a block naming `_rlnMicrographName` and no `_rlnImageName` | a particles block never fills it |

## Relion 3.0

Read only (`conventions/relion3.py`); written back as Relion 4. It applies
where a block has no `_rlnOpticsGroup`.

| Canonical | Relion 3.0 | Note |
|---|---|---|
| `optics_group` | `_rlnVoltage`, `_rlnSphericalAberration`, `_rlnAmplitudeContrast`, `_rlnMagnification`, `_rlnDetectorPixelSize` | each distinct setting a group, numbered from 1 as first held |
| `pixel_size` | `_rlnDetectorPixelSize` (µm), `_rlnMagnification` | `detector · 10⁴ / magnification` |
| `transform` | the angles, `_rlnOriginX`, `…Y`, `…Z` (px) | origin times the row's pixel size |
| `optics` | the particles' or micrographs' own rows | one row per group |

## cryoSPARC

Read only (`conventions/cryosparc.py`).

| Canonical | cryoSPARC | Note |
|---|---|---|
| `image_path`, `image_index` | `blob/path`, `blob/idx` | zero-based; a leading `>` (project-relative) dropped |
| `micrograph_path` | `location/micrograph_path` | the same |
| `coord_x`, `coord_y` | `location/center_x_frac`, `…_y_frac`, `location/micrograph_shape` | fraction times columns, rows |
| `transform` | `alignments3D/pose`, `…/shift`, `…/psize_A` | rotation vector (rad) → `A`; shift in pixels times that pixel size |
| `optics_group` | `ctf/exp_group_id` | plus one |
| `voltage`, `spherical_aberration`, `amplitude_contrast` | `ctf/accel_kv`, `ctf/cs_mm`, `ctf/amp_contrast` | |
| `pixel_size`, `image_size`, `image_dimensionality` | `blob/psize_A`, `blob/shape` | |
| `optics` | the particles' own rows | one row per group |

A single-precision field is read as its shortest decimal (2.7, not
2.700000047683716).

## Xmipp

`conventions/xmipp.py` reads and writes `_image` (`index@path`, one-based, as
Relion) and `_angleRot`, `_angleTilt`, `_anglePsi` (Relion's angles) as the
transform. `_shiftX`, `_shiftY` are pixels with no pixel size in the file:
not read, so the transform has no shift, and not written.

## Open

- cryoSPARC's rotation, above.
- Xmipp's shifts, which need a pixel size the file does not hold.
- Whether `coordinates` and `particles` are one table or two.
