// SPDX-License-Identifier: LGPL-2.1-or-later

#[derive(Debug, thiserror::Error)]
pub(crate) enum Error {
    #[error("'{path}': {source}")]
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

    #[error("{message}")]
    Unwritable { message: String },

    #[error("{0}")]
    Arrow(#[from] arrow::error::ArrowError),
}

pub(crate) fn parse_error(path: &str, line: usize, message: impl Into<String>) -> Error {
    Error::Parse {
        path: path.to_string(),
        line,
        message: message.into(),
    }
}

pub(crate) fn unwritable(message: impl Into<String>) -> Error {
    Error::Unwritable {
        message: message.into(),
    }
}
