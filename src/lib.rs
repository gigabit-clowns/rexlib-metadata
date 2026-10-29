// SPDX-License-Identifier: LGPL-2.1-or-later

#![cfg_attr(test, allow(clippy::indexing_slicing, clippy::unwrap_used))]

mod error;
mod star;
mod text;

use std::collections::HashSet;
use std::io::ErrorKind;
use std::num::NonZeroUsize;

use arrow::record_batch::RecordBatch;
use pyo3::exceptions::{
    PyFileNotFoundError, PyOSError, PyPermissionError, PyRuntimeError, PyValueError,
};
use pyo3::prelude::*;
use pyo3_arrow::PyRecordBatch;

use crate::error::Error;

#[pyfunction]
fn version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

#[pyfunction]
#[pyo3(signature = (path, columns=None))]
fn _star_read_tables(
    py: Python<'_>,
    path: &str,
    columns: Option<HashSet<String>>,
) -> PyResult<Vec<(String, PyRecordBatch)>> {
    let tables = py
        .detach(|| star::read_tables(path, columns))
        .map_err(to_python_error)?;
    Ok(tables
        .into_iter()
        .map(|(name, batch)| (name, PyRecordBatch::new(batch)))
        .collect())
}

#[pyfunction]
#[pyo3(signature = (path, chunk_size, columns=None))]
fn _star_read_chunks(
    path: &str,
    chunk_size: usize,
    columns: Option<HashSet<String>>,
) -> PyResult<StarChunks> {
    let chunk_size = NonZeroUsize::new(chunk_size)
        .ok_or_else(|| PyValueError::new_err("chunk_size has to be at least one row"))?;
    let chunks = star::Chunks::open(path, chunk_size, columns).map_err(to_python_error)?;
    Ok(StarChunks {
        chunks: Some(chunks),
    })
}

#[pyclass(module = "rexlib_metadata._rexlib")]
struct StarChunks {
    chunks: Option<star::Chunks>,
}

#[pymethods]
impl StarChunks {
    fn __iter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __next__(&mut self, py: Python<'_>) -> PyResult<Option<(String, PyRecordBatch)>> {
        let Some(chunks) = self.chunks.as_mut() else {
            return Ok(None);
        };
        match py.detach(|| chunks.next()) {
            Some(Ok((name, batch))) => Ok(Some((name, PyRecordBatch::new(batch)))),
            Some(Err(error)) => {
                self.chunks = None;
                Err(to_python_error(error))
            }
            None => {
                self.chunks = None;
                Ok(None)
            }
        }
    }
}

#[pyfunction]
fn _star_write(py: Python<'_>, path: &str, tables: Vec<(String, PyRecordBatch)>) -> PyResult<()> {
    let owned: Vec<(String, RecordBatch)> = tables
        .into_iter()
        .map(|(name, batch)| (name, batch.into_inner()))
        .collect();
    py.detach(|| star::writer::write_tables(path, &owned))
        .map_err(to_python_error)
}

fn to_python_error(error: Error) -> PyErr {
    let message = error.to_string();
    match error {
        Error::Io { source, .. } => match source.kind() {
            ErrorKind::NotFound => PyFileNotFoundError::new_err(message),
            ErrorKind::PermissionDenied => PyPermissionError::new_err(message),
            _ => PyOSError::new_err(message),
        },
        Error::Parse { .. } | Error::Unwritable { .. } => PyValueError::new_err(message),
        Error::Arrow(_) => PyRuntimeError::new_err(message),
    }
}

#[pymodule]
fn _rexlib(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(version, m)?)?;
    m.add_function(wrap_pyfunction!(_star_read_tables, m)?)?;
    m.add_function(wrap_pyfunction!(_star_read_chunks, m)?)?;
    m.add_function(wrap_pyfunction!(_star_write, m)?)?;
    m.add_class::<StarChunks>()?;
    Ok(())
}
