use std::sync::Arc;

use arrow::array::{ArrayRef, StringBuilder};
use arrow::datatypes::{DataType, Field, Schema};
use arrow::record_batch::RecordBatch;

use super::StarError;

pub(crate) fn build_record_batch(
    column_names: &[String],
    rows: &[Vec<String>],
) -> Result<RecordBatch, StarError> {
    let fields: Vec<Field> = column_names
        .iter()
        .map(|name| Field::new(name, DataType::Utf8, false))
        .collect();
    let schema = Arc::new(Schema::new(fields));

    let arrays: Vec<ArrayRef> = (0..column_names.len())
        .map(|col_idx| {
            let mut builder = StringBuilder::new();
            for row in rows {
                builder.append_value(&row[col_idx]);
            }
            Arc::new(builder.finish()) as ArrayRef
        })
        .collect();

    Ok(RecordBatch::try_new(schema, arrays)?)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_rows(data: &[&[&str]]) -> Vec<Vec<String>> {
        data.iter()
            .map(|row| row.iter().map(|s| s.to_string()).collect())
            .collect()
    }

    #[test]
    fn build_record_batch_shape() {
        let names = vec!["_rlnAngleRot".to_string(), "_rlnCoordinateX".to_string()];
        let rows = make_rows(&[&["10.5", "1024.0"], &["20.1", "2048.0"]]);

        let batch = build_record_batch(&names, &rows).unwrap();

        assert_eq!(batch.num_rows(), 2);
        assert_eq!(batch.num_columns(), 2);
        assert_eq!(batch.schema().field(0).name(), "_rlnAngleRot");
        assert_eq!(batch.schema().field(1).name(), "_rlnCoordinateX");
    }
}
