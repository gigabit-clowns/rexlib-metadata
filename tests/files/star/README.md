# STAR fixtures

Files written by other programs. Hand-written cases no real file contains live
in `tests/python/fixtures/`; `tests/python/test_real_star_files.py` asserts
what each of these produces.

Licence: BSD 3-Clause, copyright 2020 Alister Burt, in `LICENSE`, except
the Relion 3.0 files, from EMPIAR, whose data are CC0.

| File | Source | Written by | Tests |
|---|---|---|---|
| `rln3.1_data_style.star` | [teamtomo/starfile](https://github.com/teamtomo/starfile) `tests/data/` | starfile | Three blocks, optics first, column index as a comment after each name |
| `one_loop.star` | starfile `tests/data/` | starfile | One loop, 16 rows, 12 columns |
| `postprocess.star` | starfile `tests/data/` | Relion 3.0.8 | A block of `_name value` tags, then two loops |
| `run_it025_optimiser_3D.star` | starfile `tests/data/` | Relion 3.1 | Tags only |
| `two_basic_blocks.star` | starfile `tests/data/` | starfile 0.4.5 | Two blocks of tags only |
| `loop_single_quote.star` | starfile `tests/data/` | starfile | Single-quoted values |
| `single_line_middle_of_multiblock.star` | starfile `tests/data/` | starfile | Two one-row loops, the second behind a comment |
| `empty_loop.star` | starfile `tests/data/` | starfile | Unnamed `data_`, one column, no rows |
| `relion3.0_polished.star` | [EMPIAR-11796](https://www.ebi.ac.uk/empiar/EMPIAR-11796/) `data/stack`, `ApoF-T00-Polished.star` (Aiyer et al., apoferritin at tilts); first 10 of 17,000 rows | Relion 3.0.8 | No optics table: microscope and detector on each row, offsets in pixels |
| `relion3.0_micrographs.star` | [EMPIAR-10389](https://www.ebi.ac.uk/empiar/EMPIAR-10389/) `data/alignaver` (Righetto et al., Y. enterocolitica urease); first 10 of 4,312 rows | Relion 3.0-beta-2 | Micrographs with their microscope and detector, no particles |
| `relion3.1_subtomo.star` | [alisterburt/dynamo2m](https://github.com/alisterburt/dynamo2m) `test_data/relion_star_downgrade/relion3.1.star` at `b5669b5` | Relion 3.1 | 57 HIV-tutorial subtomograms, shifts in Ångström on three axes |

None has a tag with more than one value or a block mixing tags with a loop;
both are errors.
