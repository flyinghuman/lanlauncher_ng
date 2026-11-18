# Dependency and Bundled Tool Policy

## Goals
- Keep runtime and build dependencies minimal.
- Guarantee fully runnable packages without external tool installation.
- Make third-party usage auditable.

## Dependency Classes
### Class A - Allowed by default
- Standard library
- Small, maintained libraries with low transitive footprint
- Libraries with permissive licenses compatible with project goals

### Class B - Requires short design note
- Libraries with moderate transitive dependencies
- Libraries used in core runtime paths

### Class C - Requires ADR
- Heavy frameworks or runtimes
- Dependencies that materially increase package size or complexity
- Dependencies that require separate user machine installation

## Required checks for any new dependency
1. Why stdlib or existing dependency is insufficient.
2. License compatibility.
3. Security posture and maintenance activity.
4. Size/transitive impact.
5. Exit strategy (how to replace if abandoned).

## Bundled Runtime Tool Rules
- Every shipped tool must be listed in `tools/manifest.json`.
- Every entry must include:
  - `name`
  - `platform`
  - `path`
  - `version`
  - `sha256`
  - `license_file`
  - `required` flag
- Binaries are stored under `vendor/bin/<platform>/`.
- License texts are stored under `vendor/licenses/`.

## Integrity Rules
- Startup must verify checksums of required tools.
- Missing or mismatched required tools must fail with localized EN/DE error messages.
- Optional tools may degrade functionality but must report clear warnings.
