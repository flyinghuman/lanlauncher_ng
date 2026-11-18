# i18n Workflow (English)

## Mandatory languages
- English (`en`)
- German (`de`)

## Workflow for every user-facing feature
1. Add/update translation keys in `src/frontend/app/locales/en/*.json`.
2. Mirror the same keys in `src/frontend/app/locales/de/*.json`.
3. Use stable key names in code, never inline UI strings.
4. Run translation parity check script.
5. Update docs in `docs/en` and `docs/de`.

## Backend message strategy
- Backend returns stable message keys (example: `error.tool_missing`).
- Frontend maps keys to localized strings.

## Validation
Run:

```powershell
./tools/scripts/verify-i18n.ps1
```

The script fails if EN/DE key sets diverge.
