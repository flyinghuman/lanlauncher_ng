<!-- imported-from: codex:project:instructions -->
# AGENTS.md - LANLauncherNG

## Mission
Modernize LANLauncher as LANLauncherNG for Windows and Linux while preserving legacy compatibility, keeping dependencies light, bundling required runtime tools, and shipping complete English and German support.

## Start Every Session
1. Read this file.
2. Read `context.md` for current architecture and decisions.
3. Inspect `git status --short`; preserve unrelated user changes.
4. Find the relevant ticket in `TODO.md` before implementation. Add a ticket when the requested work has none.

Use the repository skills in `.agents/skills` when applicable:
- `$llng-deliver-feature` for normal feature and bug-fix delivery.
- `$llng-change-sync-platform` for sync-provider, process-lifecycle, launch, filesystem, or OS-adapter work.
- `$llng-build-release` for bundled tools, packaging, installers, update artifacts, and rollback work.

## Hard Gates
- Prefer the Python standard library and existing helpers. Keep dependencies minimal.
- Require an ADR before adding a heavyweight framework, an end-user service/process dependency, or a dependency with unclear maintenance.
- Add tests for every behavior change and bug fix. Run the full suite before handoff.
- Add every user-facing string to both EN and DE locale files in the same change; never hardcode component strings.
- Update matching pages under both `docs/en` and `docs/de` for feature, configuration, or operational changes.
- Return stable backend message keys for user-facing errors.
- Add concise comments only for non-obvious algorithms, platform edge cases, retry/failure behavior, and security-sensitive logic.
- Update the relevant `TODO.md` ticket and prepend a timestamped summary to `changelog.md` for every repository change.
- Update `context.md` when behavior, architecture, contracts, or durable project decisions change materially.

## Repository Boundaries
- Backend and adapters: `src/core`
- Frontend: `src/frontend`
- Locale sources: `src/frontend/app/locales/{en,de}/*.json`
- Tests: `tests/core`
- Runtime tool declaration: `tools/manifest.json`
- Bundled binaries: `vendor/bin/<platform>/`
- Bundled licenses: `vendor/licenses/`
- Packaging and release automation: `packaging/`, `tools/scripts/`
- Bilingual docs: `docs/en`, `docs/de`

Keep platform-specific process, filesystem, and OS integration behind adapter/provider boundaries. Never hardcode Windows-only paths, separators, or shell assumptions. Validate Windows and Linux behavior for launch, install, sync, packaging, and update changes.

## Bundled Tool Contract
- Declare each runtime tool in `tools/manifest.json`.
- Ship its platform binary under `vendor/bin/<platform>/`.
- Record version, SHA-256 checksum, and license metadata.
- Fail fast with a localized message when a required tool is absent or corrupt.
- Do not require system-wide installs for normal application operation.

For every new dependency, explain why the standard library is insufficient, document the impact in `docs/en/architecture.md` and `docs/de/architektur.md`, and add shipped license/version information when applicable.

## Validation
Run commands from the repository root with the project-local environment.

Linux full suite:
```bash
./.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -t .
```

Windows full suite:
```powershell
.\tools\scripts\run-tests.ps1
```

Required repository checks:
```powershell
.\tools\scripts\verify-i18n.ps1
.\tools\scripts\verify-bundle.ps1
.\.venv-dev-win\Scripts\python.exe -m mkdocs build --strict
```

On Linux, run PowerShell checks through `pwsh` when available. If a required platform/tool is unavailable, run all feasible checks and report the exact gap.

## Completion Check
Before handoff, inspect the final diff and confirm:
1. Requested behavior and focused tests are present.
2. EN/DE locale and documentation changes are paired where required.
3. Ticket, changelog, and any material context update are complete.
4. No unnecessary dependency or unrelated rewrite was introduced.
5. Full tests and applicable validation scripts pass.
