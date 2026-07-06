use std::fs::File;
use std::io::{BufRead, BufReader};
use std::sync::Arc;

use arrow::array::{ArrayRef, StringBuilder};
use arrow::datatypes::{DataType, Field, Schema};
use arrow::record_batch::RecordBatch;

#[derive(Debug, Clone)]
pub struct RawColumn {
    pub name: String,
}

#[derive(Debug, Clone)]
pub struct RawSchema {
    pub table_name: String,
    pub columns: Vec<RawColumn>,
}

enum State {
    Preamble,
    InBlock { table_name: String },
    ReadingColumns { table_name: String, column_names: Vec<String> },
    ReadingData { table_name: String, column_names: Vec<String>, rows: Vec<Vec<String>> },
}

pub fn read_schema(path: &str) -> Result<RawSchema, String> {
    let file = File::open(path).map_err(|e| e.to_string())?;
    let reader = BufReader::new(file);
    let mut state = State::Preamble;

    for line_result in reader.lines() {
        let line = line_result.map_err(|e| e.to_string())?;
        let line = line.trim();

        if line.is_empty() || line.starts_with('#') {
            continue;
        }

        state = match state {
            State::Preamble | State::InBlock { .. } if line.starts_with("data_") => {
                let name = line.strip_prefix("data_").expect("guard ensures starts_with(\"data_\")");
                State::InBlock { table_name: name.to_string() }
            }
            State::InBlock { table_name } if line == "loop_" => {
                State::ReadingColumns { table_name, column_names: Vec::new() }
            }
            State::ReadingColumns { table_name, mut column_names } if line.starts_with('_') => {
                let name = line.split_whitespace().next().expect("starts_with('_') guarantees a token").to_string();
                column_names.push(name);
                State::ReadingColumns { table_name, column_names }
            }
            State::ReadingColumns { table_name, column_names } => {
                let columns = column_names.into_iter().map(|name| RawColumn { name }).collect();
                return Ok(RawSchema { table_name, columns });
            }
            state => state,
        };
    }

    Err(format!("No data rows found in '{path}'"))
}

pub fn read_all(path: &str) -> Result<RecordBatch, String> {
    let file = File::open(path).map_err(|e| e.to_string())?;
    let reader = BufReader::new(file);
    let mut state = State::Preamble;

    for line_result in reader.lines() {
        let line = line_result.map_err(|e| e.to_string())?;
        let line = line.trim();

        if line.is_empty() || line.starts_with('#') {
            continue;
        }

        state = match state {
            State::Preamble | State::InBlock { .. } if line.starts_with("data_") => {
                let name = line.strip_prefix("data_").expect("guard ensures starts_with(\"data_\")");
                State::InBlock { table_name: name.to_string() }
            }
            State::InBlock { table_name } if line == "loop_" => {
                State::ReadingColumns { table_name, column_names: Vec::new() }
            }
            State::ReadingColumns { table_name, mut column_names } if line.starts_with('_') => {
                let name = line.split_whitespace().next().expect("starts_with('_') guarantees a token").to_string();
                column_names.push(name);
                State::ReadingColumns { table_name, column_names }
            }
            State::ReadingColumns { table_name, column_names } => {
                let row = parse_row(&column_names, line)?;
                State::ReadingData { table_name, column_names, rows: vec![row] }
            }
            State::ReadingData { column_names, rows, .. } if line.starts_with("data_") => {
                return build_record_batch(&column_names, &rows);
            }
            State::ReadingData { table_name, column_names, mut rows } => {
                rows.push(parse_row(&column_names, line)?);
                State::ReadingData { table_name, column_names, rows }
            }
            state => state,
        };
    }

    match state {
        State::ReadingData { column_names, rows, .. } => build_record_batch(&column_names, &rows),
        _ => Err(format!("No data rows found in '{path}'")),
    }
}

fn parse_row(column_names: &[String], line: &str) -> Result<Vec<String>, String> {
    let tokens: Vec<String> = line.split_whitespace().map(|s| s.to_string()).collect();
    if tokens.len() != column_names.len() {
        return Err(format!(
            "Row has {} values but schema has {} columns",
            tokens.len(),
            column_names.len()
        ));
    }
    Ok(tokens)
}

fn build_record_batch(column_names: &[String], rows: &[Vec<String>]) -> Result<RecordBatch, String> {
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

    RecordBatch::try_new(schema, arrays).map_err(|e| e.to_string())
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

    #[test]
    fn parse_row_rejects_wrong_column_count() {
        let names = vec!["a".to_string(), "b".to_string()];
        assert!(parse_row(&names, "1.0 2.0 3.0").is_err());
    }
}
