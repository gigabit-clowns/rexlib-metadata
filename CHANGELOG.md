First release: read and write CryoEM metadata as pandas, polars or Arrow.

### New
- `rxm.read(path)`: STAR, Xmipp XMD (`.xmd`, `.doc`, `.pos`, `.sel`) and SQLite, under canonical column names, typed.
- cryoSPARC `.cs` read (`cryosparc` extra): poses as Relion's angles, shifts in Ångström, exposure groups as optics; converts to Relion.
- Relion 3.0 files read: each particle's microscope becomes an optics group, offsets come back in Ångström, and a write gives Relion 4. Each microscope setting is read on its own, so one the file lacks no longer drops the rest.
- `result.raw`: the same file under its own names, every block of it.
- `result["particles"]`, `result.joined("particles")` (optics on each row), `columns=` to read only some columns.
- `chunks(n)`: a table a chunk at a time, in bounded memory, from the same block a whole read takes.
- `result.write(path)`: back to any format, every column of the source kept; `updates=` and `rows=` to change or filter. Written a chunk at a time, in bounded memory.
- `rxm.write(path, {"particles": df})`: canonical tables built anywhere.
- `bundle=`, `reader=`, `writer=`: conventions, readers and writers of your own; `rxm.new_registry(schema)` for a schema of your own.
- `to_arrow()` beside `to_pandas()` and `to_polars()`.
- abi3 wheels for Python 3.10 and later on Linux, macOS and Windows.
