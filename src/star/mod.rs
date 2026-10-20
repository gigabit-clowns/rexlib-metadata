pub(crate) mod lexer;

use arrow::record_batch::RecordBatch;

use crate::error::{Error, parse_error};
use crate::text::builder::build_record_batch;
use crate::text::parser::{Block, parse_blocks};

pub struct RawColumn {
    pub name: String,
}

pub struct RawSchema {
    pub table_name: String,
    pub columns: Vec<RawColumn>,
}

pub fn read_schema(path: &str) -> Result<RawSchema, Error> {
    let block = last_block(path)?;
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

pub fn read_all(path: &str) -> Result<RecordBatch, Error> {
    let block = last_block(path)?;
    build_record_batch(&block.columns, &block.rows)
}

fn last_block(path: &str) -> Result<Block, Error> {
    parse_blocks(path, lexer::tokenize_line)?
        .into_iter()
        .last()
        .ok_or_else(|| parse_error(path, 0, "no data blocks found"))
}
