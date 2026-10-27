# Dependencies

What this library depends on, and the three constraints that are not
obvious from reading `Cargo.toml` and `pyproject.toml`: a feature that must
stay off, two crates that move as one, and the pins that are split in half.

| Crate / package | Why |
|---|---|
| `pyo3` | The Rust/Python binding |
| `arrow` (`arrow-rs`) | Arrow on the Rust side |
| `pyo3-arrow` | The C Data Interface bridge to Python |
| `thiserror` | The error enums |
| `tempfile` (dev) | Files for the parser tests |
| `pyarrow` (Python) | The Python half of the bridge; the only hard runtime dependency |
| `pandas`, `polars` | Extras, one per output backend |

`arrow` is taken with `default-features = false`. Its defaults are `csv`,
`ipc` and `json`, none of which this crate imports and none of which
`pyo3-arrow` needs — it depends on the sub-crates directly. Turning them off
drops fifteen crates from the lockfile, which is wheel size and build time
for one line.

Do not enable arrow's `pyarrow` feature. It pulls in `arrow-pyarrow`, which
pins an older pyo3 and conflicts with `pyo3-arrow`; `pyo3-arrow` is the only
bridge needed, and the two together do not build.

`arrow` and `pyo3-arrow` are one upgrade, not two. `pyo3-arrow` exports no
arrow of its own, so the `RecordBatch` the parser builds and the one
`PyRecordBatch::new` accepts are the same type only while both come from the
same major; two majors in the graph and `lib.rs` stops compiling with a type
mismatch on a `RecordBatch` that looks identical in the message. `arrow` is
therefore capped in `renovate.json` at the major `pyo3-arrow` holds. The cap
stays; what moves is its bound, and it moves in the same pull request that
raises `pyo3-arrow`, never on its own.

`pyo3` is the same kind of pair and is deliberately not capped. `pyo3-arrow`
pins a `pyo3` major too, so raising `pyo3` alone breaks the build as surely
as raising `arrow` alone does — which is what a Renovate pull request for
`pyo3` is for. It fails, and the failure is the signal to raise `pyo3-arrow`
in that same branch rather than merge the one half. Capping `pyo3` too would
buy silence instead of that signal.

Two pins in `pyproject.toml` are split in half behind a PEP 508 marker, and
both for the same reason: pyarrow raised its floor to 3.11 in 26.0.0 and
pandas in 3.0.0, so the 3.10 cell has to stay behind while everything from
3.11 up moves. Renovate does not see the marker, so `renovate.json` tells the
two halves apart with `matchCurrentVersion` and caps only the old one. The
`>=` ranges of the `pandas` and `polars` extras are excluded from updates
entirely: widening them declares wider support, which is a decision for a
person to take.

The 3.10 cell is also the one that cannot have the newest of anything. When
a dependency raises its floor to 3.11, the honest move is a third split, not
a quiet upgrade that leaves 3.10 broken at install time.

The floor of the `pandas` extra is 2.2.2 rather than 2.0, and the reason is
numpy rather than us: pandas before 2.2.2 was built against numpy 1's
headers and dies on import beside numpy 2 with a dtype size mismatch. A
floor that cannot be installed in a current environment is not a floor, and
CI is where that was found — the cell that installs the oldest extras failed
on its first run, which is what it is for.
