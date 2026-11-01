# Roadmap

Phases in order; start from the first open item. A phase is done when its
tests pass and CI is green. Tick items in the pull request that earns them.
Loose ends are issues, not lines here.

## Done

| Phase | Delivered |
|---|---|
| 0 Skeleton | Rust `cdylib` with pyo3 and arrow, maturin package, CI on Linux, macOS and Windows |
| 1 STAR read | `rxm.read()`, `RawResult` / `ReadResult` to pandas and polars, `MetadataRegistry` |
| 1b Parser | Lexer, parser and builder split; quoting, comments; `Error` with path and line |
| 2 Conventions | Schema, read conventions, bundles, the read engine; Relion 4 bundle for `.star`; `result.raw` |
| 3 STAR write | `StarWriter`, write conventions, `result.write(path)`, `rxm.write(path, tables)` from memory; roundtrip over real files |
| 4 Forwarding | `columns=`; a write rereads the source and carries every column, with `updates=` and `rows=` |
| 5 Chunks | `result[name].chunks(n)` streams in bounded memory |
| 6 Multi-table, CD | Every block surfaced, `result.names`; development release on push to `main` |
| 6b Second format prep | Shared `src/text/` state machine, `reader=` / `bundle=` / `writer=`, real `.cs`, `.par`, CSV fixtures |
| 10 Performance | Benchmarks in CI through CodSpeed; borrowed tokens, whitespace fast path, Arrow-direct writer |

Not supported by the STAR parser, each an error naming the line: a data row
over several lines, and more than one `loop_` in a block.

## Phase 6 — open

- [ ] PyPI release, waiting on the name (#40)

## Phase 7 — Xmipp XMD

Done: `.xmd` read and write, Xmipp bundle (image reference, angles),
canonical shifts in Ångström, optics joined per row through `result.joined()`.

- [ ] Micrograph, coordinates, CTF and shifts, once a real `.xmd` holding
      them is under `tests/files/xmd/`
- [ ] A read convention that needs a joined column: Relion 3.0's
      `_rlnOriginX` in pixels needs the optics' pixel size, waiting on a real
      Relion 3.0 STAR

## Phase 8 — SQLite

Done: generic `SqliteReader` / `SqliteWriter` for `.sqlite` and `.db`,
paginated through one cursor per table.

- [ ] Scipion's `.sqlite` (`Objects` with `c01`…, `Classes`, `Properties`),
      waiting on real files

## Phase 9 — HDF5

Done: generic `Hdf5Reader` / `Hdf5Writer` for `.h5` and `.hdf5` (the `hdf5`
extra), paginated by slicing.

- [ ] A real CryoEM HDF5 file under `tests/files/`

## Phase 10 — open

- [ ] CodSpeed's check required by the ruleset, its threshold in `docs/ci.md`

Measured and rejected:

- Cold-read prefetch: the disk gives ~400 MiB/s, the parser takes
  185–236 MiB/s, so a cold read costs only 1.5–5 % over a warm one
  (`.github/measure/cold_read.py` at `3e50392`, for slower storage).
- LTO: every profile within 5 % of cargo's default, either way; the release
  profile stays the default.
- Skipping dropped columns while tokenising: a canonical read needs
  `_rlnImageName`, near the end of a Relion row.

## Phase 11 — Review and clean-up

After every phase above, one pass over the whole repository.

- [ ] Exhaustive review: quality, architecture, patterns, test gaps
- [ ] Every `# type: ignore[...]` and `# noqa: ...` replaced by code that
      needs none
- [ ] The clean-up the review asks for, in pull requests of their own

## Deferred

- `Relion3Bundle`, for legacy files
- `RexConvention`, the suite's own canonical spelling, waiting on the team
  agreeing it
