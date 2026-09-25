//! Log records in the OpenTelemetry Logs data model, one JSON object per line on stderr, which
//! journald keeps. `tests/vectors/log_record.json` binds this format to `app/log.py`.

use std::sync::OnceLock;
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{Map, Value};

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum Severity {
    Debug = 5,
    Info = 9,
    Warn = 13,
    Error = 17,
    Fatal = 21,
}

impl Severity {
    fn text(self) -> &'static str {
        match self {
            Severity::Debug => "DEBUG",
            Severity::Info => "INFO",
            Severity::Warn => "WARN",
            Severity::Error => "ERROR",
            Severity::Fatal => "FATAL",
        }
    }

    fn named(name: &str) -> Severity {
        match name.trim().to_ascii_lowercase().as_str() {
            "debug" => Severity::Debug,
            "warn" | "warning" => Severity::Warn,
            "error" => Severity::Error,
            "fatal" => Severity::Fatal,
            _ => Severity::Info,
        }
    }
}

/// The keys the judge may log, a subset of the vector's. No account, station or code: journald
/// outlives "Delete my data".
pub const ATTRIBUTES: &[&str] = &[
    "error.type",
    "ctester.job.id",
    "ctester.exercise.id",
    "ctester.attempt",
    "ctester.cache.signature",
    "ctester.cache.source",
    "ctester.cache.pruned",
    "ctester.cache.left",
];

static THRESHOLD: OnceLock<Severity> = OnceLock::new();
static INSTANCE: OnceLock<String> = OnceLock::new();

/// Names this worker in every record that follows; `CTESTER_WORKER_ID` is read by `config`.
/// A panic is caught per job, so without this hook it would only reach journald as prose.
pub fn init(worker_id: &str) {
    let _ = INSTANCE.set(worker_id.to_string());
    std::panic::set_hook(Box::new(|info| {
        let place = info
            .location()
            .map_or_else(String::new, |at| format!(" at {}:{}", at.file(), at.line()));
        event(
            Severity::Error,
            "judge.panic",
            &format!("panicked{place}"),
            &[],
        );
    }));
}

fn threshold() -> Severity {
    *THRESHOLD
        .get_or_init(|| Severity::named(&std::env::var("CTESTER_LOG_LEVEL").unwrap_or_default()))
}

pub fn event(severity: Severity, name: &str, body: &str, attributes: &[(&str, Value)]) {
    if severity < threshold() {
        return;
    }
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |elapsed| elapsed.as_nanos());
    let instance = INSTANCE.get().map(String::as_str);
    eprintln!(
        "{}",
        record(severity, name, body, attributes, instance, now)
    );
}

pub fn record(
    severity: Severity,
    name: &str,
    body: &str,
    attributes: &[(&str, Value)],
    instance: Option<&str>,
    now_ns: u128,
) -> Value {
    let mut entry = Map::new();
    entry.insert("Timestamp".into(), Value::from(now_ns.to_string()));
    entry.insert("SeverityText".into(), Value::from(severity.text()));
    entry.insert("SeverityNumber".into(), Value::from(severity as u8));
    entry.insert("EventName".into(), Value::from(name));
    entry.insert("Body".into(), Value::from(body));
    let kept: Map<String, Value> = attributes
        .iter()
        .filter(|(key, value)| ATTRIBUTES.contains(key) && !value.is_null())
        .map(|(key, value)| ((*key).to_string(), value.clone()))
        .collect();
    if !kept.is_empty() {
        entry.insert("Attributes".into(), Value::Object(kept));
    }
    let mut resource = Map::new();
    resource.insert("service.name".into(), Value::from("ctester-judge"));
    if let Some(id) = instance {
        resource.insert("service.instance.id".into(), Value::from(id));
    }
    entry.insert("Resource".into(), Value::Object(resource));
    Value::Object(entry)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn vector() -> Value {
        serde_json::from_str(include_str!("../../tests/vectors/log_record.json")).unwrap()
    }

    #[test]
    fn the_record_matches_the_shared_vector() {
        let vector = vector();
        let input = &vector["example"]["input"];
        let attributes: Vec<(&str, Value)> = input["attributes"]
            .as_object()
            .unwrap()
            .iter()
            .map(|(key, value)| (key.as_str(), value.clone()))
            .collect();
        assert_eq!(input["severity"], "WARN");
        assert_eq!(input["service"], "ctester-judge");
        let got = record(
            Severity::Warn,
            input["name"].as_str().unwrap(),
            input["body"].as_str().unwrap(),
            &attributes,
            None,
            u128::from(input["now_ns"].as_u64().unwrap()),
        );
        assert_eq!(got, vector["example"]["record"]);
    }

    #[test]
    fn severities_and_fields_follow_the_vector() {
        let vector = vector();
        for severity in [
            Severity::Debug,
            Severity::Info,
            Severity::Warn,
            Severity::Error,
            Severity::Fatal,
        ] {
            assert_eq!(vector["severities"][severity.text()], severity as u8);
        }
        let fields: Vec<&str> = vector["fields"]
            .as_array()
            .unwrap()
            .iter()
            .map(|field| field.as_str().unwrap())
            .collect();
        let got = record(Severity::Info, "e", "b", &[], Some("2"), 1);
        for key in got.as_object().unwrap().keys() {
            assert!(fields.contains(&key.as_str()), "{key}");
        }
        assert_eq!(got["Resource"]["service.instance.id"], "2");
    }

    #[test]
    fn only_listed_attributes_are_kept() {
        let vector = vector();
        let allowed: Vec<&str> = vector["attributes"]
            .as_array()
            .unwrap()
            .iter()
            .map(|key| key.as_str().unwrap())
            .collect();
        for key in ATTRIBUTES {
            assert!(allowed.contains(key), "{key} is not in the vector");
        }
        let got = record(
            Severity::Info,
            "e",
            "b",
            &[
                ("account", Value::from("sub")),
                ("station", Value::from("ab")),
            ],
            None,
            1,
        );
        assert!(got.get("Attributes").is_none());
    }
}
