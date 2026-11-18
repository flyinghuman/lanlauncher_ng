# Development Workflow (English)

## Feature checklist
1. Implement behavior.
2. Add EN + DE translations.
3. Add inline comments for non-obvious logic.
4. Update EN + DE docs.
5. Update TODO tickets.
6. Verify dependency impact.

## Branch quality gates
- No user-facing strings without translation keys.
- No undocumented config changes.
- No untracked bundled tool changes.

## Git hooks
Install the development linter and enable the repository hooks once per clone:

```bash
./.venv/bin/python -m pip install -r requirements-dev.txt
git config core.hooksPath .githooks
```

Both `pre-commit` and `pre-push` run Ruff and the full unittest suite through the project Python environment at `.venv` (Linux) or `.venv-dev-win` (Windows). On Windows, use `\.venv-dev-win\Scripts\python.exe -m pip install -r requirements-dev.txt` to install Ruff. A failed check stops the commit or push.

## Run tests
Always run tests from repository root (`LANLauncherNG`) using the project virtual environment.

### Windows
```powershell
.\.venv-dev-win\Scripts\python.exe -m unittest discover -s tests
```

### Linux
```bash
./.venv/bin/python -m unittest discover -s tests
```

### Optional: run one test module
```powershell
.\.venv-dev-win\Scripts\python.exe -m unittest tests.core.test_api
```

### Success criteria
- Command exits with code `0`
- Summary ends with `OK`
