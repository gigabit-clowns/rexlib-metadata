Nothing has been released yet. This is what the first release will say.

### Fixed
- A file with a data block that is announced and left empty reads, instead of
  failing the whole file.
- A `#` inside a value is part of the value, as the format says; only one
  after whitespace starts a comment.
- A byte that is not UTF-8 is an error naming the line, not "cannot open".
- A missing file raises `FileNotFoundError` and a malformed one `ValueError`,
  where everything used to be a `RuntimeError`.

### Changed
- Naming a canonical table, as `result["particles"]`, no longer reads the
  file. The name is checked against the canonical schema; a table the schema
  declares and the file does not fill is an error when the rows are asked
  for. Without this, reading a large file a chunk at a time read it whole
  first and held it.

### New
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
