#![warn(clippy::cognitive_complexity)]

mod error;
mod star;
mod text;

use pyo3::prelude::*;
use pyo3_arrow::PyRecordBatch;

#[pyfunction]
fn version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

#[pyfunction]
fn _star_read_tables(path: &str) -> PyResult<Vec<(String, PyRecordBatch)>> {
    star::read_tables(path)
        .map(|tables| {
            tables
                .into_iter()
                .map(|(name, batch)| (name, PyRecordBatch::new(batch)))
                .collect()
        })
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))
}

#[pymodule]
fn _rexlib(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(version, m)?)?;
    m.add_function(wrap_pyfunction!(_star_read_tables, m)?)?;
    Ok(())
}
