# STAR files from somewhere other than us

Files no hand of ours wrote, which is the only kind that can contradict us.
`tests/python/fixtures/` holds the small invented ones that came before this
rule and that cover cases the format allows but no file here happens to
contain.

Eight come from [teamtomo/starfile](https://github.com/teamtomo/starfile),
`tests/data/`, and `relion3.1_subtomo.star` from
[alisterburt/dynamo2m](https://github.com/alisterburt/dynamo2m),
`test_data/relion_star_downgrade/relion3.1.star` at `b5669b5`. Both are under
the same BSD 3-Clause licence, kept beside them in `LICENSE`, copyright 2020
Alister Burt. Two carry a Relion banner and were written by it; the rest were written by
that project to pin its own behaviour — which is still not us agreeing with
ourselves.

| File | Written by | What it is here for |
|---|---|---|
| `rln3.1_data_style.star` | starfile | Three blocks, optics first, and the column index written as a comment after each name |
| `one_loop.star` | starfile | One ordinary loop of 16 rows and 12 columns |
| `postprocess.star` | Relion 3.0.8 | A block of `_name value` tags, then two loops |
| `run_it025_optimiser_3D.star` | Relion 3.1 | An optimiser file: tags all the way down |
| `two_basic_blocks.star` | starfile 0.4.5 | Two blocks of tags and nothing else |
| `loop_single_quote.star` | starfile | Values in single quotes |
| `single_line_middle_of_multiblock.star` | starfile | Two one-row loops, the second behind a comment |
| `empty_loop.star` | starfile | `data_` with no name, a column, and no rows |
| `relion3.1_subtomo.star` | Relion 3.1 | 57 subtomograms of the HIV tutorial, with shifts in Ångström on three axes |

## What they found

Five read at once. The other three were one cause — a block of `_name value`
tags with no `loop_`, which the lexer rejected before the parser saw it — and
two of those three were Relion's own output, which answered whether
[#41](https://github.com/gigabit-clowns/rexlib-metadata/issues/41) was
urgent. It is done, and all eight read.

They also settled two things no amount of reading the standard would have:
no tag in any of these files carries more than one value, and no block mixes
tags with a loop. Both are now errors rather than guesses.

`tests/python/test_real_star_files.py` asserts what each of them produces.
