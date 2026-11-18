# Platform adapters

Platform-specific filesystem, process, and desktop integration belongs behind the adapter in `src/core/platform`. Service and launcher code should call the adapter instead of branching on operating system details or invoking shell commands directly.

The current adapters cover Windows and Linux. The contract includes path normalization, storage validation, opening a folder, launching an executable, and platform-specific runtime support. Windows command scripts open in a console so interactive prompts remain available. Linux folder opening uses `xdg-open`; Windows game scripts can use Wine or Proton through the launch runtime integration.

The API exposes platform information and basic storage actions:

- `GET /platform/info`
- `GET /platform/validate-storage?path=...`
- `GET /platform/open-folder?path=...`
- `GET /platform/storage-locations` for the first-run storage picker

Storage validation checks that the path exists, is a directory, and is writable. Linux Wine helper tools can be supplied under `<library>/ng_provider/tools/`; the provider-hosted `winetricks` copy and its cache are preferred when present, with `PATH` as fallback.

When adding a platform operation, keep path separators, process flags, elevation, and fallback behavior inside the adapter. Cover supported operating systems with focused tests and report unavailable platform tools through stable localized errors.
