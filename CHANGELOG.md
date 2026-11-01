Nothing has been released yet. This is what the first release will say.

### Fixed
- An SQLite read of some columns no longer fails on a table that holds none
  of them: the table comes back with its rows and no columns.
- `chunks(0)` and below raise for every format; SQLite read every row as one
  chunk, or never returned on an empty table.
- HDF5 refuses a table inside another (`a` with `a/b`) and a table of no
  columns, either of which it wrote and then could not read back.
- SQLite refuses two tables of one name with a `ValueError`.
- A STAR write that cannot open its file leaves the file there as it was;
  an I/O error names its path without claiming the file could not be opened,
  and Python's exception carries it as `filename`.
- A quote inside a bare value is part of it, and a quoted value ends only
  at a quote followed by whitespace, as STAR and CIF have it: a path such as
  `John's_data/mic.mrc` no longer makes a file unreadable.
- A byte-order mark before the first line is skipped.
- Writing refuses a value holding a line break, and a block or column name
  holding whitespace or `#`, rather than write a file it cannot read back.
- A column of more than 1 GiB of text is read as several batches rather
  than overflowing Arrow's offsets into a panic; a table held in several
  is written as it is.
- A value that does not parse names the file, the canonical table and the
  value, where it was a bare `ArrowInvalid`.
- Writing a file in its own format keeps the blocks no canonical table
  covers; it dropped them, and wrote an empty file over a source such as
  `postprocess.star`. A write that would hold nothing now raises.
- A change in `updates=` that no convention writes raises; it was dropped
  and the value read was written in its place.
- `.sqlite` and `.db`, one writer, count as one format, so a write between
  them keeps every column.
- A missing number is written empty and read back as missing; the read
  failed on it.
- Relion's and Xmipp's angles are read one by one, so a 2D classification's
  in-plane angle alone comes back as `angle_psi`.
- A file with a data block that is announced and left empty reads, instead of
  failing the whole file.
- A `#` inside a value is part of the value, as the format says; only one
  after whitespace starts a comment.
- A byte that is not UTF-8 is an error naming the line, not "cannot open".
- A missing file raises `FileNotFoundError` and a malformed one `ValueError`,
  where everything used to be a `RuntimeError`.

### Changed
- pyarrow is declared as `pyarrow>=16,<=26.0.0` rather than pinned to one version,
  so the package installs beside the pyarrow an environment already has.
- A canonical read keeps nothing of the file once its frame is handed back;
  it held a text copy of every row for as long as the result lived.
  Materialising twice reads twice; `result.raw` still keeps what it read.
- Writing a STAR file is thirteen times as fast: the writer hands each
  value from Arrow to the file, where it built three strings per value.
- Reading a STAR file is three times as fast: a million rows in 1.4 s
  rather than 4.
- Naming a canonical table, as `result["particles"]`, no longer reads the
  file. The name is checked against the canonical schema; a table the schema
  declares and the file does not fill is an error when the rows are asked
  for. Without this, reading a large file a chunk at a time read it whole
  first and held it.

### New
- `rxm.write(path, {"particles": df, ...})` writes canonical tables built
  anywhere, in pandas, polars or Arrow, through the destination's
  conventions.
- `bundle=` takes several bundles in priority order, so a convention of
  your own goes in front of Relion's: `bundle=[mine, relion4_bundle()]`.
- A joined view writes back: `result.joined("particles").write(path,
  updates=flat)` takes the particles' columns and refuses a changed optics
  column.
- `write(path, rows=...)` keeps only some rows, by position or by mask:
  read, filter the particles, write them back with every column they had.
- Benchmarks, run in CI through CodSpeed, and a comparison with starfile and
  starfile-rs: `python -m scripts.compare`.
- Reads and writes HDF5 (`.h5`, `.hdf5`) with the `hdf5` extra: a compound
  dataset, or a group of one dataset per column, is a table.
- Reads and writes SQLite (`.sqlite`, `.db`): every table, typed as the file
  declares, whole or a chunk at a time, through `.raw`.
- `result.joined("particles")` puts each particle's optics on its row.
  Writing a Relion file with optics to `.xmd` now works, the optics joined
  into the particles, where it raised.
- Reads and writes Xmipp's `.xmd`: the image reference and the angles come
  back canonical, and a written `.xmd` opens with the line Xmipp looks for.
- Reads and writes particle shifts, `shift_x`, `shift_y` and `shift_z`, in
  Ångström.
- `read(path, reader=...)` and `write(path, writer=...)` name the reader and
  the writer, beside `bundle=`, so a file can be read whatever its extension.
- One wheel per platform serves every Python from 3.10.
- Reads a canonical table a chunk at a time:
  `for chunk in result["particles"].chunks(10_000)`. The file opens when
  iteration starts and closes when it ends, so a file larger than memory
  reads in bounded memory. A chunk carries `name`, `len()`, `to_arrow()`,
  `to_pandas()` and `to_polars()`.
- Writes a canonical table back out as the format spells it:
  `result.write(path)` turns every canonical table the file fills into a data
  block, through the write conventions of the destination's extension — so
  `read("a.star").write("b.star")` round-trips and nothing has to be said
  about the format. `bundle=` writes through one of your own.
- `read(path, columns=[...])` shows only those canonical columns, and
  `result.write(path, updates=df)` writes them back with every other column
  of the source, untouched. A STAR file read that way parses only the
  columns it needs, and a reader of your own can do the same by overriding
  `Reader.read_tables_keeping`.
- A write goes through a temporary file beside the destination, so writing
  over the source is safe and a failed write leaves the old file in place.
- A column the conventions do not cover is carried over untouched when the
  destination is the format the result was read from, so filtering rows and
  writing them back does not quietly drop `_rlnCtfImage` and its neighbours.
- Writes a STAR file back: `result.raw.write(path)` writes every table the
  result holds, one data block each, under the names they carry, and the
  writer is chosen by the destination's extension. Reading a file and writing
  it again gives the same frame, quoting and all.
- A read comes back in one vocabulary, whatever the file: `rxm.read(path)`
  gives canonical column names, typed, and `result.names` says which
  canonical tables the file fills. A Relion file needs nothing said about
  it — the conventions recognise a format by the columns it has.
- `result.raw` is the same read under the file's own table and column names,
  every value a string, for when the format itself is what you are working
  on. It is also the answer for a file no convention recognises, which says
  so rather than handing back an empty frame.
- Conventions of your own: `ConventionBundle` groups a format's conventions
  by the canonical table each fills, `rxm.read(path, bundle=...)` reads one
  file through yours, and registering it applies it to every read of that
  extension, in priority order.
- Runs on Python 3.10 to 3.15, on Linux, macOS and Windows.
- Reads a STAR block of `_name value` tags, such as Relion's optimiser and
  postprocess files, as a table of one row.
- Reads every data block of a file, not only the last. `result.raw.names`
  says which tables the file holds and `result.raw["particles"]` picks one;
  a result of one table needs no name, and one of several asks for one,
  canonical or raw alike.
- Reads a STAR file into a pandas or polars DataFrame through `rxm.read`.
- Quoted values, comments and multi-block files are understood, and a
  malformed file raises an error naming the line.
- Readers are registered by extension, so a reader written in Python is as
  good as the one that ships.
