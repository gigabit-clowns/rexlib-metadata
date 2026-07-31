use super::StarError;

#[derive(Debug, PartialEq)]
pub(crate) enum Token {
    DataBlock(String), // "data_particles" → DataBlock("particles")
    Loop,              // "loop_"
    Column(String),    // "_rlnAngleRot"   → Column("_rlnAngleRot")
    Value(String),     // any data value (bare or quoted)
}

pub(crate) fn tokenize_line(
    line: &str,
    path: &str,
    line_num: usize,
) -> Result<Vec<Token>, StarError> {
    let clean_line = line.split('#').next().unwrap_or("").trim();
    if clean_line.is_empty() {
        return Ok(vec![]);
    } else if clean_line.starts_with("data_") {
        ensure_single_word(clean_line, path, line_num, "data block header")?;
        return Ok(vec![Token::DataBlock(clean_line.strip_prefix("data_").expect("guaranteed by starts_with").to_string())]);
    } else if clean_line.split_whitespace().next() == Some("loop_") {
        ensure_single_word(clean_line, path, line_num, "loop_ keyword")?;
        return Ok(vec![Token::Loop]);
    } else if clean_line.starts_with("_") {
        ensure_single_word(clean_line, path, line_num, "column name")?;
        return Ok(vec![Token::Column(clean_line.to_string())]);
    } else {
        return tokenize_values(line, path, line_num);
    }
}

fn tokenize_values(line: &str, path: &str, line_num: usize) -> Result<Vec<Token>, StarError> {
    let mut tokens: Vec<Token> = vec![];
    let mut current = String::new();
    let mut in_quote: Option<char> = None;

    for ch in line.chars() {
        if let Some(q) = in_quote {
            in_quote = process_quoted_char(ch, q, &mut current, &mut tokens);
        } else {
            let (new_quote, stop) = process_unquoted_char(ch, &mut current, &mut tokens);
            in_quote = new_quote;
            if stop {
                break;
            }
        }
    }

    if in_quote.is_some() {
        return Err(StarError::Parse {
            path: path.to_string(),
            line: line_num,
            message: "unterminated quoted value".to_string(),
        });
    }
    flush_bare(&mut current, &mut tokens);
    Ok(tokens)
}

fn process_quoted_char(ch: char, quote: char, current: &mut String, tokens: &mut Vec<Token>) -> Option<char> {
    if ch == quote {
        tokens.push(Token::Value(std::mem::take(current)));
        None
    } else {
        current.push(ch);
        Some(quote)
    }
}

fn process_unquoted_char(ch: char, current: &mut String, tokens: &mut Vec<Token>) -> (Option<char>, bool) {
    match ch {
        '#' => (None, true),
        '"' | '\'' => {
            flush_bare(current, tokens);
            (Some(ch), false)
        }
        c if c.is_whitespace() => {
            flush_bare(current, tokens);
            (None, false)
        }
        c => {
            current.push(c);
            (None, false)
        }
    }
}

fn flush_bare(current: &mut String, tokens: &mut Vec<Token>) {
    if !current.is_empty() {
        tokens.push(Token::Value(std::mem::take(current)));
    }
}

fn ensure_single_word(clean_line: &str, path: &str, line_num: usize, context: &str) -> Result<(), StarError> {
    if clean_line.split_whitespace().count() > 1 {
        return Err(StarError::Parse {
            path: path.to_string(),
            line: line_num,
            message: format!("Unexpected tokens after {}: '{}'", context, clean_line),
        });
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tok(line: &str) -> Vec<Token> {
        tokenize_line(line, "test.star", 1).unwrap()
    }

    #[test]
    fn empty_line() {
        assert!(tok("").is_empty());
    }

    #[test]
    fn blank_with_spaces() {
        assert!(tok("   ").is_empty());
    }

    #[test]
    fn comment() {
        assert!(tok("# this is a comment").is_empty());
    }

    #[test]
    fn data_block() {
        assert_eq!(tok("data_particles"), vec![Token::DataBlock("particles".into())]);
    }

    #[test]
    fn data_block_with_comment() {
        assert_eq!(tok("data_particles # Some comment"), vec![Token::DataBlock("particles".into())]);
    }

    #[test]
    fn loop_keyword() {
        assert_eq!(tok("loop_"), vec![Token::Loop]);
    }

    #[test]
    fn column_name() {
        assert_eq!(tok("_rlnAngleRot"), vec![Token::Column("_rlnAngleRot".into())]);
    }

    #[test]
    fn bare_values() {
        assert_eq!(
            tok("10.5 20.1 1024.0"),
            vec![
                Token::Value("10.5".into()),
                Token::Value("20.1".into()),
                Token::Value("1024.0".into()),
            ]
        );
    }

    #[test]
    fn double_quoted_value_with_spaces() {
        assert_eq!(
            tok(r#"10.5 "path with spaces/file.mrcs" 512.0"#),
            vec![
                Token::Value("10.5".into()),
                Token::Value("path with spaces/file.mrcs".into()),
                Token::Value("512.0".into()),
            ]
        );
    }

    #[test]
    fn single_quoted_value_with_spaces() {
        assert_eq!(
            tok("10.5 'path with spaces/file.mrcs' 512.0"),
            vec![
                Token::Value("10.5".into()),
                Token::Value("path with spaces/file.mrcs".into()),
                Token::Value("512.0".into()),
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
        assert_eq!(tok("loop_extra"), vec![Token::Value("loop_extra".into())]);
    }

    #[test]
    fn column_with_trailing_tokens_is_error() {
        assert!(tokenize_line("_rlnAngleRot extra", "test.star", 1).is_err());
    }

    #[test]
    fn column_with_comment() {
        assert_eq!(tok("_rlnAngleRot # comment"), vec![Token::Column("_rlnAngleRot".into())]);
    }
}
