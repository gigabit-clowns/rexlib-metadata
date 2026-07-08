mod star;

use pyo3::prelude::*;
use pyo3_arrow::PyRecordBatch;

#[pyfunction]
fn version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

#[pyfunction]
fn _star_read_schema(path: &str) -> PyResult<(String, Vec<String>)> {
    let schema = star::read_schema(path)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e))?;
    let column_names = schema.columns.into_iter().map(|c| c.name).collect();
    Ok((schema.table_name, column_names))
}

#[pyfunction]
fn _star_read(path: &str) -> PyResult<PyRecordBatch> {
    star::read_all(path)
        .map(PyRecordBatch::new)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e))
}

#[pymodule]
fn _rexlib(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(version, m)?)?;
    m.add_function(wrap_pyfunction!(_star_read_schema, m)?)?;
    m.add_function(wrap_pyfunction!(_star_read, m)?)?;
    Ok(())
}
