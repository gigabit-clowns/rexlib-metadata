#[derive(Debug, thiserror::Error)]
pub enum Error {
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

pub fn parse_error(path: &str, line: usize, message: impl Into<String>) -> Error {
    Error::Parse {
        path: path.to_string(),
        line,
        message: message.into(),
    }
}
