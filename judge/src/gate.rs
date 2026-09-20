//! The judge's own gate to an exercise, re-read from the content and never taken from the web
//! tier. Mirrors `content_catalog.load_exercise`; `tests/vectors/release_access.json` is the
//! compatibility contract between the two implementations of `access`.

use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::Value;

use crate::config::Config;
use crate::grade;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Mode {
    Quiz,
    Io,
    Unity,
}

impl Mode {
    const ALL: [Mode; 3] = [Mode::Quiz, Mode::Io, Mode::Unity];

    pub fn as_str(self) -> &'static str {
        match self {
            Mode::Quiz => "quiz",
            Mode::Io => "io",
            Mode::Unity => "unity",
        }
    }

    pub fn config_name(self) -> &'static str {
        match self {
            Mode::Quiz => "quiz.json",
            Mode::Io => "io.json",
            Mode::Unity => "unity.json",
        }
    }
}

pub struct Exercise {
    pub path: PathBuf,
    pub mode: Mode,
}

/// Whether closed exercises open for this owner: preview, or a moderator.
pub fn unlocked(config: &Config, owner: &str) -> bool {
    config.preview || (!owner.is_empty() && config.moderators.contains(owner))
}

/// Closed exercises open only in preview or for a moderator, recomputed from the owner here.
pub fn find(config: &Config, id: &str, owner: &str, now: i128) -> Option<Exercise> {
    let all = unlocked(config, owner);
    // Ids are unique across roots, so the first match is the only one.
    config
        .content
        .iter()
        .find_map(|root| load(root, id, all, now))
}

pub fn load(content: &Path, id: &str, all: bool, now: i128) -> Option<Exercise> {
    if !valid_id(id) {
        return None;
    }
    let dir = content.join("exercises").join(id);
    let data = read_object(&dir.join("exercise.json"))?;
    if data.get("id").and_then(Value::as_str) != Some(id) {
        return None;
    }
    if !all && access(data.get("release"), now) != "available" {
        return None;
    }
    let path = dir.join("assessment");
    let mode = detect_mode(&path)?;
    Some(Exercise { path, mode })
}

fn valid_id(id: &str) -> bool {
    let bytes = id.as_bytes();
    (1..=63).contains(&bytes.len())
        && (bytes[0].is_ascii_lowercase() || bytes[0].is_ascii_digit())
        && bytes
            .iter()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || *b == b'-')
}

fn read_object(path: &Path) -> Option<Value> {
    let value: Value = serde_json::from_slice(&std::fs::read(path).ok()?).ok()?;
    value.is_object().then_some(value)
}

/// Exactly one configuration file, or the exercise is ambiguous and stays closed.
pub fn detect_mode(dir: &Path) -> Option<Mode> {
    let mut found = Mode::ALL
        .into_iter()
        .filter(|m| dir.join(m.config_name()).is_file());
    match (found.next(), found.next()) {
        (Some(mode), None) => Some(mode),
        _ => None,
    }
}

/// The only read of a release state: a scheduled release past its date is open.
pub fn access(release: Option<&Value>, now: i128) -> &'static str {
    let state = release.and_then(|r| r.get("state")).and_then(Value::as_str);
    match state {
        Some("available") => "available",
        Some("scheduled") => {
            let moment = release
                .and_then(|r| r.get("available_from"))
                .and_then(Value::as_str)
                .and_then(parse_datetime);
            match moment {
                Some(moment) if moment <= now => "available",
                _ => "scheduled",
            }
        }
        _ => "archived",
    }
}

pub fn now() -> i128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_micros() as i128)
}

/// Microseconds since the epoch for `YYYY-MM-DD[T ]HH:MM[:SS[.fff|.ffffff]]` with `Z` or
/// `±HH:MM`. Anything else keeps the exercise closed, even where the API's parser is laxer.
pub fn parse_datetime(text: &str) -> Option<i128> {
    let text = text.replace('Z', "+00:00");
    let b = text.as_bytes();
    let digits = |from: usize, len: usize| -> Option<i128> {
        let part = b.get(from..from + len)?;
        part.iter()
            .all(u8::is_ascii_digit)
            .then(|| part.iter().fold(0, |n, d| n * 10 + i128::from(d - b'0')))
    };
    let byte = |at: usize| b.get(at).copied();
    let (year, month, day) = (digits(0, 4)?, digits(5, 2)?, digits(8, 2)?);
    if byte(4) != Some(b'-') || byte(7) != Some(b'-') || !matches!(byte(10), Some(b'T' | b' ')) {
        return None;
    }
    let (hour, minute) = (digits(11, 2)?, digits(14, 2)?);
    if byte(13) != Some(b':') {
        return None;
    }
    let mut at = 16;
    let (mut second, mut micros) = (0, 0);
    if byte(at) == Some(b':') {
        second = digits(at + 1, 2)?;
        at += 3;
        if byte(at) == Some(b'.') {
            let len = b[at + 1..]
                .iter()
                .take_while(|c| c.is_ascii_digit())
                .count();
            if len != 3 && len != 6 {
                return None;
            }
            micros = digits(at + 1, len)? * if len == 3 { 1000 } else { 1 };
            at += 1 + len;
        }
    }
    let sign = match byte(at) {
        Some(b'+') => 1,
        Some(b'-') => -1,
        _ => return None,
    };
    let (off_hour, off_minute) = (digits(at + 1, 2)?, digits(at + 4, 2)?);
    if byte(at + 3) != Some(b':') || b.len() != at + 6 {
        return None;
    }
    let leap = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
    let month_days = [
        31,
        if leap { 29 } else { 28 },
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    ];
    let valid = (1..=12).contains(&month)
        && (1..=month_days[(month.clamp(1, 12) - 1) as usize]).contains(&day)
        && hour < 24
        && minute < 60
        && second < 60
        && off_hour < 24
        && off_minute < 60;
    if !valid {
        return None;
    }
    let seconds = days_from_civil(year, month, day) * 86_400 + hour * 3600 + minute * 60 + second
        - sign * (off_hour * 3600 + off_minute * 60);
    Some(seconds * 1_000_000 + micros)
}

/// Days since 1970-01-01 in the proleptic Gregorian calendar (Howard Hinnant's algorithm).
fn days_from_civil(year: i128, month: i128, day: i128) -> i128 {
    let year = if month <= 2 { year - 1 } else { year };
    let era = year.div_euclid(400);
    let year_of_era = year - era * 400;
    let day_of_year = (153 * (if month > 2 { month - 3 } else { month + 9 }) + 2) / 5 + day - 1;
    let day_of_era = year_of_era * 365 + year_of_era / 4 - year_of_era / 100 + day_of_year;
    era * 146_097 + day_of_era - 719_468
}

/// `YYYY-MM-DD` in UTC for a count of seconds since the epoch: the inverse of
/// `days_from_civil`, used to name the run journal.
pub fn civil_date(seconds: i64) -> String {
    let days = i128::from(seconds).div_euclid(86_400);
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let day_of_era = z - era * 146_097;
    let year_of_era =
        (day_of_era - day_of_era / 1460 + day_of_era / 36_524 - day_of_era / 146_096) / 365;
    let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    let shifted = (5 * day_of_year + 2) / 153;
    let day = day_of_year - (153 * shifted + 2) / 5 + 1;
    let month = if shifted < 10 {
        shifted + 3
    } else {
        shifted - 9
    };
    let year = year_of_era + era * 400 + i128::from(month <= 2);
    format!("{year:04}-{month:02}-{day:02}")
}

pub fn load_config(exercise: &Exercise) -> Result<Value, String> {
    let path = exercise.path.join(exercise.mode.config_name());
    let raw = std::fs::read(&path).map_err(|e| format!("{}: {e}", path.display()))?;
    serde_json::from_slice(&raw).map_err(|e| format!("{}: {e}", path.display()))
}

fn valid_file_name(name: &str) -> bool {
    let Some((stem, ext)) = name.rsplit_once('.') else {
        return false;
    };
    (1..=32).contains(&stem.len())
        && stem.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_')
        && matches!(ext, "c" | "h")
}

/// The Console's optional header; `services/scratch.py` applies the same rule.
pub fn valid_header_name(name: &str) -> bool {
    valid_file_name(name) && name.ends_with(".h")
}

/// The file names a submission consists of: the config's, else the published ones.
pub fn declared_files(conf: &Value, tp_dir: &Path) -> Vec<String> {
    let published = || {
        let path = tp_dir.join("..").join("public").join("files.json");
        read_object(&path).and_then(|v| v.get("files").cloned())
    };
    let files = conf
        .get("files")
        .filter(|v| grade::truthy(v))
        .cloned()
        .or_else(published);
    let names: Vec<String> = match files {
        Some(Value::Array(items)) => items
            .iter()
            .filter_map(|item| match item {
                Value::Object(map) => map.get("name").and_then(Value::as_str),
                Value::String(s) => Some(s.as_str()),
                _ => None,
            })
            .filter(|name| valid_file_name(name))
            .map(str::to_string)
            .collect(),
        Some(Value::Object(map)) => map.keys().filter(|k| valid_file_name(k)).cloned().collect(),
        _ => Vec::new(),
    };
    if names.is_empty() {
        vec!["submission.c".to_string()]
    } else {
        names
    }
}

/// None disables the check: the exercise has no `allowed_includes.txt`.
pub fn read_allowed(tp_dir: &Path) -> Option<BTreeSet<String>> {
    let text = std::fs::read_to_string(tp_dir.join("allowed_includes.txt")).ok()?;
    Some(
        text.lines()
            .map(str::trim)
            .filter(|l| !l.is_empty())
            .map(str::to_string)
            .collect(),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn civil_date_is_the_inverse_of_days_from_civil() {
        assert_eq!(civil_date(0), "1970-01-01");
        assert_eq!(civil_date(86_399), "1970-01-01");
        assert_eq!(civil_date(86_400), "1970-01-02");
        assert_eq!(civil_date(1_709_164_800), "2024-02-29");
        assert_eq!(civil_date(1_735_689_599), "2024-12-31");
        assert_eq!(civil_date(1_735_689_600), "2025-01-01");
        // Before the epoch the division must floor, not truncate toward zero.
        assert_eq!(civil_date(-1), "1969-12-31");
        // Every round trip through the forward direction lands back on the same day.
        for day in [-25_000i128, -1, 0, 1, 19_000, 25_000, 40_000] {
            let text = civil_date((day * 86_400) as i64);
            let (year, rest) = text.split_once('-').unwrap();
            let (month, d) = rest.split_once('-').unwrap();
            let back = days_from_civil(
                year.parse().unwrap(),
                month.parse().unwrap(),
                d.parse().unwrap(),
            );
            assert_eq!(back, day, "{text}");
        }
    }

    #[test]
    fn release_access_matches_the_api_gate() {
        let vectors: Vec<Value> =
            serde_json::from_str(include_str!("../../tests/vectors/release_access.json")).unwrap();
        for v in &vectors {
            let now = parse_datetime(v["now"].as_str().unwrap()).unwrap();
            assert_eq!(access(v.get("release"), now), v["access"], "{v}");
        }
    }

    #[test]
    fn dates_parse_to_the_right_instant() {
        let utc = parse_datetime("2026-10-16T04:00:00+00:00").unwrap();
        assert_eq!(parse_datetime("2026-10-16T00:00:00-04:00"), Some(utc));
        assert_eq!(parse_datetime("2026-10-16T04:00Z"), Some(utc));
        assert_eq!(utc, 1_792_123_200_000_000);
        assert_eq!(parse_datetime("1970-01-01T00:00:00.001+00:00"), Some(1000));
        for bad in [
            "2026-10-16",
            "2026-10-16T04:00:00",
            "2026-02-30T00:00:00Z",
            "2026-10-16T04:00:00+0400",
            "2026-10-16T04:00:00.12Z",
            "2026-10-16T04:00:00Z trailing",
            "２026-10-16T04:00:00Z",
        ] {
            assert_eq!(parse_datetime(bad), None, "{bad}");
        }
    }

    fn exercise(root: &Path, id: &str, release: Value, files: &[&str]) {
        let dir = root.join("exercises").join(id);
        std::fs::create_dir_all(dir.join("assessment")).unwrap();
        std::fs::write(
            dir.join("exercise.json"),
            json!({"id": id, "release": release}).to_string(),
        )
        .unwrap();
        for f in files {
            std::fs::write(dir.join("assessment").join(f), "{}").unwrap();
        }
    }

    #[test]
    fn the_gate_searches_every_content_root() {
        let scratch = crate::spool::tests::Scratch::new("gate-roots");
        let (a, b) = (scratch.0.join("a"), scratch.0.join("b"));
        exercise(&a, "surface", json!({"state": "available"}), &["io.json"]);
        exercise(&b, "nombres", json!({"state": "available"}), &["quiz.json"]);
        exercise(&b, "ferme", json!({"state": "archived"}), &["io.json"]);
        let config = Config::from_lookup(|key| match key {
            "CTESTER_CONTENT" => Some(format!("{}:{}", a.display(), b.display())),
            _ => None,
        })
        .unwrap();
        let now = now();
        assert_eq!(
            find(&config, "surface", "", now).map(|e| e.mode),
            Some(Mode::Io)
        );
        // The second root is reached, and its mode is its own.
        assert_eq!(
            find(&config, "nombres", "", now).map(|e| e.mode),
            Some(Mode::Quiz)
        );
        assert!(find(&config, "absent", "", now).is_none());
        // Searching further roots must not reopen what the content closed.
        assert!(find(&config, "ferme", "", now).is_none());
        // Nor may a root be escaped through the id.
        assert!(find(&config, "../b/exercises/nombres", "", now).is_none());
    }

    #[test]
    fn the_gate_reopens_nothing_the_content_closed() {
        let scratch = crate::spool::tests::Scratch::new("gate");
        let root = scratch.0.clone();
        exercise(
            &root,
            "surface",
            json!({"state": "available"}),
            &["io.json"],
        );
        exercise(&root, "nombres", json!({"state": "archived"}), &["io.json"]);
        exercise(
            &root,
            "double",
            json!({"state": "available"}),
            &["io.json", "quiz.json"],
        );
        exercise(
            &root,
            "menteur",
            json!({"state": "available"}),
            &["io.json"],
        );
        std::fs::write(
            root.join("exercises/menteur/exercise.json"),
            r#"{"id": "autre", "release": {"state": "available"}}"#,
        )
        .unwrap();
        let now = now();
        assert_eq!(
            load(&root, "surface", false, now).map(|e| e.mode),
            Some(Mode::Io)
        );
        assert!(load(&root, "nombres", false, now).is_none());
        assert!(load(&root, "nombres", true, now).is_some());
        assert!(load(&root, "double", true, now).is_none());
        assert!(load(&root, "menteur", true, now).is_none());
        for hostile in [
            "../../etc/passwd",
            "Surface",
            "",
            "-x",
            "a/b",
            &"a".repeat(64),
        ] {
            assert!(load(&root, hostile, true, now).is_none(), "{hostile}");
        }
    }

    #[test]
    fn declared_files_filter_hostile_names() {
        let dir = Path::new("/nonexistent/assessment");
        assert_eq!(declared_files(&json!({}), dir), ["submission.c"]);
        let conf = json!({"files": [{"name": "calendrier.h"}, {"name": "calendrier.c"}]});
        assert_eq!(declared_files(&conf, dir), ["calendrier.h", "calendrier.c"]);
        let conf = json!({"files": [{"name": "../../etc/passwd"}, {"name": "a/b.c"}, {"name": "bon.c"},
                                     {"name": "script.sh"}, {"name": ".hidden"}, "x.c"]});
        assert_eq!(declared_files(&conf, dir), ["bon.c", "x.c"]);
        assert_eq!(
            declared_files(&json!({"files": [{"name": "x.sh"}]}), dir),
            ["submission.c"]
        );
    }

    #[test]
    fn a_console_header_is_a_plain_h_file_name() {
        for good in ["pile.h", "pile_2.h", &format!("{}.h", "a".repeat(32))] {
            assert!(valid_header_name(good), "{good}");
        }
        for bad in [
            "",
            ".h",
            "pile.c",
            "pile.H",
            "../pile.h",
            "a/b.h",
            "pi le.h",
            "é.h",
            &format!("{}.h", "a".repeat(33)),
        ] {
            assert!(!valid_header_name(bad), "{bad}");
        }
    }
}
