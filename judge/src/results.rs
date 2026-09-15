//! What the judge writes back. The tree is root's and the web container mounts it read-only,
//! so the API can read a verdict but never write, replace or pre-create one: the judge alone
//! creates `results/<id>`, and that directory is the claim.

use std::fs::{File, OpenOptions};
use std::io::{self, Write};
use std::os::fd::AsFd;
use std::os::unix::fs::{DirBuilderExt, OpenOptionsExt};
use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime};

use rustix::fs::{AtFlags, Mode, OFlags};
use serde_json::{Map, Value, json};

use crate::spool::{Job, random_hex};

const DURATIONS: &str = "durees.json";
const DURATION_WINDOW: i64 = 20;
const CONSOLE_LOCK: &str = ".console";

/// Atomic JSON write: readers see the old file or the new one, never half of it.
pub fn write_json_at(dir: impl AsFd, name: &str, value: &Value) -> io::Result<()> {
    let tmp = format!(".{name}.{}", random_hex(8));
    let flags = OFlags::WRONLY | OFlags::CREATE | OFlags::EXCL | OFlags::NOFOLLOW | OFlags::CLOEXEC;
    let fd = rustix::fs::openat(&dir, &tmp, flags, Mode::from_raw_mode(0o644))?;
    let written = File::from(fd)
        .write_all(value.to_string().as_bytes())
        .and_then(|()| Ok(rustix::fs::renameat(&dir, &tmp, &dir, name)?));
    if written.is_err() {
        let _ = rustix::fs::unlinkat(&dir, &tmp, AtFlags::empty());
    }
    written
}

fn mkdir(path: &Path) -> io::Result<()> {
    std::fs::DirBuilder::new().mode(0o755).create(path)
}

pub struct Results {
    pub root: PathBuf,
}

impl Results {
    pub fn open(root: &Path) -> Result<Results, String> {
        std::fs::DirBuilder::new()
            .recursive(true)
            .mode(0o755)
            .create(root)
            .map_err(|e| format!("{}: {e}", root.display()))?;
        Ok(Results {
            root: root.to_path_buf(),
        })
    }

    pub fn dir(&self, job: &Job) -> PathBuf {
        self.root.join(job.as_str())
    }

    pub fn done(&self, job: &Job) -> bool {
        std::fs::symlink_metadata(self.dir(job).join("result.json")).is_ok()
    }

    /// Atomic mkdir, which is all the locking workers on a single host need.
    pub fn claim(&self, job: &Job) -> bool {
        let dir = self.dir(job);
        let exists = mkdir(&dir).or_else(|e| match e.kind() {
            io::ErrorKind::AlreadyExists => Ok(()),
            _ => Err(e),
        });
        exists.is_ok() && mkdir(&dir.join(".lock")).is_ok()
    }

    pub fn lock_time(&self, job: &Job) -> Option<SystemTime> {
        std::fs::symlink_metadata(self.dir(job).join(".lock"))
            .and_then(|m| m.modified())
            .ok()
    }

    pub fn unlock(&self, job: &Job) -> bool {
        std::fs::remove_dir(self.dir(job).join(".lock")).is_ok()
    }

    pub fn retries(&self, job: &Job) -> u64 {
        let n = std::fs::read(self.dir(job).join("reprises.json"))
            .ok()
            .and_then(|b| serde_json::from_slice::<Value>(&b).ok())
            .and_then(|v| v.get("n").cloned());
        match n {
            Some(Value::Number(n)) => n
                .as_u64()
                .or_else(|| n.as_f64().map(|f| f.max(0.0) as u64))
                .unwrap_or(0),
            Some(Value::String(s)) => s.trim().parse().unwrap_or(0),
            _ => 0,
        }
    }

    pub fn write_json(&self, job: Option<&Job>, name: &str, value: &Value) -> io::Result<()> {
        let dir = job.map_or_else(|| self.root.clone(), |job| self.dir(job));
        write_json_at(File::open(dir)?, name, value)
    }

    pub fn write_result(&self, job: &Job, mut payload: Value) -> io::Result<()> {
        if let Some(map) = payload.as_object_mut() {
            map.insert("state".into(), json!("done"));
        }
        self.write_json(Some(job), "result.json", &payload)
    }

    pub fn write_state(&self, job: &Job, state: Value) {
        let _ = self.write_json(Some(job), "state.json", &state);
    }

    /// `build` and `out` of a console session, which the API streams as they grow.
    pub fn append(&self, job: &Job, name: &str) -> io::Result<File> {
        OpenOptions::new()
            .append(true)
            .create(true)
            .mode(0o644)
            .open(self.dir(job).join(name))
    }

    /// Held for a whole console session; the API probes it read-only to see the worker alive.
    pub fn claim_file(&self, job: &Job) -> io::Result<File> {
        OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .mode(0o644)
            .open(self.dir(job).join("claim"))
    }

    /// One console session for the whole service, so the other workers keep grading.
    pub fn console_lock(&self, stale_after: Duration) -> bool {
        let lock = self.root.join(CONSOLE_LOCK);
        match mkdir(&lock) {
            Ok(()) => true,
            Err(e) if e.kind() == io::ErrorKind::AlreadyExists => {
                let stale = std::fs::symlink_metadata(&lock)
                    .and_then(|m| m.modified())
                    .is_ok_and(|t| {
                        SystemTime::now()
                            .duration_since(t)
                            .is_ok_and(|age| age > stale_after)
                    });
                let retaken = stale && std::fs::remove_dir(&lock).is_ok() && mkdir(&lock).is_ok();
                if retaken {
                    eprintln!("ctester: console: verrou perime repris");
                }
                retaken
            }
            Err(_) => false,
        }
    }

    pub fn console_unlock(&self) {
        let _ = std::fs::remove_dir(self.root.join(CONSOLE_LOCK));
    }

    pub fn durations(&self) -> Map<String, Value> {
        let read = std::fs::read(self.root.join(DURATIONS)).ok();
        match read.and_then(|b| serde_json::from_slice(&b).ok()) {
            Some(Value::Object(map)) => map,
            _ => Map::new(),
        }
    }

    /// A sliding mean per exercise, read by the API for its ETA.
    pub fn record_duration(&self, key: &str, seconds: f64) {
        // Jobs rejected before a container starts would drag the average to zero.
        if key.is_empty() || seconds < 0.5 {
            return;
        }
        let mut all = self.durations();
        let (mean, n) = match all.get(key).and_then(Value::as_array).map(Vec::as_slice) {
            Some([mean, n]) => match (mean.as_f64(), n.as_f64()) {
                (Some(mean), Some(n)) => (mean, (n as i64).min(DURATION_WINDOW)),
                _ => (0.0, 0),
            },
            _ => (0.0, 0),
        };
        let n = n + 1;
        let mean = ((mean + (seconds - mean) / n as f64) * 100.0).round() / 100.0;
        all.insert(key.to_string(), json!([mean, n]));
        let _ = self.write_json(None, DURATIONS, &Value::Object(all));
    }

    /// Only job directories: `durees.json` and `.console` are the service's, not a job's.
    pub fn sweep(&self, now: SystemTime, after: Duration) {
        let Ok(entries) = std::fs::read_dir(&self.root) else {
            return;
        };
        for entry in entries.flatten() {
            let is_job = entry.file_name().to_str().and_then(Job::parse).is_some();
            let old = entry
                .metadata()
                .and_then(|m| m.modified())
                .is_ok_and(|t| now.duration_since(t).is_ok_and(|age| age > after));
            if is_job && entry.file_type().is_ok_and(|t| t.is_dir()) && old {
                let _ = std::fs::remove_dir_all(entry.path());
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::spool::tests::Scratch;
    use std::os::unix::fs::PermissionsExt;

    fn results() -> (Scratch, Results) {
        let scratch = Scratch::new("results");
        let results = Results::open(&scratch.0.join("results")).unwrap();
        (scratch, results)
    }

    fn job(n: u32) -> Job {
        Job::parse(&format!("{n:032x}")).unwrap()
    }

    #[test]
    fn the_claim_is_the_judge_s_own_directory() {
        let (_scratch, results) = results();
        let first = job(7);
        assert!(!results.done(&first));
        assert!(results.claim(&first));
        assert!(!results.claim(&first));
        let mode = std::fs::metadata(results.dir(&first))
            .unwrap()
            .permissions()
            .mode();
        assert_eq!(
            mode & 0o777,
            0o755,
            "the API must read, and only read, a job's results"
        );
        assert!(results.lock_time(&first).is_some());
        assert!(results.unlock(&first));
        assert!(results.claim(&first));
        results
            .write_json(Some(&first), "reprises.json", &json!({"n": 2}))
            .unwrap();
        assert_eq!(results.retries(&first), 2);
        results
            .write_result(&first, json!({"status": "ok"}))
            .unwrap();
        assert!(results.done(&first));
        let verdict: Value = serde_json::from_slice(
            &std::fs::read(results.dir(&first).join("result.json")).unwrap(),
        )
        .unwrap();
        assert_eq!(verdict["state"], "done");
        assert!(
            results.write_result(&job(8), json!({})).is_err(),
            "no result without a claim"
        );
    }

    #[test]
    fn the_console_lock_is_single_and_expires() {
        let (_scratch, results) = results();
        assert!(results.console_lock(Duration::from_secs(240)));
        assert!(!results.console_lock(Duration::from_secs(240)));
        results.console_unlock();
        assert!(results.console_lock(Duration::from_secs(240)));
        std::thread::sleep(Duration::from_millis(10));
        assert!(results.console_lock(Duration::ZERO));
    }

    #[test]
    fn durations_are_a_bounded_sliding_mean() {
        let (_scratch, results) = results();
        results.record_duration("tp2-ex3", 0.01);
        results.record_duration("", 9.0);
        assert!(results.durations().is_empty());
        results.record_duration("tp2-ex3", 4.0);
        results.record_duration("tp2-ex3", 6.0);
        assert_eq!(results.durations()["tp2-ex3"], json!([5.0, 2]));
        for _ in 0..30 {
            results.record_duration("tp1", 20.0);
        }
        assert_eq!(results.durations()["tp1"][1], json!(DURATION_WINDOW + 1));
        std::fs::write(results.root.join(DURATIONS), "pas du json").unwrap();
        assert!(results.durations().is_empty());
        results.record_duration("tp1", 3.0);
        assert_eq!(results.durations()["tp1"], json!([3.0, 1]));
    }

    #[test]
    fn sweep_removes_old_jobs_and_nothing_of_the_service() {
        let (_scratch, results) = results();
        assert!(results.claim(&job(1)));
        assert!(results.console_lock(Duration::from_secs(240)));
        results.record_duration("tp1", 3.0);
        results.sweep(
            SystemTime::now() + Duration::from_secs(7200),
            Duration::from_secs(600),
        );
        assert!(!results.dir(&job(1)).exists(), "sweep kept a stale job");
        assert!(results.root.join(CONSOLE_LOCK).exists());
        assert!(results.root.join(DURATIONS).exists());
    }
}
