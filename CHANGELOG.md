Nothing has been released yet. This is what the first release will say.

### Fixed
- A file with a data block that is announced and left empty reads, instead of
  failing the whole file.
- A `#` inside a value is part of the value, as the format says; only one
  after whitespace starts a comment.
- A byte that is not UTF-8 is an error naming the line, not "cannot open".
- A missing file raises `FileNotFoundError` and a malformed one `ValueError`,
  where everything used to be a `RuntimeError`.

### New
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
