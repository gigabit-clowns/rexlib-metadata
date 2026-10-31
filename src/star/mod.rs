// SPDX-License-Identifier: LGPL-2.1-or-later

pub(crate) mod lexer;
pub(crate) mod writer;

use std::collections::HashSet;
use std::num::NonZeroUsize;

use crate::error::Error;
use crate::text::Token;
use crate::text::builder::{ArrowSink, Chunk, Table};
use crate::text::parser::{Parser, parse_blocks};

type Tokenize = for<'a> fn(&'a str, &str, usize) -> Result<Vec<Token<'a>>, Error>;

/// Every block of a STAR file, keeping only the columns `columns` names
/// when it names any, each as one batch or as several where a column would
/// outgrow what one can hold.
pub(crate) fn read_tables(
    path: &str,
    columns: Option<HashSet<String>>,
) -> Result<Vec<Table>, Error> {
    let mut sink = ArrowSink::new(None, columns);
    parse_blocks(path, lexer::tokenize_line, &mut sink)?;
    Ok(sink.into_tables())
}

/// The blocks of a STAR file, `chunk_size` rows at a time, read as they
/// are asked for.
pub(crate) struct Chunks {
    parser: Parser<Tokenize>,
    sink: ArrowSink,
    done: bool,
}

impl Chunks {
    pub(crate) fn open(
        path: &str,
        chunk_size: NonZeroUsize,
        columns: Option<HashSet<String>>,
    ) -> Result<Self, Error> {
        Ok(Self {
            parser: Parser::open(path, lexer::tokenize_line as Tokenize)?,
            sink: ArrowSink::new(Some(chunk_size), columns),
            done: false,
        })
    }
}

impl Iterator for Chunks {
    type Item = Result<Chunk, Error>;

    fn next(&mut self) -> Option<Self::Item> {
        while !self.done {
            if let Some(chunk) = self.sink.pop() {
                return Some(Ok(chunk));
            }
            match self.parser.step(&mut self.sink) {
                Ok(more) => self.done = !more,
                Err(error) => {
                    self.done = true;
                    return Some(Err(error));
                }
            }
        }
        self.sink.pop().map(Ok)
    }
}

#[cfg(test)]
mod tests {
    use std::fmt::Write as _;
    use std::io::Write;

    use tempfile::NamedTempFile;

    use super::*;
    use arrow::record_batch::RecordBatch;

    use crate::text::builder::{rows_of_record_batch, single};

    fn written(bytes: &[u8]) -> NamedTempFile {
        let mut file = NamedTempFile::new().unwrap();
        file.write_all(bytes).unwrap();
        file
    }

    fn tables(content: &str) -> Vec<(String, RecordBatch)> {
        let file = written(content.as_bytes());
        single(read_tables(file.path().to_str().unwrap(), None).unwrap())
    }

    fn error(content: &str) -> Error {
        let file = written(content.as_bytes());
        read_tables(file.path().to_str().unwrap(), None).unwrap_err()
    }

    fn chunks(content: &str, size: usize, columns: Option<&[&str]>) -> Vec<Chunk> {
        let file = written(content.as_bytes());
        let keep = columns.map(|names| names.iter().map(ToString::to_string).collect());
        Chunks::open(
            file.path().to_str().unwrap(),
            NonZeroUsize::new(size).unwrap(),
            keep,
        )
        .unwrap()
        .collect::<Result<_, _>>()
        .unwrap()
    }

    fn shape(chunks: &[Chunk]) -> Vec<(&str, usize)> {
        chunks
            .iter()
            .map(|(name, _, batch)| (name.as_str(), batch.num_rows()))
            .collect()
    }

    fn numbered(rows: usize) -> String {
        let mut content =
            String::from("data_optics\n_rlnVoltage 300\n\ndata_particles\nloop_\n_x\n_y\n");
        for row in 1..=rows {
            writeln!(content, "{row} a{row}").unwrap();
        }
        content
    }

    #[test]
    fn a_block_is_cut_every_chunk_size_rows() {
        let read = chunks(&numbered(25), 10, None);

        assert_eq!(
            shape(&read),
            [
                ("optics", 1),
                ("particles", 10),
                ("particles", 10),
                ("particles", 5)
            ]
        );
    }

    #[test]
    fn every_chunk_of_one_block_carries_its_ordinal() {
        let read = chunks(&numbered(25), 10, None);

        let ordinals: Vec<usize> = read.iter().map(|(_, at, _)| *at).collect();

        assert_eq!(ordinals, [0, 1, 1, 1]);
    }

    #[test]
    fn two_blocks_of_one_name_are_told_apart_by_their_ordinal() {
        let read = chunks(
            "data_p
loop_
_x
1

data_p
loop_
_x
2
",
            10,
            None,
        );

        assert_eq!(shape(&read), [("p", 1), ("p", 1)]);
        assert_eq!(read[0].1, 0);
        assert_eq!(read[1].1, 1);
    }

    #[test]
    fn a_block_of_an_exact_multiple_leaves_no_empty_chunk() {
        let read = chunks(&numbered(20), 10, None);

        assert_eq!(
            shape(&read),
            [("optics", 1), ("particles", 10), ("particles", 10)]
        );
    }

    #[test]
    fn a_block_with_no_rows_is_one_empty_chunk() {
        let read = chunks("data_optics\n\ndata_p\nloop_\n_x\n", 10, None);

        assert_eq!(shape(&read), [("optics", 0), ("p", 0)]);
        assert_eq!(read[1].2.num_columns(), 1);
    }

    #[test]
    fn chunks_put_back_together_are_the_whole_read() {
        let content = numbered(25);
        let whole = tables(&content);
        let read = chunks(&content, 7, None);

        let rows: Vec<Vec<String>> = read
            .iter()
            .filter(|(name, _, _)| name == "particles")
            .flat_map(|(_, _, batch)| rows_of_record_batch(batch).unwrap().1)
            .collect();

        assert_eq!(rows, rows_of_record_batch(&whole[1].1).unwrap().1);
    }

    #[test]
    fn only_the_columns_asked_for_are_built() {
        let read = chunks(&numbered(3), 10, Some(&["_y", "_rlnMissing"]));

        let names = |batch: &RecordBatch| -> Vec<String> {
            batch
                .schema()
                .fields()
                .iter()
                .map(|field| field.name().clone())
                .collect()
        };
        assert_eq!(names(&read[0].2), Vec::<String>::new());
        assert_eq!(read[0].2.num_rows(), 1);
        assert_eq!(names(&read[1].2), ["_y"]);
        assert_eq!(rows_of_record_batch(&read[1].2).unwrap().1[2], ["a3"]);
    }

    #[test]
    fn a_chunk_read_before_a_broken_line_comes_back_and_then_the_error() {
        let file = written(b"data_p\nloop_\n_x\n1\n2\n3 4\n");
        let mut read = Chunks::open(
            file.path().to_str().unwrap(),
            NonZeroUsize::new(2).unwrap(),
            None,
        )
        .unwrap();

        assert_eq!(read.next().unwrap().unwrap().2.num_rows(), 2);
        assert!(matches!(
            read.next(),
            Some(Err(Error::Parse { line: 6, .. }))
        ));
        assert!(read.next().is_none());
    }

    #[test]
    fn a_whole_read_keeps_only_the_columns_asked_for() {
        let file = written(numbered(3).as_bytes());
        let keep = HashSet::from(["_x".to_string()]);
        let read = single(read_tables(file.path().to_str().unwrap(), Some(keep)).unwrap());

        assert_eq!(read[0].1.num_columns(), 0);
        assert_eq!(read[1].1.num_columns(), 1);
        assert_eq!(read[1].1.num_rows(), 3);
    }

    #[test]
    fn every_block_comes_back_in_order() {
        let read = tables(
            "data_optics\n\nloop_\n_rlnVoltage\n300.0\n\n\
             data_particles\n\nloop_\n_rlnAngleRot\n10.5\n20.1\n",
        );

        assert_eq!(read.len(), 2);
        assert_eq!(read[0].0, "optics");
        assert_eq!(read[0].1.num_rows(), 1);
        assert_eq!(read[1].0, "particles");
        assert_eq!(read[1].1.num_rows(), 2);
    }

    #[test]
    fn a_block_announced_and_left_empty_does_not_fail_the_file() {
        let read = tables("data_optics\n\ndata_particles\n\nloop_\n_x\n1\n");

        assert_eq!(read.len(), 2);
        assert_eq!(read[0].1.num_columns(), 0);
        assert_eq!(read[0].1.num_rows(), 0);
        assert_eq!(read[1].1.num_rows(), 1);
    }

    #[test]
    fn two_blocks_of_one_name_both_come_back() {
        let read = tables("data_p\n\nloop_\n_x\n1\n\ndata_p\n\nloop_\n_x\n2\n");

        assert_eq!(read.len(), 2);
        assert_eq!(read[0].0, "p");
        assert_eq!(read[1].0, "p");
    }

    #[test]
    fn a_block_of_tags_is_one_row() {
        let read = tables("data_general\n_rlnVoltage 300.0\n_rlnMaskName mask.mrc\n");

        assert_eq!(read.len(), 1);
        assert_eq!(read[0].1.num_rows(), 1);
        assert_eq!(read[0].1.num_columns(), 2);
    }

    #[test]
    fn a_file_with_no_blocks_is_no_tables() {
        assert_eq!(tables("# nothing but a comment\n").len(), 0);
    }

    #[test]
    fn a_missing_file_says_which_one() {
        let err = read_tables("no/such/file.star", None).unwrap_err();

        assert!(matches!(err, Error::Io { .. }));
        assert!(err.to_string().contains("no/such/file.star"));
    }

    #[test]
    fn a_column_outgrowing_its_bytes_cuts_the_block_into_batches() {
        let file = written(b"data_p\nloop_\n_x\naaaa\nbbbb\ncc\n");
        let mut sink = ArrowSink::new(None, None).with_byte_limit(4);

        parse_blocks(
            file.path().to_str().unwrap(),
            lexer::tokenize_line,
            &mut sink,
        )
        .unwrap();
        let read = sink.into_tables();

        assert_eq!(read.len(), 1);
        let rows: Vec<usize> = read[0].1.iter().map(RecordBatch::num_rows).collect();
        assert_eq!(rows, [1, 1, 1]);
    }

    #[test]
    fn a_byte_order_mark_before_the_first_line_is_not_read() {
        let read = tables("\u{feff}data_p\nloop_\n_rlnA\n1\n");

        assert_eq!(read[0].0, "p");
        assert_eq!(read[0].1.num_rows(), 1);
    }

    #[test]
    fn a_byte_that_is_not_utf8_is_a_parse_error_with_its_line() {
        let mut bytes = b"data_p\n\nloop_\n_name\n".to_vec();
        bytes.push(0xff);
        bytes.extend_from_slice(b".mrc\n");
        let file = written(&bytes);

        match read_tables(file.path().to_str().unwrap(), None).unwrap_err() {
            Error::Parse { line, message, .. } => {
                assert_eq!(line, 5);
                assert!(message.contains("UTF-8"));
            }
            other => panic!("expected a parse error, got {other:?}"),
        }
    }

    #[test]
    fn a_row_too_short_for_its_columns_names_the_line() {
        match error("data_p\n\nloop_\n_a\n_b\n1 2\n3\n") {
            Error::Parse { line, .. } => assert_eq!(line, 7),
            other => panic!("expected a parse error, got {other:?}"),
        }
    }
}
