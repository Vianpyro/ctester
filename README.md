# CTester

**ctester** is a self-hosted C code judge built for **[TCH009](https://www.etsmtl.ca/etudes/cours/TCH009)**, a C programming course at ÉTS.

Students write their code in the browser, submit it, and get immediate feedback from a set of hidden tests — without exposing the tests themselves.

## What it does

* Compile and test C programs directly from the browser
* Support **unit tests**, **stdin/stdout tests**, and **quizzes**
* Keep test cases and expected outputs private
* Run untrusted native code inside isolated, disposable sandboxes
* Offer a **Console**: an interactive C scratchpad where a signed-in student
  runs an arbitrary program and answers it while it runs
* Provide optional student accounts, progress tracking, and an assistance forum
* Host **team assignments**: students pick a team from a numbered list, then
  share a live-collaborative workspace with revision history and a single ZIP
  hand-in per team
* Publish course content independently from the application

The service is designed primarily as a **practice and feedback tool**, not as a grading or anti-cheating system.

## Architecture

```text
Browser
   │
   ▼
FastAPI ──► submission spool ──► worker
                                   │
                                   ▼
                              gVisor sandbox
                                   │
                                   ▼
                            C compiler + tests
```

The web-facing API never compiles or executes student code and never has access to the private test suite. A separate host worker handles execution and creates a fresh sandbox for each submission.

The application is intentionally small: a FastAPI backend, a static Svelte frontend, and a small set of Python scripts handling content publication and test execution.

The frontend is a **static bundle**: it is built once and served by GitHub Pages, with no server-side rendering and no Node process in production. It reaches the API over HTTP and WebSocket only, so the backend stays independent of the frontend's technology. Screens a student can only open with an account — the chat, progress, the leaderboard, the collection, the Console, a team workspace — are separate chunks fetched on the click that needs them, which is why a visitor with no account downloads none of them.

Team assignments add one WebSocket endpoint, which relays [Yjs](https://github.com/yjs/yjs) updates between the members of one team without interpreting them. The server holds the authorization and the durable plain-text copy; the CRDT holds the merge.

Students pick their own team from a numbered list, the way they already do in Moodle — and the numbers match, which is the point. Teams are numbered per course group, and the lists freeze when the assignment opens: the very date that opens the shared document is the one that closes the lists, so there is never a moment when a student can both join a team and read its work. The instructor never sees an account identifier, which is exactly why he cannot write the roster himself.

## Tech stack

* **Python 3.13**
* **FastAPI / Uvicorn**
* **Svelte 5 + Vite + TypeScript**, built to a static bundle
* **PostgreSQL** for optional persistence
* **Docker + gVisor** for code execution
* **Ansible** for deployment and infrastructure

Python dependencies are pinned, and so are the frontend's three runtime dependencies — [marked](https://github.com/markedjs/marked) and [DOMPurify](https://github.com/cure53/DOMPurify) for rendering forum messages, [Yjs](https://github.com/yjs/yjs) for the shared editor. Each is bundled into the chunk that needs it and nowhere else.

## Project structure

```text
app/                  FastAPI application
frontend/
  index.html          the document, and where its CSP lives
  public/             copied verbatim: the pre-paint theme script, CNAME, icon
  src/
    components/       the workbench: editor, verdict, bar, action bar
    features/         the screens fetched on demand, one directory each
    lib/
      api/            the typed client and the wire types
      auth/           the OIDC session
      collab/         the shared document and the caret geometry
      domain/         pure logic: catalog, verdict, highlighter, main.c export
      state/          domain state, one small module per owner
  tests/              Vitest suites, run against the modules and the built bundle
content_catalog.py    Course content validation and lookup
publish_content.py    Content publication and releases
runner.py             Host-side execution worker
import_teams.py       Instructor-side roster tool (corrections)
build-unity.sh        Unit-test execution
build-io.sh           stdin/stdout execution
test_*.py             Application and integration tests
```

Course tests and solutions live in a separate private repository. Deployment and infrastructure are maintained separately.

## Development

```sh
pip install -r requirements-dev.txt   # once
npm ci                                # once

npm run dev                           # the page, on Vite's dev server
npm run build                         # the static bundle, into frontend/dist

# The page and the API on one origin, which is what the local mode is for:
CTESTER_KEY=dev CTESTER_PUBLISHED=/tmp/published CTESTER_PAGE=frontend/dist   python3 app/main.py
```

The project includes tests for the API, the content catalogue, the frontend and PostgreSQL integration:

```sh
npm run check     # types, across TypeScript and Svelte
npm test          # the frontend suites
python3 test_ctester.py
python3 test_api.py
```

---

Built for teaching C at **École de technologie supérieure (ÉTS)**.
