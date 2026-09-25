//! The spool belongs to the API (65534) and holds only its inputs; the judge, root, reads them
//! and writes nothing back here (see `results.rs`). Every read resolves beneath the spool with
//! `openat2(RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS)`, so no entry the API plants can redirect it.
//! Without `openat2` the judge does not start.

use std::collections::BTreeSet;
use std::fs::File;
use std::io::{self, Read};
use std::os::fd::OwnedFd;
use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use rustix::fs::{AtFlags, FileType, FlockOperation, Mode, OFlags, ResolveFlags, Stat};
use serde_json::Value;

use crate::grade;

pub const MAX_READ: usize = 4 * 1024 * 1024;

pub const MODERATORS: &str = "moderators.json";

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

fn denied(message: String) -> io::Error {
    io::Error::new(io::ErrorKind::PermissionDenied, message)
}

/// Refuses links (already), FIFOs, devices and hard links: only a file the API wrote itself.
fn plain(fd: OwnedFd, what: &str) -> io::Result<File> {
    let stat = rustix::fs::fstat(&fd)?;
    if FileType::from_raw_mode(stat.st_mode) != FileType::RegularFile || stat.st_nlink != 1 {
        return Err(denied(format!("{what}: not a plain file")));
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
        let flags = flags | OFlags::CLOEXEC | OFlags::NONBLOCK;
        Ok(rustix::fs::openat2(
            &self.fd,
            rel,
            flags,
            Mode::empty(),
            RESOLVE,
        )?)
    }

    fn dir(&self, rel: &str) -> io::Result<OwnedFd> {
        self.resolve(rel, OFlags::RDONLY | OFlags::DIRECTORY)
    }

    pub fn open_file(&self, rel: &str) -> io::Result<File> {
        plain(self.resolve(rel, OFlags::RDONLY)?, rel)
    }

    pub fn read(&self, rel: &str, limit: usize) -> io::Result<Vec<u8>> {
        let mut data = Vec::new();
        self.open_file(rel)?
            .take(limit as u64 + 1)
            .read_to_end(&mut data)?;
        if data.len() > limit {
            return Err(denied(format!("{rel}: larger than {limit} bytes")));
        }
        Ok(data)
    }

    pub fn read_json(&self, rel: &str) -> io::Result<Value> {
        serde_json::from_slice(&self.read(rel, MAX_READ)?)
            .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))
    }

    /// Nobody when anything is off
    pub fn moderators(&self) -> BTreeSet<String> {
        let Ok(Value::Array(subs)) = self
            .read(MODERATORS, 65536)
            .and_then(|raw| serde_json::from_slice(&raw).map_err(io::Error::other))
        else {
            return BTreeSet::new();
        };
        subs.iter()
            .filter_map(Value::as_str)
            .map(str::to_string)
            .collect()
    }

    /// A field of `job.json` as text; "" when anything is off.
    pub fn job_field(&self, job: &Job, field: &str) -> String {
        match self.read_json(&job.file("job.json")) {
            Ok(Value::Object(map)) => map.get(field).map(grade::as_text).unwrap_or_default(),
            _ => String::new(),
        }
    }

    /// `job.json`'s mtime, which is when the job became claimable: the API writes that file
    /// last and atomically, so nothing of the job predates it.
    pub fn queued_at(&self, job: &Job) -> Option<SystemTime> {
        let dir = self.dir(job.as_str()).ok()?;
        let stat = rustix::fs::statat(&dir, "job.json", AtFlags::SYMLINK_NOFOLLOW).ok()?;
        Some(mtime(&stat))
    }

    pub fn exists(&self, dir: &str, name: &str) -> bool {
        self.dir(dir)
            .and_then(|d| Ok(rustix::fs::statat(&d, name, AtFlags::SYMLINK_NOFOLLOW)?))
            .is_ok()
    }

    /// Read-only on purpose: flock needs no write access, and `alive` belongs to the API.
    pub fn lock_held(&self, rel: &str) -> bool {
        let Ok(file) = self.open_file(rel) else {
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

    /// Complete jobs, oldest first; whether one is done is for `Results` to say. Links and
    /// foreign names are never jobs.
    pub fn jobs(&self) -> Vec<Job> {
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
            if FileType::from_raw_mode(stat.st_mode) == FileType::RegularFile {
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

    /// A script written by a child process: a write descriptor held here would leak into a
    /// concurrent test's fork and make running the script fail with ETXTBSY.
    pub fn executable(path: &Path, body: &str) {
        use std::io::Write;
        use std::process::{Command, Stdio};
        let mut child = Command::new("sh")
            .args(["-c", "cat > \"$0\" && chmod 755 \"$0\""])
            .arg(path)
            .stdin(Stdio::piped())
            .spawn()
            .unwrap();
        child
            .stdin
            .take()
            .unwrap()
            .write_all(body.as_bytes())
            .unwrap();
        assert!(child.wait().unwrap().success());
    }

    /// A spool plus `cible`, a directory outside it that every attack aims at.
    fn hostile() -> (Scratch, Spool, PathBuf) {
        let scratch = Scratch::new("hostile");
        let root = scratch.0.join("spool");
        let target = scratch.0.join("target");
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
    fn root_reads_follow_no_link_nor_hard_link_nor_fifo() {
        let (_scratch, spool, target) = hostile();
        let secret = target.join("secret");
        let j = job(&spool, 1, "{}");
        symlink(&secret, spool.root.join(j.file("files.json"))).unwrap();
        assert!(spool.read_json(&j.file("files.json")).is_err());
        std::fs::hard_link(&secret, spool.root.join(j.file("answers.json"))).unwrap();
        assert!(spool.read(&j.file("answers.json"), MAX_READ).is_err());

        // `src` as a link: a nested path is refused at the link, not only at the last component.
        symlink(&target, spool.root.join(j.file("src"))).unwrap();
        assert!(spool.read(&j.file("src/secret"), MAX_READ).is_err());

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
        assert!(!spool.jobs().contains(&other));
        assert!(spool.jobs().contains(&j));

        std::fs::write(spool.root.join(j.file("big")), vec![b'x'; 11]).unwrap();
        assert!(spool.read(&j.file("big"), 10).is_err());
        assert!(!spool.exists(j.as_str(), "absent"));
        assert!(spool.exists(j.as_str(), "files.json"));
        untouched(&target);
    }

    #[test]
    fn jobs_come_oldest_first_and_links_are_never_jobs() {
        let (_scratch, spool, target) = hostile();
        let first = job(&spool, 7, "{}");
        std::thread::sleep(Duration::from_millis(20));
        let second = job(&spool, 3, "{}");
        std::fs::create_dir(spool.root.join("pas-un-job")).unwrap();
        std::fs::write(spool.root.join("pas-un-job/job.json"), "{}").unwrap();
        let link = Job::parse(&format!("{:032x}", 9)).unwrap();
        symlink(&target, spool.root.join(link.as_str())).unwrap();
        assert_eq!(spool.jobs(), [first.clone(), second]);

        spool.sweep(
            SystemTime::now() + Duration::from_secs(7200),
            Duration::from_secs(600),
        );
        untouched(&target);
        assert!(
            !spool.root.join(first.as_str()).exists(),
            "sweep kept a stale job"
        );
    }

    #[test]
    fn the_roster_is_a_plain_list_or_nobody() {
        let (scratch, spool, target) = hostile();
        let roster = spool.root.join(MODERATORS);
        assert!(spool.moderators().is_empty());
        std::fs::write(&roster, r#"["sub-a", 7, "sub-b"]"#).unwrap();
        let expected: BTreeSet<String> = ["sub-a", "sub-b"].map(String::from).into();
        assert_eq!(spool.moderators(), expected);
        for garbage in [r#"{"sub-a": true}"#, "sub-a", ""] {
            std::fs::write(&roster, garbage).unwrap();
            assert!(spool.moderators().is_empty(), "{garbage:?}");
        }
        // A link to a list outside the spool.
        std::fs::remove_file(&roster).unwrap();
        let outside = scratch.0.join("outside.json");
        std::fs::write(&outside, r#"["sub-a"]"#).unwrap();
        symlink(&outside, &roster).unwrap();
        assert!(spool.moderators().is_empty());
        untouched(&target);
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
