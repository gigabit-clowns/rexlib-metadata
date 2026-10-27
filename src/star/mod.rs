pub(crate) mod lexer;

use arrow::record_batch::RecordBatch;

use crate::error::Error;
use crate::text::builder::build_record_batch;
use crate::text::parser::parse_blocks;

pub fn read_tables(path: &str) -> Result<Vec<(String, RecordBatch)>, Error> {
    parse_blocks(path, lexer::tokenize_line)?
        .into_iter()
        .map(|block| {
            let batch = build_record_batch(&block.columns, &block.rows)?;
            Ok((block.name, batch))
        })
        .collect()
}
