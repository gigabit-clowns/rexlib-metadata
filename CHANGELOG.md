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
- Runs on Python 3.10 to 3.15, on Linux, macOS and Windows.
- Reads a STAR block of `_name value` tags, such as Relion's optimiser and
  postprocess files, as a table of one row.
- Reads every data block of a file, not only the last. `result.names` says
  which tables there are and `result["particles"]` picks one; a file of one
  table needs no name, and a file of several asks for one.
- Reads a STAR file into a pandas or polars DataFrame through `rxm.read`,
  with every value kept as a string.
- Quoted values, comments and multi-block files are understood, and a
  malformed file raises an error naming the line.
- Readers are registered by extension, so a reader written in Python is as
  good as the one that ships.
