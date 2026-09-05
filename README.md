# CTester

**ctester** is a self-hosted C code judge built for **[TCH009](https://www.etsmtl.ca/etudes/cours/TCH009)**, a C programming course at ÉTS.

Students write their code in the browser, submit it, and get immediate feedback from a set of hidden tests — without exposing the tests themselves.

## What it does

* Compile and test C programs directly from the browser
* Support **unit tests**, **stdin/stdout tests**, and **quizzes**
* Keep test cases and expected outputs private
* Run untrusted native code inside isolated, disposable sandboxes
* Provide optional student accounts, progress tracking, and an assistance forum
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

The application is intentionally small: a FastAPI backend, a dependency-free frontend, and a small set of Python scripts handling content publication and test execution.

## Tech stack

* **Python 3.13**
* **FastAPI / Uvicorn**
* **Vanilla JavaScript / HTML / CSS**
* **PostgreSQL** for optional persistence
* **Docker + gVisor** for code execution
* **Ansible** for deployment and infrastructure

Python dependencies are pinned, and the frontend has no build step.

## Project structure

```text
app/                  FastAPI application
web/                  Frontend
content_catalogue.py  Course content validation and lookup
publish_content.py    Content publication and releases
runner.py             Host-side execution worker
build-unity.sh        Unit-test execution
build-io.sh            stdin/stdout execution
test_*.py             Application and integration tests
```

Course tests and solutions live in a separate private repository. Deployment and infrastructure are maintained separately.

## Development

Run the application locally with Python and configure the required environment variables for the desired features.

The project also includes tests for the API, content catalogue, frontend, and PostgreSQL integration.

---

Built for teaching C at **École de technologie supérieure (ÉTS)**.
