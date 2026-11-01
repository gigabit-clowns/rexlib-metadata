// SPDX-License-Identifier: LGPL-2.1-or-later

use std::collections::{HashSet, VecDeque};
use std::num::NonZeroUsize;
use std::sync::Arc;

use arrow::array::{Array, ArrayRef, StringArray, StringBuilder};
use arrow::datatypes::{DataType, Field, Schema};
use arrow::record_batch::{RecordBatch, RecordBatchOptions};

use super::parser::Sink;
use crate::error::{Error, unwritable};

/// The bytes a column of one batch may hold before the batch is cut: an
/// Arrow string array addresses its text with 32-bit offsets, and a column
/// past 2 GiB would overflow them.
const BYTE_LIMIT: usize = 1 << 30;

pub(crate) struct ArrowSink {
    chunk_size: Option<NonZeroUsize>,
    byte_limit: usize,
    keep: Option<HashSet<String>>,
    block: Option<OpenBlock>,
    blocks: usize,
    chunks: VecDeque<Chunk>,
}

impl Default for ArrowSink {
    fn default() -> Self {
        Self {
            chunk_size: None,
            byte_limit: BYTE_LIMIT,
            keep: None,
            block: None,
            blocks: 0,
            chunks: VecDeque::new(),
        }
    }
}

pub(crate) type Table = (String, Vec<RecordBatch>);

/// A batch, the name of the block it came from, and which block that was:
/// two blocks of one name are told apart by nothing else.
pub(crate) type Chunk = (String, usize, RecordBatch);

struct OpenBlock {
    name: String,
    ordinal: usize,
    kept: Vec<bool>,
    columns: Vec<String>,
    builders: Vec<StringBuilder>,
    rows: usize,
    cut: bool,
}

impl ArrowSink {
    /// A sink cutting a batch every `chunk_size` rows, keeping only the
    /// columns `keep` names when it names any.
    pub(crate) fn new(chunk_size: Option<NonZeroUsize>, keep: Option<HashSet<String>>) -> Self {
        Self {
            chunk_size,
            keep,
            ..Self::default()
        }
    }

    pub(crate) fn pop(&mut self) -> Option<Chunk> {
        self.chunks.pop_front()
    }

    #[cfg(test)]
    pub(crate) fn with_byte_limit(mut self, byte_limit: usize) -> Self {
        self.byte_limit = byte_limit;
        self
    }

    pub(crate) fn into_tables(self) -> Vec<Table> {
        let mut tables: Vec<(usize, Table)> = Vec::new();
        for (name, ordinal, batch) in self.chunks {
            match tables.last_mut() {
                Some((last, (_, batches))) if *last == ordinal => batches.push(batch),
                _ => tables.push((ordinal, (name, vec![batch]))),
            }
        }
        tables.into_iter().map(|(_, table)| table).collect()
    }

    fn opened(&self, name: &str, columns: &[String]) -> OpenBlock {
        let kept: Vec<bool> = columns
            .iter()
            .map(|column| self.keep.as_ref().is_none_or(|keep| keep.contains(column)))
            .collect();
        let columns: Vec<String> = columns
            .iter()
            .zip(&kept)
            .filter(|(_, kept)| **kept)
            .map(|(column, _)| column.clone())
            .collect();
        OpenBlock {
            name: name.to_string(),
            ordinal: self.blocks,
            kept,
            builders: builders_for(&columns),
            columns,
            rows: 0,
            cut: false,
        }
    }

    fn cut(&mut self) -> Result<(), Error> {
        let Some(block) = self.block.as_mut() else {
            return Ok(());
        };
        let builders = std::mem::replace(&mut block.builders, builders_for(&block.columns));
        let batch = record_batch(&block.columns, builders, std::mem::take(&mut block.rows))?;
        block.cut = true;
        self.chunks
            .push_back((block.name.clone(), block.ordinal, batch));
        Ok(())
    }

    fn is_full(&self) -> bool {
        let Some(block) = &self.block else {
            return false;
        };
        self.chunk_size.is_some_and(|size| block.rows >= size.get())
            || block
                .builders
                .iter()
                .any(|builder| builder.values_slice().len() >= self.byte_limit)
    }
}

impl Sink for ArrowSink {
    fn open(&mut self, name: &str, columns: &[String]) {
        self.block = Some(self.opened(name, columns));
        self.blocks += 1;
    }

    fn row<'v>(&mut self, values: impl Iterator<Item = &'v str>) -> Result<(), Error> {
        let block = self
            .block
            .as_mut()
            .expect("the parser opens a block before its first row");
        let kept = values
            .zip(&block.kept)
            .filter(|(_, kept)| **kept)
            .map(|(value, _)| value);
        for (builder, value) in block.builders.iter_mut().zip(kept) {
            builder.append_value(value);
        }
        block.rows += 1;
        if self.is_full() {
            self.cut()?;
        }
        Ok(())
    }

    fn close(&mut self, name: String, columns: Vec<String>) -> Result<(), Error> {
        if self.block.is_none() {
            self.block = Some(self.opened(&name, &columns));
            self.blocks += 1;
        }
        if self
            .block
            .as_ref()
            .is_some_and(|block| !block.cut || block.rows > 0)
        {
            self.cut()?;
        }
        self.block = None;
        Ok(())
    }
}

fn builders_for(columns: &[String]) -> Vec<StringBuilder> {
    columns.iter().map(|_| StringBuilder::new()).collect()
}

fn record_batch(
    column_names: &[String],
    mut builders: Vec<StringBuilder>,
    rows: usize,
) -> Result<RecordBatch, Error> {
    let fields: Vec<Field> = column_names
        .iter()
        .map(|name| Field::new(name, DataType::Utf8, false))
        .collect();
    let schema = Arc::new(Schema::new(fields));
    let arrays: Vec<ArrayRef> = builders
        .iter_mut()
        .map(|builder| Arc::new(builder.finish()) as ArrayRef)
        .collect();

    let options = RecordBatchOptions::new().with_row_count(Some(rows));
    Ok(RecordBatch::try_new_with_options(schema, arrays, &options)?)
}

#[cfg(test)]
pub(crate) fn single(tables: Vec<Table>) -> Vec<(String, RecordBatch)> {
    tables
        .into_iter()
        .map(|(name, mut batches)| {
            assert_eq!(batches.len(), 1, "block '{name}' came as several batches");
            (name, batches.remove(0))
        })
        .collect()
}

#[cfg(test)]
pub(crate) fn build_record_batch(
    column_names: &[String],
    rows: &[Vec<String>],
) -> Result<RecordBatch, Error> {
    let mut sink = ArrowSink::default();
    sink.open("", column_names);
    for row in rows {
        sink.row(row.iter().map(String::as_str))?;
    }
    sink.close(String::new(), column_names.to_vec())?;
    Ok(sink.pop().expect("a closed block is a batch").2)
}

#[cfg(test)]
pub(crate) fn rows_of_record_batch(
    batch: &RecordBatch,
) -> Result<(Vec<String>, Vec<Vec<String>>), Error> {
    let names: Vec<String> = batch
        .schema()
        .fields()
        .iter()
        .map(|field| field.name().clone())
        .collect();
    let columns = string_columns(batch)?;
    let rows = (0..batch.num_rows())
        .map(|row| columns.iter().map(|column| value_at(column, row)).collect())
        .collect();
    Ok((names, rows))
}

pub(crate) fn string_columns(batch: &RecordBatch) -> Result<Vec<&StringArray>, Error> {
    batch
        .columns()
        .iter()
        .zip(batch.schema().fields())
        .map(|(column, field)| {
            column
                .as_any()
                .downcast_ref::<StringArray>()
                .ok_or_else(|| {
                    unwritable(format!(
                        "column '{}' is {}, and a text format writes Utf8 only",
                        field.name(),
                        field.data_type()
                    ))
                })
        })
        .collect()
}

#[cfg(test)]
fn value_at(column: &StringArray, row: usize) -> String {
    if column.is_null(row) {
        String::new()
    } else {
        column.value(row).to_string()
    }
}

#[cfg(test)]
mod tests {
    use arrow::array::AsArray;

    use super::*;

    fn make_rows(data: &[&[&str]]) -> Vec<Vec<String>> {
        data.iter()
            .map(|row| row.iter().map(std::string::ToString::to_string).collect())
            .collect()
    }

    fn names(of: &[&str]) -> Vec<String> {
        of.iter().map(std::string::ToString::to_string).collect()
    }

    #[test]
    fn a_batch_keeps_every_value_where_it_was() {
        let rows = make_rows(&[&["10.5", "1024.0", "a"], &["20.1", "2048.0", "b"]]);

        let batch = build_record_batch(&names(&["rot", "x", "name"]), &rows).unwrap();

        assert_eq!(batch.num_rows(), 2);
        assert_eq!(batch.num_columns(), 3);
        assert_eq!(batch.schema().field(1).name(), "x");
        assert_eq!(batch.column(1).as_string::<i32>().value(0), "1024.0");
        assert_eq!(batch.column(2).as_string::<i32>().value(1), "b");
    }

    #[test]
    fn a_block_with_no_columns_is_a_batch_of_no_rows() {
        let batch = build_record_batch(&[], &[]).unwrap();

        assert_eq!(batch.num_rows(), 0);
        assert_eq!(batch.num_columns(), 0);
    }

    #[test]
    fn a_column_with_no_rows_keeps_its_name() {
        let batch = build_record_batch(&names(&["rot"]), &[]).unwrap();

        assert_eq!(batch.num_rows(), 0);
        assert_eq!(batch.schema().field(0).name(), "rot");
    }
}
