Nothing has been released yet. This is what the first release will say.

### New
- Runs on Python 3.10 to 3.15, on Linux, macOS and Windows.
- Reads a STAR file into a pandas or polars DataFrame through `rm.read`,
  with every value kept as a string.
- Quoted values, comments and multi-block files are understood, and a
  malformed file raises an error naming the line.
- Readers are registered by extension, so a reader written in Python is as
  good as the one that ships.
