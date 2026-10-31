# Files from EMPIAR

Three formats no reader here reads yet, each trimmed from a real deposition
so that the reader written for it meets the file before it meets us.
`star/` has a README of its own.

All three come from `ftp.ebi.ac.uk/empiar/world_availability/`, fetched on
2026-10-31. EMPIAR releases everything it archives under
[CC0](https://creativecommons.org/publicdomain/zero/1.0/): "All data
archived in EMPIAR can be re-used freely without any conditions or
restrictions".

| File | From | Trimmed to |
|---|---|---|
| `par/Frealign9Parameter_0_r1.par` | EMPIAR-10076, `data/Frealign9Parameter_0_r1.par` | The header line and the first 10 of 131 899 rows |
| `csv/final.csv` | EMPIAR-10255, `data/final.csv` | The seven lines before the rows, two of them empty, the first 10 of 157 204 rows, and the two empty lines the file ends with |
| `cs/J114_particles_exported.cs` | EMPIAR-13345, `data/h41_gs/rotated/trna_a-pe_EMD-56849/J114_particles_exported.cs` | The first 10 of 3152 rows, saved again with `numpy.save`, so the `.npy` header states the new shape |

Nothing else was changed: the rows kept are the file's first rows, byte for
byte in the two text files and value for value in the `.cs`.

## What trimming them showed

- The `.par` is fixed width, 136 characters a row, and every row of the
  full file splits into its 16 fields on whitespace. Nothing runs into its
  neighbour here, which does not mean nothing ever does.
- The CSV opens with two empty lines before `_table,images` and ends with
  two after the last row. A reader that expects the block to start on the
  first line fails on a file cryoSPARC wrote.
- Every `blob/path` in the `.cs` starts with `>`, as
  `>J114/restack/batch_0_restacked.mrc`. That is cryoSPARC's way of marking
  a path as relative to its project, and a convention has to know it.

`tests/python/test_fixtures.py` pins the shape of each file.
