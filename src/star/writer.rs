// SPDX-License-Identifier: LGPL-2.1-or-later

use std::fs::File;
use std::io::{BufWriter, Write};

use arrow::record_batch::RecordBatch;

use crate::error::{Error, unwritable};
use crate::text::builder::rows_of_record_batch;

pub(crate) fn write_tables(path: &str, tables: &[(String, RecordBatch)]) -> Result<(), Error> {
    let file = File::create(path).map_err(|source| io_error(path, source))?;
    let mut out = BufWriter::new(file);
    for (name, batch) in tables {
        let (columns, rows) = rows_of_record_batch(batch)?;
        check_names(&columns)?;
        let quoted = quote_rows(&rows)?;
        write_block(&mut out, name, &columns, &quoted).map_err(|source| io_error(path, source))?;
    }
    out.flush().map_err(|source| io_error(path, source))
}

fn io_error(path: &str, source: std::io::Error) -> Error {
    Error::Io {
        path: path.to_string(),
        source,
    }
}

fn check_names(columns: &[String]) -> Result<(), Error> {
    for column in columns {
        if !column.starts_with('_') {
            return Err(unwritable(format!(
                "column '{column}' does not start with '_', and a STAR file \
                 would not read it back as a column"
            )));
        }
    }
    Ok(())
}

fn quote_rows(rows: &[Vec<String>]) -> Result<Vec<Vec<String>>, Error> {
    rows.iter()
        .map(|row| row.iter().map(|value| quoted(value)).collect())
        .collect()
}

fn quoted(value: &str) -> Result<String, Error> {
    if !needs_quotes(value) {
        return Ok(value.to_string());
    }
    match (value.contains('"'), value.contains('\'')) {
        (true, true) => Err(unwritable(format!(
            "the value {value:?} holds both kinds of quote, which STAR has no \
             way to escape"
        ))),
        (true, false) => Ok(format!("'{value}'")),
        _ => Ok(format!("\"{value}\"")),
    }
}

fn needs_quotes(value: &str) -> bool {
    value.is_empty()
        || value.contains(char::is_whitespace)
        || value.contains('"')
        || value.contains('\'')
        || value.starts_with('#')
        || value.starts_with('_')
        || value.starts_with("data_")
        || value == "loop_"
}

fn write_block<W: Write>(
    out: &mut W,
    name: &str,
    columns: &[String],
    rows: &[Vec<String>],
) -> std::io::Result<()> {
    writeln!(out, "data_{name}")?;
    writeln!(out)?;
    writeln!(out, "loop_")?;
    for (index, column) in columns.iter().enumerate() {
        writeln!(out, "{column} #{}", index + 1)?;
    }
    for row in rows {
        writeln!(out, "{}", row.join(" "))?;
    }
    writeln!(out)
}

#[cfg(test)]
mod tests {
    use arrow::array::{Array, Int32Array, StringArray};
    use arrow::datatypes::{DataType, Field, Schema};
    use std::sync::Arc;
    use tempfile::TempDir;

    use super::*;
    use crate::star::read_tables;
    use crate::text::builder::build_record_batch;

    fn batch(columns: &[&str], rows: &[&[&str]]) -> RecordBatch {
        let names: Vec<String> = columns.iter().map(ToString::to_string).collect();
        let values: Vec<Vec<String>> = rows
            .iter()
            .map(|row| row.iter().map(ToString::to_string).collect())
            .collect();
        build_record_batch(&names, &values).unwrap()
    }

    fn round_trip(tables: &[(String, RecordBatch)]) -> Vec<(String, RecordBatch)> {
        let directory = TempDir::new().unwrap();
        let path = directory.path().join("out.star");
        let path = path.to_str().unwrap();

        write_tables(path, tables).unwrap();
        read_tables(path, None).unwrap()
    }

    fn one(name: &str, columns: &[&str], rows: &[&[&str]]) -> Vec<(String, RecordBatch)> {
        vec![(name.to_string(), batch(columns, rows))]
    }

    fn written(tables: &[(String, RecordBatch)]) -> Result<(), Error> {
        let directory = TempDir::new().unwrap();
        let path = directory.path().join("out.star");
        write_tables(path.to_str().unwrap(), tables)
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
            ("optics".to_string(), batch(&["_rlnVoltage"], &[&["300.0"]])),
            (
                "particles".to_string(),
                batch(&["_rlnAngleRot"], &[&["10.5"]]),
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

        let error = written(&[("p".to_string(), numbers)]).unwrap_err();

        assert!(error.to_string().contains("_rlnClassNumber"));
        assert!(error.to_string().contains("Utf8"));
    }

    #[test]
    fn a_path_that_cannot_be_opened_says_which() {
        let error =
            write_tables("no/such/place/out.star", &one("p", &["_rlnA"], &[&["1"]])).unwrap_err();

        assert!(matches!(error, Error::Io { .. }));
        assert!(error.to_string().contains("no/such/place/out.star"));
    }
}
