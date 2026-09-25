# Working notes

Operations, deployment and troubleshooting are in [docs/operations.md](docs/operations.md).
The Typst authoring guide is [docs/content/typst.md](docs/content/typst.md).
Languages and how to add one are in [docs/translations.md](docs/translations.md).

## Layout

- `app/`: FastAPI. `routers/` hold the HTTP boundary only, `services/` hold the logic (tested by direct
  calls), `state.py` holds all SQL, `schemas.py` validates request shape only, and `config.py` holds
  every setting.
- `frontend/`: Svelte 5 + TypeScript. `lib/domain/` is pure logic with no DOM, `lib/state/` has one
  small module per owner, `features/` are lazily loaded screens, and `App.svelte` alone decides what
  is mounted.
- `judge/`: the host judge in Rust (root). `grade.rs` holds the grading rules, `spool.rs` every access
  to the API-owned spool, `gate.rs` the judge's gate to an exercise.
- `worker/`: `content_catalog.py`, `publish_content.py` and `typst_build.py` form the content
  pipeline. `judge.py` calls the Rust grading rules for the content tools. `build-*.sh` run inside
  the sandbox, and `local_build.py` runs the same scripts on the host for the content tools.
- `admin/`: the teacher's dashboard, a separate read-only FastAPI app on the LAN. It imports
  `app/state.py` and `app/services/spool.py`; `journal.py` is stdlib-only so the checks can
  import it.
- `deploy/`: the Compose stack, systemd units and update scripts, all configured by `/opt/ctester/.env`.
- `scripts/`: command-line tools. `demo_content.py` + `demo_content_data.py` write the engine's
  example content base, which is what the format is documented against and what CI publishes.
- `tests/`: the Python checks. `tests/fixture/unity/` is a stand-in for Unity, so the checks
  build a unity exercise without a content repository.
- `docs/content/format.md`: the content format, for anyone bringing their own exercises.

## Rules the code depends on

- **CTester ships no exercises.** No file under `app/`, `worker/`, `judge/` or `frontend/src/`
  names an exercise, a collection or a skill. Course vocabulary lives in the content repository:
  skills and their wording in `catalog.json`, the collection's cards in `cards.json`. The engine
  fixes the mechanism (the four difficulties, the three modes, the quiz types, the card drawings)
  and nothing else. The checks run without any content: `test_sandbox.py` writes its own fixture,
  and `demo_content.py` is the example base.

- **One uvicorn worker.** Quotas, presence, the token cache and collaboration rooms live in memory.
- **Endpoints are `def`** (except WebSockets and the two event streams, the admin's and the
  update notice's `/events`) and share one
  PostgreSQL connection behind a lock.
- **No identity in request bodies.** The account always comes from the validated token; a test scans
  `schemas.py` for this.
- **Every word a student reads is in `frontend/src/locales/`**, `en.json` being the source and
  the fallback. The API refuses with a key (`headers.error(400, "db_down")`, or
  `(key, params)`) from `services/`, never with a sentence or a Pydantic error; the judge answers
  with codes (`reason`, `hint`, `code`); `policy.py` holds ids and numbers only. Tests bind API
  keys and policy ids to `en.json`, and every literal `t("...")` key to it.
- **Exercise ids are unique across every content root.** `CTESTER_CONTENT` may list several
  repositories; `discover()` merges them into one flat namespace and a duplicate id fails the
  publication. Only one root may hold `shared/unity`.
- **`find_exercise()` is the only gate** to an exercise in the API; the judge re-checks with `gate.rs`.
  `tests/vectors/release_access.json` binds the two implementations of `access`.
- **The spool holds only the API's inputs; the judge writes only to `results/`.** The judge reads the
  spool without following links and mounts nothing from it (mounts are staged in `CTESTER_WORK`).
  `results/` is root's and mounted read-only into web: the API reads verdicts, never writes one.
- **Anything `test_ctester.py` imports must be standard-library only.** It runs with the host Python on
  the Dell. The same goes for `csp.py`, `log.py`, `services/source.py`, `worker/` and `bot/bridge.py`.
- **The CSP exists twice:** `app/csp.py` and the `<meta>` in `frontend/index.html`. A test compares
  them. No inline scripts. The page names no host: `vite.config.ts` fills `%API_ORIGIN%`,
  `%API_WS%`, `%AUTH_ORIGIN%`, `%TITLE%`, `%TAGLINE%` and `%LANG%` at build time from
  `CTESTER_API_ORIGIN`, `CTESTER_AUTH_ORIGIN`, `CTESTER_TITLE` and `CTESTER_LANG`, the variables
  the server reads, so the two copies stay comparable. **Only the `pages` job builds the deployed
  page**: those settings live in the `github-pages` environment, which no other job enters.
- **The anonymous bundle stays small.** Anything that needs an account is loaded lazily, and
  `bundle.test.ts` checks the built output.
- **Tables and grants live together** in `app/schema.sql`. Any table with an `account` column must be
  cleared by `state.forget()`, and tests enforce both rules.
- **Persisted ids never change:** achievement, card and frame ids, event ids (`solved:<exercise>`), and
  status values. The same goes for locale keys, the API's error keys and the judge's codes: a
  translation platform tracks them. Card ids come from the content's `cards.json`, so renaming one there orphans what
  students already earned; a card naming an unknown exercise fails the publication instead of
  becoming quietly unobtainable.
- **The page never declares a result.** XP, solved states and verdicts are derived by the server.
- **The worker trusts nothing from the web tier.** It re-resolves the exercise and recomputes the
  moderator role itself.
- **The admin app demands a moderator's OIDC token** on every `/api` route, on top of the
  proxy's access list. It never writes anything but its copy of the judge's run journal.
- **Student names and code are hidden by the server, not the page.** `/api/runs` omits `account`
  without `?reveal=1`. Submitted code is read back from the spool or `exercise_state`, never
  stored again, and rendered with `textContent` under a CSP: it is untrusted text in a page that
  holds a moderator token.
- **The judge journals every run** to `results/runs-<date>.jsonl`, from `write_result()` so no
  exit path is missed. A test binds its fields to `admin/journal.py` and `state.RUN_COLUMNS`.
- **Logs follow the OpenTelemetry data model and carry no identity.** Every service writes JSON
  lines through `app/log.py` (the judge through `log.rs`, bound by `tests/vectors/log_record.json`).
  Docker logs and journald outlive "Delete my data", so no account, name, token, address, header,
  body or code is logged: attributes outside `log.ATTRIBUTES` are dropped, a stack trace keeps
  frames without the message, and requests are logged by route template. Event names are stable
  and each one is documented in `docs/operations.md`; a test checks both.
- **A Console session is not a graded run.** It is excluded from failures, the success rate and
  every timing average; `exercise_id = ':console'` keeps it visible on its own.

## Style

- English identifiers and comments. Text shown to students only in the locale files.
- Comments only where a constraint is not visible in the code: one or two plain sentences.

## Checks

```sh
(cd judge && cargo fmt --check && cargo clippy --all-targets -- -D warnings && cargo test)
(cd judge && cargo build --release)   # verify_content.py and test_sandbox.py call this binary
npm run check && npm run build && npm test
python3 tests/test_ctester.py
python3 tests/test_api.py
python3 tests/test_sandbox.py                        # its own fixture, no content needed
python3 scripts/demo_content.py --out /tmp/demo      # the engine's example content base
python3 scripts/validate_content.py /tmp/demo/content
python3 scripts/verify_content.py   /tmp/demo/content
```

`test_postgres.py` needs a real PostgreSQL; see the operations guide.
