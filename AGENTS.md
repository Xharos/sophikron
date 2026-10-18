# Agent Instructions

## Project structure

- `frontend/`: SvelteKit, TypeScript and JavaScript.
- `backend/`: Python and FastAPI.
- `docs/`: project documentation.
- `infra/`: infrastructure configuration.
- `.github/`: GitHub workflows and contribution templates.

Respect the existing architecture and keep frontend and backend responsibilities separate.

## Code quality

- Write simple, readable, maintainable code. Prefer clarity over cleverness.
- Follow the language conventions and established project patterns.
- Use consistent formatting and respect the existing linting and formatting configuration.
- Follow conventional naming rules: `snake_case` for Python modules, variables and functions; `PascalCase` for classes and Svelte components; `camelCase` for TypeScript variables and functions; use clear, consistent names for files.
- Avoid unnecessary dependencies, duplication and unrelated changes.

## Documentation

- Document every function and method in English, using the conventions of its language.
- In Python, use docstrings. In TypeScript and JavaScript, use appropriate documentation comments, such as JSDoc, when documenting functions.
- Keep documentation concise, accurate and useful. Update it when behavior or setup changes.

## Tests and verification

- Add or update unit tests for every behavior change, including relevant edge cases.
- Run the relevant tests, linting, formatting and build checks available in the project.
- Never claim that a check passed unless it was actually run successfully.
- Report any checks that could not be run.

## Security

- Never expose or commit secrets, credentials, private keys or local `.env` files.
- Validate user input and uploaded files.
- Enforce authorization on the backend.
- Treat user-provided JavaScript as untrusted code and never execute it without appropriate isolation.

## Git and changes

- Do not use Git commands unless explicitly authorized by the user.
- Never commit, push, rewrite history, force-push or amend commits without explicit authorization.
- Never discard or overwrite unrelated user changes.
- Ask before destructive or irreversible operations.
- Preserve applicable copyright and license notices. The project is licensed under GNU GPL v3.0.
