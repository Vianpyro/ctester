//! Verdict cache: a verdict is reused when the judge and the normalised sources are unchanged.

use std::collections::BTreeMap;
use std::fs::File;
use std::path::{Path, PathBuf};
use std::sync::LazyLock;
use std::time::SystemTime;

use regex::Regex;
use serde_json::Value;
use sha2::{Digest, Sha256};

use crate::config::Config;
use crate::gate::{self, Exercise, Mode};
use crate::grade;
use crate::results;

/// Change it whenever the key's recipe changes, so no entry computed the old way is served.
const KEY_PREFIX: &[u8] = b"ctester-judge/1";

/// Wall-clock limits depend on load, not on the code: caching them would freeze bad luck.
const NEVER_CACHED: [&str; 3] = ["timeout", "compile_timeout", "error"];

static LEXER: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(concat!(
        r"(?s)(?P<block>/\*.*?\*/)",
        r"|(?P<line>//(?:[^\n\\]|\\.)*)",
        r#"|(?P<string>"(?:[^"\\\n]|\\.)*")"#,
        r"|(?P<char>'(?:[^'\\\n]|\\.)*')",
        r"|(?P<word>[A-Za-z_][A-Za-z0-9_]*|\.?[0-9](?:[A-Za-z0-9_.]|[eEpP][-+])*)",
        r"|(?P<space>[\s\x1c-\x1f]+)",
        r"|(?P<other>.)",
    ))
    .expect("static lexer")
});

/// The judge binary itself holds the grading rules, so a new build invalidates every verdict.
static EXE_DIGEST: LazyLock<Vec<u8>> = LazyLock::new(|| {
    std::env::current_exe().and_then(std::fs::read).map_or_else(
        |_| b"absent:".to_vec(),
        |bytes| Sha256::digest(bytes).to_vec(),
    )
});

/// Comments and layout do not change a verdict, so they do not change the key either.
pub fn normalize_c(source: &str) -> String {
    let word = |c: Option<char>| c.is_some_and(|c| c.is_ascii_alphanumeric() || c == '_');
    let mut out = String::new();
    let (mut space, mut directive, mut line_start) = (false, false, true);
    for caps in LEXER.captures_iter(source) {
        let text = caps.get(0).map_or("", |m| m.as_str());
        let trivia = ["block", "line", "space"]
            .iter()
            .any(|g| caps.name(g).is_some());
        if trivia {
            if caps.name("space").is_some() && text.contains('\n') && directive {
                out.push('\n');
                (space, directive) = (false, false);
            } else {
                space = true;
            }
            if text.contains('\n') {
                line_start = true;
            }
            continue;
        }
        if space && word(out.chars().last()) && word(text.chars().next()) {
            out.push(' ');
        }
        if text == "#" && line_start {
            directive = true;
        }
        out.push_str(text);
        (space, line_start) = (false, false);
    }
    out
}

/// Length-prefixed, so "ab" + "c" and "a" + "bc" hash differently.
fn hash_bytes(hasher: &mut Sha256, blob: &[u8]) {
    hasher.update(format!("{}:", blob.len()).as_bytes());
    hasher.update(blob);
}

fn hash_file(hasher: &mut Sha256, path: &Path) {
    match std::fs::read(path) {
        Ok(bytes) => hash_bytes(hasher, &bytes),
        Err(_) => hasher.update(b"absent:"),
    }
}

fn sorted_entries(dir: &Path) -> Vec<std::fs::DirEntry> {
    let mut entries: Vec<_> =
        std::fs::read_dir(dir).map_or_else(|_| Vec::new(), |e| e.flatten().collect());
    entries.sort_by_key(std::fs::DirEntry::file_name);
    entries
}

/// Files of a directory first, then its subdirectories, each in name order; links to
/// directories are not descended.
fn hash_tree(hasher: &mut Sha256, root: &Path, rel: &str) {
    let dir = root.join(rel);
    let (mut files, mut dirs) = (Vec::new(), Vec::new());
    for entry in sorted_entries(&dir) {
        let name = entry.file_name().to_string_lossy().into_owned();
        let child = if rel.is_empty() {
            name
        } else {
            format!("{rel}/{name}")
        };
        match entry.file_type() {
            Ok(t) if t.is_dir() => dirs.push(child),
            Ok(t) if t.is_symlink() && entry.path().is_dir() => {}
            _ => files.push(child),
        }
    }
    for file in files {
        hash_bytes(hasher, file.as_bytes());
        hash_file(hasher, &root.join(&file));
    }
    for sub in dirs {
        hash_tree(hasher, root, &sub);
    }
}

/// Everything that decides a verdict except the submission.
pub fn fingerprint(config: &Config, exercise_id: &str, exercise: &Exercise) -> Sha256 {
    let mut hasher = Sha256::new();
    hash_bytes(&mut hasher, KEY_PREFIX);
    hash_bytes(
        &mut hasher,
        format!("{exercise_id}|{}", exercise.mode.as_str()).as_bytes(),
    );
    hash_tree(&mut hasher, &exercise.path, "");
    if exercise.mode == Mode::Unity {
        hash_tree(&mut hasher, &config.unity_dir(), "");
    }
    hash_file(
        &mut hasher,
        &exercise.path.join("..").join("public").join("files.json"),
    );
    let build = if exercise.mode == Mode::Unity {
        &config.build_unity
    } else {
        &config.build_io
    };
    hash_file(&mut hasher, build);
    hash_bytes(&mut hasher, &EXE_DIGEST);
    hash_bytes(&mut hasher, config.image.as_bytes());
    let env: BTreeMap<_, _> = config.sandbox_env.iter().cloned().collect();
    hash_bytes(
        &mut hasher,
        serde_json::to_string(&env).unwrap_or_default().as_bytes(),
    );
    hasher
}

pub fn hex(hasher: &Sha256) -> String {
    hasher
        .clone()
        .finalize()
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}

pub fn signature(fingerprint: &Sha256, conf: &Value, tp_dir: &Path, sent: &Value) -> String {
    let mut hasher = fingerprint.clone();
    for name in gate::declared_files(conf, tp_dir) {
        let source = sent.get(&name).map(grade::as_text).unwrap_or_default();
        hash_bytes(&mut hasher, name.as_bytes());
        hash_bytes(&mut hasher, normalize_c(&source).as_bytes());
    }
    hex(&hasher)
}

pub fn cachable(conf: &Value, verdict: &Value) -> bool {
    let wanted = conf.get("cache").is_none_or(grade::truthy);
    let status = verdict.get("status").and_then(Value::as_str).unwrap_or("");
    wanted && verdict.is_object() && !NEVER_CACHED.contains(&status)
}

pub struct Cache {
    dir: PathBuf,
    max: i64,
    prune_every: u64,
    writes: u64,
}

impl Cache {
    pub fn new(config: &Config) -> Cache {
        Cache {
            dir: config.work.join("cache"),
            max: config.cache_max,
            prune_every: config.cache_prune_every,
            writes: 0,
        }
    }

    fn path(&self, sig: &str) -> PathBuf {
        self.dir.join(format!("{sig}.json"))
    }

    /// Touching the entry on a hit is what makes pruning drop the least recently served.
    pub fn read(&self, sig: &str) -> Option<Value> {
        if self.max <= 0 {
            return None;
        }
        let path = self.path(sig);
        let verdict: Value = serde_json::from_slice(&std::fs::read(&path).ok()?).ok()?;
        if !verdict.is_object() {
            return None;
        }
        let _ = File::open(&path).and_then(|f| f.set_modified(SystemTime::now()));
        Some(verdict)
    }

    pub fn write(&mut self, sig: &str, verdict: &Value) {
        if self.max <= 0 {
            return;
        }
        let written = std::fs::create_dir_all(&self.dir)
            .and_then(|()| File::open(&self.dir))
            .and_then(|dir| results::write_json_at(&dir, &format!("{sig}.json"), verdict));
        if written.is_err() {
            return;
        }
        self.writes += 1;
        if self.writes >= self.prune_every {
            self.writes = 0;
            self.prune();
        }
    }

    fn prune(&self) {
        let mut entries: Vec<(SystemTime, PathBuf)> = sorted_entries(&self.dir)
            .into_iter()
            .filter(|e| e.file_type().is_ok_and(|t| t.is_file()))
            .filter_map(|e| Some((e.metadata().ok()?.modified().ok()?, e.path())))
            .collect();
        let surplus = entries.len() as i64 - self.max + self.prune_every as i64;
        if surplus <= 0 {
            return;
        }
        entries.sort();
        for (_, path) in entries.iter().take(surplus as usize) {
            let _ = std::fs::remove_file(path);
        }
        eprintln!(
            "ctester: cache pruned {surplus} entries ({} left)",
            entries.len() as i64 - surplus
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::spool::tests::Scratch;
    use serde_json::json;

    #[test]
    fn strings_and_characters_are_never_taken_for_comments() {
        let n = normalize_c;
        assert_eq!(n("int x;"), "int x;");
        assert_eq!(n("intx;"), "intx;");
        assert_eq!(n("int/*c*/x;"), n("int x;"));
        assert_ne!(n("int x = 1;"), n("int x = 2;"));
        assert!(n(r#"puts("http://a");"#).contains("http://a"));
        assert!(n(r#"puts("/*"); int x;"#).ends_with("int x;"));
        assert!(n(r#"char c = '"'; int x;"#).ends_with("int x;"));
        assert!(n(r#"char *s = "a\"b//c"; int z;"#).ends_with("int z;"));
        assert_eq!(n("int x; // n'oublie pas\nint y;"), n("int x;int y;"));
        assert_eq!(n("/* jamais fermé"), "/*jamais fermé");
        assert_eq!(n("// suite \\\n encore\nint y;"), "int y;");
    }

    #[test]
    fn layout_is_ignored_but_code_is_not() {
        let loose = "// mon programme\n#include <stdio.h>\n\n\nint main(void) {\n\n    /* la boucle */\n    for (int i = 0; i < 3; i++)\n        printf(\"%d\\n\", i);\n\n    return 0;\n}\n";
        let tight =
            "#include <stdio.h>\nint main(void){for(int i=0;i<3;i++)printf(\"%d\\n\",i);return 0;}";
        assert_eq!(normalize_c(loose), normalize_c(tight));
        assert_ne!(normalize_c("int x;"), normalize_c("intx;"));
        assert_ne!(
            normalize_c("#define A 1\n#define B 2"),
            normalize_c("#define A 1 #define B 2")
        );
        assert_ne!(
            normalize_c(r#"puts("http://a"); int x;"#),
            normalize_c(r#"puts("http://b"); int x;"#)
        );
    }

    #[test]
    fn verdicts_that_depend_on_load_are_never_cached() {
        let ok = json!({"status": "ok", "passed": 1});
        assert!(cachable(&json!({}), &ok));
        assert!(cachable(&json!({}), &json!({"status": "compile_error"})));
        for status in NEVER_CACHED {
            assert!(!cachable(&json!({}), &json!({"status": status})));
        }
        assert!(!cachable(&json!({"cache": false}), &ok));
        assert!(!cachable(&json!({"cache": null}), &ok));
    }

    fn cache(dir: &Path, max: i64, prune_every: u64) -> Cache {
        Cache {
            dir: dir.to_path_buf(),
            max,
            prune_every,
            writes: 0,
        }
    }

    #[test]
    fn the_cache_prunes_the_least_recently_served() {
        let scratch = Scratch::new("cache");
        let ok = json!({"status": "ok"});
        let mut c = cache(&scratch.0, 100, 500);
        c.write(&"a".repeat(64), &ok);
        assert_eq!(c.read(&"a".repeat(64)), Some(ok.clone()));
        assert_eq!(c.read(&"b".repeat(64)), None);
        assert_eq!(cache(&scratch.0, 0, 500).read(&"a".repeat(64)), None);

        for (rank, name) in ["vieux", "moyen", "recent"].iter().enumerate() {
            let sig = name.repeat(16);
            c.write(&sig, &ok);
            let when = SystemTime::UNIX_EPOCH + std::time::Duration::from_secs(1000 + rank as u64);
            File::open(c.path(&sig))
                .unwrap()
                .set_modified(when)
                .unwrap();
        }
        assert!(c.read(&"vieux".repeat(16)).is_some());
        std::fs::remove_file(c.path(&"a".repeat(64))).unwrap();
        let mut pruning = cache(&scratch.0, 3, 0);
        pruning.write(&"neuf".repeat(16), &ok);
        assert!(
            pruning.read(&"moyen".repeat(16)).is_none(),
            "the least served survived"
        );
        assert!(
            pruning.read(&"vieux".repeat(16)).is_some(),
            "a served entry was dropped"
        );
        std::fs::write(c.path(&"f".repeat(64)), "{ pas du json").unwrap();
        assert!(c.read(&"f".repeat(64)).is_none());
    }

    #[test]
    fn the_signature_follows_the_judge_as_much_as_the_code() {
        let scratch = Scratch::new("signature");
        let content = scratch.0.join("content");
        let tp = content.join("exercises/tp2-ex1/assessment");
        std::fs::create_dir_all(&tp).unwrap();
        std::fs::write(
            tp.join("io.json"),
            r#"{"cases": [{"stdin": "", "expect": [1]}]}"#,
        )
        .unwrap();
        let config = Config::from_lookup(|k| {
            (k == "CTESTER_CONTENT").then(|| content.display().to_string())
        })
        .unwrap();
        let exercise = Exercise {
            path: tp.clone(),
            mode: Mode::Io,
        };
        let conf = json!({});
        let code = json!({"submission.c": "int main(void){return 0;}"});
        let sig = |id: &str, sent: &Value| {
            signature(&fingerprint(&config, id, &exercise), &conf, &tp, sent)
        };

        let base = sig("tp2-ex1", &code);
        assert_eq!(sig("tp2-ex1", &code), base);
        assert_ne!(sig("tp2-ex2", &code), base);
        assert_eq!(
            sig(
                "tp2-ex1",
                &json!({"submission.c": "int main(void)\n{\n\n    return 0;\n}\n"})
            ),
            base
        );
        assert_ne!(
            sig(
                "tp2-ex1",
                &json!({"submission.c": "int main(void){return 1;}"})
            ),
            base
        );
        std::fs::write(tp.join("io.json"), r#"{"cases": []}"#).unwrap();
        let edited = sig("tp2-ex1", &code);
        assert_ne!(edited, base);
        std::fs::write(tp.join("test_ajoute.c"), "void test_x(void){}").unwrap();
        assert_ne!(sig("tp2-ex1", &code), edited);
    }
}
