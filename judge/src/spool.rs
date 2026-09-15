//! The spool belongs to the API (65534) and the judge runs as root, so every access resolves
//! beneath the spool with `openat2(RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS)`: no entry the API
//! plants can redirect a read, a write or a lock. Without `openat2` the judge does not start.

use std::fs::File;
use std::io::{self, Read, Write};
use std::os::fd::{AsFd, OwnedFd};
use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use rustix::fs::{AtFlags, FileType, FlockOperation, Mode, OFlags, ResolveFlags, Stat};
use serde_json::{Map, Value, json};

use crate::grade;

pub const MAX_READ: usize = 4 * 1024 * 1024;
const DURATIONS: &str = "durees.json";
const DURATION_WINDOW: i64 = 20;
const CONSOLE_LOCK: &str = ".console";

const RESOLVE: ResolveFlags = ResolveFlags::BENEATH
    .union(ResolveFlags::NO_SYMLINKS)
    .union(ResolveFlags::NO_MAGICLINKS);

/// A job directory name as the API creates them: 32 lowercase hex digits.
#[derive(Clone, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct Job(String);

impl Job {
    pub fn parse(name: &str) -> Option<Job> {
        let hex = name.len() == 32 && name.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'));
        hex.then(|| Job(name.to_string()))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }

    pub fn file(&self, name: &str) -> String {
        format!("{}/{name}", self.0)
    }
}

pub struct Spool {
    pub root: PathBuf,
    fd: OwnedFd,
}

fn other(message: String) -> io::Error {
    io::Error::new(io::ErrorKind::PermissionDenied, message)
}

/// Refuses links (already), FIFOs, devices and hard links: only a file the API wrote itself.
fn plain(fd: OwnedFd, what: &str) -> io::Result<File> {
    let stat = rustix::fs::fstat(&fd)?;
    if FileType::from_raw_mode(stat.st_mode) != FileType::RegularFile || stat.st_nlink != 1 {
        return Err(other(format!("{what}: not a plain file")));
    }
    Ok(File::from(fd))
}

fn mtime(stat: &Stat) -> SystemTime {
    UNIX_EPOCH
        + Duration::new(
            stat.st_mtime.max(0) as u64,
            stat.st_mtime_nsec.clamp(0, 999_999_999) as u32,
        )
}

pub fn random_hex(bytes: usize) -> String {
    let mut buf = vec![0u8; bytes];
    let mut filled = 0;
    while filled < bytes {
        match rustix::rand::getrandom(&mut buf[filled..], rustix::rand::GetRandomFlags::empty()) {
            Ok(n) => filled += n,
            Err(rustix::io::Errno::INTR) => continue,
            Err(e) => panic!("getrandom failed: {e}"),
        }
    }
    buf.iter().map(|b| format!("{b:02x}")).collect()
}

/// Atomic JSON write under a random name opened O_EXCL: a predictable one could be planted.
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

/// Any failure of the probe stops the judge: there is deliberately no weaker fallback.
pub fn require_openat2(probe: rustix::io::Result<OwnedFd>) -> Result<(), String> {
    match probe {
        Ok(_) => Ok(()),
        Err(rustix::io::Errno::NOSYS) => Err(
            "openat2 is unavailable (Linux 5.6+ required, or a seccomp filter blocks it)".into(),
        ),
        Err(e) => Err(format!("openat2 probe failed: {e}")),
    }
}

impl Spool {
    pub fn open(root: &Path) -> Result<Spool, String> {
        let flags = OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC;
        let fd = rustix::fs::open(root, flags, Mode::empty())
            .map_err(|e| format!("{}: {e}", root.display()))?;
        let spool = Spool {
            root: root.to_path_buf(),
            fd,
        };
        require_openat2(rustix::fs::openat2(
            &spool.fd,
            ".",
            flags,
            Mode::empty(),
            RESOLVE,
        ))?;
        Ok(spool)
    }

    fn resolve(&self, rel: &str, flags: OFlags) -> io::Result<OwnedFd> {
        let rel = if rel.is_empty() { "." } else { rel };
        // openat2 rejects a mode without O_CREAT, unlike openat.
        let mode = if flags.contains(OFlags::CREATE) {
            Mode::from_raw_mode(0o644)
        } else {
            Mode::empty()
        };
        let flags = flags | OFlags::CLOEXEC | OFlags::NONBLOCK;
        Ok(rustix::fs::openat2(&self.fd, rel, flags, mode, RESOLVE)?)
    }

    fn dir(&self, rel: &str) -> io::Result<OwnedFd> {
        self.resolve(rel, OFlags::RDONLY | OFlags::DIRECTORY)
    }

    pub fn open_file(&self, rel: &str, flags: OFlags) -> io::Result<File> {
        plain(self.resolve(rel, flags)?, rel)
    }

    pub fn read(&self, rel: &str, limit: usize) -> io::Result<Vec<u8>> {
        let mut data = Vec::new();
        self.open_file(rel, OFlags::RDONLY)?
            .take(limit as u64 + 1)
            .read_to_end(&mut data)?;
        if data.len() > limit {
            return Err(other(format!("{rel}: larger than {limit} bytes")));
        }
        Ok(data)
    }

    pub fn read_json(&self, rel: &str) -> io::Result<Value> {
        serde_json::from_slice(&self.read(rel, MAX_READ)?)
            .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))
    }

    /// A field of `job.json` as `str()` would print it; "" when anything is off.
    pub fn job_field(&self, job: &Job, field: &str) -> String {
        match self.read_json(&job.file("job.json")) {
            Ok(Value::Object(map)) => map.get(field).map(grade::as_text).unwrap_or_default(),
            _ => String::new(),
        }
    }

    pub fn exists(&self, dir: &str, name: &str) -> bool {
        self.dir(dir)
            .and_then(|d| Ok(rustix::fs::statat(&d, name, AtFlags::SYMLINK_NOFOLLOW)?))
            .is_ok()
    }

    pub fn write_json(&self, dir: &str, name: &str, value: &Value) -> io::Result<()> {
        write_json_at(self.dir(dir)?, name, value)
    }

    pub fn write_result(&self, job: &Job, mut payload: Value) -> io::Result<()> {
        if let Some(map) = payload.as_object_mut() {
            map.insert("state".into(), json!("done"));
        }
        self.write_json(job.as_str(), "result.json", &payload)
    }

    pub fn write_state(&self, job: &Job, state: Value) {
        let _ = self.write_json(job.as_str(), "state.json", &state);
    }

    /// Read-only on purpose: flock needs no write access, and the lock files belong to the API.
    pub fn lock_held(&self, rel: &str) -> bool {
        let Ok(file) = self.open_file(rel, OFlags::RDONLY) else {
            return false;
        };
        match rustix::fs::flock(&file, FlockOperation::NonBlockingLockExclusive) {
            Err(_) => true,
            Ok(()) => {
                let _ = rustix::fs::flock(&file, FlockOperation::Unlock);
                false
            }
        }
    }

    /// mkdir is atomic, which is all the locking workers on a single host need.
    pub fn claim(&self, job: &Job) -> bool {
        self.dir(job.as_str())
            .and_then(|d| {
                Ok(rustix::fs::mkdirat(
                    &d,
                    ".lock",
                    Mode::from_raw_mode(0o755),
                )?)
            })
            .is_ok()
    }

    pub fn lock_time(&self, job: &Job) -> Option<SystemTime> {
        let dir = self.dir(job.as_str()).ok()?;
        rustix::fs::statat(&dir, ".lock", AtFlags::SYMLINK_NOFOLLOW)
            .ok()
            .map(|s| mtime(&s))
    }

    pub fn unlock(&self, job: &Job) -> bool {
        self.dir(job.as_str())
            .and_then(|d| Ok(rustix::fs::unlinkat(&d, ".lock", AtFlags::REMOVEDIR)?))
            .is_ok()
    }

    pub fn retries(&self, job: &Job) -> u64 {
        let n = self
            .read_json(&job.file("reprises.json"))
            .ok()
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

    /// Complete jobs without a result, oldest first. Links and foreign names are never jobs.
    pub fn pending(&self) -> Vec<Job> {
        let Ok(entries) = std::fs::read_dir(&self.root) else {
            return Vec::new();
        };
        let mut jobs = Vec::new();
        for entry in entries.flatten() {
            let Some(job) = entry.file_name().to_str().and_then(Job::parse) else {
                continue;
            };
            let Ok(dir) = self.dir(job.as_str()) else {
                continue;
            };
            let Ok(stat) = rustix::fs::statat(&dir, "job.json", AtFlags::SYMLINK_NOFOLLOW) else {
                continue;
            };
            let done = rustix::fs::statat(&dir, "result.json", AtFlags::SYMLINK_NOFOLLOW).is_ok();
            if FileType::from_raw_mode(stat.st_mode) == FileType::RegularFile && !done {
                jobs.push((mtime(&stat), job));
            }
        }
        jobs.sort();
        jobs.into_iter().map(|(_, job)| job).collect()
    }

    pub fn sweep(&self, now: SystemTime, after: Duration) {
        let Ok(entries) = std::fs::read_dir(&self.root) else {
            return;
        };
        for entry in entries.flatten() {
            let name = entry.file_name();
            let Ok(stat) = rustix::fs::statat(&self.fd, &name, AtFlags::SYMLINK_NOFOLLOW) else {
                continue;
            };
            let old = now
                .duration_since(mtime(&stat))
                .is_ok_and(|age| age > after);
            if FileType::from_raw_mode(stat.st_mode) == FileType::Directory && old {
                // std's remove_dir_all removes a link instead of following it, at every level.
                let _ = std::fs::remove_dir_all(self.root.join(name));
            }
        }
    }

    /// One console session for the whole service, so the other workers keep grading.
    pub fn console_lock(&self, stale_after: Duration) -> bool {
        let mode = Mode::from_raw_mode(0o755);
        match rustix::fs::mkdirat(&self.fd, CONSOLE_LOCK, mode) {
            Ok(()) => true,
            Err(rustix::io::Errno::EXIST) => {
                let Ok(stat) =
                    rustix::fs::statat(&self.fd, CONSOLE_LOCK, AtFlags::SYMLINK_NOFOLLOW)
                else {
                    return false;
                };
                let stale = SystemTime::now()
                    .duration_since(mtime(&stat))
                    .is_ok_and(|age| age > stale_after);
                let retaken = stale
                    && rustix::fs::unlinkat(&self.fd, CONSOLE_LOCK, AtFlags::REMOVEDIR).is_ok()
                    && rustix::fs::mkdirat(&self.fd, CONSOLE_LOCK, mode).is_ok();
                if retaken {
                    eprintln!("ctester: console: verrou perime repris");
                }
                retaken
            }
            Err(_) => false,
        }
    }

    pub fn console_unlock(&self) {
        let _ = rustix::fs::unlinkat(&self.fd, CONSOLE_LOCK, AtFlags::REMOVEDIR);
    }

    pub fn durations(&self) -> Map<String, Value> {
        match self.read_json(DURATIONS) {
            Ok(Value::Object(map)) => map,
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
        let _ = self.write_json("", DURATIONS, &Value::Object(all));
    }
}

#[cfg(test)]
pub mod tests {
    use super::*;
    use std::os::unix::fs::symlink;

    pub struct Scratch(pub PathBuf);

    impl Scratch {
        pub fn new(label: &str) -> Scratch {
            let path = std::env::temp_dir().join(format!("ctester-{label}-{}", random_hex(6)));
            std::fs::create_dir_all(&path).unwrap();
            Scratch(path)
        }
    }

    impl Drop for Scratch {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    /// A spool plus `cible`, a directory outside it that every attack aims at.
    fn hostile() -> (Scratch, Spool, PathBuf) {
        let scratch = Scratch::new("hostile");
        let root = scratch.0.join("spool");
        let target = scratch.0.join("cible");
        std::fs::create_dir_all(&root).unwrap();
        std::fs::create_dir_all(&target).unwrap();
        std::fs::write(target.join("secret"), "SECRET").unwrap();
        let spool = Spool::open(&root).unwrap();
        (scratch, spool, target)
    }

    fn job(spool: &Spool, n: u32, body: &str) -> Job {
        let job = Job::parse(&format!("{n:032x}")).unwrap();
        std::fs::create_dir(spool.root.join(job.as_str())).unwrap();
        std::fs::write(spool.root.join(job.file("job.json")), body).unwrap();
        job
    }

    fn untouched(target: &Path) {
        let mut names: Vec<_> = std::fs::read_dir(target)
            .unwrap()
            .map(|e| e.unwrap().file_name())
            .collect();
        names.sort();
        assert_eq!(names, ["secret"]);
        assert_eq!(
            std::fs::read_to_string(target.join("secret")).unwrap(),
            "SECRET"
        );
    }

    #[test]
    fn job_names_are_exactly_what_the_api_creates() {
        assert!(Job::parse(&"a".repeat(32)).is_some());
        for bad in [
            "",
            "..",
            "cache",
            &"A".repeat(32),
            &"a".repeat(31),
            &format!("{}/", "a".repeat(31)),
        ] {
            assert!(Job::parse(bad).is_none(), "{bad}");
        }
    }

    #[test]
    fn root_writes_follow_no_link() {
        let (_scratch, spool, target) = hostile();
        let secret = target.join("secret");
        let j = job(&spool, 1, r#"{"exercise_id": "tp2-ex1"}"#);
        for name in ["result.json", "state.json", "reprises.json"] {
            symlink(&secret, spool.root.join(j.file(name))).unwrap();
        }
        symlink(
            target.join("pendant"),
            spool.root.join(j.file("result.json.tmp")),
        )
        .unwrap();
        spool.write_result(&j, json!({"status": "ok"})).unwrap();
        spool.write_state(&j, json!({"state": "exited"}));
        spool
            .write_json(j.as_str(), "reprises.json", &json!({"n": 1}))
            .unwrap();
        untouched(&target);
        let result = spool.root.join(j.file("result.json"));
        assert!(!result.is_symlink());
        assert_eq!(
            serde_json::from_slice::<Value>(&std::fs::read(result).unwrap()).unwrap()["state"],
            "done"
        );

        symlink(&secret, spool.root.join(DURATIONS)).unwrap();
        spool.record_duration("tp2-ex1", 3.0);
        untouched(&target);

        let link = Job::parse(&format!("{:032x}", 3)).unwrap();
        symlink(&target, spool.root.join(link.as_str())).unwrap();
        assert!(!spool.pending().contains(&link));
        assert!(!spool.claim(&link));
        assert!(spool.write_result(&link, json!({})).is_err());
        spool.write_state(&link, json!({}));
        assert!(!spool.unlock(&link));
        untouched(&target);

        // `src` as a link: a nested path is refused at the link, not only at the last component.
        symlink(&target, spool.root.join(j.file("src"))).unwrap();
        assert!(spool.read(&j.file("src/secret"), MAX_READ).is_err());
        assert!(
            spool
                .open_file(&j.file("src/nouveau"), OFlags::WRONLY | OFlags::CREATE)
                .is_err()
        );
        untouched(&target);

        spool.sweep(
            SystemTime::now() + Duration::from_secs(7200),
            Duration::from_secs(600),
        );
        untouched(&target);
        assert!(
            !spool.root.join(j.as_str()).exists(),
            "sweep kept a stale job"
        );
    }

    #[test]
    fn root_reads_follow_no_link_nor_hard_link_nor_fifo() {
        let (_scratch, spool, target) = hostile();
        let secret = target.join("secret");
        let j = job(&spool, 1, "{}");
        symlink(&secret, spool.root.join(j.file("files.json"))).unwrap();
        assert!(spool.read_json(&j.file("files.json")).is_err());
        std::fs::hard_link(&secret, spool.root.join(j.file("answers.json"))).unwrap();
        assert!(spool.read(&j.file("answers.json"), MAX_READ).is_err());

        let fifo = spool.root.join(j.file("in"));
        assert!(
            std::process::Command::new("mkfifo")
                .arg(&fifo)
                .status()
                .unwrap()
                .success()
        );
        let start = std::time::Instant::now();
        assert!(spool.read(&j.file("in"), MAX_READ).is_err());
        assert!(!spool.lock_held(&j.file("in")));
        assert!(start.elapsed() < Duration::from_secs(2));

        let other = job(&spool, 2, "{}");
        std::fs::remove_file(spool.root.join(other.file("job.json"))).unwrap();
        symlink(
            spool.root.join(j.file("job.json")),
            spool.root.join(other.file("job.json")),
        )
        .unwrap();
        assert_eq!(spool.job_field(&other, "exercise_id"), "");
        assert!(!spool.pending().contains(&other));
        assert!(spool.pending().contains(&j));

        std::fs::write(spool.root.join(j.file("big")), vec![b'x'; 11]).unwrap();
        assert!(spool.read(&j.file("big"), 10).is_err());
        assert!(!spool.exists(j.as_str(), "absent"));
        assert!(spool.exists(j.as_str(), "files.json"));
    }

    #[test]
    fn claim_reclaim_and_pending_order() {
        let (_scratch, spool, _target) = hostile();
        let first = job(&spool, 7, "{}");
        std::thread::sleep(Duration::from_millis(20));
        let second = job(&spool, 3, "{}");
        std::fs::create_dir(spool.root.join("pas-un-job")).unwrap();
        std::fs::write(spool.root.join("pas-un-job/job.json"), "{}").unwrap();
        assert_eq!(spool.pending(), [first.clone(), second.clone()]);
        assert!(spool.claim(&first));
        assert!(!spool.claim(&first));
        assert!(spool.lock_time(&first).is_some());
        assert!(spool.unlock(&first));
        assert!(spool.claim(&first));
        spool
            .write_json(first.as_str(), "reprises.json", &json!({"n": 2}))
            .unwrap();
        assert_eq!(spool.retries(&first), 2);
        spool.write_result(&second, json!({})).unwrap();
        assert_eq!(spool.pending(), [first]);
    }

    #[test]
    fn the_console_lock_is_single_and_expires() {
        let (_scratch, spool, _target) = hostile();
        assert!(spool.console_lock(Duration::from_secs(240)));
        assert!(!spool.console_lock(Duration::from_secs(240)));
        spool.console_unlock();
        assert!(spool.console_lock(Duration::from_secs(240)));
        assert!(
            spool.console_lock(Duration::ZERO) || {
                std::thread::sleep(Duration::from_millis(10));
                spool.console_lock(Duration::ZERO)
            }
        );
    }

    #[test]
    fn durations_are_a_bounded_sliding_mean() {
        let (_scratch, spool, _target) = hostile();
        spool.record_duration("tp2-ex3", 0.01);
        spool.record_duration("", 9.0);
        assert!(spool.durations().is_empty());
        spool.record_duration("tp2-ex3", 4.0);
        spool.record_duration("tp2-ex3", 6.0);
        assert_eq!(spool.durations()["tp2-ex3"], json!([5.0, 2]));
        for _ in 0..30 {
            spool.record_duration("tp1", 20.0);
        }
        assert_eq!(spool.durations()["tp1"][1], json!(DURATION_WINDOW + 1));
        std::fs::write(spool.root.join(DURATIONS), "pas du json").unwrap();
        assert!(spool.durations().is_empty());
        spool.record_duration("tp1", 3.0);
        assert_eq!(spool.durations()["tp1"], json!([3.0, 1]));
    }

    #[test]
    fn a_missing_openat2_stops_the_judge() {
        assert!(
            require_openat2(Err(rustix::io::Errno::NOSYS))
                .unwrap_err()
                .contains("5.6")
        );
        assert!(require_openat2(Err(rustix::io::Errno::PERM)).is_err());
    }
}
