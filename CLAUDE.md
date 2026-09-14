# Working notes

Operations, deployment and troubleshooting are in [docs/operations.md](docs/operations.md).
The Typst authoring guide is [docs/content/typst.md](docs/content/typst.md).

## Layout

- `app/`: FastAPI. `routers/` hold the HTTP boundary only, `services/` hold the logic (tested by direct
  calls), `state.py` holds all SQL, `schemas.py` validates request shape only, and `config.py` holds
  every setting.
- `frontend/`: Svelte 5 + TypeScript. `lib/domain/` is pure logic with no DOM, `lib/state/` has one
  small module per owner, `features/` are lazily loaded screens, and `App.svelte` alone decides what
  is mounted.
- `worker/`: `runner.py` is the host worker (root). `content_catalog.py`, `publish_content.py` and
  `typst_build.py` form the content pipeline. `build-*.sh` run inside the sandbox.
- `scripts/`: command-line tools. `tests/`: the Python checks.

## Rules the code depends on

- **One uvicorn worker.** Quotas, presence, the token cache and collaboration rooms live in memory.
- **Endpoints are `def`, not `async def`,** and share one PostgreSQL connection behind a lock.
- **No identity in request bodies.** The account always comes from the validated token; a test scans
  `schemas.py` for this.
- **Student-facing messages are French** and come from `services/`, not from Pydantic errors.
- **`find_exercise()` is the only gate** to an exercise, in the API and in the worker.
- **Anything `test_ctester.py` imports must be standard-library only.** It runs with the host Python on
  the Dell. The same goes for `csp.py`, `services/source.py`, `worker/` and `bot/bridge.py`.
- **The CSP exists twice:** `app/csp.py` and the `<meta>` in `frontend/index.html`. A test compares
  them. No inline scripts.
- **The anonymous bundle stays small.** Anything that needs an account is loaded lazily, and
  `bundle.test.ts` checks the built output.
- **Tables and grants live together** in `app/schema.sql`. Any table with an `account` column must be
  cleared by `state.forget()`, and tests enforce both rules.
- **Persisted ids never change:** achievement, card and frame ids, event ids (`solved:<exercise>`), and
  status values.
- **The page never declares a result.** XP, solved states and verdicts are derived by the server.
- **The worker trusts nothing from the web tier.** It re-resolves the exercise and recomputes the
  moderator role itself.

## Style

- English identifiers and comments. French only in text shown to students.
- Comments only where a constraint is not visible in the code: one or two plain sentences.

## Checks

```sh
npm run check && npm run build && npm test
python3 tests/test_ctester.py
python3 tests/test_api.py
python3 scripts/validate_content.py ../unittests/content
python3 scripts/verify_content.py   ../unittests/content
python3 tests/test_sandbox.py       ../unittests/content
```

`test_postgres.py` needs a real PostgreSQL; see the operations guide.
