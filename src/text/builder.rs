use std::sync::Arc;

use arrow::array::{ArrayRef, StringBuilder};
use arrow::datatypes::{DataType, Field, Schema};
use arrow::record_batch::{RecordBatch, RecordBatchOptions};

use crate::error::Error;

pub(crate) fn build_record_batch(
    column_names: &[String],
    rows: &[Vec<String>],
) -> Result<RecordBatch, Error> {
    let fields: Vec<Field> = column_names
        .iter()
        .map(|name| Field::new(name, DataType::Utf8, false))
        .collect();
    let schema = Arc::new(Schema::new(fields));

    let mut builders: Vec<StringBuilder> = column_names
        .iter()
        .map(|_| StringBuilder::with_capacity(rows.len(), 0))
        .collect();
    for row in rows {
        for (builder, value) in builders.iter_mut().zip(row) {
            builder.append_value(value);
        }
    }
    let arrays: Vec<ArrayRef> = builders
        .iter_mut()
        .map(|builder| Arc::new(builder.finish()) as ArrayRef)
        .collect();

    let options = RecordBatchOptions::new().with_row_count(Some(rows.len()));
    Ok(RecordBatch::try_new_with_options(schema, arrays, &options)?)
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
