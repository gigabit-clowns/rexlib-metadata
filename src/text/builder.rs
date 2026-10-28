// SPDX-License-Identifier: LGPL-2.1-or-later

use std::sync::Arc;

use arrow::array::{Array, ArrayRef, StringArray, StringBuilder};
use arrow::datatypes::{DataType, Field, Schema};
use arrow::record_batch::{RecordBatch, RecordBatchOptions};

use super::parser::Sink;
use crate::error::{Error, unwritable};

#[derive(Default)]
pub(crate) struct ArrowSink {
    builders: Option<Vec<StringBuilder>>,
    rows: usize,
    tables: Vec<(String, RecordBatch)>,
}

impl ArrowSink {
    pub(crate) fn into_tables(self) -> Vec<(String, RecordBatch)> {
        self.tables
    }
}

impl Sink for ArrowSink {
    fn open(&mut self, columns: &[String]) {
        self.builders = Some(builders_for(columns));
        self.rows = 0;
    }

    fn row(&mut self, values: &[String]) {
        let builders = self
            .builders
            .as_mut()
            .expect("the parser opens a block before its first row");
        for (builder, value) in builders.iter_mut().zip(values) {
            builder.append_value(value);
        }
        self.rows += 1;
    }

    fn close(&mut self, name: String, columns: Vec<String>) -> Result<(), Error> {
        let builders = self
            .builders
            .take()
            .unwrap_or_else(|| builders_for(&columns));
        let batch = record_batch(&columns, builders, std::mem::take(&mut self.rows))?;
        self.tables.push((name, batch));
        Ok(())
    }
}

fn builders_for(columns: &[String]) -> Vec<StringBuilder> {
    columns.iter().map(|_| StringBuilder::new()).collect()
}

fn record_batch(
    column_names: &[String],
    mut builders: Vec<StringBuilder>,
    rows: usize,
) -> Result<RecordBatch, Error> {
    let fields: Vec<Field> = column_names
        .iter()
        .map(|name| Field::new(name, DataType::Utf8, false))
        .collect();
    let schema = Arc::new(Schema::new(fields));
    let arrays: Vec<ArrayRef> = builders
        .iter_mut()
        .map(|builder| Arc::new(builder.finish()) as ArrayRef)
        .collect();

    let options = RecordBatchOptions::new().with_row_count(Some(rows));
    Ok(RecordBatch::try_new_with_options(schema, arrays, &options)?)
}

#[cfg(test)]
pub(crate) fn build_record_batch(
    column_names: &[String],
    rows: &[Vec<String>],
) -> Result<RecordBatch, Error> {
    let mut sink = ArrowSink::default();
    sink.open(column_names);
    for row in rows {
        sink.row(row);
    }
    sink.close(String::new(), column_names.to_vec())?;
    Ok(sink.tables.remove(0).1)
}

pub(crate) fn rows_of_record_batch(
    batch: &RecordBatch,
) -> Result<(Vec<String>, Vec<Vec<String>>), Error> {
    let names: Vec<String> = batch
        .schema()
        .fields()
        .iter()
        .map(|field| field.name().clone())
        .collect();
    let columns = string_columns(batch)?;
    let rows = (0..batch.num_rows())
        .map(|row| columns.iter().map(|column| value_at(column, row)).collect())
        .collect();
    Ok((names, rows))
}

fn string_columns(batch: &RecordBatch) -> Result<Vec<&StringArray>, Error> {
    batch
        .columns()
        .iter()
        .zip(batch.schema().fields())
        .map(|(column, field)| {
            column
                .as_any()
                .downcast_ref::<StringArray>()
                .ok_or_else(|| {
                    unwritable(format!(
                        "column '{}' is {}, and a text format writes Utf8 only",
                        field.name(),
                        field.data_type()
                    ))
                })
        })
        .collect()
}

fn value_at(column: &StringArray, row: usize) -> String {
    if column.is_null(row) {
        String::new()
    } else {
        column.value(row).to_string()
    }
}

#[cfg(test)]
mod tests {
    use arrow::array::AsArray;

    use super::*;

    fn make_rows(data: &[&[&str]]) -> Vec<Vec<String>> {
        data.iter()
            .map(|row| row.iter().map(std::string::ToString::to_string).collect())
            .collect()
    }

    fn names(of: &[&str]) -> Vec<String> {
        of.iter().map(std::string::ToString::to_string).collect()
    }

    #[test]
    fn a_batch_keeps_every_value_where_it_was() {
        let rows = make_rows(&[&["10.5", "1024.0", "a"], &["20.1", "2048.0", "b"]]);

        let batch = build_record_batch(&names(&["rot", "x", "name"]), &rows).unwrap();

        assert_eq!(batch.num_rows(), 2);
        assert_eq!(batch.num_columns(), 3);
        assert_eq!(batch.schema().field(1).name(), "x");
        assert_eq!(batch.column(1).as_string::<i32>().value(0), "1024.0");
        assert_eq!(batch.column(2).as_string::<i32>().value(1), "b");
    }

    #[test]
    fn a_block_with_no_columns_is_a_batch_of_no_rows() {
        let batch = build_record_batch(&[], &[]).unwrap();

        assert_eq!(batch.num_rows(), 0);
        assert_eq!(batch.num_columns(), 0);
    }

    #[test]
    fn a_column_with_no_rows_keeps_its_name() {
        let batch = build_record_batch(&names(&["rot"]), &[]).unwrap();

        assert_eq!(batch.num_rows(), 0);
        assert_eq!(batch.schema().field(0).name(), "rot");
    }
}
