// SPDX-License-Identifier: LGPL-2.1-or-later

pub(crate) mod builder;
pub(crate) mod parser;

use crate::error::Error;

/// The longest line read, in bytes.
pub(crate) const LINE_LIMIT: usize = 1 << 30;

/// One piece of a line, borrowed from it.
#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) enum Token<'a> {
	DataBlock(&'a str),
	Loop,
	Column(&'a str),
	Value(&'a str),
}

/// Splits the lines of one text format into tokens.
pub(crate) trait Lexer {
	fn tokenize<'a>(
		&self,
		line: &'a str,
		path: &str,
		line_num: usize,
	) -> Result<Vec<Token<'a>>, Error>;

	/// Whether `line` can only be a row of values, told without tokenizing it.
	fn is_row(&self, line: &str) -> bool;
}
