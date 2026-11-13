# RRM – team rules for AI assistants

Research Resource Manager (RRM), team Echipa 1, group 3144A (USV).
These rules are for anyone on the team working with an AI coding assistant (Claude Code or similar).

## Where things live

- GitHub org: https://github.com/RRM-3144A – `rrm-backend` (this repo, FastAPI) and `rrm-frontend` (Next.js).
- Jira: project **E1** on https://student-team-svbnqcvw.atlassian.net
  (cloudId `d3f2b019-292a-4b54-b355-3bb3f1699bf6`; transition ids: 11 = To Do, 21 = In Progress, 31 = Done).
- Confluence: space **Echipa1IP** – Lab 5 (stack, database design), Lab 6 (coding style).

## Before starting a task

1. Pick a Jira task in **To Do** that nobody is assigned to. Tasks **In Progress** or assigned to someone else are taken.
2. Assign it to yourself and move it to **In Progress**, so the other teammates' assistants skip it.
3. Pull the latest `main`.

## Workflow: one Jira task = one branch = one commit = one PR

1. Branch from the latest `main`: `E1-XX-short-name` (e.g. `E1-19-operating-schedule`).
2. One commit per task. The message starts with `E1-XX: ` and has a short body explaining the change.
3. Run the tests (`.venv/bin/pytest`) before pushing; every new endpoint or rule gets tests.
4. Open a PR into `main`. Title = commit title; the description links the Jira task, lists what changed and the test result.
5. A **human** reviews the PR and decides when to merge. The assistant does not merge on its own.
6. Merge with **"Create a merge commit"** (never squash or rebase). Branches are deleted automatically on merge.
7. After the merge, move the Jira task to **Done**. A task with backend and frontend parts stays In Progress until both PRs are merged.
8. If a PR is built on top of another unmerged PR (stacked), retarget it to `main` before the PR below it is merged. Otherwise GitHub closes it when the base branch is deleted. Keep stacks short (≤ 3 open PRs).
9. Never force-push to `main`, and never delete someone else's branch.

## Backend conventions

- Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16, pytest.
- PEP 8: `snake_case` for functions, variables and modules; `PascalCase` for classes and Pydantic/SQLAlchemy models; 4-space indent.
- Layout: `app/routers/` (endpoints), `app/services/` (business rules), `app/models.py`, `app/schemas.py`, `app/dependencies.py` (`get_current_user`, `require_admin`), `tests/`.
- Schema changes: edit `app/models.py`, then `alembic revision --autogenerate -m "..."`, and check the generated migration.
- Errors: 401 not signed in, 403 wrong role, 404 not found, 409 conflict (e.g. slot taken), 422 invalid input.
- Tests run on in-memory SQLite (`tests/conftest.py`). Use the fixtures `client`, `db`, `make_user`, `student`, `admin` and `auth_headers(user)`.
- Sign-in is Google-only and restricted to `@student.usv.ro` accounts.

## Frontend conventions (rrm-frontend)

- TypeScript, Next.js, Google TypeScript style guide.
- `camelCase` for variables and functions, `PascalCase` for React components; ESLint via `npm run lint` must pass.
