// SPDX-License-Identifier: LGPL-2.1-or-later

use std::fs::File;
use std::io::{BufRead, BufReader, ErrorKind};

use super::Token;
use crate::error::{Error, parse_error};

#[derive(Debug)]
pub(crate) struct Block {
    pub name: String,
    pub columns: Vec<String>,
    pub rows: Vec<Vec<String>>,
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

pub(crate) fn parse_blocks<T>(path: &str, tokenize: T) -> Result<Vec<Block>, Error>
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::NamedTempFile;

    fn parse(content: &str) -> Vec<Block> {
        let mut f = NamedTempFile::new().unwrap();
        write!(f, "{content}").unwrap();
        parse_blocks(
            f.path().to_str().unwrap(),
            crate::star::lexer::tokenize_line,
        )
        .unwrap()
    }

    fn parse_err(content: &str) -> Error {
        let mut f = NamedTempFile::new().unwrap();
        write!(f, "{content}").unwrap();
        parse_blocks(
            f.path().to_str().unwrap(),
            crate::star::lexer::tokenize_line,
        )
        .unwrap_err()
    }

    fn comma_lexer(line: &str, path: &str, line_num: usize) -> Result<Vec<Token>, Error> {
        let line = line.trim();
        if line.is_empty() {
            return Ok(vec![]);
        }
        if let Some(name) = line.strip_prefix("_table,") {
            return Ok(vec![Token::DataBlock(name.to_string())]);
        }
        if line == "_header" {
            return Ok(vec![Token::Loop]);
        }
        if let Some(names) = line.strip_prefix("_columns,") {
            return Ok(names
                .split(',')
                .map(|name| Token::Column(name.to_string()))
                .collect());
        }
        if line.starts_with('_') {
            return Err(parse_error(
                path,
                line_num,
                format!("unknown keyword '{line}'"),
            ));
        }
        Ok(line
            .split(',')
            .map(|value| Token::Value(value.trim().to_string()))
            .collect())
    }

    fn parse_commas(content: &str) -> Vec<Block> {
        let mut f = NamedTempFile::new().unwrap();
        write!(f, "{content}").unwrap();
        parse_blocks(f.path().to_str().unwrap(), comma_lexer).unwrap()
    }

    #[test]
    fn the_same_machine_reads_a_comma_separated_file() {
        let blocks = parse_commas(
            "_table,images
_header
_columns,uid,angle
1,10.5
2,20.1
",
        );
        assert_eq!(blocks.len(), 1);
        assert_eq!(blocks[0].name, "images");
        assert_eq!(blocks[0].columns, vec!["uid", "angle"]);
        assert_eq!(blocks[0].rows, vec![vec!["1", "10.5"], vec!["2", "20.1"]]);
    }

    #[test]
    fn another_lexer_inherits_the_same_errors() {
        let mut f = NamedTempFile::new().unwrap();
        write!(
            f,
            "_table,images
_header
_columns,uid,angle
1
"
        )
        .unwrap();
        let err = parse_blocks(f.path().to_str().unwrap(), comma_lexer).unwrap_err();
        assert!(matches!(err, Error::Parse { .. }));
    }

    #[test]
    fn single_block_shape() {
        let blocks = parse("data_particles\n\nloop_\n_rlnAngleRot\n10.5\n20.1\n");
        assert_eq!(blocks.len(), 1);
        assert_eq!(blocks[0].name, "particles");
        assert_eq!(blocks[0].columns, vec!["_rlnAngleRot"]);
        assert_eq!(blocks[0].rows.len(), 2);
    }

    #[test]
    fn empty_block_has_zero_rows() {
        let blocks = parse("data_particles\n\nloop_\n_rlnAngleRot\n_rlnAngleTilt\n");
        assert_eq!(blocks.len(), 1);
        assert_eq!(blocks[0].rows.len(), 0);
        assert_eq!(blocks[0].columns.len(), 2);
    }

    #[test]
    fn empty_file_returns_no_blocks() {
        let blocks = parse("");
        assert_eq!(blocks.len(), 0);
    }

    #[test]
    fn multi_block() {
        let content = "\
data_optics\n\nloop_\n_rlnVoltage\n300.0\n\n\
data_particles\n\nloop_\n_rlnAngleRot\n10.5\n20.1\n";
        let blocks = parse(content);
        assert_eq!(blocks.len(), 2);
        assert_eq!(blocks[0].name, "optics");
        assert_eq!(blocks[1].name, "particles");
        assert_eq!(blocks[1].rows.len(), 2);
    }

    #[test]
    fn quoted_value_preserved() {
        let content =
            "data_particles\n\nloop_\n_rlnMicrographName\n\"path with spaces/file.mrcs\"\n";
        let blocks = parse(content);
        assert_eq!(blocks[0].rows[0][0], "path with spaces/file.mrcs");
    }

    #[test]
    fn wrong_column_count_is_error() {
        let content = "data_particles\n\nloop_\n_rlnAngleRot\n_rlnAngleTilt\n10.5\n";
        let err = parse_err(content);
        assert!(matches!(err, Error::Parse { .. }));
    }

    #[test]
    fn block_without_loop_is_kept_empty() {
        let blocks = parse("data_optics\n\ndata_particles\n\nloop_\n_rlnAngleRot\n10.5\n");
        assert_eq!(blocks.len(), 2);
        assert_eq!(blocks[0].name, "optics");
        assert_eq!(blocks[0].columns.len(), 0);
        assert_eq!(blocks[0].rows.len(), 0);
        assert_eq!(blocks[1].rows.len(), 1);
    }

    #[test]
    fn values_before_loop_are_an_error() {
        assert!(matches!(
            parse_err("data_particles\n10.5 20.1\n"),
            Error::Parse { .. }
        ));
    }

    #[test]
    fn column_outside_a_loop_is_an_error() {
        assert!(matches!(
            parse_err("data_particles\n_rlnAngleRot\n"),
            Error::Parse { .. }
        ));
    }

    #[test]
    fn column_after_the_first_row_is_an_error() {
        assert!(matches!(
            parse_err("data_particles\n\nloop_\n_rlnAngleRot\n10.5\n_rlnAngleTilt\n"),
            Error::Parse { .. }
        ));
    }

    #[test]
    fn second_loop_in_one_block_is_an_error() {
        assert!(matches!(
            parse_err("data_particles\n\nloop_\n_rlnAngleRot\n10.5\n\nloop_\n_rlnAngleTilt\n"),
            Error::Parse { .. }
        ));
    }

    #[test]
    fn content_outside_a_data_block_is_an_error() {
        assert!(matches!(
            parse_err("loop_\n_rlnAngleRot\n10.5\n"),
            Error::Parse { .. }
        ));
    }

    #[test]
    fn parse_error_reports_the_offending_line() {
        let content = "data_particles\n\nloop_\n_rlnAngleRot\n_rlnAngleTilt\n10.5 20.1\n10.5\n";
        match parse_err(content) {
            Error::Parse { line, .. } => assert_eq!(line, 7),
            other => panic!("expected a parse error, got {other:?}"),
        }
    }
}
