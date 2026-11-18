# Release Checklist

## Build
- [ ] Patch version bumped in `VERSION` (for code changes, use `tools/scripts/build_and_publish_update.py`)
- [ ] Windows package created
- [ ] Linux package created
- [ ] Signed update ZIP and `update-manifest.json` published to `LLNGUPDATEFOLDER`
- [ ] SHA256 checksums generated

## Validation
- [ ] Startup check passes (`required_bundle_tools_invalid` not triggered)
- [ ] Core API health/version reachable
- [ ] Catalog API reachable
- [ ] Sync status/speed API reachable
- [ ] Frontend UI loads with EN and DE

## Compliance
- [ ] Tool manifest updated
- [ ] Tool licenses present in `vendor/licenses`
- [ ] Bilingual docs updated (`docs/en` + `docs/de`)
- [ ] Bilingual release notes prepared

## Publish
- [ ] Artifacts uploaded
- [ ] Checksums uploaded
- [ ] Release notes published
