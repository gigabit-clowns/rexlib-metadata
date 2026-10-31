# XMD files Xmipp wrote

Both come from [I2PC/testDataSym](https://github.com/I2PC/testDataSym) at
`83a11ad`, Xmipp's test data for symmetry, under the Apache License 2.0 kept
beside them in `LICENSE`. Xmipp wrote them: each opens with the
`# XMIPP_STAR_1 *` line its writer puts first.

| File | From | What it is here for |
|---|---|---|
| `c3_stk.xmd` | `C/C3/c3_stk.xmd` | Projections of a C3 phantom: `_image` first, then the angles and shifts |
| `i222.xmd` | `I/i222/i222.xmd` | The same columns in alphabetical order, which is how some Xmipp programs write them |

Each is trimmed to its first 10 of 400 rows. Nothing else was changed.

## What they showed

- Xmipp names a block it has no name for `noname`, written out, where STAR
  leaves the name empty. The raw table is called `noname`.
- `_shiftX` and `_shiftY` are in pixels, and neither file says how large a
  pixel is, so they stay raw until a file that does arrives.
- They carry no micrograph, coordinates or CTF. Those conventions wait for a
  real file holding them.

`tests/python/test_xmipp.py` asserts what both produce.
