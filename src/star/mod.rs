pub(crate) mod lexer;

use arrow::record_batch::RecordBatch;

use crate::error::Error;
use crate::text::builder::build_record_batch;
use crate::text::parser::parse_blocks;

pub(crate) fn read_tables(path: &str) -> Result<Vec<(String, RecordBatch)>, Error> {
    parse_blocks(path, lexer::tokenize_line)?
        .into_iter()
        .map(|block| {
            let batch = build_record_batch(&block.columns, &block.rows)?;
            Ok((block.name, batch))
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use std::io::Write;

    use tempfile::NamedTempFile;

    use super::*;

    fn written(bytes: &[u8]) -> NamedTempFile {
        let mut file = NamedTempFile::new().unwrap();
        file.write_all(bytes).unwrap();
        file
    }

    fn tables(content: &str) -> Vec<(String, RecordBatch)> {
        let file = written(content.as_bytes());
        read_tables(file.path().to_str().unwrap()).unwrap()
    }

    fn error(content: &str) -> Error {
        let file = written(content.as_bytes());
        read_tables(file.path().to_str().unwrap()).unwrap_err()
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
        let err = read_tables("no/such/file.star").unwrap_err();

        assert!(matches!(err, Error::Io { .. }));
        assert!(err.to_string().contains("no/such/file.star"));
    }

    #[test]
    fn a_byte_that_is_not_utf8_is_a_parse_error_with_its_line() {
        let mut bytes = b"data_p\n\nloop_\n_name\n".to_vec();
        bytes.push(0xff);
        bytes.extend_from_slice(b".mrc\n");
        let file = written(&bytes);

        match read_tables(file.path().to_str().unwrap()).unwrap_err() {
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
