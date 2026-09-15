#![forbid(unsafe_code)]
// The runner, which uses most of `grade`, only exists on Linux.
#![cfg_attr(not(target_os = "linux"), allow(dead_code))]

mod grade;

#[cfg(target_os = "linux")]
mod cache;
#[cfg(target_os = "linux")]
mod config;
#[cfg(target_os = "linux")]
mod console;
#[cfg(target_os = "linux")]
mod gate;
#[cfg(target_os = "linux")]
mod results;
#[cfg(target_os = "linux")]
mod sandbox;
#[cfg(target_os = "linux")]
mod spool;

use std::io::Read;
use std::process::ExitCode;

use serde_json::{Value, json};

const USAGE: &str = "usage: ctester-judge run [--once] | self-check | grade < request.json";

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let args: Vec<&str> = args.iter().map(String::as_str).collect();
    match args.as_slice() {
        ["grade"] => report(grade_request()),
        #[cfg(target_os = "linux")]
        ["self-check"] => report(runner::Runner::start().map(|r| r.describe())),
        #[cfg(target_os = "linux")]
        ["run"] | ["run", "--once"] => match runner::Runner::start() {
            Ok(mut runner) => runner.run(args.len() == 2),
            Err(message) => {
                eprintln!("ctester: refusing to start: {message}");
                ExitCode::FAILURE
            }
        },
        _ => {
            eprintln!("{USAGE}");
            ExitCode::from(2)
        }
    }
}

fn report(result: Result<Value, String>) -> ExitCode {
    match result {
        Ok(value) => {
            println!("{value}");
            ExitCode::SUCCESS
        }
        Err(message) => {
            eprintln!("ctester-judge: {message}");
            ExitCode::FAILURE
        }
    }
}

/// One JSON request on stdin, for the content tools that need the grading rules.
fn grade_request() -> Result<Value, String> {
    let mut raw = String::new();
    std::io::stdin()
        .read_to_string(&mut raw)
        .map_err(|e| e.to_string())?;
    let request: Value = serde_json::from_str(&raw).map_err(|e| e.to_string())?;
    let text = |key: &str| request.get(key).and_then(Value::as_str).unwrap_or("");
    let tolerance = grade::tolerance(&request)?;
    match text("op") {
        "verdict" => {
            let rc = request
                .get("rc")
                .and_then(Value::as_i64)
                .ok_or("rc is required")?;
            let cases = request
                .get("cases")
                .and_then(Value::as_array)
                .map_or(&[][..], Vec::as_slice);
            let mode = if text("mode").is_empty() {
                "unity"
            } else {
                text("mode")
            };
            grade::judge_output(mode, rc, text("output"), text("nonce"), cases, tolerance)
        }
        "check_case" => {
            let case = request.get("case").ok_or("case is required")?;
            Ok(json!({"reason": grade::check_case(case, text("output"), tolerance)?}))
        }
        "grade_quiz" => {
            let field = |key| request.get(key).ok_or(format!("{key} is required"));
            grade::grade_quiz(field("quiz")?, field("answers")?)
        }
        other => Err(format!("unknown op {other:?}")),
    }
}

#[cfg(target_os = "linux")]
mod runner {
    use std::collections::{HashMap, HashSet};
    use std::panic::{AssertUnwindSafe, catch_unwind};
    use std::process::ExitCode;
    use std::time::{Duration, Instant, SystemTime};

    use serde_json::{Value, json};
    use sha2::Sha256;

    use crate::cache::{self, Cache};
    use crate::config::Config;
    use crate::console;
    use crate::gate::{self, Exercise, Mode};
    use crate::grade;
    use crate::results::Results;
    use crate::sandbox::{self, Stage};
    use crate::spool::{self, Job, Spool};

    const CONSOLE_DURATION: &str = ":console";

    struct Context {
        exercise: Exercise,
        conf: Value,
        fingerprint: Sha256,
    }

    pub struct Runner {
        config: Config,
        spool: Spool,
        results: Results,
        cache: Cache,
        /// Per pending job: (fingerprint it was computed under, signature).
        signatures: HashMap<Job, (String, String)>,
    }

    fn internal_error() -> Value {
        json!({"status": "error", "message": "Erreur interne du juge. Réessaie."})
    }

    impl Runner {
        pub fn start() -> Result<Runner, String> {
            Runner::with(Config::from_env()?)
        }

        fn with(config: Config) -> Result<Runner, String> {
            std::fs::create_dir_all(&config.spool)
                .map_err(|e| format!("{}: {e}", config.spool.display()))?;
            let jobs = config.work.join("jobs");
            std::fs::create_dir_all(&jobs).map_err(|e| format!("{}: {e}", jobs.display()))?;
            for script in [&config.build_io, &config.build_unity] {
                if !script.is_file() {
                    return Err(format!("{} is missing", script.display()));
                }
            }
            let spool = Spool::open(&config.spool)?;
            let results = Results::open(&config.results)?;
            let cache = Cache::new(&config);
            Ok(Runner {
                config,
                spool,
                results,
                cache,
                signatures: HashMap::new(),
            })
        }

        pub fn describe(&self) -> Value {
            let c = &self.config;
            json!({
                "spool": c.spool, "results": c.results, "work": c.work, "content": c.content, "image": c.image,
                "runtime": c.runtime, "job_timeout": c.job_timeout, "lock_stale": c.lock_stale,
                "sweep_after": c.sweep_after, "preview": c.preview, "cache_max": c.cache_max,
                "moderators": c.moderators.len(), "sandbox_env": c.sandbox_env,
            })
        }

        fn job_path(&self, job: &Job) -> String {
            self.spool.root.join(job.as_str()).display().to_string()
        }

        fn pending(&self) -> Vec<Job> {
            let mut jobs = self.spool.jobs();
            jobs.retain(|job| !self.results.done(job));
            jobs
        }

        pub fn run(&mut self, once: bool) -> ExitCode {
            if self.config.preview {
                eprintln!("ctester: PREVIEW ACTIVE -- exercises not yet open are being graded");
            }
            loop {
                // Known verdicts first, then a single compilation per pass.
                let mut worked = self.serve_known() > 0;
                for job in self.pending() {
                    let console = self.spool.job_field(&job, "kind") == "console";
                    let stale = Duration::from_secs(self.config.console_session_max + 60);
                    if console && !self.results.console_lock(stale) {
                        continue;
                    }
                    if !self.results.claim(&job)
                        && !(self.reclaim(&job) && self.results.claim(&job))
                    {
                        if console {
                            self.results.console_unlock();
                        }
                        continue;
                    }
                    worked = true;
                    self.process(&job, console);
                    if console {
                        self.results.console_unlock();
                    }
                    break;
                }
                // The spool first: its job directories are never newer than their results.
                let after = Duration::from_secs(self.config.sweep_after);
                self.spool.sweep(SystemTime::now(), after);
                self.results.sweep(SystemTime::now(), after);
                let work = Spool::open(&self.config.work.join("jobs"));
                if let Ok(work) = work {
                    work.sweep(
                        SystemTime::now(),
                        Duration::from_secs(self.config.sweep_after),
                    );
                }
                if once {
                    return ExitCode::SUCCESS;
                }
                if !worked {
                    std::thread::sleep(Duration::from_millis(500));
                }
            }
        }

        /// A job must never take the worker down, a panic included.
        fn process(&mut self, job: &Job, console: bool) {
            let start = Instant::now();
            let outcome = catch_unwind(AssertUnwindSafe(|| match console {
                true => console::run_console(&self.config, &self.spool, &self.results, job),
                false => self.run_job(job),
            }));
            let failure = match outcome {
                Ok(Ok(verdict)) => match self.results.write_result(job, verdict) {
                    Ok(()) => {
                        let key = match console {
                            true => CONSOLE_DURATION.to_string(),
                            false => self.spool.job_field(job, "exercise_id"),
                        };
                        self.results
                            .record_duration(&key, start.elapsed().as_secs_f64());
                        return;
                    }
                    Err(e) => e.to_string(),
                },
                Ok(Err(message)) => message,
                Err(_) => "panic".to_string(),
            };
            eprintln!("ctester: {}: {failure}", self.job_path(job));
            let _ = self.results.write_result(job, internal_error());
            if console {
                self.results.write_state(
                    job,
                    json!({"state": "exited", "code": -1, "reason": "worker"}),
                );
            }
        }

        fn reclaim(&self, job: &Job) -> bool {
            let stale = Duration::from_secs(self.config.lock_stale);
            let Some(locked) = self.results.lock_time(job) else {
                return false;
            };
            if SystemTime::now()
                .duration_since(locked)
                .is_ok_and(|age| age < stale)
                || locked > SystemTime::now()
            {
                return false;
            }
            let attempt = self.results.retries(job) + 1;
            if attempt > self.config.lock_retries {
                eprintln!(
                    "ctester: {}: abandoned after {} reclaim(s)",
                    self.job_path(job),
                    attempt - 1
                );
                let verdict = json!({"status": "error", "message": "Le juge a été interrompu pendant ce test. Relance-le."});
                let _ = self.results.write_result(job, verdict);
                return false;
            }
            // Counted before the rmdir, so a worker dying in between still uses up the attempt.
            if self
                .results
                .write_json(Some(job), "reprises.json", &json!({"n": attempt}))
                .is_err()
                || !self.results.unlock(job)
            {
                return false;
            }
            eprintln!(
                "ctester: {}: stale lock reclaimed (attempt {attempt})",
                self.job_path(job)
            );
            true
        }

        fn context(&self, exercise_id: &str) -> Option<Context> {
            let exercise = gate::find(&self.config, exercise_id, "", gate::now())?;
            if exercise.mode == Mode::Quiz {
                return None;
            }
            let conf = gate::load_config(&exercise).ok()?;
            let fingerprint = cache::fingerprint(&self.config, exercise_id, &exercise);
            Some(Context {
                exercise,
                conf,
                fingerprint,
            })
        }

        fn signature_of(&mut self, job: &Job, ctx: &Context) -> Option<String> {
            let mark = cache::hex(&ctx.fingerprint);
            if let Some((known, sig)) = self.signatures.get(job)
                && *known == mark
            {
                return Some(sig.clone());
            }
            let sent = self
                .spool
                .read_json(&job.file("files.json"))
                .ok()
                .filter(Value::is_object)?;
            let sig = cache::signature(&ctx.fingerprint, &ctx.conf, &ctx.exercise.path, &sent);
            self.signatures.insert(job.clone(), (mark, sig.clone()));
            Some(sig)
        }

        /// Serves every already-known verdict before compiling anything.
        fn serve_known(&mut self) -> usize {
            let mut contexts: HashMap<String, Option<Context>> = HashMap::new();
            let mut alive = HashSet::new();
            let mut served = 0;
            for job in self.pending() {
                alive.insert(job.clone());
                let exercise_id = self.spool.job_field(&job, "exercise_id");
                if !contexts.contains_key(&exercise_id) {
                    let ctx = self.context(&exercise_id);
                    contexts.insert(exercise_id.clone(), ctx);
                }
                let Some(ctx) = &contexts[&exercise_id] else {
                    continue;
                };
                let Some(sig) = self.signature_of(&job, ctx) else {
                    continue;
                };
                let Some(verdict) = self.cache.read(&sig) else {
                    continue;
                };
                if !self.results.claim(&job) {
                    continue;
                }
                eprintln!("ctester: cache servi {exercise_id} {} [file]", &sig[..12]);
                if self.results.write_result(&job, verdict).is_ok() {
                    served += 1;
                }
            }
            self.signatures.retain(|job, _| alive.contains(job));
            served
        }

        fn run_job(&mut self, job: &Job) -> Result<Value, String> {
            let exercise_id = self.spool.job_field(job, "exercise_id");
            let owner = self.spool.job_field(job, "owner");
            let Some(exercise) = gate::find(&self.config, &exercise_id, &owner, gate::now()) else {
                return Ok(json!({"status": "error", "message": "Exercice inconnu."}));
            };
            let read = |name: &str| {
                self.spool
                    .read_json(&job.file(name))
                    .map_err(|e| format!("{name}: {e}"))
            };
            let conf = gate::load_config(&exercise)?;
            if exercise.mode == Mode::Quiz {
                return grade::grade_quiz(&conf, &read("answers.json")?);
            }
            let sent = read("files.json")?;
            if !sent.is_object() {
                return Err("files.json must be an object".into());
            }
            let fingerprint = cache::fingerprint(&self.config, &exercise_id, &exercise);
            let sig = cache::signature(&fingerprint, &conf, &exercise.path, &sent);
            if let Some(known) = self.cache.read(&sig) {
                eprintln!("ctester: cache servi {exercise_id} {} [dépilé]", &sig[..12]);
                return Ok(known);
            }
            let mut verdict = self.judge(job, &exercise, &conf, &sent)?;
            if cache::cachable(&conf, &verdict) {
                self.cache.write(&sig, &verdict);
                eprintln!("ctester: cache écrit {exercise_id} {}", &sig[..12]);
            } else if let Some(map) = verdict.as_object_mut() {
                map.insert("rejouer".into(), json!(true));
            }
            Ok(verdict)
        }

        fn judge(
            &self,
            job: &Job,
            exercise: &Exercise,
            conf: &Value,
            sent: &Value,
        ) -> Result<Value, String> {
            let stage = Stage::create(&self.config, job).map_err(|e| e.to_string())?;
            let names = gate::declared_files(conf, &exercise.path);
            let mut code = String::new();
            for name in &names {
                let content = sent.get(name).map(grade::as_text).unwrap_or_default();
                std::fs::write(stage.0.join("src").join(name), &content)
                    .map_err(|e| e.to_string())?;
                code.push_str(&content);
                code.push('\n');
            }
            let allowed = gate::read_allowed(&exercise.path).map(|mut allowed| {
                allowed.extend(names.iter().cloned());
                allowed
            });
            let bad = grade::forbidden_includes(&code, allowed.as_ref());
            if !bad.is_empty() {
                let message = format!(
                    "En-têtes non autorisés pour ce TP : {}. Utilise seulement ce qui a été vu en cours.",
                    bad.join(", ")
                );
                return Ok(json!({"status": "forbidden_include", "message": message}));
            }
            let nonce = spool::random_hex(16);
            let name = format!("ctester-{}", &job.as_str()[..16]);
            let (cases, tolerance) = match exercise.mode {
                Mode::Io => {
                    let cases = match conf.get("cases") {
                        None => Vec::new(),
                        Some(Value::Array(cases)) => cases.clone(),
                        Some(_) => return Err("cases must be a list".into()),
                    };
                    let dir = stage.0.join("cases");
                    std::fs::create_dir(&dir).map_err(|e| e.to_string())?;
                    for (index, case) in cases.iter().enumerate() {
                        let stdin = match case.get("stdin") {
                            None => "",
                            Some(Value::String(s)) => s,
                            Some(_) => return Err("stdin must be text".into()),
                        };
                        std::fs::write(dir.join(format!("{:02}.in", index + 1)), stdin)
                            .map_err(|e| e.to_string())?;
                    }
                    (cases, grade::tolerance(conf)?)
                }
                _ => (Vec::new(), grade::DEFAULT_TOLERANCE),
            };
            let argv = sandbox::judge_argv(
                &self.config,
                &stage.0,
                &exercise.path,
                &name,
                exercise.mode,
                &nonce,
            );
            let (rc, out) = sandbox::run(&self.config, &argv, &name)?;
            grade::judge_output(exercise.mode.as_str(), rc, &out, &nonce, &cases, tolerance)
        }
    }

    #[cfg(test)]
    mod tests {
        use super::*;
        use crate::spool::tests::Scratch;
        use rustix::fs::{FlockOperation, Mode, OFlags};
        use std::os::unix::fs::{PermissionsExt, symlink};
        use std::path::Path;

        struct World {
            scratch: Scratch,
            runner: Runner,
            next: u32,
        }

        fn write(path: &Path, body: &str) {
            std::fs::create_dir_all(path.parent().unwrap()).unwrap();
            std::fs::write(path, body).unwrap();
        }

        fn exercise(content: &Path, id: &str, state: &str, file: &str, conf: &str) {
            let dir = content.join("exercises").join(id);
            write(
                &dir.join("exercise.json"),
                &json!({"id": id, "release": {"state": state}}).to_string(),
            );
            write(&dir.join("assessment").join(file), conf);
        }

        impl World {
            fn new() -> World {
                let scratch = Scratch::new("e2e");
                let root = scratch.0.clone();
                let content = root.join("content");
                let io_conf = r#"{"cases": [{"stdin": "1\n", "expect": [1]}]}"#;
                exercise(&content, "tp-io", "available", "io.json", io_conf);
                write(
                    &content.join("exercises/tp-io/assessment/allowed_includes.txt"),
                    "stdio.h\n",
                );
                exercise(&content, "tp-unity", "available", "unity.json", "{}");
                let quiz = r#"{"questions": [{"id": "q1", "type": "hex8", "answer": "A7"}]}"#;
                exercise(&content, "tp-quiz", "available", "quiz.json", quiz);
                exercise(&content, "tp-ferme", "archived", "io.json", io_conf);
                std::fs::create_dir_all(content.join("shared/unity")).unwrap();
                for script in ["build-io.sh", "build-unity.sh", "build-scratch.sh"] {
                    write(&root.join(script), "#!/bin/bash\n");
                }
                write(
                    &root.join("docker"),
                    include_str!("../tests/fake_docker.sh"),
                );
                std::fs::set_permissions(
                    root.join("docker"),
                    std::fs::Permissions::from_mode(0o755),
                )
                .unwrap();
                let p = |name: &str| root.join(name).display().to_string();
                let pairs = [
                    ("CTESTER_SPOOL", p("spool")),
                    ("CTESTER_RESULTS", p("results")),
                    ("CTESTER_WORK", p("work")),
                    ("CTESTER_CONTENT", p("content")),
                    ("CTESTER_BUILD_IO", p("build-io.sh")),
                    ("CTESTER_BUILD_UNITY", p("build-unity.sh")),
                    ("CTESTER_BUILD_SCRATCH", p("build-scratch.sh")),
                    ("CTESTER_DOCKER", p("docker")),
                    ("CTESTER_JOB_TIMEOUT", "10".into()),
                    ("CTESTER_FORUM_MODERATORS", "sub-prof".into()),
                    ("CTESTER_CONSOLE_SESSION_MAX", "20".into()),
                    ("CTESTER_CONSOLE_IDLE_MAX", "10".into()),
                ];
                let lookup = |k: &str| {
                    pairs
                        .iter()
                        .find(|(key, _)| *key == k)
                        .map(|(_, v)| v.clone())
                };
                let runner = Runner::with(Config::from_lookup(lookup).unwrap()).unwrap();
                World {
                    scratch,
                    runner,
                    next: 0,
                }
            }

            fn dir(&self, job: &Job) -> PathBuf {
                self.scratch.0.join("spool").join(job.as_str())
            }

            /// As the API does: every file first, `job.json` last.
            fn submit(&mut self, job: &str, files: &[(&str, &str)]) -> Job {
                self.next += 1;
                let id = Job::parse(&format!("{:032x}", self.next)).unwrap();
                for (name, body) in files {
                    write(&self.dir(&id).join(name), body);
                }
                write(&self.dir(&id).join("job.json"), job);
                id
            }

            fn out(&self, job: &Job) -> PathBuf {
                self.scratch.0.join("results").join(job.as_str())
            }

            fn result(&self, job: &Job) -> Value {
                let bytes =
                    std::fs::read(self.out(job).join("result.json")).expect("no result.json");
                serde_json::from_slice(&bytes).unwrap()
            }

            fn runs(&self) -> usize {
                let calls =
                    std::fs::read_to_string(self.scratch.0.join("calls")).unwrap_or_default();
                calls.lines().filter(|l| l.starts_with("run")).count()
            }
        }

        use std::path::PathBuf;

        fn files(source: &str) -> String {
            json!({"submission.c": source}).to_string()
        }

        #[test]
        fn the_judge_grades_end_to_end_through_the_spool() {
            let mut w = World::new();
            let io = r#"{"exercise_id": "tp-io"}"#;
            let ok = w.submit(io, &[("files.json", &files("int main(void){return 0;}"))]);
            w.runner.run(true);
            let verdict = w.result(&ok);
            assert_eq!(verdict["status"], "ok", "{verdict}");
            assert_eq!(
                (verdict["passed"].as_i64(), verdict["state"].as_str()),
                (Some(1), Some("done"))
            );
            assert_eq!(w.runs(), 1);

            // A burst of the same code, laid out differently, pays for no second compilation.
            let twins: Vec<Job> = (0..3)
                .map(|i| {
                    w.submit(
                        io,
                        &[(
                            "files.json",
                            &files(&format!("int main(void)\n{{{}return 0;}}", " ".repeat(i))),
                        )],
                    )
                })
                .collect();
            w.runner.run(true);
            for twin in &twins {
                assert_eq!(w.result(twin)["passed"], 1);
            }
            assert_eq!(w.runs(), 1, "a known verdict was compiled again");

            let wrong = w.submit(io, &[("files.json", &files("FAUX"))]);
            w.runner.run(true);
            assert_eq!(w.result(&wrong)["passed"], 0);

            let before = w.runs();
            let forbidden = w.submit(io, &[("files.json", &files("#include <unistd.h>\n"))]);
            w.runner.run(true);
            assert_eq!(w.result(&forbidden)["status"], "forbidden_include");
            assert_eq!(
                w.runs(),
                before,
                "a forbidden include still reached the sandbox"
            );

            let broken = w.submit(io, &[("files.json", &files("ERREUR"))]);
            w.runner.run(true);
            let verdict = w.result(&broken);
            assert_eq!(verdict["status"], "compile_error");
            assert!(verdict["gcc"].as_str().unwrap().contains("ERREUR"));

            let unity = w.submit(
                r#"{"exercise_id": "tp-unity"}"#,
                &[("files.json", &files("int f;"))],
            );
            w.runner.run(true);
            assert_eq!(w.result(&unity)["kind"], "unity");

            let quiz = w.submit(
                r#"{"exercise_id": "tp-quiz"}"#,
                &[("answers.json", r#"{"q1": "0xa7"}"#)],
            );
            w.runner.run(true);
            assert_eq!(w.result(&quiz)["passed"], 1);

            let closed = w.submit(
                r#"{"exercise_id": "tp-ferme"}"#,
                &[("files.json", &files("x"))],
            );
            w.runner.run(true);
            assert_eq!(w.result(&closed)["message"], "Exercice inconnu.");
            let owner = r#"{"exercise_id": "tp-ferme", "owner": "sub-prof"}"#;
            let moderated = w.submit(owner, &[("files.json", &files("x"))]);
            w.runner.run(true);
            assert_eq!(w.result(&moderated)["status"], "ok");
        }

        #[test]
        fn a_hostile_spool_reaches_nothing_outside_through_the_loop() {
            let mut w = World::new();
            let target = w.scratch.0.join("cible");
            write(&target.join("secret"), "SECRET");
            let job = w.submit(
                r#"{"exercise_id": "tp-io"}"#,
                &[("files.json", &files("int main(void){return 7;}"))],
            );
            symlink(&target, w.dir(&job).join("src")).unwrap();
            symlink(&target, w.dir(&job).join("cases")).unwrap();
            // A verdict forged in the spool is not a verdict: the judge still grades the job.
            write(
                &w.dir(&job).join("result.json"),
                r#"{"status": "ok", "passed": 99}"#,
            );
            symlink(target.join("ecrase"), w.dir(&job).join("state.json")).unwrap();
            w.runner.run(true);
            assert_eq!(w.result(&job)["passed"], 1);
            let names: Vec<_> = std::fs::read_dir(&target)
                .unwrap()
                .map(|e| e.unwrap().file_name())
                .collect();
            assert_eq!(names, ["secret"]);
            let calls = std::fs::read_to_string(w.scratch.0.join("calls")).unwrap();
            let spool = w.scratch.0.join("spool").display().to_string();
            assert!(
                !calls.contains(&format!("{spool}/")),
                "a mount came from the spool: {calls}"
            );
            let leftovers = std::fs::read_dir(w.scratch.0.join("work/jobs"))
                .unwrap()
                .count();
            assert_eq!(leftovers, 0, "staging left behind");
        }

        #[test]
        fn a_console_session_runs_and_ends_on_its_own() {
            let mut w = World::new();
            let job = w.submit(
                r#"{"kind": "console"}"#,
                &[
                    ("src/main.c", "int main(void){return 0;}"),
                    ("in", "bonjour\n"),
                    ("eof", ""),
                ],
            );
            let flags = OFlags::RDWR | OFlags::CREATE;
            let alive =
                rustix::fs::open(w.dir(&job).join("alive"), flags, Mode::from_raw_mode(0o644))
                    .unwrap();
            rustix::fs::flock(&alive, FlockOperation::NonBlockingLockExclusive).unwrap();
            w.runner.run(true);
            let verdict = w.result(&job);
            assert_eq!(
                (verdict["reason"].as_str(), verdict["code"].as_i64()),
                (Some("exited"), Some(0)),
                "{verdict}"
            );
            assert_eq!(
                std::fs::read_to_string(w.out(&job).join("out")).unwrap(),
                "lu: bonjour\n"
            );
            let state: Value =
                serde_json::from_slice(&std::fs::read(w.out(&job).join("state.json")).unwrap())
                    .unwrap();
            assert_eq!(state["state"], "exited");
            assert!(
                w.runner.results.console_lock(Duration::from_secs(600)),
                "the console lock was kept"
            );
        }
    }
}
