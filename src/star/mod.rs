pub(crate) mod builder;
pub(crate) mod lexer;
pub(crate) mod parser;

use arrow::record_batch::RecordBatch;
use builder::build_record_batch;
use parser::parse_blocks;

#[derive(Debug, thiserror::Error)]
pub enum StarError {
    #[error("cannot open '{path}': {source}")]
    Io {
        path: String,
        #[source]
        source: std::io::Error,
    },

    #[error("{path}:{line}: {message}")]
    Parse {
        path: String,
        line: usize,
        message: String,
    },

    #[error("{0}")]
    Arrow(#[from] arrow::error::ArrowError),
}

pub struct RawColumn {
    pub name: String,
}

pub struct RawSchema {
    pub table_name: String,
    pub columns: Vec<RawColumn>,
}

pub fn read_schema(path: &str) -> Result<RawSchema, StarError> {
    let blocks = parse_blocks(path)?;
    let block = blocks.into_iter().last().ok_or_else(|| StarError::Parse {
        path: path.to_string(),
        line: 0,
        message: "no data blocks found".to_string(),
    })?;
    let columns = block
        .columns
        .into_iter()
        .map(|name| RawColumn { name })
        .collect();
    Ok(RawSchema {
        table_name: block.name,
        columns,
    })
}

pub fn read_all(path: &str) -> Result<RecordBatch, StarError> {
    let blocks = parse_blocks(path)?;
    let block = blocks.into_iter().last().ok_or_else(|| StarError::Parse {
        path: path.to_string(),
        line: 0,
        message: "no data blocks found".to_string(),
    })?;
    build_record_batch(&block.columns, &block.rows)
}
