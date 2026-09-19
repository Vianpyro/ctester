//! Grading: turns sandbox output into the verdict students see. The messages are shown to
//! students as they are, so a change to one is a change to the course.

use std::collections::{BTreeSet, HashMap};
use std::sync::LazyLock;

use regex::Regex;
use serde_json::{Map, Value, json};
use unicode_normalization::UnicodeNormalization;
use unicode_normalization::char::canonical_combining_class;

pub const MAX_GCC_CHARS: usize = 8000;
const MAX_FAILED_NAMES: usize = 50;
const MAX_CASE_OUTPUT: usize = 600;
const MAX_STDERR: usize = 2000;
const MAX_GIVEN: usize = 64;
const MAX_NUMBERS: usize = 20;
// Exit codes of `worker/build-*.sh`, beside timeout(1)'s and SIGKILL's.
pub const COMPILE_FAILED: i64 = 10;
pub const LINK_FAILED: i64 = 11;
pub const COMPILE_TIMEOUT: i64 = 12;
pub const TIMED_OUT: i64 = 124;
pub const KILLED: i64 = 137;
/// Outside Unity's range: Unity exits with its number of failed tests.
pub const ASAN_EXIT: i64 = 86;
pub const DEFAULT_TOLERANCE: f64 = 0.005;

/// A config of the wrong shape, reported as an internal error rather than guessed around.
pub type Result<T> = std::result::Result<T, String>;

fn re(pattern: &str) -> Regex {
    Regex::new(pattern).expect("static pattern")
}

// Digits are ASCII on purpose: a student's output in another script is not a number.
static SUMMARY_RE: LazyLock<Regex> =
    LazyLock::new(|| re(r"(?m)^([0-9]+) Tests ([0-9]+) Failures ([0-9]+) Ignored"));
static FAIL_RE: LazyLock<Regex> =
    LazyLock::new(|| re(r"(?m)^[^\n:]*:[0-9]+:([A-Za-z0-9_]{1,64}):FAIL"));
static INCLUDE_RE: LazyLock<Regex> =
    LazyLock::new(|| re(r#"(?m)^[ \t]*#[ \t]*include[ \t]*[<"]([^>"\n]+)"#));
static NUMBER_RE: LazyLock<Regex> =
    LazyLock::new(|| re(r"[-+]?[0-9]+(?:[.,][0-9]+)?(?:[eE][-+]?[0-9]+)?"));
// Letters and non-decimal numerics: in "inférieur" or "nan²" no nan stands on its own.
static LETTER_RE: LazyLock<Regex> = LazyLock::new(|| re(r"^[\p{L}\p{Nl}\p{No}]$"));

/// Unicode White_Space plus the four information separators, which student output can carry.
fn is_space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

fn strip(s: &str) -> &str {
    s.trim_matches(is_space)
}

/// `s[:n]`, counted in characters.
fn head(s: &str, n: usize) -> &str {
    s.char_indices().nth(n).map_or(s, |(i, _)| &s[..i])
}

/// Every Unicode line break, not only `\n`: it decides where nonce markers start.
fn splitlines(s: &str) -> Vec<&str> {
    let mut lines = Vec::new();
    let mut start = 0;
    let mut chars = s.char_indices().peekable();
    while let Some((i, c)) = chars.next() {
        let breaks = matches!(
            c,
            '\n' | '\r'
                | '\x0b'
                | '\x0c'
                | '\x1c'
                | '\x1d'
                | '\x1e'
                | '\u{85}'
                | '\u{2028}'
                | '\u{2029}'
        );
        if !breaks {
            continue;
        }
        lines.push(&s[start..i]);
        start = i + c.len_utf8();
        if c == '\r' && chars.peek().is_some_and(|&(_, next)| next == '\n') {
            chars.next();
            start += 1;
        }
    }
    if start < s.len() {
        lines.push(&s[start..]);
    }
    lines
}

/// C's `%g`, as in_range messages print their bounds: six significant digits, no trailing zeros.
pub fn format_g(f: f64) -> String {
    if f.is_nan() {
        return "nan".into();
    }
    if f.is_infinite() {
        return if f > 0.0 { "inf" } else { "-inf" }.into();
    }
    if f == 0.0 {
        return if f.is_sign_negative() { "-0" } else { "0" }.into();
    }
    let sci = format!("{:.5e}", f);
    let (mantissa, exp) = sci.split_once('e').expect("{:e} has an exponent");
    let exp: i32 = exp.parse().expect("{:e} exponent");
    let trim = |s: &str| {
        if s.contains('.') {
            s.trim_end_matches('0').trim_end_matches('.').to_string()
        } else {
            s.to_string()
        }
    };
    if !(-4..6).contains(&exp) {
        let sign = if exp < 0 { '-' } else { '+' };
        format!("{}e{}{:02}", trim(mantissa), sign, exp.abs())
    } else {
        trim(&format!("{:.*}", (5 - exp) as usize, f))
    }
}

/// A JSON value as text: strings as they are, anything else as JSON, `null` as nothing.
pub(crate) fn as_text(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        Value::Null => String::new(),
        other => other.to_string(),
    }
}

pub(crate) fn truthy(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64() != Some(0.0),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}

/// `obj.get(key)`, which raises when `obj` is not a dict.
fn get<'a>(obj: &'a Value, key: &str) -> Result<Option<&'a Value>> {
    match obj {
        Value::Object(map) => Ok(map.get(key)),
        _ => Err(format!("expected an object around {key:?}")),
    }
}

fn as_str<'a>(v: &'a Value, what: &str) -> Result<&'a str> {
    v.as_str().ok_or_else(|| format!("{what} must be text"))
}

fn as_number(v: &Value, what: &str) -> Result<f64> {
    match v {
        Value::Number(n) => n.as_f64().ok_or_else(|| format!("{what} is not a number")),
        Value::Bool(b) => Ok(f64::from(u8::from(*b))),
        _ => Err(format!("{what} must be a number")),
    }
}

/// `float(conf.get("tolerance", DEFAULT_TOLERANCE))`: a number, or text such as "0.01".
pub fn tolerance(conf: &Value) -> Result<f64> {
    match get(conf, "tolerance")? {
        None => Ok(DEFAULT_TOLERANCE),
        Some(Value::String(s)) => strip(s)
            .parse()
            .map_err(|_| "tolerance is not a number".into()),
        Some(other) => as_number(other, "tolerance"),
    }
}

/// `int(value)`: truncates floats, parses text.
fn py_int(v: &Value, what: &str) -> Result<i64> {
    if let Some(i) = v.as_i64() {
        return Ok(i);
    }
    match v {
        Value::String(s) => strip(s)
            .parse()
            .map_err(|_| format!("{what} is not an integer")),
        other => {
            let f = as_number(other, what)?;
            if f.is_finite() {
                Ok(f.trunc() as i64)
            } else {
                Err(format!("{what} is not finite"))
            }
        }
    }
}

fn without_separators(text: &str) -> String {
    text.chars()
        .filter(|c| !is_space(*c) && *c != '_')
        .collect()
}

/// `int(s, radix)` as (negative, magnitude without leading zeros), so any length compares.
fn parse_int(s: &str, radix: u32) -> Option<(bool, String)> {
    let (negative, rest) = match s.as_bytes().first() {
        Some(b'-') => (true, &s[1..]),
        Some(b'+') => (false, &s[1..]),
        _ => (false, s),
    };
    let rest = if radix == 16 {
        rest.strip_prefix("0x")
            .or_else(|| rest.strip_prefix("0X"))
            .unwrap_or(rest)
    } else {
        rest
    };
    if rest.is_empty() || !rest.chars().all(|c| c.is_ascii() && c.is_digit(radix)) {
        return None;
    }
    let magnitude = rest.trim_start_matches('0').to_ascii_lowercase();
    if magnitude.is_empty() {
        return Some((false, "0".into()));
    }
    Some((negative, magnitude))
}

fn norm_bin(text: &str) -> Option<String> {
    let s = without_separators(text).to_lowercase();
    let s = s.strip_prefix("0b").unwrap_or(&s);
    (!s.is_empty() && s.chars().all(|c| c == '0' || c == '1')).then(|| s.to_string())
}

fn norm_hex(text: &str) -> Option<(bool, String)> {
    let s = without_separators(text).to_lowercase();
    let s = s.strip_prefix("0x").unwrap_or(&s);
    let s = s.strip_suffix('h').unwrap_or(s);
    parse_int(s, 16)
}

fn norm_int(text: &str) -> Option<(bool, String)> {
    parse_int(&without_separators(text).replace('−', "-"), 10)
}

pub fn check_answer(kind: &str, given: &str, expected: &str) -> (bool, &'static str) {
    match kind {
        "bin8" => {
            let (got, want) = (norm_bin(given), norm_bin(expected));
            let Some(got) = got else {
                return (false, "ce n'est pas une suite de 0 et de 1");
            };
            if want.as_ref() == Some(&got) {
                return (true, "");
            }
            if want.is_some_and(|want| parse_int(&want, 2) == parse_int(&got, 2)) {
                return (false, "bonne valeur, mais l'énoncé demande 8 bits");
            }
            (false, "")
        }
        "hex8" => match norm_hex(given) {
            None => (false, "ce n'est pas un nombre hexadécimal"),
            Some(got) => (norm_hex(expected) == Some(got), ""),
        },
        _ => match norm_int(given) {
            None => (false, "ce n'est pas un nombre entier"),
            Some(got) => (norm_int(expected) == Some(got), ""),
        },
    }
}

pub fn grade_quiz(quiz: &Value, answers: &Value) -> Result<Value> {
    let empty = Vec::new();
    let questions = match get(quiz, "questions")? {
        None => &empty,
        Some(Value::Array(questions)) => questions,
        Some(_) => return Err("questions must be a list".into()),
    };
    let blank = json!("");
    let mut wrong = Vec::new();
    for question in questions {
        let qid = as_text(get(question, "id")?.unwrap_or(&blank));
        let given = as_text(get(answers, &qid)?.unwrap_or(&blank));
        let kind = get(question, "type")?
            .and_then(Value::as_str)
            .unwrap_or("int");
        let expected = as_text(get(question, "answer")?.unwrap_or(&blank));
        let (ok, hint) = check_answer(kind, &given, &expected);
        if !ok {
            let label = get(question, "label")?.map_or_else(|| qid.clone(), as_text);
            let hint = if strip(&given).is_empty() {
                "non répondu"
            } else {
                hint
            };
            wrong.push(
                json!({"id": qid, "label": label, "given": head(&given, MAX_GIVEN), "hint": hint}),
            );
        }
    }
    Ok(json!({
        "status": "ok",
        "kind": "quiz",
        "total": questions.len(),
        "passed": questions.len() - wrong.len(),
        "wrong": wrong,
    }))
}

pub fn extract_numbers(text: &str) -> Vec<f64> {
    NUMBER_RE
        .find_iter(text)
        .filter_map(|m| m.as_str().replace(',', ".").parse().ok())
        .collect()
}

fn close_enough(got: f64, want: f64, tol: f64) -> bool {
    (got - want).abs() <= (want.abs() * tol).max(1e-9)
}

pub fn match_subsequence(numbers: &[f64], expected: &[f64], tol: f64) -> bool {
    let mut index = 0;
    for &want in expected {
        while index < numbers.len() && !close_enough(numbers[index], want, tol) {
            index += 1;
        }
        if index >= numbers.len() {
            return false;
        }
        index += 1;
    }
    true
}

/// Lower case, compatibility decomposition, accents dropped: "Écoulement" matches "ecoulement".
pub fn fold(text: &str) -> String {
    text.to_lowercase()
        .nfkd()
        .filter(|c| canonical_combining_class(*c) == 0)
        .collect()
}

fn is_letter(c: char) -> bool {
    let mut buf = [0; 4];
    LETTER_RE.is_match(c.encode_utf8(&mut buf))
}

/// `inf`, `-inf`, `infinity` or `nan` as a word of its own, in any case. Not `\b`, which
/// splits "inférieur" at the accent; scanned by hand because `regex` has no lookaround.
pub fn has_nonfinite(text: &str) -> bool {
    let chars: Vec<char> = text.chars().collect();
    let same = |c: char, want: char| {
        c.to_ascii_lowercase() == want || (want == 'i' && matches!(c, 'ı' | 'İ'))
    };
    for start in 0..chars.len() {
        if start > 0 && is_letter(chars[start - 1]) {
            continue;
        }
        let body = if chars[start] == '-' {
            start + 1
        } else {
            start
        };
        for word in ["infinity", "inf", "nan"] {
            let end = body + word.len();
            if end <= chars.len()
                && word
                    .chars()
                    .zip(&chars[body..end])
                    .all(|(w, &c)| same(c, w))
                && (end == chars.len() || !is_letter(chars[end]))
            {
                return true;
            }
        }
    }
    false
}

pub fn check_case(case: &Value, output: &str, tol: f64) -> Result<String> {
    let folded = fold(output);
    if let Some(absent) = get(case, "absent")? {
        let Value::Array(words) = absent else {
            return Err("absent must be a list".into());
        };
        for word in words {
            let word = as_str(word, "absent")?;
            if folded.contains(&fold(word)) {
                return Ok(format!(
                    "la sortie mentionne « {word} », qui ne devrait pas y etre"
                ));
            }
        }
    }
    if let Some(wanted) = get(case, "contains")?.filter(|v| truthy(v))
        && !folded.contains(&fold(as_str(wanted, "contains")?))
    {
        return Ok("la sortie ne contient pas le mot attendu".into());
    }
    if let Some(bounds) = get(case, "in_range")?.filter(|v| truthy(v)) {
        let count = get(case, "count")?.map_or(Ok(1), |v| py_int(v, "count"))?;
        let (low, high) = match bounds.as_array().map(Vec::as_slice) {
            Some([low, high, ..]) => (as_number(low, "in_range")?, as_number(high, "in_range")?),
            _ => return Err("in_range must hold two numbers".into()),
        };
        let inside = extract_numbers(output)
            .into_iter()
            .filter(|n| low <= *n && *n <= high)
            .count() as i64;
        if inside < count {
            return Ok(format!(
                "ta sortie contient {inside} valeur{} entre {} et {}, il en faut au moins {count}",
                if inside == 1 { "" } else { "s" },
                format_g(low),
                format_g(high),
            ));
        }
    }
    if let Some(expected) = get(case, "expect")?.filter(|v| truthy(v)) {
        let expected = expected
            .as_array()
            .ok_or("expect must be a list")?
            .iter()
            .map(|v| as_number(v, "expect"))
            .collect::<Result<Vec<f64>>>()?;
        let numbers = extract_numbers(output);
        if match_subsequence(&numbers, &expected, tol) {
            return Ok(String::new());
        }
        let reason = if has_nonfinite(output) {
            "ta sortie contient inf ou nan : division par zéro, ou une variable utilisée alors que \
             sa lecture a échoué. Vérifie que ton programme lit exactement autant de valeurs que le \
             cas lui en fournit"
                .to_string()
        } else if numbers.is_empty() {
            "ta sortie ne contient aucun nombre : vérifie que tu affiches bien le résultat, et que \
             c'est le bon exercice"
                .to_string()
        } else if numbers.len() < expected.len() {
            format!(
                "ta sortie ne contient que {} nombre{}, or ce cas en attend {} : vérifie que tu \
                 affiches TOUTES les valeurs demandées par l'énoncé",
                numbers.len(),
                if numbers.len() == 1 { "" } else { "s" },
                expected.len(),
            )
        } else {
            "la sortie ne contient pas les valeurs attendues, dans l'ordre".to_string()
        };
        return Ok(reason);
    }
    Ok(String::new())
}

/// One program run per case: (stdout, stderr, exit code).
pub type Run = (String, String, i64);

/// Markers carry a per-job nonce, so a program cannot print fake case boundaries.
pub fn split_runs(output: &str, nonce: &str) -> HashMap<String, Run> {
    let (begin, err, end) = (
        format!("{nonce} BEGIN "),
        format!("{nonce} ERR "),
        format!("{nonce} END "),
    );
    let mut runs = HashMap::new();
    let mut name: Option<String> = None;
    let (mut out_lines, mut err_lines, mut in_err) = (Vec::new(), Vec::new(), false);
    for line in splitlines(output) {
        if let Some(rest) = line.strip_prefix(&begin) {
            name = Some(strip(rest).to_string());
            out_lines.clear();
            err_lines.clear();
            in_err = false;
        } else if name.is_some() && line.starts_with(&err) {
            in_err = true;
        } else if let Some(rest) = line.strip_prefix(&end)
            && let Some(current) = name.take()
        {
            let parts: Vec<&str> = rest.split(is_space).filter(|p| !p.is_empty()).collect();
            let code = match parts.get(1) {
                Some(p) if p.bytes().all(|b| b.is_ascii_digit()) => p.parse().unwrap_or(i64::MAX),
                _ => 0,
            };
            let joined = |lines: &[&str]| strip(&lines.join("\n")).to_string();
            runs.insert(current, (joined(&out_lines), joined(&err_lines), code));
            in_err = false;
        } else if name.is_some() {
            if in_err {
                err_lines.push(line)
            } else {
                out_lines.push(line)
            }
        }
    }
    runs
}

/// Splits gcc's warnings block out of the output: (warnings, the rest).
pub fn extract_warnings(output: &str, nonce: &str) -> (String, String) {
    let (start, stop) = (format!("{nonce} WARN\n"), format!("{nonce} ENDWARN"));
    let Some(i) = output.find(&start) else {
        return (String::new(), output.to_string());
    };
    let Some(j) = output[i..].find(&stop).map(|j| i + j) else {
        return (String::new(), output.to_string());
    };
    let body = output.get(i + start.len()..j).map_or("", strip);
    (
        head(body, MAX_GCC_CHARS).to_string(),
        format!("{}{}", &output[..i], &output[j + stop.len()..]),
    )
}

pub fn with_warnings(mut result: Value, warnings: &str) -> Value {
    if !warnings.is_empty()
        && result.get("status").and_then(Value::as_str) != Some("compile_error")
        && let Some(map) = result.as_object_mut()
    {
        map.insert("warnings".into(), json!(warnings));
    }
    result
}

pub fn verdict_io(rc: i64, output: &str, cases: &[Value], nonce: &str, tol: f64) -> Result<Value> {
    if matches!(
        rc,
        COMPILE_FAILED | LINK_FAILED | COMPILE_TIMEOUT | TIMED_OUT | KILLED
    ) {
        return Ok(verdict(rc, output));
    }
    let runs = split_runs(output, nonce);
    let blank = json!("");
    let mut failed = Vec::new();
    for (index, case) in cases.iter().enumerate() {
        let number = index + 1;
        let stdin = get(case, "stdin")?.unwrap_or(&blank);
        let Some((text, err, code)) = runs.get(&format!("{number:02}")) else {
            failed.push(json!({"case": number, "stdin": stdin, "stdout": "",
                               "reason": "le programme n'a pas terminé"}));
            continue;
        };
        let reason = match *code {
            TIMED_OUT | KILLED => {
                "le programme a été interrompu : boucle infinie, ou il attend plus de \
                          valeurs qu'il n'en reçoit"
                    .to_string()
            }
            ASAN_EXIT => "le programme a débordé de la mémoire qu'il a réservée (voir le rapport \
                          ci-dessous : il nomme la ligne)"
                .to_string(),
            0 => check_case(case, text, tol)?,
            code => format!("le programme s'est terminé anormalement (code {code})"),
        };
        if !reason.is_empty() {
            let numbers: Vec<f64> = extract_numbers(text)
                .into_iter()
                .take(MAX_NUMBERS)
                .collect();
            failed.push(json!({
                "case": number,
                "stdin": stdin,
                "stdout": head(text, MAX_CASE_OUTPUT),
                "numbers": numbers,
                "stderr": head(err, MAX_STDERR),
                "reason": reason,
            }));
        }
    }
    Ok(json!({
        "status": "ok",
        "kind": "io",
        "total": cases.len(),
        "passed": cases.len() - failed.len(),
        "cases": failed,
    }))
}

/// Untrusted: student code shares the process and could print a fake summary.
pub fn parse_unity(out: &str) -> Option<Map<String, Value>> {
    let caps = SUMMARY_RE.captures_iter(out).last()?;
    // ponytail: absurdly long counts saturate at u64::MAX; only a forged summary has them.
    let number = |i: usize| caps[i].parse::<u64>().unwrap_or(u64::MAX);
    let (total, failures, ignored) = (number(1), number(2), number(3));
    let names: Vec<&str> = FAIL_RE
        .captures_iter(out)
        .take(MAX_FAILED_NAMES)
        .map(|c| c.get(1).map_or("", |m| m.as_str()))
        .collect();
    let passed = (i128::from(total) - i128::from(failures) - i128::from(ignored)).max(0);
    let mut map = Map::new();
    map.insert("total".into(), json!(total));
    map.insert("passed".into(), json!(passed as u64));
    map.insert("ignored".into(), json!(ignored));
    map.insert("failed".into(), json!(names));
    Some(map)
}

pub fn verdict(rc: i64, out: &str) -> Value {
    match rc {
        COMPILE_FAILED => json!({
            "status": "compile_error",
            "message": "Ton fichier ne compile pas.",
            "gcc": head(out, MAX_GCC_CHARS),
        }),
        LINK_FAILED => json!({
            "status": "link_error",
            "message": "Ton code compile, mais l'édition de liens avec les tests a échoué. \
                        Vérifie que les fonctions demandées ont exactement le nom et la signature \
                        de l'énoncé, et que tu ne définis pas de fonction main().",
        }),
        COMPILE_TIMEOUT => json!({
            "status": "compile_timeout",
            "message": "La compilation a été trop longue et a été abandonnée.",
        }),
        ASAN_EXIT => json!({
            "status": "memory_error",
            "message": "Ton code sort des limites de la mémoire qu'il a le droit d'utiliser : un \
                        indice hors des bornes d'un tableau, une chaîne sans son '\\0', ou un \
                        pointeur qui ne pointe plus sur rien. Revois tes conditions de boucle (< \
                        et non <=) et la taille que tu réserves.",
        }),
        TIMED_OUT | KILLED => json!({
            "status": "timeout",
            "message": "Le programme a été interrompu : boucle infinie, attente d'une entrée, ou \
                        trop de processus créés.",
        }),
        _ => match parse_unity(out) {
            None => json!({
                "status": "error",
                "message": "Les tests se sont arrêtés avant la fin (plantage probable : segfault, \
                            débordement, pointeur invalide).",
            }),
            Some(mut parsed) => {
                parsed.insert("status".into(), json!("ok"));
                parsed.insert("kind".into(), json!("unity"));
                Value::Object(parsed)
            }
        },
    }
}

/// A course rule, not a security boundary: the regex also sees includes in comments.
pub fn forbidden_includes(code: &str, allowed: Option<&BTreeSet<String>>) -> Vec<String> {
    let Some(allowed) = allowed else {
        return Vec::new();
    };
    INCLUDE_RE
        .captures_iter(code)
        .filter_map(|c| c.get(1).map(|m| m.as_str().to_string()))
        .filter(|h| !allowed.contains(h))
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect()
}

/// What follows the sandbox: warnings block out, verdict, warnings back in.
pub fn judge_output(
    mode: &str,
    rc: i64,
    output: &str,
    nonce: &str,
    cases: &[Value],
    tol: f64,
) -> Result<Value> {
    let (warnings, rest) = if nonce.is_empty() {
        (String::new(), output.to_string())
    } else {
        extract_warnings(output, nonce)
    };
    let result = if mode == "io" {
        verdict_io(rc, &rest, cases, nonce, tol)?
    } else {
        verdict(rc, &rest)
    };
    Ok(with_warnings(result, &warnings))
}

#[cfg(test)]
mod tests {
    use super::*;

    const UNITY_OK: &str = "test_tp1.c:12:test_addition:PASS\ntest_tp1.c:19:test_soustraction:PASS\n\n\
                            -----------------------\n2 Tests 0 Failures 0 Ignored\nOK\n";
    const UNITY_FAIL: &str = "test_tp1.c:12:test_addition:PASS\n\
                              test_tp1.c:19:test_pop_pile_vide:FAIL: Expected 42 Was 0\n\
                              test_tp1.c:25:test_realloc:FAIL: Expected NULL Was 0x7ffd\n\
                              test_tp1.c:31:test_ignore:IGNORE\n\n\
                              -----------------------\n4 Tests 2 Failures 1 Ignored\nFAIL\n";

    fn run(code: i64, name: &str) -> String {
        format!("n BEGIN {name}\nn ERR {name}\nn END {name} {code}\n")
    }

    #[test]
    fn unity_summaries_are_counted_but_never_quoted() {
        let ok = Value::Object(parse_unity(UNITY_OK).unwrap());
        assert_eq!(
            ok,
            json!({"total": 2, "passed": 2, "ignored": 0, "failed": []})
        );
        let bad = Value::Object(parse_unity(UNITY_FAIL).unwrap());
        assert_eq!(
            (
                bad["total"].as_u64(),
                bad["passed"].as_u64(),
                bad["ignored"].as_u64()
            ),
            (Some(4), Some(1), Some(1))
        );
        assert_eq!(bad["failed"], json!(["test_pop_pile_vide", "test_realloc"]));
        assert!(!bad.to_string().contains("Expected 42"));
        assert!(parse_unity("test_tp1.c:12:test_a:PASS\nSegmentation fault").is_none());
        assert!(parse_unity("").is_none());

        let forged = format!(
            "<script>alert(1)</script>:1:nom avec espaces et ; rm -rf /:FAIL: x\nt.c:1:{}:FAIL: x\n1 Tests 1 Failures 0 Ignored\n",
            "z".repeat(200)
        );
        let forged = parse_unity(&forged).unwrap();
        assert_eq!(
            (forged["failed"].clone(), forged["total"].clone()),
            (json!([]), json!(1))
        );
        let two =
            parse_unity("9 Tests 0 Failures 0 Ignored\n2 Tests 2 Failures 0 Ignored\n").unwrap();
        assert_eq!(
            (two["total"].clone(), two["passed"].clone()),
            (json!(2), json!(0))
        );
    }

    #[test]
    fn exit_codes_map_to_verdicts() {
        assert_eq!(
            verdict(10, "erreur.c:3: error: ...")["status"],
            "compile_error"
        );
        assert_eq!(
            verdict(10, &"x".repeat(99_999))["gcc"],
            "x".repeat(MAX_GCC_CHARS)
        );
        let link = verdict(11, "peu importe");
        assert_eq!(link["status"], "link_error");
        assert!(link.get("gcc").is_none());
        assert_eq!(verdict(12, "")["status"], "compile_timeout");
        assert_eq!(verdict(124, "")["status"], "timeout");
        assert_eq!(verdict(137, "")["status"], "timeout");
        assert_eq!(verdict(0, UNITY_OK)["kind"], "unity");
        assert_eq!(verdict(139, "Segmentation fault")["status"], "error");

        let asan = verdict(ASAN_EXIT, "peu importe ce qu'il a imprime");
        assert_eq!(asan["status"], "memory_error");
        assert!(asan["message"].as_str().unwrap().contains("tableau"));
        assert_eq!(asan.as_object().unwrap().len(), 2);
        assert!(!asan.to_string().contains("peu importe"));
    }

    #[test]
    fn an_asan_report_reaches_io_students_bounded() {
        let cases = [json!({"stdin": "", "expect": [1]})];
        let report =
            "ERROR: AddressSanitizer: stack-buffer-overflow\n    #0 in remplir tableaux.c:12";
        let out = format!("n BEGIN 01\nn ERR 01\n{report}\nn END 01 {ASAN_EXIT}\n");
        let result = verdict_io(0, &out, &cases, "n", DEFAULT_TOLERANCE).unwrap();
        let case = &result["cases"][0];
        assert!(case["reason"].as_str().unwrap().contains("débordé"));
        assert!(case["stderr"].as_str().unwrap().contains("tableaux.c:12"));

        let long = format!(
            "n BEGIN 01\nn ERR 01\n{}\nn END 01 {ASAN_EXIT}\n",
            "z".repeat(5000)
        );
        let result = verdict_io(0, &long, &cases, "n", DEFAULT_TOLERANCE).unwrap();
        assert_eq!(
            result["cases"][0]["stderr"]
                .as_str()
                .unwrap()
                .chars()
                .count(),
            MAX_STDERR
        );
    }

    #[test]
    fn quiz_answers_are_normalised() {
        assert_eq!(check_answer("bin8", "00010111", "00010111"), (true, ""));
        assert!(check_answer("bin8", "0001 0111", "00010111").0);
        assert!(check_answer("bin8", "0b0001_0111", "00010111").0);
        let (right, hint) = check_answer("bin8", "10111", "00010111");
        assert!(!right && hint.contains("8 bits"));
        assert_eq!(check_answer("bin8", "00010110", "00010111"), (false, ""));
        assert!(!check_answer("bin8", "quarante-deux", "00010111").0);

        for given in ["A7", "a7", "0xa7", "0XA7", "00a7", "a7h"] {
            assert!(check_answer("hex8", given, "A7").0, "{given}");
        }
        assert_eq!(check_answer("hex8", "A8", "A7"), (false, ""));
        assert!(!check_answer("hex8", "zz", "A7").0);
        assert!(check_answer("hex8", "-0x1f", "-1f").0);

        for given in ["-79", " -79 ", "−79", "\u{a0}-7_9\u{2028}"] {
            assert!(check_answer("int", given, "-79").0, "{given:?}");
        }
        assert!(check_answer("int", "+84", "84").0);
        assert!(check_answer("int", "-0", "0").0);
        assert!(check_answer("int", "007", "7").0);
        assert_eq!(check_answer("int", "79", "-79"), (false, ""));
        assert!(!check_answer("int", "1e3", "1000").0);
        assert!(!check_answer("autre", "--1", "1").0);
    }

    #[test]
    fn a_graded_quiz_never_reveals_the_answer_key() {
        let quiz = json!({"label": "TP", "questions": [
            {"id": "q1", "group": "G1", "label": "23", "type": "bin8", "answer": "00010111"},
            {"id": "q2", "group": "G1", "label": "167", "type": "hex8", "answer": "A7"},
            {"id": "q3", "group": "G2", "label": "10110001 en complément à 2", "type": "int", "answer": "-79"},
        ]});
        let perfect = grade_quiz(
            &quiz,
            &json!({"q1": "0001 0111", "q2": "0xa7", "q3": "-79"}),
        )
        .unwrap();
        assert_eq!(
            perfect,
            json!({"status": "ok", "kind": "quiz", "total": 3, "passed": 3, "wrong": []})
        );

        let partial = grade_quiz(&quiz, &json!({"q1": "10111", "q2": "A7"})).unwrap();
        assert_eq!(
            (partial["passed"].clone(), partial["total"].clone()),
            (json!(1), json!(3))
        );
        let wrong = partial["wrong"].as_array().unwrap();
        assert!(wrong[0]["hint"].as_str().unwrap().contains("8 bits"));
        assert_eq!(wrong[1]["hint"], "non répondu");
        assert_eq!(wrong[1]["label"], "10110001 en complément à 2");
        assert!(!partial.to_string().contains("-79"));

        let long = grade_quiz(&quiz, &json!({"q1": "é".repeat(70)})).unwrap();
        assert_eq!(
            long["wrong"][0]["given"].as_str().unwrap().chars().count(),
            64
        );
        assert!(grade_quiz(&quiz, &json!(["pas", "un", "objet"])).is_err());
    }

    #[test]
    fn numbers_are_read_with_either_decimal_mark() {
        assert_eq!(extract_numbers("Surface = 15 cm2"), [15.0, 2.0]);
        assert_eq!(extract_numbers("I = 2,50 A"), [2.5]);
        assert!(extract_numbers("rien du tout").is_empty());
        assert_eq!(extract_numbers("-3.5 et +4"), [-3.5, 4.0]);
        assert_eq!(extract_numbers("1e5 2E-3 x-1y"), [1e5, 2e-3, -1.0]);
        assert_eq!(extract_numbers("٣ digits of other scripts"), [] as [f64; 0]);
    }

    #[test]
    fn expected_values_are_a_tolerant_ordered_subsequence() {
        let tol = DEFAULT_TOLERANCE;
        let out =
            extract_numbers("Entrez la longueur (max 100) : 5\nLargeur : 3\nSurface = 15 cm2");
        assert!(match_subsequence(&out, &[15.0], tol));
        assert!(match_subsequence(&[7.0, 2.0], &[7.0, 2.0], tol));
        assert!(!match_subsequence(&[2.0, 7.0], &[7.0, 2.0], tol));
        assert!(match_subsequence(&[23.88], &[23.88459], tol));
        assert!(!match_subsequence(&[2.0], &[2.5], tol));
        assert!(match_subsequence(&[0.0], &[0.0], tol));
        assert!(!match_subsequence(&[0.01], &[0.0], tol));
    }

    #[test]
    fn words_match_without_case_or_accents() {
        let tol = DEFAULT_TOLERANCE;
        let case = json!({"contains": "laminaire", "absent": ["turbulent", "transitoire"]});
        assert_eq!(
            check_case(&case, "L'ecoulement est LAMINAIRE", tol).unwrap(),
            ""
        );
        assert_eq!(check_case(&case, "écoulement laminaire", tol).unwrap(), "");
        assert_ne!(check_case(&case, "ecoulement turbulent", tol).unwrap(), "");
        let prompt = "laminaire, turbulent ou transitoire ? -> laminaire";
        assert_ne!(check_case(&case, prompt, tol).unwrap(), "");
        assert!(
            check_case(&case, "l'ecoulement est calme", tol)
                .unwrap()
                .contains("ne contient pas le mot attendu")
        );
        assert_eq!(fold("ÉCOULEMENT ﬁn"), "ecoulement fin");
    }

    #[test]
    fn in_range_counts_values_and_prints_its_bounds() {
        let tol = DEFAULT_TOLERANCE;
        let dice = json!({"in_range": [1, 6], "count": 5});
        assert_eq!(check_case(&dice, "3 1 6 2 4", tol).unwrap(), "");
        assert_eq!(
            check_case(&dice, "Lancer 100 fois : 3 1 6 2 4", tol).unwrap(),
            ""
        );
        let short = check_case(&dice, "3 1 6", tol).unwrap();
        assert!(
            short.contains("3 valeurs entre 1 et 6") && short.contains("au moins 5"),
            "{short}"
        );
        assert_ne!(check_case(&dice, "0 7 8 9 10", tol).unwrap(), "");
        let mean = json!({"in_range": [3.4, 3.6]});
        assert_eq!(check_case(&mean, "Moyenne : 3.4997", tol).unwrap(), "");
        assert!(
            check_case(&mean, "Moyenne : 2.9", tol)
                .unwrap()
                .contains("0 valeurs entre 3.4 et 3.6")
        );
        let text_count = json!({"in_range": [1, 6], "count": "2"});
        assert!(
            check_case(&text_count, "1", tol)
                .unwrap()
                .contains("1 valeur entre")
        );
        for (value, printed) in [
            (0.00001, "1e-05"),
            (0.0001, "0.0001"),
            (100000.0, "100000"),
            (1e6, "1e+06"),
            (999999.5, "1e+06"),
            (123456789.0, "1.23457e+08"),
            (-0.0, "-0"),
            (3.4, "3.4"),
        ] {
            assert_eq!(format_g(value), printed);
        }
    }

    #[test]
    fn diagnostics_say_why_the_values_are_missing() {
        let tol = DEFAULT_TOLERANCE;
        let case = json!({"expect": [23.88459]});
        let inf = check_case(
            &case,
            "Entrez la tension (V) : L'intensite est : inf A",
            tol,
        )
        .unwrap();
        assert!(inf.contains("inf ou nan") && inf.contains("autant de valeurs"));
        let none = check_case(&case, "Entrez la tension (V) : ", tol).unwrap();
        assert!(none.contains("aucun nombre") && none.contains("bon exercice"));
        let wrong = "la sortie ne contient pas les valeurs attendues, dans l'ordre";
        assert_eq!(check_case(&case, "resultat : 42.0", tol).unwrap(), wrong);
        let few = check_case(
            &json!({"expect": [4, 3, 4]}),
            "Entrez le nombre de pennys : On obtient ainsi 4 livre(s) et 3 shilling(s).",
            tol,
        )
        .unwrap();
        assert!(
            few.contains("que 2 nombres")
                && few.contains("en attend 3")
                && !few.contains("[4, 3, 4]")
        );
        assert_eq!(
            check_case(&json!({"expect": [4, 3, 4]}), "9 puis 9 puis 9", tol).unwrap(),
            wrong
        );

        for word in [
            "inferieur",
            "inférieur",
            "nanometre",
            "information",
            "infini",
            "ainf",
            "infé",
            "nan²",
        ] {
            assert!(!has_nonfinite(word), "{word}");
        }
        for word in [
            "inf",
            "-inf",
            "NaN",
            "Inf A",
            "nan\n",
            "-nan",
            "Infinity",
            "İnf",
            "1inf",
            "_inf_",
            "a\u{301}nan",
        ] {
            assert!(has_nonfinite(word), "{word}");
        }
    }

    #[test]
    fn runs_are_split_on_this_job_s_markers_only() {
        let out = "bruit avant\nabc123 BEGIN 01\nSurface = 15\nabc123 END 01 0\n\
                   abc123 BEGIN 02\nSurface = 9\nabc123 END 02 0\nabc123 BEGIN 03\nabc123 END 03 137\n";
        let runs = split_runs(out, "abc123");
        assert_eq!(runs.len(), 3);
        assert_eq!(runs["01"], ("Surface = 15".to_string(), String::new(), 0));
        assert_eq!(runs["03"].2, 137);
        // Every Unicode line break separates markers, not only `\n`.
        let runs = split_runs(
            "n BEGIN 01\ra\u{2028}n END 01 0\u{2029}n BEGIN 02\r\nb\x0cn END 02 abc",
            "n",
        );
        assert_eq!(runs["01"], ("a".to_string(), String::new(), 0));
        assert_eq!(runs["02"], ("b".to_string(), String::new(), 0));

        let cases = [
            json!({"stdin": "5\n3\n", "expect": [15]}),
            json!({"stdin": "12\n7\n", "expect": [84]}),
            json!({"stdin": "1\n1\n", "expect": [1]}),
        ];
        let got = verdict_io(0, out, &cases, "abc123", DEFAULT_TOLERANCE).unwrap();
        assert_eq!(
            (
                got["kind"].clone(),
                got["total"].clone(),
                got["passed"].clone()
            ),
            (json!("io"), json!(3), json!(1))
        );
        let second = &got["cases"][0];
        assert_eq!(
            (
                second["case"].clone(),
                second["stdin"].clone(),
                second["stdout"].clone()
            ),
            (json!(2), json!("12\n7\n"), json!("Surface = 9"))
        );
        assert_eq!(second["numbers"], json!([9.0]));
        assert!(
            got["cases"][1]["reason"]
                .as_str()
                .unwrap()
                .contains("interrompu")
        );

        assert_eq!(
            verdict_io(
                0,
                "deadbeef BEGIN 01\n0 Failures\ndeadbeef END 01 0\n",
                &cases,
                "abc123",
                0.005
            )
            .unwrap()["passed"],
            0
        );
        assert_eq!(
            verdict_io(10, "sub.c:3: error: ...", &cases, "abc123", 0.005).unwrap()["status"],
            "compile_error"
        );
        let cut = verdict_io(137, "", &cases, "abc123", 0.005).unwrap();
        assert!(cut["status"] == "timeout" && cut.get("cases").is_none());
        let missing = verdict_io(0, "", &cases[..1], "abc123", 0.005).unwrap();
        assert_eq!(
            missing["cases"][0]["reason"],
            "le programme n'a pas terminé"
        );

        let crash = format!("{}n BEGIN 02\nSurface = 84\nn END 02 0\n", run(139, "01"));
        let got = verdict_io(0, &crash, &cases[..2], "n", DEFAULT_TOLERANCE).unwrap();
        let reason = got["cases"][0]["reason"].as_str().unwrap();
        assert!(reason.contains("anormalement") && reason.contains("code 139"));
    }

    #[test]
    fn gcc_warnings_are_split_out_and_kept_off_compile_errors() {
        let out = "n0nce WARN\nsub.c:4:9: warning: 'somme' is used uninitialized\nn0nce ENDWARN\n\
                   n0nce BEGIN 01\nResultat 12\nn0nce ERR 01\nmise au point : i vaut 3\nn0nce END 01 0\n";
        let (warnings, rest) = extract_warnings(out, "n0nce");
        assert!(warnings.contains("is used uninitialized"));
        assert!(!rest.contains("warning") && !rest.contains("WARN"));
        assert_eq!(
            split_runs(&rest, "n0nce")["01"],
            (
                "Resultat 12".to_string(),
                "mise au point : i vaut 3".to_string(),
                0
            )
        );

        let success = with_warnings(json!({"status": "ok", "passed": 3, "total": 3}), &warnings);
        assert!(
            success["warnings"]
                .as_str()
                .unwrap()
                .contains("uninitialized")
        );
        assert!(
            with_warnings(json!({"status": "compile_error", "gcc": "..."}), &warnings)
                .get("warnings")
                .is_none()
        );
        assert!(
            with_warnings(json!({"status": "ok"}), "")
                .get("warnings")
                .is_none()
        );

        assert_eq!(
            extract_warnings("abc", "n0nce"),
            (String::new(), "abc".to_string())
        );
        let forged = "deadbeef WARN\nmenteur\ndeadbeef ENDWARN\n";
        assert_eq!(
            extract_warnings(forged, "n0nce"),
            (String::new(), forged.to_string())
        );
        let cut = "n0nce WARN\nsub.c:3: warning: partiel";
        assert_eq!(
            extract_warnings(cut, "n0nce"),
            (String::new(), cut.to_string())
        );
        let long = format!("n0nce WARN\n{}\nn0nce ENDWARN", "w".repeat(9000));
        assert_eq!(extract_warnings(&long, "n0nce").0.len(), MAX_GCC_CHARS);

        let judged = judge_output(
            "unity",
            0,
            &format!("n0nce WARN\nw\nn0nce ENDWARN\n{UNITY_OK}"),
            "n0nce",
            &[],
            0.005,
        )
        .unwrap();
        assert_eq!(
            (judged["kind"].clone(), judged["warnings"].clone()),
            (json!("unity"), json!("w"))
        );
    }

    #[test]
    fn forbidden_includes_follow_the_allow_list() {
        let code = "#include <stdio.h>\n#include  \"pile.h\"\n#include <unistd.h>\nint main(){}\n";
        let allowed: BTreeSet<String> = ["stdio.h", "stdlib.h", "pile.h"].map(String::from).into();
        assert_eq!(forbidden_includes(code, Some(&allowed)), ["unistd.h"]);
        assert!(forbidden_includes(code, None).is_empty());
        assert!(forbidden_includes("int main(){}", Some(&allowed)).is_empty());
        assert_eq!(
            forbidden_includes("  #  include <net/if.h>", Some(&allowed)),
            ["net/if.h"]
        );
        assert_eq!(
            forbidden_includes(
                "#include <b.h>\n#include <a.h>\n#include <b.h>",
                Some(&allowed)
            ),
            ["a.h", "b.h"]
        );
    }

    #[test]
    fn scalars_print_like_the_content_tools_expect() {
        assert_eq!(as_text(&json!("A7")), "A7");
        assert_eq!(as_text(&json!(12)), "12");
        assert_eq!(as_text(&json!(null)), "");
        assert_eq!(tolerance(&json!({})).unwrap(), DEFAULT_TOLERANCE);
        assert_eq!(tolerance(&json!({"tolerance": 0.01})).unwrap(), 0.01);
        assert_eq!(tolerance(&json!({"tolerance": " 1e-3 "})).unwrap(), 1e-3);
        assert!(tolerance(&json!({"tolerance": "x"})).is_err());
        assert!(tolerance(&json!({"tolerance": null})).is_err());
    }

    #[test]
    fn a_forged_marker_without_the_nonce_counts_for_nothing() {
        let forged = "deadbeef BEGIN 01\n1\ndeadbeef END 01 0\n";
        let cases = [json!({"stdin": "", "expect": [1]})];
        let result = verdict_io(0, forged, &cases, "0123456789abcdef", DEFAULT_TOLERANCE).unwrap();
        assert_eq!(result["passed"], 0);
    }

    #[test]
    fn only_the_last_unity_summary_counts_and_names_are_bounded() {
        let mut out: String = (0..80)
            .map(|i| format!("t.c:{i}:test_{i}:FAIL\n"))
            .collect();
        out.push_str("99 Tests 0 Failures 0 Ignored\n80 Tests 80 Failures 0 Ignored\n");
        let parsed = parse_unity(&out).unwrap();
        assert_eq!(parsed["passed"], 0);
        assert_eq!(parsed["failed"].as_array().unwrap().len(), MAX_FAILED_NAMES);
    }

    #[test]
    fn truncations_count_characters_not_bytes() {
        let out = "é".repeat(MAX_GCC_CHARS + 10);
        let gcc = verdict(10, &out)["gcc"].as_str().unwrap().to_string();
        assert_eq!(gcc.chars().count(), MAX_GCC_CHARS);
    }

    #[test]
    fn no_verdict_echoes_the_expected_values() {
        let cases = [json!({"stdin": "12\n7\n", "expect": [84]})];
        let out = "n BEGIN 01\nSurface = 9\nn END 01 0\n";
        let result = verdict_io(0, out, &cases, "n", DEFAULT_TOLERANCE).unwrap();
        assert!(!result.to_string().contains("84"), "{result}");
    }

    #[test]
    fn malformed_content_is_an_error_not_a_guess() {
        assert!(check_case(&json!({"expect": ["a"]}), "1", DEFAULT_TOLERANCE).is_err());
        assert!(check_case(&json!({"absent": "turbulent"}), "x", DEFAULT_TOLERANCE).is_err());
    }
}
