# Contributing to TheCouncil

Thank you for your interest in contributing! This document provides guidelines for reporting issues, submitting code changes, and participating in the project.

## Code of Conduct

Be respectful, inclusive, and professional in all interactions. We welcome contributors of all backgrounds and experience levels.

## Reporting Issues

### Security Vulnerabilities

For security issues, see [SECURITY.md](SECURITY.md). Do not open public issues for security vulnerabilities.

### Bug Reports

When reporting bugs, include:

- **Description**: What behavior did you observe vs. what did you expect?
- **Steps to reproduce**: Exact commands or actions that trigger the issue
- **Environment**: Python version, OS, relevant dependency versions
- **Logs**: Error messages, stack traces, or relevant logs

Example:

```markdown
**Description**
Running `python -m pytest tests/` fails with ImportError

**Steps to reproduce**
1. Clone the repo
2. Create a venv and run `pip install -r requirements.txt`
3. Run `pytest tests/ -q`

**Expected**: Tests pass
**Actual**: ImportError: no module named 'council.core'

**Environment**
- Python 3.12.1
- Ubuntu 24.04
- commit abc1234
```

### Feature Requests

Describe the feature, why you need it, and if possible, see if there is: already a similar feature request or pull request for your feature!

## Development Setup

### Backend

```bash
# Clone and setup
git clone https://github.com/kavin0x/TheCouncil.git
cd TheCouncil
python -m venv .venv
source .venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -r requirements.txt

# Setup environment
cp .env.example .env
# Edit .env and add your API keys

# Run tests
pytest tests/ -q

# Run API
uvicorn council.api.app:app --reload
```

### Frontend

```bash
cd web
npm ci
npm run dev          # dev server (localhost:3000)
npm run test         # run tests
npm run lint         # check style
npm run typecheck    # check types
```

## Code Style

### Python

- **Formatter**: [ruff format](https://docs.astral.sh/ruff/)
- **Linter**: [ruff check](https://docs.astral.sh/ruff/)
- **Type hints**: Use type hints for function arguments and returns
- **Docstrings**: Include docstrings for public functions and classes

```bash
# Format and check
ruff check . --fix
ruff format .
```

### TypeScript/React

- **Formatter**: [Prettier](https://prettier.io/) via `npm run format`
- **Linter**: [ESLint](https://eslint.org/) via `npm run lint`
- **Types**: Strict TypeScript mode; no `any` unless unavoidable

```bash
cd web
npm run lint --fix
npm run format
npm run typecheck
```

## Submitting Changes

### Branch Naming

Use descriptive branch names:

- `feature/awesome-feature` — New feature
- `fix/bug-description` — Bug fix
- `docs/update-readme` — Documentation
- `refactor/component-name` — Refactoring

### Commit Messages

Write clear, descriptive commit messages:

Follow the [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) specification.

```text
Short summary (50 chars or less)

Longer explanation of the change if needed. Wrap at 72 characters.
Include the problem being solved and how your change addresses it.

- Use bullet points for multiple changes
- Reference issues like "Fixes #123"
```

### Conventional Commits

Use the [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) format for all commit messages.

Examples:

```text
feat(api): add run status endpoint
fix(web): handle null response in dashboard
docs(contributing): add commit message guidelines
```

### Pull Request Process

1. **Fork** the repository (if you don't have write access)
2. **Create a branch** from `main` with a descriptive name
3. **Make your changes** with clear, atomic commits
4. **Test locally**:
   - Backend: `pytest tests/ -q` and `ruff check .`
   - Frontend: `npm run test && npm run typecheck`
5. **Push** to your branch
6. **Open a pull request** with:
   - Clear title and description
   - Link to related issues (`Fixes #123`)
   - Summary of changes
   - Any breaking changes or migration steps

### PR Review Guidelines

- Small, focused PRs are easier to review
- Explain the "why" in comments, not just the "what"
- Respond promptly to reviewer feedback
- Mark conversations as resolved once addressed

## Testing

### Backend Tests

```bash
# Run all tests
pytest tests/ -q

# Run specific test file
pytest tests/test_api.py -q

# Run specific test
pytest tests/test_api.py::test_create_run -q

# Run with coverage
pytest tests/ --cov=council --cov-report=html
```

### Frontend Tests

```bash
cd web

# Unit tests
npm run test

# E2E tests
npm run test:e2e

# Watch mode
npm run test:watch
```

### Adding Tests

- For new features, add corresponding tests
- For bug fixes, add a test that reproduces the bug first
- Aim for meaningful test coverage (70%+ for critical paths)
- Use descriptive test names: `test_create_run_validates_panel_size`

## Documentation

- Update [README.md](README.md) for user-facing changes
- Update [CLAUDE.md](CLAUDE.md) for architecture and environment setup
- Add docstrings to functions and classes
- Document breaking changes in PR description

## Release Process

Maintainers will:

1. Review and merge PRs
2. Update version numbers (semantic versioning)
3. Update CHANGELOG (if one exists)
4. Tag releases on GitHub
5. Deploy to package registries if applicable

## Questions?

- Open an issue for questions or discussion
- Check existing issues and discussions first
- Be patient and respectful

Thank you for contributing!
