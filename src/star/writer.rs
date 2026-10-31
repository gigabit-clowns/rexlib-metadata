// SPDX-License-Identifier: LGPL-2.1-or-later

use std::fs::File;
use std::io::{BufWriter, Write};

use arrow::array::{Array, StringArray};
use arrow::record_batch::RecordBatch;

use crate::error::{Error, unwritable};
use crate::text::builder::{Table, string_columns};

const BUFFER: usize = 1 << 20;

/// A value refused while writing removes the half-written file.
pub(crate) fn write_tables(
    path: &str,
    header: Option<&str>,
    tables: &[Table],
) -> Result<(), Error> {
    if let Some(header) = header {
        check_header(header)?;
    }
    for (name, batches) in tables {
        check_names(name, first(name, batches)?)?;
        for batch in batches {
            string_columns(batch)?;
        }
    }
    let written = write_file(path, header, tables);
    if written.is_err() {
        let _ = std::fs::remove_file(path);
    }
    written
}

fn write_file(path: &str, header: Option<&str>, tables: &[Table]) -> Result<(), Error> {
    let io = |source| io_error(path, source);
    let file = File::create(path).map_err(io)?;
    let mut out = BufWriter::with_capacity(BUFFER, file);
    if let Some(header) = header {
        writeln!(out, "{header}").map_err(io)?;
    }
    for (name, batches) in tables {
        write_block(&mut out, path, name, batches)?;
    }
    out.flush().map_err(io)
}

fn first<'a>(name: &str, batches: &'a [RecordBatch]) -> Result<&'a RecordBatch, Error> {
    batches.first().ok_or_else(|| {
        unwritable(format!(
            "table '{name}' came with no batch, and so with no columns to write"
        ))
    })
}

fn io_error(path: &str, source: std::io::Error) -> Error {
    Error::Io {
        path: path.to_string(),
        source,
    }
}

fn check_header(header: &str) -> Result<(), Error> {
    match header.lines().find(|line| !line.starts_with('#')) {
        Some(line) => Err(unwritable(format!(
            "the header line {line:?} is not a comment, and a STAR file would \
             read it as data"
        ))),
        None => Ok(()),
    }
}

fn check_names(name: &str, batch: &RecordBatch) -> Result<(), Error> {
    if !is_one_word(name) {
        return Err(unwritable(format!(
            "the block name {name:?} holds whitespace or '#', and a STAR file \
             would not read it back as one name"
        )));
    }
    let schema = batch.schema();
    match schema
        .fields()
        .iter()
        .find(|field| !field.name().starts_with('_') || !is_one_word(field.name()))
    {
        Some(field) => Err(unwritable(format!(
            "column {:?} does not start with '_' or holds whitespace or '#', \
             and a STAR file would not read it back as that column",
            field.name()
        ))),
        None => Ok(()),
    }
}

fn is_one_word(name: &str) -> bool {
    !name.contains(|ch: char| ch == '#' || ch.is_whitespace())
}

fn write_block<W: Write>(
    out: &mut W,
    path: &str,
    name: &str,
    batches: &[RecordBatch],
) -> Result<(), Error> {
    let io = |source| io_error(path, source);
    writeln!(out, "data_{name}\n\nloop_").map_err(io)?;
    for (index, field) in first(name, batches)?.schema().fields().iter().enumerate() {
        writeln!(out, "{} #{}", field.name(), index + 1).map_err(io)?;
    }
    for batch in batches {
        let columns = string_columns(batch)?;
        for row in 0..batch.num_rows() {
            write_row(out, path, &columns, row)?;
        }
    }
    writeln!(out).map_err(io)
}

fn write_row<W: Write>(
    out: &mut W,
    path: &str,
    columns: &[&StringArray],
    row: usize,
) -> Result<(), Error> {
    for (index, column) in columns.iter().enumerate() {
        if index > 0 {
            out.write_all(b" ")
                .map_err(|source| io_error(path, source))?;
        }
        let value = if column.is_null(row) {
            ""
        } else {
            column.value(row)
        };
        write_value(out, path, value)?;
    }
    out.write_all(b"\n")
        .map_err(|source| io_error(path, source))
}

fn write_value<W: Write>(out: &mut W, path: &str, value: &str) -> Result<(), Error> {
    let io = |source| io_error(path, source);
    if !needs_quotes(value) {
        return out.write_all(value.as_bytes()).map_err(io);
    }
    let quote = quote_for(value)?;
    out.write_all(quote).map_err(io)?;
    out.write_all(value.as_bytes()).map_err(io)?;
    out.write_all(quote).map_err(io)
}

fn quote_for(value: &str) -> Result<&'static [u8], Error> {
    if value.contains(['\n', '\r']) {
        return Err(unwritable(format!(
            "the value {value:?} holds a line break, which a STAR value, \
             read one line at a time, cannot"
        )));
    }
    match (value.contains('"'), value.contains('\'')) {
        (true, true) => Err(unwritable(format!(
            "the value {value:?} holds both kinds of quote, which STAR has no \
             way to escape"
        ))),
        (true, false) => Ok(b"'"),
        _ => Ok(b"\""),
    }
}

fn needs_quotes(value: &str) -> bool {
    value.is_empty()
        || value.starts_with(['#', '_'])
        || value.starts_with("data_")
        || value == "loop_"
        || value.bytes().any(|byte| {
            matches!(
                byte,
                b' ' | b'\t' | b'\n' | b'\r' | 0x0B | 0x0C | b'"' | b'\''
            )
        })
        || (!value.is_ascii() && value.contains(char::is_whitespace))
}

#[cfg(test)]
mod tests {
    use arrow::array::{Array, Int32Array, StringArray};
    use arrow::datatypes::{DataType, Field, Schema};
    use std::sync::Arc;
    use tempfile::TempDir;

    use super::*;
    use crate::star::read_tables;
    use crate::text::builder::{build_record_batch, single};

    fn batch(columns: &[&str], rows: &[&[&str]]) -> RecordBatch {
        let names: Vec<String> = columns.iter().map(ToString::to_string).collect();
        let values: Vec<Vec<String>> = rows
            .iter()
            .map(|row| row.iter().map(ToString::to_string).collect())
            .collect();
        build_record_batch(&names, &values).unwrap()
    }

    fn round_trip(tables: &[Table]) -> Vec<(String, RecordBatch)> {
        let directory = TempDir::new().unwrap();
        let path = directory.path().join("out.star");
        let path = path.to_str().unwrap();

        write_tables(path, None, tables).unwrap();
        single(read_tables(path, None).unwrap())
    }

    fn one(name: &str, columns: &[&str], rows: &[&[&str]]) -> Vec<Table> {
        vec![(name.to_string(), vec![batch(columns, rows)])]
    }

    fn written(tables: &[Table]) -> Result<(), Error> {
        let directory = TempDir::new().unwrap();
        let path = directory.path().join("out.star");
        write_tables(path.to_str().unwrap(), None, tables)
    }

    fn values_of(batch: &RecordBatch, column: usize) -> Vec<String> {
        let array = batch
            .column(column)
            .as_any()
            .downcast_ref::<StringArray>()
            .unwrap();
        (0..array.len())
            .map(|row| array.value(row).to_string())
            .collect()
    }

    #[test]
    fn what_was_written_reads_back_the_same() {
        let read = round_trip(&one(
            "particles",
            &["_rlnCoordinateX", "_rlnCoordinateY"],
            &[&["1024.0", "2048.0"], &["512.0", "256.0"]],
        ));

        assert_eq!(read.len(), 1);
        assert_eq!(read[0].0, "particles");
        assert_eq!(read[0].1.num_rows(), 2);
        assert_eq!(values_of(&read[0].1, 0), ["1024.0", "512.0"]);
        assert_eq!(read[0].1.schema().field(1).name(), "_rlnCoordinateY");
    }

    #[test]
    fn every_block_comes_back_in_order() {
        let read = round_trip(&[
            (
                "optics".to_string(),
                vec![batch(&["_rlnVoltage"], &[&["300.0"]])],
            ),
            (
                "particles".to_string(),
                vec![batch(&["_rlnAngleRot"], &[&["10.5"]])],
            ),
        ]);

        assert_eq!(read.len(), 2);
        assert_eq!(read[0].0, "optics");
        assert_eq!(read[1].0, "particles");
    }

    #[test]
    fn a_value_with_spaces_survives() {
        let read = round_trip(&one(
            "p",
            &["_rlnMicrographName"],
            &[&["folder with spaces/mic 001.mrcs"]],
        ));

        assert_eq!(
            values_of(&read[0].1, 0),
            ["folder with spaces/mic 001.mrcs"]
        );
    }

    #[test]
    fn a_value_that_looks_structural_survives() {
        let read = round_trip(&one(
            "p",
            &["_rlnName"],
            &[&["data_particles"], &["loop_"], &["_rlnAngleRot"], &["#1"]],
        ));

        assert_eq!(
            values_of(&read[0].1, 0),
            ["data_particles", "loop_", "_rlnAngleRot", "#1"]
        );
    }

    #[test]
    fn a_value_holding_one_kind_of_quote_takes_the_other() {
        let read = round_trip(&one(
            "p",
            &["_rlnName"],
            &[&["it's here"], &["say \"what\""]],
        ));

        assert_eq!(values_of(&read[0].1, 0), ["it's here", "say \"what\""]);
    }

    #[test]
    fn an_empty_value_survives() {
        let read = round_trip(&one("p", &["_rlnA", "_rlnB"], &[&["", "1.0"]]));

        assert_eq!(values_of(&read[0].1, 0), [""]);
        assert_eq!(values_of(&read[0].1, 1), ["1.0"]);
    }

    #[test]
    fn a_value_holding_both_quotes_says_so() {
        let error = written(&one("p", &["_rlnA"], &[&["it's \"this\""]])).unwrap_err();

        assert!(matches!(error, Error::Unwritable { .. }));
        assert!(error.to_string().contains("both kinds of quote"));
    }

    #[test]
    fn a_header_comes_first_and_reads_as_a_comment() {
        let directory = TempDir::new().unwrap();
        let path = directory.path().join("out.xmd");
        let path = path.to_str().unwrap();
        let tables = one("noname", &["_image"], &[&["1@a.stk"]]);

        write_tables(path, Some("# XMIPP_STAR_1 *"), &tables).unwrap();

        let text = std::fs::read_to_string(path).unwrap();
        assert!(text.starts_with(
            "# XMIPP_STAR_1 *
data_noname
"
        ));
        assert_eq!(
            values_of(&single(read_tables(path, None).unwrap())[0].1, 0),
            ["1@a.stk"]
        );
    }

    #[test]
    fn a_header_that_is_not_a_comment_says_so() {
        let directory = TempDir::new().unwrap();
        let path = directory.path().join("out.star");
        let tables = one("p", &["_rlnA"], &[&["1"]]);

        let error = write_tables(
            path.to_str().unwrap(),
            Some(
                "# fine
data_",
            ),
            &tables,
        )
        .unwrap_err();

        assert!(error.to_string().contains("\"data_\""));
        assert!(!path.exists());
    }

    #[test]
    fn a_value_refused_while_writing_leaves_no_file_behind() {
        let directory = TempDir::new().unwrap();
        let path = directory.path().join("out.star");
        let mut tables = one("first", &["_rlnA"], &[&["fine"]]);
        tables.extend(one("second", &["_rlnA"], &[&["it's \"this\""]]));

        let error = write_tables(path.to_str().unwrap(), None, &tables).unwrap_err();

        assert!(error.to_string().contains("both kinds of quote"));
        assert!(!path.exists());
    }

    #[test]
    fn a_value_holding_a_line_break_says_so() {
        for value in ["a\nb", "a\r\nb"] {
            let error = written(&one("p", &["_rlnA"], &[&[value]])).unwrap_err();

            assert!(error.to_string().contains("line break"), "{value:?}");
        }
    }

    #[test]
    fn a_name_the_reader_would_split_or_cut_says_so() {
        for column in ["_rln A", "_rlnA#1"] {
            let error = written(&one("p", &[column], &[&["1"]])).unwrap_err();

            assert!(
                error.to_string().contains("whitespace or '#'"),
                "{column:?}"
            );
        }
        for block in ["two words", "a#b"] {
            let error = written(&one(block, &["_rlnA"], &[&["1"]])).unwrap_err();

            assert!(error.to_string().contains("block name"), "{block:?}");
        }
    }

    #[test]
    fn a_value_with_a_quote_inside_comes_back_as_it_was() {
        let read = round_trip(&one("p", &["_rlnA"], &[&["John's_data/mic.mrc"]]));

        assert_eq!(values_of(&read[0].1, 0), ["John's_data/mic.mrc"]);
    }

    #[test]
    fn a_column_name_a_reader_would_not_see_says_so() {
        let error = written(&one("p", &["coord_x"], &[&["1.0"]])).unwrap_err();

        assert!(error.to_string().contains("coord_x"));
        assert!(error.to_string().contains("'_'"));
    }

    #[test]
    fn a_column_that_is_not_text_says_which_one() {
        let schema = Arc::new(Schema::new(vec![Field::new(
            "_rlnClassNumber",
            DataType::Int32,
            false,
        )]));
        let column = Arc::new(Int32Array::from(vec![1, 2]));
        let numbers = RecordBatch::try_new(schema, vec![column]).unwrap();

        let error = written(&[("p".to_string(), vec![numbers])]).unwrap_err();

        assert!(error.to_string().contains("_rlnClassNumber"));
        assert!(error.to_string().contains("Utf8"));
    }

    #[test]
    fn a_path_that_cannot_be_opened_says_which() {
        let error = write_tables(
            "no/such/place/out.star",
            None,
            &one("p", &["_rlnA"], &[&["1"]]),
        )
        .unwrap_err();

        assert!(matches!(error, Error::Io { .. }));
        assert!(error.to_string().contains("no/such/place/out.star"));
    }
}
