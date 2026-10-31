// SPDX-License-Identifier: LGPL-2.1-or-later

use crate::error::{Error, parse_error};
use crate::text::Token;

pub(crate) fn tokenize_line<'a>(
    line: &'a str,
    path: &str,
    line_num: usize,
) -> Result<Vec<Token<'a>>, Error> {
    match line.trim_start().bytes().next() {
        None | Some(b'#' | b'd' | b'l' | b'_') => keyword_or_values(line, path, line_num),
        Some(_) => tokenize_values(line, path, line_num),
    }
}

fn keyword_or_values<'a>(
    line: &'a str,
    path: &str,
    line_num: usize,
) -> Result<Vec<Token<'a>>, Error> {
    let clean_line = line.split_once('#').map_or(line, |(head, _)| head).trim();
    if clean_line.is_empty() {
        Ok(vec![])
    } else if let Some(name) = clean_line.strip_prefix("data_") {
        ensure_single_word(clean_line, path, line_num, "data block header")?;
        Ok(vec![Token::DataBlock(name)])
    } else if clean_line.split_whitespace().next() == Some("loop_") {
        ensure_single_word(clean_line, path, line_num, "loop_ keyword")?;
        Ok(vec![Token::Loop])
    } else if clean_line.starts_with('_') {
        tokenize_tag(line, clean_line, path, line_num)
    } else {
        tokenize_values(line, path, line_num)
    }
}

fn tokenize_tag<'a>(
    line: &'a str,
    clean_line: &'a str,
    path: &str,
    line_num: usize,
) -> Result<Vec<Token<'a>>, Error> {
    let name = clean_line
        .split_whitespace()
        .next()
        .expect("guaranteed by starts_with('_')");
    let after_name = line
        .find(name)
        .map(|at| at + name.len())
        .expect("the name came from this line");
    let mut tokens = vec![Token::Column(name)];
    tokens.extend(tokenize_values(&line[after_name..], path, line_num)?);
    Ok(tokens)
}

/// Where the scan of a line is: between values, inside a bare one that
/// began at a byte, or inside a quoted one whose text begins at a byte.
#[derive(Clone, Copy)]
enum Scan {
    Between,
    Bare(usize),
    Quoted(char, usize),
}

fn tokenize_values<'a>(
    line: &'a str,
    path: &str,
    line_num: usize,
) -> Result<Vec<Token<'a>>, Error> {
    match plain_values(line) {
        Some(tokens) => Ok(tokens),
        None => scanned_values(line, path, line_num),
    }
}

/// Every value of `line`, quoted ones included, one character at a time.
fn scanned_values<'a>(line: &'a str, path: &str, line_num: usize) -> Result<Vec<Token<'a>>, Error> {
    let mut tokens = Vec::new();
    let mut scan = Scan::Between;
    for (at, ch) in line.char_indices() {
        scan = match scan {
            Scan::Quoted(quote, from) => quoted(line, quote, from, at, ch, &mut tokens),
            Scan::Between if ch == '#' => break,
            _ => unquoted(line, scan, at, ch, &mut tokens),
        };
    }
    match scan {
        Scan::Quoted(..) => Err(parse_error(path, line_num, "unterminated quoted value")),
        Scan::Bare(from) => {
            tokens.push(Token::Value(&line[from..]));
            Ok(tokens)
        }
        Scan::Between => Ok(tokens),
    }
}

/// The values of a line split on ASCII whitespace, or None for a line the
/// scan has to read: one with a quote, a character beyond ASCII, or a
/// vertical tab, which `char::is_whitespace` counts and this split does not.
fn plain_values(line: &str) -> Option<Vec<Token<'_>>> {
    let mut tokens = Vec::new();
    for value in line.split_ascii_whitespace() {
        if value.starts_with('#') {
            break;
        }
        if !value
            .bytes()
            .all(|byte| byte.is_ascii() && !matches!(byte, b'"' | b'\'' | b'\x0B'))
        {
            return None;
        }
        tokens.push(Token::Value(value));
    }
    Some(tokens)
}

fn quoted<'a>(
    line: &'a str,
    quote: char,
    from: usize,
    at: usize,
    ch: char,
    tokens: &mut Vec<Token<'a>>,
) -> Scan {
    if ch == quote {
        tokens.push(Token::Value(&line[from..at]));
        Scan::Between
    } else {
        Scan::Quoted(quote, from)
    }
}

fn unquoted<'a>(
    line: &'a str,
    scan: Scan,
    at: usize,
    ch: char,
    tokens: &mut Vec<Token<'a>>,
) -> Scan {
    let ends_bare = ch == '"' || ch == '\'' || ch.is_whitespace();
    if let (Scan::Bare(from), true) = (scan, ends_bare) {
        tokens.push(Token::Value(&line[from..at]));
    }
    match ch {
        '"' | '\'' => Scan::Quoted(ch, at + ch.len_utf8()),
        c if c.is_whitespace() => Scan::Between,
        _ if matches!(scan, Scan::Bare(_)) => scan,
        _ => Scan::Bare(at),
    }
}

fn ensure_single_word(
    clean_line: &str,
    path: &str,
    line_num: usize,
    context: &str,
) -> Result<(), Error> {
    if clean_line.split_whitespace().count() > 1 {
        return Err(parse_error(
            path,
            line_num,
            format!("unexpected tokens after {context}: '{clean_line}'"),
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tok(line: &str) -> Vec<Token<'_>> {
        tokenize_line(line, "test.star", 1).unwrap()
    }

    #[test]
    fn a_plain_line_reads_as_the_full_scan_reads_it() {
        let lines = [
            "1.0 2.0 abc",
            "   leading and trailing   ",
            "tab\tseparated\t\tvalues",
            "a#b c",
            "a #comment",
            "#only a comment",
            "x\ry",
            "1 2 # it's a comment",
            "",
        ];
        for line in lines {
            assert_eq!(
                plain_values(line),
                Some(scanned_values(line, "test.star", 1).unwrap()),
                "{line:?}"
            );
        }
    }

    #[test]
    fn a_line_with_a_quote_a_vertical_tab_or_beyond_ascii_is_scanned() {
        for line in ["'a b' c", "a\"b", "a\x0Bb", "ñ b"] {
            assert!(plain_values(line).is_none(), "{line:?}");
        }
        assert_eq!(tok("a\x0Bb"), vec![Token::Value("a"), Token::Value("b")]);
    }

    #[test]
    fn empty_line() {
        assert_eq!(tok(""), []);
    }

    #[test]
    fn blank_with_spaces() {
        assert_eq!(tok("   "), []);
    }

    #[test]
    fn comment() {
        assert_eq!(tok("# this is a comment"), []);
    }

    #[test]
    fn data_block() {
        assert_eq!(tok("data_particles"), vec![Token::DataBlock("particles")]);
    }

    #[test]
    fn data_block_with_comment() {
        assert_eq!(
            tok("data_particles # Some comment"),
            vec![Token::DataBlock("particles")]
        );
    }

    #[test]
    fn loop_keyword() {
        assert_eq!(tok("loop_"), vec![Token::Loop]);
    }

    #[test]
    fn column_name() {
        assert_eq!(tok("_rlnAngleRot"), vec![Token::Column("_rlnAngleRot")]);
    }

    #[test]
    fn bare_values() {
        assert_eq!(
            tok("10.5 20.1 1024.0"),
            vec![
                Token::Value("10.5"),
                Token::Value("20.1"),
                Token::Value("1024.0"),
            ]
        );
    }

    #[test]
    fn double_quoted_value_with_spaces() {
        assert_eq!(
            tok(r#"10.5 "path with spaces/file.mrcs" 512.0"#),
            vec![
                Token::Value("10.5"),
                Token::Value("path with spaces/file.mrcs"),
                Token::Value("512.0"),
            ]
        );
    }

    #[test]
    fn single_quoted_value_with_spaces() {
        assert_eq!(
            tok("10.5 'path with spaces/file.mrcs' 512.0"),
            vec![
                Token::Value("10.5"),
                Token::Value("path with spaces/file.mrcs"),
                Token::Value("512.0"),
            ]
        );
    }

    #[test]
    fn unterminated_double_quote_is_error() {
        assert!(tokenize_line(r#"10.5 "unterminated"#, "test.star", 1).is_err());
    }

    #[test]
    fn unterminated_single_quote_is_error() {
        assert!(tokenize_line("10.5 'unterminated", "test.star", 1).is_err());
    }

    #[test]
    fn data_block_with_trailing_tokens_is_error() {
        assert!(tokenize_line("data_particles extra", "test.star", 1).is_err());
    }

    #[test]
    fn loop_with_trailing_tokens_is_error() {
        assert!(tokenize_line("loop_ extra", "test.star", 1).is_err());
    }

    #[test]
    fn loop_extra_is_value() {
        assert_eq!(tok("loop_extra"), vec![Token::Value("loop_extra")]);
    }

    #[test]
    fn a_bare_name_is_a_column() {
        assert_eq!(tok("_rlnAngleRot"), vec![Token::Column("_rlnAngleRot")]);
    }

    #[test]
    fn a_name_and_a_value_are_a_tag() {
        assert_eq!(
            tok("_rlnFinalResolution                        16.363636"),
            vec![
                Token::Column("_rlnFinalResolution"),
                Token::Value("16.363636"),
            ]
        );
    }

    #[test]
    fn a_tag_value_may_be_quoted_and_hold_a_hash() {
        assert_eq!(
            tok("_rlnMaskName 'mask #2.mrc'"),
            vec![Token::Column("_rlnMaskName"), Token::Value("mask #2.mrc"),]
        );
    }

    #[test]
    fn a_comment_after_a_tag_value_is_dropped() {
        assert_eq!(
            tok("_rlnMaskName mask.mrc # which one"),
            vec![Token::Column("_rlnMaskName"), Token::Value("mask.mrc"),]
        );
    }

    #[test]
    fn a_hash_inside_a_bare_value_belongs_to_the_value() {
        assert_eq!(
            tok("mask#2.mrc 5"),
            vec![Token::Value("mask#2.mrc"), Token::Value("5"),]
        );
    }

    #[test]
    fn a_hash_after_whitespace_starts_a_comment() {
        assert_eq!(tok("5 # how many"), vec![Token::Value("5")]);
    }

    #[test]
    fn an_empty_quoted_value_stays_a_value() {
        assert_eq!(
            tok("'' . 5"),
            vec![Token::Value(""), Token::Value("."), Token::Value("5"),]
        );
    }

    #[test]
    fn column_with_comment() {
        assert_eq!(
            tok("_rlnAngleRot # comment"),
            vec![Token::Column("_rlnAngleRot")]
        );
    }
}
