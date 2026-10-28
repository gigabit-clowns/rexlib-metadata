// SPDX-License-Identifier: LGPL-2.1-or-later

//! The parser the streaming one replaced, kept to check it against.

use std::fs::File;
use std::io::{BufRead, BufReader, ErrorKind};
use std::sync::Arc;

use arrow::array::{ArrayRef, StringBuilder};
use arrow::datatypes::{DataType, Field, Schema};
use arrow::record_batch::{RecordBatch, RecordBatchOptions};

use super::Token;
use crate::error::{Error, parse_error};

#[derive(Debug)]
struct Block {
    name: String,
    columns: Vec<String>,
    rows: Vec<Vec<String>>,
}

enum State {
    Preamble,
    InBlock {
        name: String,
    },
    ReadingColumns {
        name: String,
        columns: Vec<String>,
    },
    ReadingData {
        name: String,
        columns: Vec<String>,
        rows: Vec<Vec<String>>,
    },
    ReadingTags {
        name: String,
        columns: Vec<String>,
        values: Vec<String>,
    },
}

impl State {
    fn into_block(self) -> Option<Block> {
        match self {
            Self::Preamble => None,
            Self::InBlock { name } => Some(Block {
                name,
                columns: Vec::new(),
                rows: Vec::new(),
            }),
            Self::ReadingColumns { name, columns } => Some(Block {
                name,
                columns,
                rows: Vec::new(),
            }),
            Self::ReadingData {
                name,
                columns,
                rows,
            } => Some(Block {
                name,
                columns,
                rows,
            }),
            Self::ReadingTags {
                name,
                columns,
                values,
            } => Some(Block {
                name,
                columns,
                rows: vec![values],
            }),
        }
    }
}

fn parse_blocks<T>(path: &str, tokenize: T) -> Result<Vec<Block>, Error>
where
    T: Fn(&str, &str, usize) -> Result<Vec<Token>, Error>,
{
    let file = File::open(path).map_err(|source| Error::Io {
        path: path.to_string(),
        source,
    })?;
    let reader = BufReader::new(file);

    let mut blocks = Vec::new();
    let mut state = State::Preamble;

    for (index, line) in reader.lines().enumerate() {
        let line_num = index + 1;
        let line = line.map_err(|source| match source.kind() {
            ErrorKind::InvalidData => parse_error(path, line_num, "not valid UTF-8"),
            _ => Error::Io {
                path: path.to_string(),
                source,
            },
        })?;

        let tokens = tokenize(&line, path, line_num)?;
        let Some(first) = tokens.first() else {
            continue;
        };

        state = match first {
            Token::DataBlock(name) => {
                let name = name.clone();
                blocks.extend(state.into_block());
                State::InBlock { name }
            }
            Token::Loop => open_loop(state, path, line_num)?,
            Token::Column(_) => read_names(state, &tokens, path, line_num)?,
            Token::Value(_) => read_row(state, row_values_of(&tokens), path, line_num)?,
        };
    }

    blocks.extend(state.into_block());
    Ok(blocks)
}

fn open_loop(state: State, path: &str, line: usize) -> Result<State, Error> {
    match state {
        State::InBlock { name } => Ok(State::ReadingColumns {
            name,
            columns: Vec::new(),
        }),
        State::Preamble => Err(parse_error(path, line, "loop_ outside a data block")),
        State::ReadingTags { .. } => Err(parse_error(
            path,
            line,
            "a loop_ after a block's tags is not supported",
        )),
        _ => Err(parse_error(
            path,
            line,
            "a data block with more than one loop_ is not supported",
        )),
    }
}

fn read_names(state: State, tokens: &[Token], path: &str, line: usize) -> Result<State, Error> {
    let values = row_values_of(tokens);
    let names = column_names_of(tokens);
    if values.is_empty() {
        return declare_columns(state, names, path, line);
    }
    read_tag(state, names, values, path, line)
}

fn read_tag(
    state: State,
    names: Vec<String>,
    values: Vec<String>,
    path: &str,
    line: usize,
) -> Result<State, Error> {
    let name = names
        .into_iter()
        .next()
        .expect("a tag line carries its name");
    if values.len() > 1 {
        return Err(parse_error(
            path,
            line,
            format!(
                "tag '{name}' carries {} values, where one is all a tag may have",
                values.len()
            ),
        ));
    }
    let value = values.into_iter().next().expect("checked above");
    match state {
        State::InBlock { name: block } => Ok(State::ReadingTags {
            name: block,
            columns: vec![name],
            values: vec![value],
        }),
        State::ReadingTags {
            name: block,
            mut columns,
            mut values,
        } => {
            columns.push(name);
            values.push(value);
            Ok(State::ReadingTags {
                name: block,
                columns,
                values,
            })
        }
        State::Preamble => Err(parse_error(
            path,
            line,
            format!("tag '{name}' outside a data block"),
        )),
        State::ReadingColumns { .. } | State::ReadingData { .. } => Err(parse_error(
            path,
            line,
            format!("tag '{name}' inside a loop_, which declares its columns and its rows apart"),
        )),
    }
}

fn declare_columns(
    state: State,
    names: Vec<String>,
    path: &str,
    line: usize,
) -> Result<State, Error> {
    names
        .into_iter()
        .try_fold(state, |state, name| declare_column(state, name, path, line))
}

fn declare_column(state: State, column: String, path: &str, line: usize) -> Result<State, Error> {
    match state {
        State::ReadingColumns { name, mut columns } => {
            columns.push(column);
            Ok(State::ReadingColumns { name, columns })
        }
        State::Preamble => Err(parse_error(
            path,
            line,
            format!("column '{column}' outside a data block"),
        )),
        State::InBlock { .. } => Err(parse_error(
            path,
            line,
            format!("column '{column}' outside a loop_"),
        )),
        State::ReadingData { .. } => Err(parse_error(
            path,
            line,
            format!("column '{column}' after the first data row"),
        )),
        State::ReadingTags { .. } => Err(parse_error(
            path,
            line,
            format!("column '{column}' with no value among a block's tags"),
        )),
    }
}

fn read_row(state: State, values: Vec<String>, path: &str, line: usize) -> Result<State, Error> {
    match state {
        State::ReadingColumns { name, columns } => {
            check_row_width(&columns, &values, path, line)?;
            Ok(State::ReadingData {
                name,
                columns,
                rows: vec![values],
            })
        }
        State::ReadingData {
            name,
            columns,
            mut rows,
        } => {
            check_row_width(&columns, &values, path, line)?;
            rows.push(values);
            Ok(State::ReadingData {
                name,
                columns,
                rows,
            })
        }
        State::Preamble => Err(parse_error(path, line, "data row outside a data block")),
        State::InBlock { .. } => Err(parse_error(path, line, "data row before loop_")),
        State::ReadingTags { .. } => Err(parse_error(
            path,
            line,
            "a data row among a block's tags, which are one name and one value each",
        )),
    }
}

fn check_row_width(
    columns: &[String],
    values: &[String],
    path: &str,
    line: usize,
) -> Result<(), Error> {
    if values.len() != columns.len() {
        return Err(parse_error(
            path,
            line,
            format!(
                "row has {} values but {} columns are declared",
                values.len(),
                columns.len()
            ),
        ));
    }
    Ok(())
}

fn column_names_of(tokens: &[Token]) -> Vec<String> {
    tokens
        .iter()
        .filter_map(|token| match token {
            Token::Column(name) => Some(name.clone()),
            _ => None,
        })
        .collect()
}

fn row_values_of(tokens: &[Token]) -> Vec<String> {
    tokens
        .iter()
        .filter_map(|token| match token {
            Token::Value(value) => Some(value.clone()),
            _ => None,
        })
        .collect()
}

pub(crate) fn read_tables<T>(path: &str, tokenize: T) -> Result<Vec<(String, RecordBatch)>, Error>
where
    T: Fn(&str, &str, usize) -> Result<Vec<Token>, Error>,
{
    parse_blocks(path, tokenize)?
        .into_iter()
        .map(|block| Ok((block.name, build_record_batch(&block.columns, &block.rows)?)))
        .collect()
}

fn build_record_batch(column_names: &[String], rows: &[Vec<String>]) -> Result<RecordBatch, Error> {
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
