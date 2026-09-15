//! Every setting of the judge, read once from `CTESTER_*`.

use std::collections::BTreeSet;
use std::path::PathBuf;

pub struct Config {
    pub spool: PathBuf,
    pub results: PathBuf,
    pub work: PathBuf,
    pub content: PathBuf,
    pub build_unity: PathBuf,
    pub build_io: PathBuf,
    pub build_scratch: PathBuf,
    pub docker: String,
    pub image: String,
    pub runtime: String,
    pub job_timeout: u64,
    pub memory: String,
    pub pids: String,
    pub cpus: String,
    pub sweep_after: u64,
    pub console_memory: String,
    pub console_pids: String,
    pub console_cpus: String,
    pub console_shares: String,
    pub console_session_max: u64,
    pub console_idle_max: u64,
    pub console_out_max: u64,
    pub console_in_max: u64,
    pub lock_stale: u64,
    pub lock_retries: u64,
    pub preview: bool,
    pub moderators: BTreeSet<String>,
    /// Passed to the sandbox in this order; unset variables are left out entirely, because an
    /// empty CTESTER_SANITIZERS explicitly disables the sanitizers.
    pub sandbox_env: Vec<(String, String)>,
    pub cache_max: i64,
    pub cache_prune_every: u64,
}

const SANDBOX_KEYS: [&str; 6] = [
    "CTESTER_C_STD",
    "CTESTER_SANITIZERS",
    "CTESTER_ASAN_OPTIONS",
    "CTESTER_COMPILE_TIMEOUT",
    "CTESTER_RUN_TIMEOUT",
    "CTESTER_CPU_SECONDS",
];

impl Config {
    pub fn from_env() -> Result<Config, String> {
        Config::from_lookup(|key| std::env::var(key).ok())
    }

    pub fn from_lookup(lookup: impl Fn(&str) -> Option<String>) -> Result<Config, String> {
        let text = |key: &str, default: &str| lookup(key).unwrap_or_else(|| default.to_string());
        let number = |key: &str, default: &str| -> Result<i64, String> {
            let raw = text(key, default);
            raw.trim()
                .parse()
                .map_err(|_| format!("{key}={raw:?} is not an integer"))
        };
        let seconds = |key: &str, default: &str| -> Result<u64, String> {
            u64::try_from(number(key, default)?).map_err(|_| format!("{key} must not be negative"))
        };
        let job_timeout = seconds("CTESTER_JOB_TIMEOUT", "60")?;
        let config = Config {
            spool: text("CTESTER_SPOOL", "/opt/ctester/spool").into(),
            results: text("CTESTER_RESULTS", "/opt/ctester/results").into(),
            work: text("CTESTER_WORK", "/var/lib/ctester-judge").into(),
            content: text("CTESTER_CONTENT", "/opt/ctester/content").into(),
            build_unity: text(
                "CTESTER_BUILD_UNITY",
                "/opt/ctester/src/worker/build-unity.sh",
            )
            .into(),
            build_io: text("CTESTER_BUILD_IO", "/opt/ctester/src/worker/build-io.sh").into(),
            build_scratch: text(
                "CTESTER_BUILD_SCRATCH",
                "/opt/ctester/src/worker/build-scratch.sh",
            )
            .into(),
            docker: text("CTESTER_DOCKER", "docker"),
            image: text("CTESTER_IMAGE", "gcc:14-bookworm"),
            runtime: text("CTESTER_RUNTIME", "runsc"),
            job_timeout,
            memory: text("CTESTER_MEMORY", "256m"),
            pids: text("CTESTER_PIDS", "64"),
            cpus: text("CTESTER_CPUS", "1"),
            sweep_after: seconds("CTESTER_SWEEP_AFTER", "600")?,
            console_memory: text("CTESTER_CONSOLE_MEMORY", "192m"),
            console_pids: text("CTESTER_CONSOLE_PIDS", "64"),
            console_cpus: text("CTESTER_CONSOLE_CPUS", "0.5"),
            console_shares: text("CTESTER_CONSOLE_SHARES", "512"),
            console_session_max: seconds("CTESTER_CONSOLE_SESSION_MAX", "180")?,
            console_idle_max: seconds("CTESTER_CONSOLE_IDLE_MAX", "90")?,
            console_out_max: seconds("CTESTER_CONSOLE_OUT_MAX", "1048576")?,
            console_in_max: seconds("CTESTER_CONSOLE_IN_MAX", "65536")?,
            lock_stale: seconds("CTESTER_LOCK_STALE", &(3 * job_timeout).to_string())?,
            lock_retries: seconds("CTESTER_LOCK_RETRIES", "1")?,
            preview: !matches!(text("CTESTER_PREVIEW", "").as_str(), "" | "0"),
            moderators: text("CTESTER_FORUM_MODERATORS", "")
                .split(|c: char| c == ',' || c.is_whitespace())
                .filter(|s| !s.is_empty())
                .map(str::to_string)
                .collect(),
            sandbox_env: SANDBOX_KEYS
                .iter()
                .filter_map(|key| lookup(key).map(|value| (key.to_string(), value)))
                .collect(),
            cache_max: number("CTESTER_CACHE_MAX", "20000")?,
            cache_prune_every: seconds("CTESTER_CACHE_PRUNE_EVERY", "500")?,
        };
        config.check()?;
        Ok(config)
    }

    /// Invariants a bad `.env` could break: the judge refuses to start rather than misbehave.
    fn check(&self) -> Result<(), String> {
        let mut broken = Vec::new();
        if !(self.job_timeout < self.lock_stale && self.lock_stale < self.sweep_after) {
            broken.push(
                "CTESTER_LOCK_STALE must lie between CTESTER_JOB_TIMEOUT and CTESTER_SWEEP_AFTER",
            );
        }
        if self.console_session_max * 2 >= self.sweep_after {
            broken.push("CTESTER_CONSOLE_SESSION_MAX must stay under half of CTESTER_SWEEP_AFTER");
        }
        // Explicit matches: `Option`'s ordering would let an unreadable value pass as the smaller.
        let below = |a: Option<f64>, b: Option<f64>, strict: bool| match (a, b) {
            (Some(a), Some(b)) => a < b || (!strict && a == b),
            _ => false,
        };
        let stricter = below(
            megabytes(&self.console_memory),
            megabytes(&self.memory),
            true,
        ) && below(number(&self.console_pids), number(&self.pids), false)
            && below(number(&self.console_cpus), number(&self.cpus), false);
        if !stricter {
            broken.push("the console limits must stay stricter than the grading limits");
        }
        match broken.is_empty() {
            true => Ok(()),
            false => Err(broken.join("; ")),
        }
    }

    pub fn unity_dir(&self) -> PathBuf {
        self.content.join("shared").join("unity")
    }
}

fn number(text: &str) -> Option<f64> {
    text.trim().parse().ok().filter(|n: &f64| n.is_finite())
}

/// Docker sizes such as "256m" or "1g"; None (never comparable) when unreadable.
fn megabytes(text: &str) -> Option<f64> {
    let text = text.trim().to_ascii_lowercase();
    let (digits, factor) = match text.char_indices().last() {
        Some((i, 'b')) => (&text[..i], 1.0 / (1024.0 * 1024.0)),
        Some((i, 'k')) => (&text[..i], 1.0 / 1024.0),
        Some((i, 'm')) => (&text[..i], 1.0),
        Some((i, 'g')) => (&text[..i], 1024.0),
        _ => (text.as_str(), 1.0 / (1024.0 * 1024.0)),
    };
    number(digits).map(|n| n * factor)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn with(pairs: &[(&str, &str)]) -> Result<Config, String> {
        Config::from_lookup(|key| {
            pairs
                .iter()
                .find(|(k, _)| *k == key)
                .map(|(_, v)| v.to_string())
        })
    }

    #[test]
    fn the_defaults_hold_their_own_invariants() {
        let config = with(&[]).unwrap();
        assert_eq!(config.lock_stale, 180);
        assert!(config.sandbox_env.is_empty());
    }

    #[test]
    fn a_broken_env_refuses_to_start() {
        assert!(with(&[("CTESTER_LOCK_STALE", "900")]).is_err());
        assert!(with(&[("CTESTER_CONSOLE_SESSION_MAX", "400")]).is_err());
        assert!(with(&[("CTESTER_CONSOLE_MEMORY", "1g")]).is_err());
        assert!(with(&[("CTESTER_CONSOLE_CPUS", "2")]).is_err());
        assert!(with(&[("CTESTER_MEMORY", "beaucoup")]).is_err());
        assert!(with(&[("CTESTER_CONSOLE_MEMORY", "beaucoup")]).is_err());
        assert!(with(&[("CTESTER_JOB_TIMEOUT", "soixante")]).is_err());
    }

    #[test]
    fn sandbox_variables_keep_their_order_and_an_empty_value() {
        let config = with(&[("CTESTER_RUN_TIMEOUT", "5"), ("CTESTER_SANITIZERS", "")]).unwrap();
        let keys: Vec<_> = config
            .sandbox_env
            .iter()
            .map(|(k, v)| (k.as_str(), v.as_str()))
            .collect();
        assert_eq!(
            keys,
            [("CTESTER_SANITIZERS", ""), ("CTESTER_RUN_TIMEOUT", "5")]
        );
    }

    #[test]
    fn moderators_split_on_commas_and_spaces() {
        let config = with(&[("CTESTER_FORUM_MODERATORS", "sub-a, sub-b\tsub-c,,")]).unwrap();
        assert_eq!(config.moderators.len(), 3);
    }
}
