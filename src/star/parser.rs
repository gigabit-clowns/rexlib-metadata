use std::fs::File;
use std::io::{BufRead, BufReader};

use super::StarError;
use super::lexer::{tokenize_line, Token};

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

#[derive(Debug)]
pub(crate) struct StarBlock {
    pub name: String,
    pub columns: Vec<String>,
    pub rows: Vec<Vec<String>>,
}

// ---------------------------------------------------------------------------
// parse_blocks — YOUR SECOND EXERCISE (after tokenize_line)
// ---------------------------------------------------------------------------
//
// Reads the entire file and returns all data_ blocks found.
//
// State machine rules:
//  · Use tokenize_line() to process each line — quoted-value support comes
//    for free without any extra logic here.
//  · A file may contain zero or more blocks; zero blocks is not an error here
//    (read_schema / read_all handle that case).
//  · A block with columns but zero data rows is valid.
//  · In ReadingData state, a Token::DataBlock closes the current block and
//    starts a new one (multi-block support).
//  · If a data row has a different number of values than declared columns,
//    return StarError::Parse with the line number and a descriptive message.

pub(crate) fn parse_blocks(path: &str) -> Result<Vec<StarBlock>, StarError> {
    let file = File::open(path).map_err(|source| StarError::Io {
        path: path.to_string(),
        source,
    })?;
    let reader = BufReader::new(file);

    todo!()
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::NamedTempFile;

    fn parse(content: &str) -> Vec<StarBlock> {
        let mut f = NamedTempFile::new().unwrap();
        write!(f, "{content}").unwrap();
        parse_blocks(f.path().to_str().unwrap()).unwrap()
    }

    fn parse_err(content: &str) -> StarError {
        let mut f = NamedTempFile::new().unwrap();
        write!(f, "{content}").unwrap();
        parse_blocks(f.path().to_str().unwrap()).unwrap_err()
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
        assert!(blocks[0].rows.is_empty());
        assert_eq!(blocks[0].columns.len(), 2);
    }

    #[test]
    fn empty_file_returns_no_blocks() {
        let blocks = parse("");
        assert!(blocks.is_empty());
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
        let content = "data_particles\n\nloop_\n_rlnMicrographName\n\"path with spaces/file.mrcs\"\n";
        let blocks = parse(content);
        assert_eq!(blocks[0].rows[0][0], "path with spaces/file.mrcs");
    }

    #[test]
    fn wrong_column_count_is_error() {
        let content = "data_particles\n\nloop_\n_rlnAngleRot\n_rlnAngleTilt\n10.5\n";
        let err = parse_err(content);
        assert!(matches!(err, StarError::Parse { .. }));
    }
}
