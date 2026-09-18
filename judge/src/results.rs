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

const DURATIONS: &str = "durations.json";
/// The same file before it was renamed, read while the new one does not exist yet.
const LEGACY_DURATIONS: &str = "durees.json";
/// A line longer than this is dropped rather than risk being split across two `write` calls.
const RUN_LINE_MAX: usize = 4096;
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

/// What the run journal records on top of the verdict itself. Console sessions use
/// `exercise_id = ":console"`, the key `durations.json` already uses for them.
pub struct Run<'a> {
    pub exercise_id: &'a str,
    /// The OIDC subject, or empty: an anonymous run, or a Console session, whose job
    /// deliberately carries no owner.
    pub account: String,
    /// A short hash of an anonymous browser's station id, empty when there is an account:
    /// it tells two anonymous submitters apart without naming either.
    pub station: String,
    /// The exercise's mode, resolved from the content rather than read back from the
    /// verdict: only a successful verdict carries `kind`, and a failed run is exactly
    /// when knowing the mode matters.
    pub kind: &'a str,
    pub duration_s: Option<f64>,
    pub queue_wait_s: Option<f64>,
    pub cache_hit: bool,
    pub reprises: u64,
}

#[cfg(test)]
impl Run<'_> {
    pub fn of(exercise_id: &str) -> Run<'_> {
        Run {
            exercise_id,
            account: String::new(),
            station: String::new(),
            kind: "",
            duration_s: None,
            queue_wait_s: None,
            cache_hit: false,
            reprises: 0,
        }
    }
}

pub struct Results {
    pub root: PathBuf,
    worker_id: String,
}

impl Results {
    pub fn open(root: &Path, worker_id: &str) -> Result<Results, String> {
        std::fs::DirBuilder::new()
            .recursive(true)
            .mode(0o755)
            .create(root)
            .map_err(|e| format!("{}: {e}", root.display()))?;
        Ok(Results {
            root: root.to_path_buf(),
            worker_id: worker_id.to_string(),
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

    /// The one place a verdict is published, so the journal cannot miss an exit path.
    pub fn write_result(&self, job: &Job, mut payload: Value, run: &Run) -> io::Result<()> {
        if let Some(map) = payload.as_object_mut() {
            map.insert("state".into(), json!("done"));
        }
        let written = self.write_json(Some(job), "result.json", &payload);
        if written.is_ok() {
            self.append_run(job, &payload, run);
        }
        written
    }

    /// One line per finished run, for the admin app to ingest. Every worker appends to the same
    /// file: a single `write` to a regular file opened `O_APPEND` holds the inode lock for the
    /// whole transfer, so lines never interleave. That is a local-filesystem guarantee -- it does
    /// not hold over NFS, and `results/` must stay local. `write_all` would loop on a short write
    /// and tear the line, so the line is built whole and written once, or dropped.
    fn append_run(&self, job: &Job, verdict: &Value, run: &Run) {
        let field = |name: &str| verdict.get(name).and_then(Value::as_str).unwrap_or("");
        let seconds = SystemTime::now()
            .duration_since(SystemTime::UNIX_EPOCH)
            .map_or(0, |d| d.as_secs() as i64);
        let record = json!({
            "job_id": job.as_str(),
            "exercise_id": run.exercise_id,
            "account": run.account,
            "station": run.station,
            "status": field("status"),
            // Null when the run never reached the tests: a compilation error, a timeout.
            "passed": verdict.get("passed").and_then(Value::as_i64),
            "total": verdict.get("total").and_then(Value::as_i64),
            // The verdict only names the mode when it graded successfully.
            "kind": match run.kind.is_empty() {
                true => field("kind"),
                false => run.kind,
            },
            "duration_s": run.duration_s,
            "queue_wait_s": run.queue_wait_s,
            "worker_id": self.worker_id,
            "cache_hit": run.cache_hit,
            "reprises": run.reprises,
            "finished_at": seconds,
        });
        let mut line = record.to_string().into_bytes();
        line.push(b'\n');
        if line.len() > RUN_LINE_MAX {
            return;
        }
        let name = format!("runs-{}.jsonl", crate::gate::civil_date(seconds));
        let opened = OpenOptions::new()
            .append(true)
            .create(true)
            .mode(0o644)
            .open(self.root.join(name));
        if let Ok(mut file) = opened {
            let _ = file.write(&line);
        }
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
        let read = std::fs::read(self.root.join(DURATIONS))
            .or_else(|_| std::fs::read(self.root.join(LEGACY_DURATIONS)))
            .ok();
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

    /// Only job directories: `durations.json` and `.console` are the service's, not a job's.
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
        let results = Results::open(&scratch.0.join("results"), "7").unwrap();
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
            .write_result(&first, json!({"status": "ok"}), &Run::of("tp2-ex3"))
            .unwrap();
        assert!(results.done(&first));
        let verdict: Value = serde_json::from_slice(
            &std::fs::read(results.dir(&first).join("result.json")).unwrap(),
        )
        .unwrap();
        assert_eq!(verdict["state"], "done");
        assert!(
            results
                .write_result(&job(8), json!({}), &Run::of("tp1"))
                .is_err(),
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
        std::fs::write(results.root.join(DURATIONS), "not json").unwrap();
        assert!(results.durations().is_empty());
        results.record_duration("tp1", 3.0);
        assert_eq!(results.durations()["tp1"], json!([3.0, 1]));
    }

    #[test]
    fn durations_are_read_from_the_legacy_file_until_the_new_one_exists() {
        let (_scratch, results) = results();
        std::fs::write(results.root.join(LEGACY_DURATIONS), r#"{"tp1": [4.0, 3]}"#).unwrap();
        assert_eq!(results.durations()["tp1"], json!([4.0, 3]));
        results.record_duration("tp1", 8.0);
        assert_eq!(results.durations()["tp1"], json!([5.0, 4]));
        assert!(results.root.join(DURATIONS).exists());
    }

    #[test]
    fn concurrent_workers_append_whole_lines() {
        let (scratch, _) = results();
        let root = scratch.0.join("results");
        let mut threads = Vec::new();
        for worker in 0..4u32 {
            let root = root.clone();
            threads.push(std::thread::spawn(move || {
                let results = Results::open(&root, &worker.to_string()).unwrap();
                for n in 0..25 {
                    let job = job(worker * 100 + n);
                    assert!(results.claim(&job));
                    results
                        .write_result(&job, json!({"status": "ok", "kind": "io"}), &Run::of("tp1"))
                        .unwrap();
                }
            }));
        }
        for thread in threads {
            thread.join().unwrap();
        }
        let journal = std::fs::read_dir(&root)
            .unwrap()
            .flatten()
            .map(|e| e.file_name().to_string_lossy().into_owned())
            .find(|name| name.starts_with("runs-"))
            .expect("no run journal");
        let text = std::fs::read_to_string(root.join(journal)).unwrap();
        let lines: Vec<&str> = text.lines().collect();
        assert_eq!(lines.len(), 100, "lines were lost or torn");
        for line in lines {
            let record: Value = serde_json::from_str(line).expect("interleaved line");
            assert_eq!(record["exercise_id"], json!("tp1"));
            assert_eq!(record["status"], json!("ok"));
        }
    }

    #[test]
    fn the_journal_carries_the_station_and_the_test_counts() {
        let (_scratch, results) = results();
        let graded = json!({"status": "ok", "passed": 3, "total": 5});
        let run = Run {
            station: "0a1b2c3d".into(),
            ..Run::of("tp1")
        };
        assert!(results.claim(&job(1)));
        results.write_result(&job(1), graded, &run).unwrap();
        assert!(results.claim(&job(2)));
        results
            .write_result(&job(2), json!({"status": "compile_error"}), &Run::of("tp1"))
            .unwrap();
        let journal = std::fs::read_dir(&results.root)
            .unwrap()
            .flatten()
            .find(|e| e.file_name().to_string_lossy().starts_with("runs-"))
            .expect("no run journal");
        let text = std::fs::read_to_string(journal.path()).unwrap();
        let fields: Vec<Value> = text
            .lines()
            .map(|line| {
                let r: Value = serde_json::from_str(line).unwrap();
                json!([r["station"], r["passed"], r["total"]])
            })
            .collect();
        assert_eq!(fields, [json!(["0a1b2c3d", 3, 5]), json!(["", null, null])]);
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
        assert!(results.claim(&job(2)));
        results
            .write_result(&job(2), json!({"status": "ok"}), &Run::of("tp1"))
            .unwrap();
        let journal = |root: &std::path::Path| {
            std::fs::read_dir(root)
                .unwrap()
                .flatten()
                .any(|e| e.file_name().to_string_lossy().starts_with("runs-"))
        };
        assert!(journal(&results.root), "the journal was never written");
        results.sweep(
            SystemTime::now() + Duration::from_secs(7200),
            Duration::from_secs(600),
        );
        assert!(journal(&results.root), "sweep ate the run journal");
    }
}
