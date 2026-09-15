//! gVisor containers through the Docker CLI. Nothing from the spool reaches a shell: argv only.

use std::io::Read;
use std::os::unix::process::ExitStatusExt;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitStatus, Stdio};
use std::time::{Duration, Instant};

use crate::config::Config;
use crate::gate::Mode;
use crate::spool::Job;

/// A student program can print without end; more than this is read and dropped.
const MAX_OUTPUT: usize = 16 * 1024 * 1024;

/// Root-owned scratch copy of what a container mounts. Docker resolves `-v` paths itself,
/// after any check the judge could make, so nothing is ever mounted from the spool.
pub struct Stage(pub PathBuf);

impl Stage {
    pub fn create(config: &Config, job: &Job) -> std::io::Result<Stage> {
        let path = config.work.join("jobs").join(job.as_str());
        let _ = std::fs::remove_dir_all(&path);
        std::fs::create_dir_all(path.join("src"))?;
        Ok(Stage(path))
    }
}

impl Drop for Stage {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn text(path: &Path) -> String {
    path.to_string_lossy().into_owned()
}

/// The two tmpfs mounts are the only writable surface. There is no seccomp profile: write()
/// cannot be filtered, so the read-only filesystem is the boundary.
fn hardened(
    config: &Config,
    name: &str,
    limits: [&str; 3],
    work: &str,
    tmp: &str,
    extra: &[&str],
) -> Vec<String> {
    let [memory, pids, cpus] = limits;
    let mut argv: Vec<String> = [
        config.docker.as_str(),
        "run",
        "--rm",
        "--name",
        name,
        "--runtime",
        &config.runtime,
        "--network",
        "none",
        "--read-only",
        "--tmpfs",
        &format!("/work:rw,exec,size={work},mode=0777"),
        "--tmpfs",
        &format!("/tmp:rw,size={tmp}"),
        "--memory",
        memory,
        "--memory-swap",
        memory,
        "--pids-limit",
        pids,
        "--cpus",
        cpus,
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        "65534:65534",
        "--ulimit",
        "fsize=8388608",
        "--ulimit",
        "nofile=64",
    ]
    .iter()
    .map(|s| s.to_string())
    .collect();
    argv.extend(extra.iter().map(|s| s.to_string()));
    argv
}

fn push_env(argv: &mut Vec<String>, config: &Config, nonce: &str) {
    argv.extend(["-e".to_string(), format!("CTESTER_NONCE={nonce}")]);
    for (key, value) in &config.sandbox_env {
        argv.extend(["-e".to_string(), format!("{key}={value}")]);
    }
}

pub fn judge_argv(
    config: &Config,
    stage: &Path,
    tp_dir: &Path,
    name: &str,
    mode: Mode,
    nonce: &str,
) -> Vec<String> {
    let limits = [config.memory.as_str(), &config.pids, &config.cpus];
    let mut argv = hardened(config, name, limits, "32m", "16m", &[]);
    argv.extend(["-v".to_string(), format!("{}/src:/in/src:ro", text(stage))]);
    push_env(&mut argv, config, nonce);
    // In io mode the tests are never mounted: inputs were extracted on the host.
    let mounts = match mode {
        Mode::Io => [
            format!("{}/cases:/in/cases:ro", text(stage)),
            format!("{}:/in/build.sh:ro", text(&config.build_io)),
        ]
        .to_vec(),
        _ => [
            format!("{}:/in/tests:ro", text(tp_dir)),
            format!("{}:/in/unity:ro", text(&config.unity_dir())),
            format!("{}:/in/build.sh:ro", text(&config.build_unity)),
        ]
        .to_vec(),
    };
    for mount in mounts {
        argv.extend(["-v".to_string(), mount]);
    }
    argv.extend([config.image.clone(), "bash".into(), "/in/build.sh".into()]);
    argv
}

pub fn console_argv(config: &Config, stage: &Path, name: &str, nonce: &str) -> Vec<String> {
    let limits = [
        config.console_memory.as_str(),
        &config.console_pids,
        &config.console_cpus,
    ];
    // -i only (docker refuses -t without a terminal); no log driver, or docker would record
    // everything the student types.
    let extra = [
        "--cpu-shares",
        &config.console_shares,
        "--log-driver",
        "none",
        "-i",
    ];
    let mut argv = hardened(config, name, limits, "24m", "8m", &extra);
    push_env(&mut argv, config, nonce);
    argv.extend([
        "-v".to_string(),
        format!("{}/src:/in/src:ro", text(stage)),
        "-v".to_string(),
        format!("{}:/in/build.sh:ro", text(&config.build_scratch)),
    ]);
    argv.extend([config.image.clone(), "bash".into(), "/in/build.sh".into()]);
    argv
}

/// Killing the docker client leaves the container running: it is removed by name.
pub fn remove_container(config: &Config, name: &str) {
    let _ = Command::new(&config.docker)
        .args(["rm", "-f", name])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
}

pub fn exit_code(status: ExitStatus) -> i64 {
    status
        .code()
        .map_or_else(|| -i64::from(status.signal().unwrap_or(0)), i64::from)
}

/// Runs a grading container: (exit code, stdout decoded leniently, with `\r\n` and `\r` as `\n`).
pub fn run(config: &Config, argv: &[String], name: &str) -> Result<(i64, String), String> {
    let mut child = Command::new(&argv[0])
        .args(&argv[1..])
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|e| format!("{}: {e}", argv[0]))?;
    let mut stdout = child.stdout.take().ok_or("no stdout pipe")?;
    let reader = std::thread::spawn(move || {
        let mut kept = Vec::new();
        let _ = (&mut stdout).take(MAX_OUTPUT as u64).read_to_end(&mut kept);
        let _ = std::io::copy(&mut stdout, &mut std::io::sink());
        kept
    });
    let deadline = Instant::now() + Duration::from_secs(config.job_timeout);
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break Some(status),
            Ok(None) if Instant::now() < deadline => std::thread::sleep(Duration::from_millis(10)),
            _ => break None,
        }
    };
    let Some(status) = status else {
        let _ = child.kill();
        remove_container(config, name);
        let _ = child.wait();
        let _ = reader.join();
        return Ok((137, String::new()));
    };
    let bytes = reader.join().unwrap_or_default();
    let out = String::from_utf8_lossy(&bytes)
        .replace("\r\n", "\n")
        .replace('\r', "\n")
        .replace("/in/src/", "");
    Ok((exit_code(status), out))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config(pairs: &[(&str, &str)]) -> Config {
        Config::from_lookup(|k| {
            pairs
                .iter()
                .find(|(key, _)| *key == k)
                .map(|(_, v)| v.to_string())
        })
        .unwrap()
    }

    fn after<'a>(argv: &'a [String], flag: &str) -> Vec<&'a str> {
        argv.windows(2)
            .filter(|w| w[0] == flag)
            .map(|w| w[1].as_str())
            .collect()
    }

    fn size(argv: &[String], mount: &str) -> u32 {
        let tmpfs = after(argv, "--tmpfs");
        let spec = tmpfs
            .iter()
            .find(|t| t.starts_with(&format!("{mount}:")))
            .unwrap();
        spec.split("size=")
            .nth(1)
            .unwrap()
            .split(['m', ','])
            .next()
            .unwrap()
            .parse()
            .unwrap()
    }

    const STAGE: &str = "/var/lib/ctester-judge/jobs/abc";

    #[test]
    fn the_grading_container_is_locked_down() {
        let config = config(&[
            ("CTESTER_CONTENT", "/opt/ctester/content"),
            ("CTESTER_C_STD", "gnu23"),
            ("CTESTER_SANITIZERS", ""),
            ("CTESTER_RUN_TIMEOUT", "5"),
        ]);
        let io = judge_argv(
            &config,
            Path::new(STAGE),
            Path::new("/tests/tp1"),
            "ctester-abc",
            Mode::Io,
            "n0nce",
        );
        let head: Vec<&str> = io.iter().take(32).map(String::as_str).collect();
        assert_eq!(
            head,
            [
                "docker",
                "run",
                "--rm",
                "--name",
                "ctester-abc",
                "--runtime",
                "runsc",
                "--network",
                "none",
                "--read-only",
                "--tmpfs",
                "/work:rw,exec,size=32m,mode=0777",
                "--tmpfs",
                "/tmp:rw,size=16m",
                "--memory",
                "256m",
                "--memory-swap",
                "256m",
                "--pids-limit",
                "64",
                "--cpus",
                "1",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--user",
                "65534:65534",
                "--ulimit",
                "fsize=8388608",
                "--ulimit",
                "nofile=64",
            ]
        );
        assert_eq!(
            io[io.len() - 3..],
            ["gcc:14-bookworm", "bash", "/in/build.sh"]
        );
        assert_eq!(
            after(&io, "-e"),
            [
                "CTESTER_NONCE=n0nce",
                "CTESTER_C_STD=gnu23",
                "CTESTER_SANITIZERS=",
                "CTESTER_RUN_TIMEOUT=5"
            ]
        );
        // In io mode the tests are never mounted: inputs were extracted on the host.
        assert_eq!(
            after(&io, "-v"),
            [
                &format!("{STAGE}/src:/in/src:ro"),
                &format!("{STAGE}/cases:/in/cases:ro"),
                "/opt/ctester/src/worker/build-io.sh:/in/build.sh:ro"
            ]
        );

        let unity = judge_argv(
            &config,
            Path::new(STAGE),
            Path::new("/tests/tp1"),
            "c",
            Mode::Unity,
            "n",
        );
        assert_eq!(
            after(&unity, "-v"),
            [
                &format!("{STAGE}/src:/in/src:ro"),
                "/tests/tp1:/in/tests:ro",
                "/opt/ctester/content/shared/unity:/in/unity:ro",
                "/opt/ctester/src/worker/build-unity.sh:/in/build.sh:ro"
            ]
        );
        assert!(
            !unity
                .iter()
                .any(|a| a == "--privileged" || a.contains("submission.c"))
        );
    }

    #[test]
    fn the_console_mounts_nothing_private_and_is_stricter() {
        let config = config(&[("CTESTER_CONTENT", "/opt/ctester/content")]);
        let console = console_argv(&config, Path::new(STAGE), "ctester-sbx-abc", "n");
        let joined = console.join(" ");
        for private in [
            "/opt/ctester/content",
            "/in/cases",
            "/in/tests",
            "/in/unity",
            "shared/unity",
        ] {
            assert!(!joined.contains(private), "{private}");
        }
        assert_eq!(
            after(&console, "-v"),
            [
                &format!("{STAGE}/src:/in/src:ro"),
                "/opt/ctester/src/worker/build-scratch.sh:/in/build.sh:ro"
            ]
        );
        // -i without -t (docker refuses a terminal it does not have), and no log of the keystrokes.
        assert!(
            console.iter().any(|a| a == "-i") && !console.iter().any(|a| a == "-t" || a == "-it")
        );
        assert_eq!(after(&console, "--log-driver"), ["none"]);
        assert_eq!(after(&console, "--user"), ["65534:65534"]);

        let grading = judge_argv(
            &config,
            Path::new(STAGE),
            Path::new("/t"),
            "c",
            Mode::Io,
            "n",
        );
        assert!(size(&console, "/work") < size(&grading, "/work"));
        assert!(size(&console, "/tmp") < size(&grading, "/tmp"));
        assert!(after(&console, "--cpu-shares")[0].parse::<u32>().unwrap() < 1024);
    }

    #[test]
    fn a_timeout_removes_the_container_and_reports_137() {
        let scratch = crate::spool::tests::Scratch::new("sandbox");
        let log = scratch.0.join("calls");
        let fake = scratch.0.join("docker");
        std::fs::write(
            &fake,
            format!(
                "#!/bin/sh\necho \"$@\" >> {}\n[ \"$1\" = run ] && exec sleep 30\nexit 0\n",
                log.display()
            ),
        )
        .unwrap();
        std::fs::set_permissions(&fake, std::os::unix::fs::PermissionsExt::from_mode(0o755))
            .unwrap();
        let config = config(&[
            ("CTESTER_DOCKER", fake.to_str().unwrap()),
            ("CTESTER_JOB_TIMEOUT", "1"),
        ]);
        let argv = judge_argv(
            &config,
            &scratch.0,
            Path::new("/tp"),
            "ctester-x",
            Mode::Io,
            "n",
        );
        let start = Instant::now();
        assert_eq!(
            run(&config, &argv, "ctester-x").unwrap(),
            (137, String::new())
        );
        assert!(start.elapsed() < Duration::from_secs(10));
        assert!(
            std::fs::read_to_string(log)
                .unwrap()
                .contains("rm -f ctester-x")
        );
    }

    #[test]
    fn output_is_decoded_with_plain_newlines() {
        let scratch = crate::spool::tests::Scratch::new("sandbox");
        let fake = scratch.0.join("docker");
        std::fs::write(
            &fake,
            "#!/bin/sh\nprintf 'a\\r\\nb\\rc /in/src/x.c \\377\\n'\nexit 3\n",
        )
        .unwrap();
        std::fs::set_permissions(&fake, std::os::unix::fs::PermissionsExt::from_mode(0o755))
            .unwrap();
        let config = config(&[("CTESTER_DOCKER", fake.to_str().unwrap())]);
        let argv = vec![fake.display().to_string()];
        assert_eq!(
            run(&config, &argv, "x").unwrap(),
            (3, "a\nb\nc x.c \u{fffd}\n".to_string())
        );
    }
}
