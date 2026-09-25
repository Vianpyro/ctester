//! Interactive console sessions: the API appends keystrokes to `in` and reads `build`/`out`;
//! the judge pipes them through a sandbox until one of the session limits ends it.

use std::fs::File;
use std::io::{Read, Write};
use std::path::Path;
use std::process::{Command, Stdio};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use rustix::fs::FlockOperation;
use serde_json::{Value, json};

use crate::config::Config;
use crate::gate;
use crate::log::{self, Severity};
use crate::results::Results;
use crate::sandbox::{self, Stage};
use crate::spool::{self, Job, MAX_READ, Spool};

#[derive(Default)]
pub struct Counter {
    pub out_bytes: AtomicU64,
    pub over: AtomicBool,
    pub seen_ms: AtomicU64,
    pub compiled: AtomicBool,
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_millis() as u64)
}

impl Counter {
    fn touch(&self) {
        self.seen_ms.store(now_ms(), Ordering::Relaxed);
    }
}

/// Splits the container's output at `<nonce> RUN`: gcc's text goes to `build`, the program's
/// to `out`, capped at `out_max` bytes.
pub fn pump(
    mut source: impl Read,
    mut build: File,
    mut out: File,
    nonce: &str,
    counter: &Counter,
    out_max: u64,
) {
    let separator = format!("{nonce} RUN\n").into_bytes();
    // The buffer keeps a tail between reads, so a marker split across two reads is still found.
    let keep = separator.len() - 1;
    let (mut buffer, mut in_build) = (Vec::new(), true);
    let mut write = |to_out: bool, bytes: &[u8]| {
        if bytes.is_empty() {
            return;
        }
        let mut bytes = bytes;
        if to_out {
            let used = counter.out_bytes.load(Ordering::Relaxed);
            let remaining = out_max.saturating_sub(used);
            if remaining == 0 {
                counter.over.store(true, Ordering::Relaxed);
                return;
            }
            if bytes.len() as u64 >= remaining {
                counter.over.store(true, Ordering::Relaxed);
                bytes = &bytes[..remaining as usize];
            }
            counter
                .out_bytes
                .store(used + bytes.len() as u64, Ordering::Relaxed);
        }
        let target = if to_out { &mut out } else { &mut build };
        let _ = target.write_all(bytes);
        counter.touch();
    };
    let mut chunk = vec![0u8; 65536];
    loop {
        let n = match source.read(&mut chunk) {
            Ok(0) | Err(_) => break,
            Ok(n) => n,
        };
        if !in_build {
            write(true, &chunk[..n]);
            continue;
        }
        buffer.extend_from_slice(&chunk[..n]);
        if let Some(i) = buffer.windows(separator.len()).position(|w| w == separator) {
            write(false, &buffer[..i]);
            let after = buffer.split_off(i + separator.len());
            buffer.clear();
            in_build = false;
            counter.compiled.store(true, Ordering::Relaxed);
            write(true, &after);
        } else if buffer.len() > keep {
            let tail = buffer.split_off(buffer.len() - keep);
            write(false, &buffer);
            buffer = tail;
        }
    }
    if !buffer.is_empty() {
        write(!in_build, &buffer);
    }
}

/// Copies `main.c` and the optional header into `dest`. The header's name comes from the API's
/// `job.json`, so it is checked again before it becomes a path.
fn stage_sources(spool: &Spool, job: &Job, dest: &Path) -> std::io::Result<()> {
    let mut names = vec!["main.c".to_string()];
    let header = spool.job_field(job, "header");
    if !header.is_empty() {
        if !gate::valid_header_name(&header) {
            return Err(std::io::Error::other(format!(
                "invalid header name {header:?}"
            )));
        }
        names.push(header);
    }
    for name in names {
        let source = spool.read(&job.file(&format!("src/{name}")), MAX_READ)?;
        std::fs::write(dest.join(&name), source)?;
    }
    Ok(())
}

fn exited(results: &Results, job: &Job, code: i64, reason: &str) -> Value {
    results.write_state(
        job,
        json!({"state": "exited", "code": code, "reason": reason}),
    );
    json!({"status": "console", "code": code, "reason": reason})
}

pub fn run_console(
    config: &Config,
    spool: &Spool,
    results: &Results,
    job: &Job,
) -> Result<Value, String> {
    let name = format!("ctester-sbx-{}", &job.as_str()[..16]);
    let nonce = spool::random_hex(16);
    let counter = Arc::new(Counter::default());
    counter.touch();

    if !config.build_scratch.is_file() {
        log::event(
            Severity::Error,
            "console.build_missing",
            &format!(
                "CTESTER_BUILD_SCRATCH not found ({})",
                config.build_scratch.display()
            ),
            &[("ctester.job.id", json!(job.as_str()))],
        );
        return Ok(exited(results, job, -1, "build_missing"));
    }
    if !spool.lock_held(&job.file("alive")) {
        return Ok(exited(results, job, -1, "api"));
    }
    let Ok(claim) = results.claim_file(job) else {
        return Ok(exited(results, job, -1, "worker"));
    };
    let held = (0..100).any(|_| {
        let ok = rustix::fs::flock(&claim, FlockOperation::NonBlockingLockExclusive).is_ok();
        if !ok {
            std::thread::sleep(Duration::from_millis(10));
        }
        ok
    });
    if !held {
        log::event(
            Severity::Warn,
            "console.claim_held",
            "the session's claim is already held",
            &[("ctester.job.id", json!(job.as_str()))],
        );
        return Ok(exited(results, job, -1, "worker"));
    }

    let staged = Stage::create(config, job).and_then(|stage| {
        stage_sources(spool, job, &stage.0.join("src"))?;
        Ok(stage)
    });
    let stage = match staged {
        Ok(stage) => stage,
        Err(e) => {
            log::event(
                Severity::Error,
                "console.stage_failed",
                &format!("the session could not be staged: {e}"),
                &[("ctester.job.id", json!(job.as_str()))],
            );
            return Ok(exited(results, job, -1, "worker"));
        }
    };

    results.write_state(
        job,
        json!({"state": "compiling", "ttl": config.console_session_max}),
    );
    let outputs = results
        .append(job, "build")
        .and_then(|build| Ok((build, results.append(job, "out")?)));
    let argv = sandbox::console_argv(config, &stage.0, &name, &nonce);
    let (reader, writer) = std::io::pipe().map_err(|e| e.to_string())?;
    let mut command = Command::new(&argv[0]);
    command
        .args(&argv[1..])
        .stdin(Stdio::piped())
        .stdout(writer.try_clone().map_err(|e| e.to_string())?)
        .stderr(writer);
    let mut child = command.spawn().map_err(|e| format!("{}: {e}", argv[0]))?;
    // The parent's copies of the pipe must close, or the pump would never see the end.
    drop(command);
    let pump_thread = match outputs {
        Ok((build, out)) => {
            let (counter, nonce, out_max) =
                (Arc::clone(&counter), nonce.clone(), config.console_out_max);
            Some(std::thread::spawn(move || {
                pump(reader, build, out, &nonce, &counter, out_max)
            }))
        }
        // The results tree is root's, so this is a full disk or a broken mount: end at once.
        Err(_) => {
            counter.over.store(true, Ordering::Relaxed);
            None
        }
    };

    let mut stdin = child.stdin.take();
    let start = Instant::now();
    let (mut read, mut announced) = (0u64, false);
    let mut chunk = vec![0u8; 65536];
    let mut reason = loop {
        if !matches!(child.try_wait(), Ok(None)) {
            break "exited";
        }
        if read < config.console_in_max
            && let Ok(input) = spool.open_file(&job.file("in"))
        {
            let want = (config.console_in_max - read).min(chunk.len() as u64) as usize;
            if let Ok(n) = rustix::io::pread(&input, &mut chunk[..want], read)
                && n > 0
            {
                read += n as u64;
                counter.touch();
                if let Some(pipe) = stdin.as_mut() {
                    let _ = pipe.write_all(&chunk[..n]).and_then(|()| pipe.flush());
                }
            }
        }
        if stdin.is_some() && spool.exists(job.as_str(), "eof") {
            stdin = None;
        }
        if !spool.lock_held(&job.file("alive")) {
            break "api";
        }
        if start.elapsed() > Duration::from_secs(config.console_session_max) {
            break "timeout";
        }
        let idle = now_ms().saturating_sub(counter.seen_ms.load(Ordering::Relaxed));
        if idle > config.console_idle_max * 1000 {
            break "idle";
        }
        if counter.over.load(Ordering::Relaxed) {
            break "output";
        }
        if !announced && counter.compiled.load(Ordering::Relaxed) {
            announced = true;
            results.write_state(
                job,
                json!({"state": "running", "ttl": config.console_session_max}),
            );
        }
        std::thread::sleep(Duration::from_millis(25));
    };

    // child.kill() alone would only kill the docker client.
    sandbox::remove_container(config, &name);
    let deadline = Instant::now() + Duration::from_secs(5);
    let mut status = None;
    while status.is_none() && Instant::now() < deadline {
        status = child.try_wait().ok().flatten();
        if status.is_none() {
            std::thread::sleep(Duration::from_millis(20));
        }
    }
    if status.is_none() {
        let _ = child.kill();
        status = child.wait().ok();
    }
    drop(stdin);
    if let Some(thread) = pump_thread {
        let deadline = Instant::now() + Duration::from_secs(5);
        while !thread.is_finished() && Instant::now() < deadline {
            std::thread::sleep(Duration::from_millis(20));
        }
        if thread.is_finished() {
            let _ = thread.join();
        }
    }
    drop(stage);

    let code = status.map_or(-1, sandbox::exit_code);
    if reason == "exited" && !counter.compiled.load(Ordering::Relaxed) {
        reason = if code == crate::grade::COMPILE_TIMEOUT {
            "compile_timeout"
        } else {
            "compile_error"
        };
    }
    let result = exited(results, job, code, reason);
    drop(claim);
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::spool::tests::Scratch;

    fn pump_bytes(chunks: &[&[u8]], nonce: &str, out_max: u64) -> (Vec<u8>, Vec<u8>, Counter) {
        struct Chunks<'a>(Vec<&'a [u8]>);
        impl Read for Chunks<'_> {
            fn read(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
                match self.0.first_mut() {
                    None => Ok(0),
                    Some(chunk) => {
                        let n = chunk.len().min(buf.len());
                        buf[..n].copy_from_slice(&chunk[..n]);
                        *chunk = &chunk[n..];
                        if chunk.is_empty() {
                            self.0.remove(0);
                        }
                        Ok(n)
                    }
                }
            }
        }
        let scratch = Scratch::new("pump");
        let (b, o) = (scratch.0.join("build"), scratch.0.join("out"));
        let counter = Counter::default();
        pump(
            Chunks(chunks.to_vec()),
            File::create(&b).unwrap(),
            File::create(&o).unwrap(),
            nonce,
            &counter,
            out_max,
        );
        (
            std::fs::read(b).unwrap(),
            std::fs::read(o).unwrap(),
            counter,
        )
    }

    #[test]
    fn the_phase_switches_on_the_marker_even_split_across_reads() {
        let flow: &[u8] = b"warning: ceci vient de gcc\nabcd1234 RUN\nEntrez : 42\n";
        let marker = flow.windows(8).position(|w| w == b"abcd1234").unwrap();
        for cut in [None, Some(marker + 3), Some(marker + 12)] {
            let chunks: Vec<&[u8]> = match cut {
                None => vec![flow],
                Some(at) => vec![&flow[..at], &flow[at..]],
            };
            let (build, out, counter) = pump_bytes(&chunks, "abcd1234", 1 << 20);
            assert_eq!(build, b"warning: ceci vient de gcc\n", "{cut:?}");
            assert_eq!(out, b"Entrez : 42\n", "{cut:?}");
            assert!(counter.compiled.load(Ordering::Relaxed));
        }
    }

    fn staged_names(job_json: &str, files: &[(&str, &str)]) -> Result<Vec<String>, String> {
        let scratch = Scratch::new("stage");
        let (root, dest) = (scratch.0.join("spool"), scratch.0.join("dest"));
        let job = Job::parse(&"b".repeat(32)).unwrap();
        std::fs::create_dir_all(root.join(job.file("src"))).unwrap();
        std::fs::create_dir_all(&dest).unwrap();
        std::fs::write(root.join(job.file("job.json")), job_json).unwrap();
        std::fs::write(scratch.0.join("secret.h"), "SECRET").unwrap();
        for (name, text) in files {
            let path = root.join(job.file(&format!("src/{name}")));
            match text.strip_prefix("->") {
                Some(target) => std::os::unix::fs::symlink(scratch.0.join(target), path).unwrap(),
                None => std::fs::write(path, text).unwrap(),
            }
        }
        let spool = Spool::open(&root).unwrap();
        stage_sources(&spool, &job, &dest).map_err(|e| e.to_string())?;
        let mut names: Vec<String> = std::fs::read_dir(&dest)
            .unwrap()
            .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
            .collect();
        names.sort();
        assert!(
            !names
                .iter()
                .any(|n| std::fs::read_to_string(dest.join(n)).unwrap() == "SECRET")
        );
        Ok(names)
    }

    #[test]
    fn the_console_stages_main_c_and_only_a_valid_header() {
        let main = ("main.c", "int main(void){return 0;}");
        assert_eq!(
            staged_names(r#"{"kind": "console"}"#, &[main, ("autre.h", "x")]),
            Ok(vec!["main.c".to_string()])
        );
        assert_eq!(
            staged_names(
                r#"{"kind": "console", "header": "pile.h"}"#,
                &[main, ("pile.h", "#define N 3\n")]
            ),
            Ok(vec!["main.c".to_string(), "pile.h".to_string()])
        );
        for name in ["../secret.h", "a.c", ".h", "src/pile.h"] {
            let job = json!({"kind": "console", "header": name}).to_string();
            assert!(staged_names(&job, &[main]).is_err(), "{name}");
        }
        let linked = r#"{"kind": "console", "header": "pile.h"}"#;
        assert!(staged_names(linked, &[main, ("pile.h", "->secret.h")]).is_err());
        assert!(staged_names(linked, &[main]).is_err(), "a missing header");
    }

    #[test]
    fn the_output_is_capped() {
        let big = [b"n RUN\n".as_slice(), &[b'x'; 5000]].concat();
        let (_, out, counter) = pump_bytes(&[&big], "n", 100);
        assert!(counter.over.load(Ordering::Relaxed));
        assert!(out.len() <= 100);
    }
}
