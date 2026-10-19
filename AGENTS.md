# AGENTS.md

## 1. Project

Sophikron is a pedagogical platform for teachers and students.

- Frontend: SvelteKit, Svelte, TypeScript, Bulma.
- Backend: Python, FastAPI.
- Database: PostgreSQL, SQLAlchemy 2.x, Alembic.
- Infrastructure: Docker Compose.
- Tests and quality: pytest, Ruff, frontend checks, GitHub Actions.
- License: GNU GPL v3.0.

Directories: `frontend/`, `backend/`, `docs/`, `infra/`, `.github/`.

Respect the existing architecture and keep frontend, API, business logic and data access appropriately separated.

## 2. Collaboration and decision-making

The user is the technical decision-maker and reviewer. Develop collaboratively, not as an autonomous agent implementing
entire features without feedback.

- For substantial features, clarify requirements, constraints and acceptance criteria before coding.
- Ask concise questions whenever ambiguity could materially affect functionality, architecture, security, data models or
  maintainability.
- Present meaningful alternatives and their trade-offs when a decision requires the user's input.
- State reasonable assumptions for minor, low-risk details instead of asking unnecessary questions.
- Before substantial implementation, present the proposed design, affected components, database changes, security
  implications and testing strategy.
- Obtain explicit approval before implementing a feature when significant decisions remain.
- Work in small, reviewable increments. Summarize changes and verification results after each meaningful increment.
- Pause before the next major phase when user feedback or a new decision is needed.
- If new information materially changes the approved scope or design, stop and discuss it first.
- The user may explicitly authorize autonomous execution for a specific task. Respect its scope and existing safety
  constraints.

## 3. Workflow

For each task:

1. Inspect relevant code, configuration and documentation.
2. Clarify requirements and obtain approval when required by Section 2.
3. Implement the smallest coherent change.
4. Add or update tests and documentation.
5. Run applicable checks.
6. Summarize changes, verification results and remaining issues.

Plan substantial tasks before coding; handle small, unambiguous tasks directly. If asked only to discuss or plan, do not
modify files.

## 4. Code quality

- Prefer simple, readable, maintainable solutions over clever abstractions.
- Follow existing patterns, `.editorconfig` and language conventions.
- Avoid unnecessary dependencies, duplication, unrelated refactoring and breaking changes without approval.
- Python: use `snake_case`, type annotations and return types. Use `PascalCase` for classes. Document every function and
  method with concise English docstrings, including `Parameters` and `Returns` where applicable.
- TypeScript/JavaScript: use `camelCase`, explicit types and avoid unjustified `any`. Use `PascalCase` for Svelte
  components and concise English JSDoc where useful.
- Keep documentation accurate and update it when behavior or setup changes.

## 5. Frontend and backend

- Use Bulma and existing SvelteKit conventions; keep components focused and styles maintainable.
- Ensure responsive layouts, accessible forms, keyboard navigation and appropriate loading, empty, success and error
  states.
- Use semantic HTML, page-specific titles and meta descriptions. Consider canonical URLs, Open Graph, sitemaps and
  `robots.txt` when relevant.
- Keep routing, business logic and data access separated on the backend.
- Validate inputs server-side, return appropriate HTTP errors and document API behavior where useful.
- Never rely on frontend validation or hidden UI as security controls.
- Never expose private lessons, accounts or student data through APIs, metadata or search indexing.

## 6. Database

- Use SQLAlchemy 2.x and Alembic consistently.
- Never modify an already-applied migration; create a new migration instead. Review generated migrations.
- Consider constraints, indexes, transactions, data integrity and rollback implications.
- Add PostgreSQL integration tests when behavior depends on PostgreSQL semantics.
- Never reset, truncate or delete persistent data or database volumes without explicit authorization.

## 7. Security

- Never commit secrets, credentials, tokens, private keys or local `.env` files. Keep `.env.example` free of real
  credentials.
- Validate untrusted input server-side and use parameterized database operations.
- Enforce backend authentication and authorization on every protected operation; follow deny-by-default principles.
- Protect sessions, password reset and account recovery. Prefer established security libraries over custom cryptography.
- Consider CSRF, XSS, brute force, privilege escalation and information disclosure where relevant.
- Validate uploads by size, type and content; store them safely and enforce access permissions.
- Treat user-provided JavaScript as untrusted. Never execute it without an appropriate isolation model.
- Test important authorization boundaries. Discuss significant security trade-offs before adopting a different security
  architecture.
- Never claim that passing tests proves comprehensive security or production readiness.

## 8. Tests and verification

Add or update tests for every behavior change, including relevant failure and authorization cases.

- Unit tests: business rules, calculations and validation.
- Integration tests: API, database and migrations.
- End-to-end tests: critical user journeys when available.
- Mock dependencies only when needed to isolate behavior; do not hide integration problems.

Run from `backend/`:

```bash
python -m pytest -q
ruff check .
```

Run from `frontend/`:

```bash
npm run check
npm run lint
npm run build
```

For infrastructure changes, validate the relevant Docker Compose configuration and builds when possible. Use the actual
project scripts and report commands, results, failures and checks not run. Never claim a check passed unless it actually
did.

## 9. Dependencies and documentation

- Keep the README accurate for setup, configuration, development and testing.
- Before adding significant dependencies, external services or paid infrastructure, explain the purpose, alternatives,
  maintenance, licensing, security and cost implications; obtain approval when the choice is consequential.
- Document lasting architectural decisions and relevant API behavior concisely.

## 10. Git and file safety

- Do not run Git commands unless explicitly authorized.
- Never commit, push, amend, rewrite history, force-push or create branches without explicit authorization.
- Inspect files before editing. Preserve unrelated user changes and keep diffs focused.
- Ask before destructive or irreversible operations.
- Preserve copyright and license notices. Never include secrets in deliverables.

## 11. Definition of done

A task is complete when its agreed acceptance criteria are met, relevant tests and checks have been run and reported,
necessary migrations and documentation are updated, and security implications have been considered. Summarize changes,
verification results and remaining limitations.

Completing one increment does not authorize starting the next major phase when review or approval is required.
