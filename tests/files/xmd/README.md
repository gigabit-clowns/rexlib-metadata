# XMD fixtures

From [I2PC/testDataSym](https://github.com/I2PC/testDataSym) at `83a11ad`,
Apache License 2.0 in `LICENSE`. Written by Xmipp (each opens with
`# XMIPP_STAR_1 *`), trimmed to the first 10 of 400 rows, otherwise unchanged.
Xmipp writes an unnamed block as `noname`, which becomes the raw table's name.
`tests/python/test_xmipp.py` asserts what both produce.

| File | Source | Tests |
|---|---|---|
| `c3_stk.xmd` | `C/C3/c3_stk.xmd` | C3 phantom projections: `_image`, then angles and shifts |
| `i222.xmd` | `I/i222/i222.xmd` | The same columns in alphabetical order |

Neither carries micrograph, coordinates, CTF or pixel size, so those
conventions and `_shiftX`/`_shiftY` (pixels) wait for a file that does.
