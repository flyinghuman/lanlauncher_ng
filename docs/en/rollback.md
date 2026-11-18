# Rollback Guide (English)

## When to rollback
- Critical startup failure after release
- Data migration issue causing unreadable state
- Broken sync behavior across multiple clients

## Rollback steps
1. Stop running launcher process.
2. Back up current `data/` and `config/` directories.
3. Try launcher API rollback first: `GET /app/update/rollback`.
4. If API rollback is unavailable, replace app package with last known good release.
5. Restore previous `config/`.
6. If schema downgrade is not supported, restore previous `data/` backup.
7. Start launcher and verify `/health` and `/version`.

## Interrupted update recovery
- During shutdown update, launcher writes `data/update/last-run.json` and `data/update/session-<id>.json`.
- On next shutdown attempt, interrupted `directory_swap` sessions are detected as `phase=recovery_required`.
- Use `/app/shutdown/apply?session_id=<id>&action=resume` to continue updater.
- Use `/app/shutdown/apply?session_id=<id>&action=abort` to stop recovery and restore best-effort backup.

## Verification
- Catalog list works.
- Sync status/speed endpoints respond.
- Frontend loads in EN and DE.
