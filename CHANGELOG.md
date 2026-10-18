# Unreleased

Nothing has been released yet. What main holds so far:

- Reads a STAR file into a pandas or polars DataFrame, through `rm.read`,
  with every value kept as a string.
- Quoted values, comments and multi-block files are parsed; a malformed file
  raises an error naming the line.
- Readers are registered by extension, and a reader written in Python is as
  good as the one that ships.
