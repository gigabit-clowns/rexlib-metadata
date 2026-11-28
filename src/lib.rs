// SPDX-License-Identifier: LGPL-2.1-or-later

mod error;
mod star;
mod text;

use std::collections::HashSet;
use std::io::ErrorKind;

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
#[pyo3(name = "_star_read_tables", signature = (path, columns=None))]
fn star_read_tables(
	py: Python<'_>,
	path: &str,
	columns: Option<HashSet<String>>,
) -> PyResult<Vec<(String, Vec<PyRecordBatch>)>> {
	let tables = py
		.detach(|| star::read_tables(path, columns))
		.map_err(to_python_error)?;
	Ok(tables
		.into_iter()
		.map(|(name, batches)| (name, batches.into_iter().map(PyRecordBatch::new).collect()))
		.collect())
}

#[pyfunction]
#[pyo3(name = "_star_read_headers")]
fn star_read_headers(py: Python<'_>, path: &str) -> PyResult<Vec<(String, Vec<String>)>> {
	py.detach(|| star::read_headers(path))
		.map_err(to_python_error)
}

#[pyfunction]
#[pyo3(name = "_star_read_chunks", signature = (path, chunk_size, columns=None))]
fn star_read_chunks(
	py: Python<'_>,
	path: &str,
	chunk_size: usize,
	columns: Option<HashSet<String>>,
) -> PyResult<StarChunks> {
	let chunks = py
		.detach(|| star::Chunks::open(path, chunk_size, columns))
		.map_err(to_python_error)?;
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

	fn __next__(&mut self, py: Python<'_>) -> PyResult<Option<(String, usize, PyRecordBatch)>> {
		let Some(chunks) = self.chunks.as_mut() else {
			return Ok(None);
		};
		match py.detach(|| chunks.next()) {
			Some(Ok((name, ordinal, batch))) => {
				Ok(Some((name, ordinal, PyRecordBatch::new(batch))))
			}
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
#[pyo3(name = "_star_write", signature = (path, tables, header=None))]
fn star_write(
	py: Python<'_>,
	path: &str,
	tables: Vec<(String, Vec<PyRecordBatch>)>,
	header: Option<&str>,
) -> PyResult<()> {
	let owned: Vec<(String, Vec<RecordBatch>)> = tables
		.into_iter()
		.map(|(name, batches)| {
			let batches = batches.into_iter().map(PyRecordBatch::into_inner).collect();
			(name, batches)
		})
		.collect();
	py.detach(|| star::writer::write_tables(path, header, &owned))
		.map_err(to_python_error)
}

#[pyfunction]
#[pyo3(name = "_star_stream", signature = (path, header=None))]
fn star_stream(py: Python<'_>, path: &str, header: Option<&str>) -> PyResult<StarStream> {
	let stream = py
		.detach(|| star::writer::Stream::create(path, header))
		.map_err(to_python_error)?;
	Ok(StarStream {
		stream: Some(stream),
	})
}

#[pyclass(module = "rexlib_metadata._rexlib")]
struct StarStream {
	stream: Option<star::writer::Stream>,
}

impl StarStream {
	fn open(&mut self) -> PyResult<&mut star::writer::Stream> {
		self.stream
			.as_mut()
			.ok_or_else(|| PyValueError::new_err("the STAR file is already closed"))
	}
}

#[pymethods]
impl StarStream {
	fn begin(&mut self, py: Python<'_>, name: &str, columns: Vec<String>) -> PyResult<()> {
		let stream = self.open()?;
		py.detach(|| stream.begin(name, columns))
			.map_err(to_python_error)
	}

	fn write(&mut self, py: Python<'_>, batch: PyRecordBatch) -> PyResult<()> {
		let stream = self.open()?;
		let batch = batch.into_inner();
		py.detach(|| stream.write(&batch)).map_err(to_python_error)
	}

	fn close(&mut self, py: Python<'_>) -> PyResult<()> {
		match self.stream.take() {
			Some(stream) => py.detach(|| stream.finish()).map_err(to_python_error),
			None => Ok(()),
		}
	}

	fn abandon(&mut self, py: Python<'_>) {
		let stream = self.stream.take();
		py.detach(|| drop(stream));
	}

	fn __enter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
		slf
	}

	fn __exit__(
		&mut self,
		py: Python<'_>,
		kind: Option<&Bound<'_, PyAny>>,
		_value: Option<&Bound<'_, PyAny>>,
		_traceback: Option<&Bound<'_, PyAny>>,
	) -> PyResult<bool> {
		match kind {
			None => self.close(py)?,
			Some(_) => self.abandon(py),
		}
		Ok(false)
	}
}

fn to_python_error(error: Error) -> PyErr {
	let message = error.to_string();
	match error {
		Error::Io { path, source } => {
			let reason = source.to_string();
			let reason = source
				.raw_os_error()
				.and_then(|code| reason.strip_suffix(&format!(" (os error {code})")))
				.unwrap_or(&reason)
				.to_string();
			let arguments = (source.raw_os_error(), reason, path);
			match source.kind() {
				ErrorKind::NotFound => PyFileNotFoundError::new_err(arguments),
				ErrorKind::PermissionDenied => PyPermissionError::new_err(arguments),
				_ => PyOSError::new_err(arguments),
			}
		}
		Error::Parse { .. } | Error::Unwritable { .. } | Error::Argument(_) => {
			PyValueError::new_err(message)
		}
		Error::Arrow(_) => PyRuntimeError::new_err(message),
	}
}

#[pymodule(name = "_rexlib")]
fn rexlib(m: &Bound<'_, PyModule>) -> PyResult<()> {
	m.add_function(wrap_pyfunction!(version, m)?)?;
	m.add_function(wrap_pyfunction!(star_read_tables, m)?)?;
	m.add_function(wrap_pyfunction!(star_read_chunks, m)?)?;
	m.add_function(wrap_pyfunction!(star_read_headers, m)?)?;
	m.add_function(wrap_pyfunction!(star_write, m)?)?;
	m.add_function(wrap_pyfunction!(star_stream, m)?)?;
	m.add_class::<StarChunks>()?;
	m.add_class::<StarStream>()?;
	Ok(())
}
