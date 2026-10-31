// SPDX-License-Identifier: LGPL-2.1-or-later

pub(crate) mod builder;
pub(crate) mod parser;

/// One piece of a line, borrowed from it: a row of a million lines then
/// allocates nothing per value until the builder copies it into Arrow.
#[derive(Debug, PartialEq)]
pub(crate) enum Token<'a> {
    DataBlock(&'a str),
    Loop,
    Column(&'a str),
    Value(&'a str),
}
