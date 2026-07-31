pub(crate) mod builder;
pub(crate) mod lexer;
pub(crate) mod parser;

use arrow::record_batch::RecordBatch;
use builder::build_record_batch;
use parser::parse_blocks;

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------
//
// thiserror::Error is a derive macro that auto-generates Display and
// std::error::Error implementations from the #[error("...")] attributes on
// each variant. Without thiserror you would write those impls by hand
// (~20 lines of boilerplate).
//
// Placeholders in the #[error] string:
//   {field_name}  → calls Display on that field
//   {source} / {0} → same, but also marks it as the root cause
//
// #[from] generates an impl From<T> for the variant automatically, so you
// can use `?` directly with that error type.
//
// #[source] (without #[from]) marks the root cause but does not generate
// From. Use it when you construct the variant manually (e.g. StarError::Io).

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

// ---------------------------------------------------------------------------
// Public types (used by lib.rs)
// ---------------------------------------------------------------------------

pub struct RawColumn {
    pub name: String,
}

pub struct RawSchema {
    pub table_name: String,
    pub columns: Vec<RawColumn>,
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

pub fn read_schema(path: &str) -> Result<RawSchema, StarError> {
    let blocks = parse_blocks(path)?;
    let block = blocks
        .into_iter()
        .last()
        .ok_or_else(|| StarError::Parse {
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
    let block = blocks
        .into_iter()
        .last()
        .ok_or_else(|| StarError::Parse {
            path: path.to_string(),
            line: 0,
            message: "no data blocks found".to_string(),
        })?;
    build_record_batch(&block.columns, &block.rows)
}
