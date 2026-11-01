# Dependencies

| Crate / package | Why |
|---|---|
| `pyo3` | The Rust/Python binding |
| `arrow` (`arrow-rs`) | Arrow on the Rust side |
| `pyo3-arrow` | The C Data Interface bridge to Python |
| `thiserror` | The error enums |
| `tempfile` (dev) | Files for the parser tests |
| `pyarrow` | The Python half of the bridge; the only hard runtime dependency |
| `pandas`, `polars` | Extras, one per output backend |
| `h5py` | The `hdf5` extra, imported only when an HDF5 file is opened |

What is not obvious from the manifests:

- `arrow` and `pyo3-arrow` take `default-features = false`: arrow's
  defaults are unused, and `pyo3-arrow`'s `buffer_protocol` would keep the
  wheel off abi3 before 3.11.
- Never enable arrow's `pyarrow` feature: it conflicts with `pyo3-arrow`.
- `arrow` and `pyo3-arrow` upgrade together, or `lib.rs` stops compiling, so
  `renovate.json` caps `arrow` at the major `pyo3-arrow` holds. `pyo3` is
  left uncapped on purpose: its failing Renovate PR is the signal to raise
  `pyo3-arrow` in the same branch.
- Runtime ranges run from what the code needs (`pyarrow>=16`, the first
  built for NumPy 2) to the newest version CI has passed, which Renovate
  widens. The oldest-extras cell installs each floor.
- A pin split at `python_version == '3.10'` keeps 3.10 on the last release
  that supports it; `renovate.json` caps only that half.
- `h5py` has no 3.15 wheel yet, so the 3.15 cells skip HDF5.
