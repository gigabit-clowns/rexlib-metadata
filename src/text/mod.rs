// SPDX-License-Identifier: LGPL-2.1-or-later

pub(crate) mod builder;
pub(crate) mod parser;

#[derive(Debug, PartialEq)]
pub(crate) enum Token {
    DataBlock(String),
    Loop,
    Column(String),
    Value(String),
}
