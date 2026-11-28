// SPDX-License-Identifier: LGPL-2.1-or-later

use std::fs::File;
use std::io::{BufRead, BufReader, ErrorKind, Read};

use super::{LINE_LIMIT, Lexer, Token};
use crate::error::{Error, parse_error};

/// Receives each block as `open`, its rows, then `close`.
pub(crate) trait Sink {
    fn open(&mut self, name: &str, columns: &[String]);
    fn row<'v>(&mut self, values: impl Iterator<Item = &'v str>) -> Result<(), Error>;
    fn close(&mut self) -> Result<(), Error>;
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
        columns: Vec<String>,
    },
    ReadingTags {
        name: String,
        columns: Vec<String>,
        values: Vec<String>,
    },
}

impl State {
    fn close<S: Sink>(self, sink: &mut S) -> Result<(), Error> {
        match self {
            Self::Preamble => return Ok(()),
            Self::InBlock { name } => sink.open(&name, &[]),
            Self::ReadingColumns { name, columns } => sink.open(&name, &columns),
            Self::ReadingData { .. } => {}
            Self::ReadingTags {
                name,
                columns,
                values,
            } => {
                sink.open(&name, &columns);
                sink.row(values.iter().map(String::as_str))?;
            }
        }
        sink.close()
    }
}

pub(crate) fn parse_blocks<L: Lexer, S: Sink>(
    path: &str,
    lexer: L,
    sink: &mut S,
) -> Result<(), Error> {
    let mut parser = Parser::open(path, lexer)?;
    while parser.step(sink)? {}
    Ok(())
}

/// Every block's name and columns, handing `sink` the first row of a loop
/// and none after it.
pub(crate) fn parse_headers<L: Lexer, S: Sink>(
    path: &str,
    lexer: L,
    sink: &mut S,
) -> Result<(), Error> {
    let mut parser = Parser::open(path, lexer)?;
    parser.skip_rows = true;
    while parser.step(sink)? {}
    Ok(())
}

/// Reads one line at a time into a buffer it keeps.
pub(crate) struct Parser<L> {
    path: String,
    reader: BufReader<File>,
    line: String,
    line_num: usize,
    lexer: L,
    state: State,
    skip_rows: bool,
}

impl<L: Lexer> Parser<L> {
    pub(crate) fn open(path: &str, lexer: L) -> Result<Self, Error> {
        let file = File::open(path).map_err(|source| Error::Io {
            path: path.to_string(),
            source,
        })?;
        Ok(Self {
            path: path.to_string(),
            reader: BufReader::new(file),
            line: String::new(),
            line_num: 0,
            lexer,
            state: State::Preamble,
            skip_rows: false,
        })
    }

    /// Hands one line to `sink`, and says whether there are more.
    pub(crate) fn step<S: Sink>(&mut self, sink: &mut S) -> Result<bool, Error> {
        let state = std::mem::replace(&mut self.state, State::Preamble);
        if !self.read_line()? {
            state.close(sink)?;
            return Ok(false);
        }
        self.state = if self.skips(&state) {
            state
        } else {
            self.next_state(state, sink)?
        };
        Ok(true)
    }

    fn skips(&self, state: &State) -> bool {
        matches!(state, State::ReadingData { .. })
            && self.skip_rows
            && self.lexer.is_row(&self.line)
    }

    /// Reads the next line into the buffer, without its line ending, and
    /// says whether there was one.
    fn read_line(&mut self) -> Result<bool, Error> {
        self.line.clear();
        self.line_num += 1;
        let read = (&mut self.reader)
            .take(LINE_LIMIT as u64 + 1)
            .read_line(&mut self.line)
            .map_err(|source| match source.kind() {
                ErrorKind::InvalidData => parse_error(&self.path, self.line_num, "not valid UTF-8"),
                _ => Error::Io {
                    path: self.path.clone(),
                    source,
                },
            })?;
        if read > LINE_LIMIT {
            return Err(parse_error(
                &self.path,
                self.line_num,
                "a line longer than 1 GiB, which an Arrow string column cannot hold",
            ));
        }
        if self.line_num == 1 && self.line.starts_with('\u{feff}') {
            self.line.drain(..'\u{feff}'.len_utf8());
        }
        if self.line.ends_with('\n') {
            self.line.pop();
            if self.line.ends_with('\r') {
                self.line.pop();
            }
        }
        Ok(read > 0)
    }

    fn next_state<S: Sink>(&self, state: State, sink: &mut S) -> Result<State, Error> {
        let path = self.path.as_str();
        let line_num = self.line_num;
        let tokens = self.lexer.tokenize(&self.line, path, line_num)?;
        match tokens.as_slice() {
            [] => Ok(state),
            [Token::DataBlock(name)] => {
                let name = (*name).to_string();
                state.close(sink)?;
                Ok(State::InBlock { name })
            }
            [Token::Loop] => open_loop(state, path, line_num),
            [Token::Column(name), rest @ ..] if all_values(rest) && !rest.is_empty() => {
                read_tag(state, name, rest, path, line_num)
            }
            [Token::Column(_), ..] if tokens.iter().all(is_column) => {
                declare_columns(state, &tokens, path, line_num)
            }
            values if all_values(values) => read_row(state, values, sink, path, line_num),
            _ => Err(parse_error(
                path,
                line_num,
                "a line whose tokens come in an order no line of a table has",
            )),
        }
    }
}

fn is_column(token: &Token) -> bool {
    matches!(token, Token::Column(_))
}

fn all_values(tokens: &[Token]) -> bool {
    tokens.iter().all(|token| matches!(token, Token::Value(_)))
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

fn read_tag(
    state: State,
    name: &str,
    values: &[Token],
    path: &str,
    line: usize,
) -> Result<State, Error> {
    let [Token::Value(value)] = values else {
        return Err(parse_error(
            path,
            line,
            format!(
                "tag '{name}' carries {} values, where one is all a tag may have",
                values.len()
            ),
        ));
    };
    let (name, value) = (name.to_string(), (*value).to_string());
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
            refuse_repeat(&columns, &name, path, line)?;
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
    tokens: &[Token],
    path: &str,
    line: usize,
) -> Result<State, Error> {
    column_names_of(tokens)
        .into_iter()
        .try_fold(state, |state, name| declare_column(state, name, path, line))
}

fn declare_column(state: State, column: String, path: &str, line: usize) -> Result<State, Error> {
    match state {
        State::ReadingColumns { name, mut columns } => {
            refuse_repeat(&columns, &column, path, line)?;
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

fn refuse_repeat(columns: &[String], name: &str, path: &str, line: usize) -> Result<(), Error> {
    if columns.iter().any(|column| column == name) {
        return Err(parse_error(
            path,
            line,
            format!("column '{name}' is declared twice in one block"),
        ));
    }
    Ok(())
}

fn read_row<S: Sink>(
    state: State,
    tokens: &[Token],
    sink: &mut S,
    path: &str,
    line: usize,
) -> Result<State, Error> {
    match state {
        State::ReadingColumns { name, columns } => {
            check_row_width(&columns, tokens, path, line)?;
            sink.open(&name, &columns);
            sink.row(values_of(tokens))?;
            Ok(State::ReadingData { columns })
        }
        State::ReadingData { ref columns } => {
            check_row_width(columns, tokens, path, line)?;
            sink.row(values_of(tokens))?;
            Ok(state)
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
    tokens: &[Token],
    path: &str,
    line: usize,
) -> Result<(), Error> {
    let width = values_of(tokens).count();
    if width != columns.len() {
        return Err(parse_error(
            path,
            line,
            format!(
                "row has {width} values but {} columns are declared",
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
            Token::Column(name) => Some((*name).to_string()),
            _ => None,
        })
        .collect()
}

fn values_of<'a>(tokens: &[Token<'a>]) -> impl Iterator<Item = &'a str> {
    tokens.iter().filter_map(|token| match token {
        Token::Value(value) => Some(*value),
        _ => None,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::NamedTempFile;

    #[derive(Debug)]
    struct Block {
        name: String,
        columns: Vec<String>,
        rows: Vec<Vec<String>>,
    }

    #[derive(Default)]
    struct Blocks {
        blocks: Vec<Block>,
        open: bool,
    }

    impl Sink for Blocks {
        fn open(&mut self, name: &str, columns: &[String]) {
            assert!(!self.open, "block '{name}' opened inside another");
            self.open = true;
            self.blocks.push(Block {
                name: name.to_string(),
                columns: columns.to_vec(),
                rows: Vec::new(),
            });
        }

        fn row<'v>(&mut self, values: impl Iterator<Item = &'v str>) -> Result<(), Error> {
            assert!(self.open, "a row outside a block");
            let block = self.blocks.last_mut().unwrap();
            block.rows.push(values.map(ToString::to_string).collect());
            Ok(())
        }

        fn close(&mut self) -> Result<(), Error> {
            assert!(self.open, "a block closed that was never opened");
            self.open = false;
            Ok(())
        }
    }

    fn blocks_of(content: &str, lexer: impl Lexer) -> Result<Vec<Block>, Error> {
        let mut f = NamedTempFile::new().unwrap();
        write!(f, "{content}").unwrap();
        let mut sink = Blocks::default();
        parse_blocks(f.path().to_str().unwrap(), lexer, &mut sink)?;
        Ok(sink.blocks)
    }

    fn parse(content: &str) -> Vec<Block> {
        blocks_of(content, crate::star::lexer::Star).unwrap()
    }

    fn parse_err(content: &str) -> Error {
        blocks_of(content, crate::star::lexer::Star).unwrap_err()
    }

    struct Commas;

    impl Lexer for Commas {
        fn tokenize<'a>(
            &self,
            line: &'a str,
            path: &str,
            line_num: usize,
        ) -> Result<Vec<Token<'a>>, Error> {
            let line = line.trim();
            if line.is_empty() {
                return Ok(vec![]);
            }
            if let Some(name) = line.strip_prefix("_table,") {
                return Ok(vec![Token::DataBlock(name)]);
            }
            if line == "_header" {
                return Ok(vec![Token::Loop]);
            }
            if let Some(names) = line.strip_prefix("_columns,") {
                return Ok(names.split(',').map(Token::Column).collect());
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
                .map(|value| Token::Value(value.trim()))
                .collect())
        }

        fn is_row(&self, line: &str) -> bool {
            !line.trim().is_empty() && !line.trim_start().starts_with('_')
        }
    }

    struct Fixed(Vec<Token<'static>>);

    impl Lexer for Fixed {
        fn tokenize<'a>(&self, line: &'a str, _: &str, _: usize) -> Result<Vec<Token<'a>>, Error> {
            Ok(match line {
                "data_a" => vec![Token::DataBlock("a")],
                "loop_" => vec![Token::Loop],
                "_x" => vec![Token::Column("_x")],
                _ => self.0.clone(),
            })
        }

        fn is_row(&self, _: &str) -> bool {
            false
        }
    }

    fn parse_commas(content: &str) -> Vec<Block> {
        blocks_of(content, Commas).unwrap()
    }

    #[test]
    fn tokens_in_an_order_no_line_has_are_an_error() {
        for tokens in [
            vec![Token::Value("1"), Token::Column("_x")],
            vec![Token::Column("_x"), Token::Value("1"), Token::Column("_y")],
            vec![Token::DataBlock("b"), Token::Value("1")],
            vec![Token::Loop, Token::Loop],
        ] {
            let err = blocks_of("data_a\nloop_\n_x\nline\n", Fixed(tokens)).unwrap_err();
            match err {
                Error::Parse { line, message, .. } => {
                    assert_eq!(line, 4);
                    assert!(message.contains("order"), "{message}");
                }
                other => panic!("expected a parse error, got {other:?}"),
            }
        }
    }

    #[test]
    fn every_block_is_opened_and_closed_once() {
        let blocks = parse("data_a\n\ndata_b\nloop_\n_x\n\ndata_c\n_y 1\n_z 2\n");
        let shapes: Vec<_> = blocks
            .iter()
            .map(|block| (block.name.as_str(), block.columns.len(), block.rows.len()))
            .collect();
        assert_eq!(shapes, vec![("a", 0, 0), ("b", 1, 0), ("c", 2, 1)]);
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
        let err = blocks_of(
            "_table,images
_header
_columns,uid,angle
1
",
            Commas,
        )
        .unwrap_err();
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
