#![cfg_attr(test, allow(clippy::indexing_slicing, clippy::unwrap_used))]

mod error;
mod star;
mod text;

use std::io::ErrorKind;

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
fn _star_read_tables(py: Python<'_>, path: &str) -> PyResult<Vec<(String, PyRecordBatch)>> {
    let tables = py
        .detach(|| star::read_tables(path))
        .map_err(to_python_error)?;
    Ok(tables
        .into_iter()
        .map(|(name, batch)| (name, PyRecordBatch::new(batch)))
        .collect())
}

fn to_python_error(error: Error) -> PyErr {
    let message = error.to_string();
    match error {
        Error::Io { source, .. } => match source.kind() {
            ErrorKind::NotFound => PyFileNotFoundError::new_err(message),
            ErrorKind::PermissionDenied => PyPermissionError::new_err(message),
            _ => PyOSError::new_err(message),
        },
        Error::Parse { .. } => PyValueError::new_err(message),
        Error::Arrow(_) => PyRuntimeError::new_err(message),
    }
}

#[pymodule]
fn _rexlib(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(version, m)?)?;
    m.add_function(wrap_pyfunction!(_star_read_tables, m)?)?;
    Ok(())
}
