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
| `numpy` | The `cryosparc` extra, imported only when a `.cs` is opened |
| `pdoc` (`docs` group) | The Python reference, templated in `docs/pdoc/` |

What is not obvious from the manifests:

- `arrow` and `pyo3-arrow` take `default-features = false`: arrow's
  defaults are unused, and `pyo3-arrow`'s `buffer_protocol` would keep the
  wheel off abi3 before 3.11.
- Never enable arrow's `pyarrow` feature: it conflicts with `pyo3-arrow`.
- `arrow`, `pyo3` and `pyo3-arrow` upgrade together, or `lib.rs` stops
  compiling, so Renovate raises them in one pull request. It fails while
  `arrow` or `pyo3` is a major ahead of `pyo3-arrow`, until a `pyo3-arrow`
  release catches up.
- Every range, extras included, runs from what the code needs (`pyarrow>=16`, the first
  built for NumPy 2) to the newest version CI has passed, which Renovate
  widens. The oldest-extras cell installs each floor.
- A pin split by `python_version` keeps an older Python on the last release
  that supports it; `renovate.json` caps only the older halves.
