# Commit Message Instructions

Generate Git commit messages following the Conventional Commits 1.0.0 specification.

## Format

```
<type>(<optional scope>): <description>
```

Examples:

```
feat(auth): add refresh token rotation
fix(server): prevent duplicate lobby creation
docs(readme): document installation steps
refactor(protocol): simplify packet serialization
```

## Commit types

Choose the single best type that represents the primary purpose of the changes.

| Type | Use when |
|------|----------|
| feat | Adding a new feature |
| fix | Fixing a bug |
| docs | Documentation only |
| style | Formatting or whitespace only |
| refactor | Code restructuring without changing behavior |
| perf | Performance improvements |
| test | Adding or updating tests |
| build | Build system or dependencies |
| ci | CI/CD configuration |
| chore | Maintenance that does not fit another type |
| revert | Reverting a previous commit |

Do **not** use `refactor` unless the changes actually restructure existing code.

Do **not** use `feat` for documentation or tests.

## Scope

Include a scope only when it clearly identifies the affected area.

Examples:

- auth
- api
- client
- server
- protocol
- engine
- ui
- db
- docker
- ci
- docs

Avoid generic scopes like `project` or `misc`.

## Subject

The subject must:

- be written in the imperative mood
- start with a lowercase verb
- not end with a period
- be concise (preferably under 72 characters)

Good:

```
docs(readme): document self-hosting
fix(auth): prevent expired token reuse
```

Bad:

```
Updated README
Refactor code structure for improved readability
Fixed several bugs.
```

## Body

Only include a body when additional context is genuinely useful.

The body should explain **why**, not **how**.

## Breaking changes

If the change is incompatible with previous behavior, append a footer:

```
BREAKING CHANGE: <description>
```

## Priorities

Always inspect the Git diff before generating the message.

Documentation-only changes **must** use `docs`.

Test-only changes **must** use `test`.

Formatting-only changes **must** use `style`.

Dependency updates should generally use `build` or `chore`.

Never generate generic commit messages such as:

- Update code
- Refactor code structure
- Improve readability
- Various fixes
- Miscellaneous changes

The commit message must accurately summarize the actual changes present in the diff.
