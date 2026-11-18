(() => {
  const state = {
    locale: localStorage.getItem("llng.locale") || "de",
    dictionary: {},
    query: "",
    sort: "title",
    order: "asc",
    installed: "all",
    genreId: "all",
    genres: [],
    viewMode: localStorage.getItem("llng.view_mode") || "grid",
    gridTileSize: localStorage.getItem("llng.grid_tile_size") || "medium",
    page: 1,
    pageSize: 0,
    total: 0,
    catalogItems: [],
    listSyncStatus: {},
    listSyncPollBusy: false,
    topTrafficMode: localStorage.getItem("llng.top_traffic_mode") || "bar",
    topTrafficHistory: [],
    topTrafficSample: {
      download_bps: 0,
      upload_bps: 0,
      disk_read_bps: 0,
      disk_write_bps: 0,
      disk_total_bps: 0,
    },
    rescanStartBusy: false,
    rescanMonitorRunning: false,
    selectedGameId: "",
    selectedGame: null,
    selectedGameSync: {
      active: false,
      progress_percent: 0,
      install_state: "missing",
      sync_state: "missing",
      installed: false,
      needs_update: false,
      down_eta: 0,
      down_speed: 0,
      upload_speed: 0,
      down_status: 0,
      install_console_lines: [],
    },
    selectedGameStatus: {
      server_start_exists: false,
    },
    syncStatus: {
      provider: "none",
      running: false,
      state: "disabled",
      pid: null,
      last_error: "",
    },
    lanGameInventory: {
      root_path: "",
      folders: [],
    },
    selectedGameLaunchSettings: {
      linux_runtime_override: "",
      linux_leave_terminal_open: false,
      effective_linux_runtime: "wine",
    },
    winetricksCatalog: {
      packages: [],
      default_selected: [],
    },
    selectedGameWinetricksPackages: [],
    selectedGameProviderType: "",
    extraSyncItems: [],
    extraSyncEditingOriginalId: "",
    localGameEditingOriginalId: "",
    serverFolderEditing: null,
    syncRunning: false,
    logsPaused: false,
    logsLoading: false,
    logsSourceFilter: localStorage.getItem("llng.logs_source_filter") || "all",
    logsLimit: localStorage.getItem("llng.logs_limit") || "200",
    logsEntries: [],
    catalogRetryTimer: 0,
    catalogLoadAttempts: 0,
    catalogLoaded: false,
    catalogSyncRefreshTimer: 0,
    logsCollapsed: localStorage.getItem("llng.logs_collapsed") === "1",
    settingsCollapsed: localStorage.getItem("llng.settings_collapsed") !== "0",
    settingsDirty: false,
    activeTab: localStorage.getItem("llng.active_tab") || "home",
    activeStatusProvider:
      localStorage.getItem("llng.active_status_provider") || "resilio",
    activeProviderTab:
      localStorage.getItem("llng.active_provider_tab") || "ouisync",
    ouisyncInventoryLoading: false,
    ouisyncInventoryRefreshPending: false,
    ouisyncInventoryLastRefresh: 0,
    ouisyncSelectedRepositoryHash: "",
    ouisyncDirectoryPath: "/",
    ouisyncCopyBusy: false,
    ouisyncNudgeBusy: false,
    shutdownUpdatePollTimer: 0,
    shutdownUpdateAutoCloseTimer: 0,
    shutdownUpdateSessionId: "",
    shutdownUpdateLines: [],
    shutdownUpdateRecoveryRequired: false,
    shutdownSignalSent: false,
    updateAvailable: false,
    backendReady: false,
    storageLocations: [],
    settings: {
      nickname: "",
      theme: "dark",
      log_level: "WARNING",
      auto_start_sync: true,
      sync_only_mode: false,
      library_path_initialized: false,
      windows_game_drive_letter: "D",
      linux_install_path: "/media/library",
      linux_windows_runtime: "wine",
      linux_proton_path: "",
      linux_proton_ge_path: "",
      lan_mode: "client",
      platform: "unknown",
      effective_library_path: "/media/library",
      local_docs_file_url: "",
      local_docs_file_path: "",
      provider_interfaces: [],
    },
    launcherSite: {
      source_url: "http://launcher.lan/launcher.ini",
      reachable: false,
      last_success_at: 0,
      last_error: "",
      lan_title: "",
      lan_url: "",
      stats_url: "http://launcher.lan/stats.php",
      links: [],
      disable_games: [],
      managed_by_lan_server: false,
    },
    lanServerSettings: { settings: null, assets: [] },
  };

  const TOP_TRAFFIC_HISTORY_LIMIT = 2048;
  const GRID_TILE_SIZE_STORAGE_KEY = "llng.grid_tile_size";
  const GRID_TILE_SIZE_PRESETS = {
    very_small: {
      minWidth: 150,
      preferredWidth: 170,
      maxWidth: 190,
    },
    small: {
      minWidth: 170,
      preferredWidth: 200,
      maxWidth: 220,
    },
    medium: {
      minWidth: 200,
      preferredWidth: 235,
      maxWidth: 260,
    },
    big: {
      minWidth: 230,
      preferredWidth: 270,
      maxWidth: 300,
    },
    very_big: {
      minWidth: 260,
      preferredWidth: 310,
      maxWidth: 340,
    },
  };
  let topTrafficResizeObserver = null;
  let catalogResizeObserver = null;

  const el = {
    appTitle: document.getElementById("app-title"),
    appTitleLegacy: document.getElementById("app-tilte"),
    appSubtitle: document.getElementById("app-subtitle"),
    topProviderBadges: document.getElementById("top-provider-badges"),
    topActions: document.querySelector(".top-actions"),
    topTrafficToggle: document.getElementById("top-traffic-toggle"),
    topTrafficChart: document.getElementById("top-traffic-chart"),
    topTrafficInfo: document.getElementById("top-traffic-info"),
    topTrafficInfoHint: document.getElementById("top-traffic-info-hint"),
    topTrafficInfoDownloadLabel: document.getElementById(
      "top-traffic-info-download-label",
    ),
    topTrafficInfoDownloadValue: document.getElementById(
      "top-traffic-info-download-value",
    ),
    topTrafficInfoUploadLabel: document.getElementById(
      "top-traffic-info-upload-label",
    ),
    topTrafficInfoUploadValue: document.getElementById(
      "top-traffic-info-upload-value",
    ),
    topTrafficInfoDiskReadLabel: document.getElementById(
      "top-traffic-info-disk-read-label",
    ),
    topTrafficInfoDiskReadValue: document.getElementById(
      "top-traffic-info-disk-read-value",
    ),
    topTrafficInfoDiskWriteLabel: document.getElementById(
      "top-traffic-info-disk-write-label",
    ),
    topTrafficInfoDiskWriteValue: document.getElementById(
      "top-traffic-info-disk-write-value",
    ),
    topHelpDocs: document.getElementById("top-help-docs"),
    topLinksSelect: document.getElementById("top-links-select"),
    topUpdateHint: document.getElementById("top-update-hint"),
    localeSelect: document.getElementById("locale-select"),
    stopAppBtn: document.getElementById("stop-app-btn"),
    tabHomeBtn: document.getElementById("tab-home-btn"),
    tabStatusBtn: document.getElementById("tab-status-btn"),
    tabProvidersBtn: document.getElementById("tab-providers-btn"),
    tabSettingsBtn: document.getElementById("tab-settings-btn"),
    tabLogsBtn: document.getElementById("tab-logs-btn"),
    homePanel: document.getElementById("home-panel"),
    statusPanel: document.getElementById("status-panel"),
    statusTitle: document.getElementById("status-title"),
    providersPanel: document.getElementById("providers-panel"),
    settingsPanel: document.getElementById("settings-panel"),
    logsPanel: document.getElementById("logs-panel"),
    providerTabs: {
      ouisync: document.getElementById("provider-tab-ouisync-btn"),
      resilio: document.getElementById("provider-tab-resilio-btn"),
    },
    ouisyncNativePanel: document.getElementById("ouisync-native-panel"),
    ouisyncInventoryStatus: document.getElementById("ouisync-inventory-status"),
    ouisyncHealthSummary: document.getElementById("ouisync-health-summary"),
    ouisyncCatalogList: document.getElementById("ouisync-catalog-list"),
    ouisyncRepositoryList: document.getElementById("ouisync-repository-list"),
    ouisyncDirectoryPath: document.getElementById("ouisync-directory-path"),
    ouisyncDirectoryList: document.getElementById("ouisync-directory-list"),
    ouisyncDirectoryUp: document.getElementById("ouisync-directory-up"),
    ouisyncSettingsRepository: document.getElementById("ouisync-settings-repository"),
    ouisyncSettingsHint: document.getElementById("ouisync-settings-hint"),
    ouisyncSettingDht: document.getElementById("ouisync-setting-dht"),
    ouisyncSettingPex: document.getElementById("ouisync-setting-pex"),
    ouisyncSettingCache: document.getElementById("ouisync-setting-cache"),
    ouisyncMountStatus: document.getElementById("ouisync-mount-status"),
    ouisyncMountStart: document.getElementById("ouisync-mount-start"),
    ouisyncMountStop: document.getElementById("ouisync-mount-stop"),
    ouisyncMountForceStop: document.getElementById("ouisync-mount-force-stop"),
    ouisyncCopyTarget: document.getElementById("ouisync-copy-target"),
    ouisyncCopyStatus: document.getElementById("ouisync-copy-status"),
    ouisyncNudgeSync: document.getElementById("ouisync-nudge-sync"),
    ouisyncNudgeStatus: document.getElementById("ouisync-nudge-status"),
    ouisyncPeersCard: document.getElementById("ouisync-peers-card"),
    ouisyncPeersHint: document.getElementById("ouisync-peers-hint"),
    ouisyncPeerList: document.getElementById("ouisync-peer-list"),
    ouisyncPeerListeners: document.getElementById("ouisync-peer-listeners"),
    ouisyncPeerAddForm: document.getElementById("ouisync-peer-add-form"),
    ouisyncPeerAddInput: document.getElementById("ouisync-peer-add-input"),
    ouisyncPeerAddButton: document.getElementById("ouisync-peer-add-button"),
    ouisyncPeerStatus: document.getElementById("ouisync-peer-status"),
    ouisyncDebugHealth: document.getElementById("ouisync-debug-health"),
    ouisyncDebugSeed: document.getElementById("ouisync-debug-seed"),
    ouisyncResetSeed: document.getElementById("ouisync-reset-seed"),
    ouisyncDebugModal: document.getElementById("ouisync-debug-modal"),
    ouisyncDebugModalClose: document.getElementById("ouisync-debug-modal-close"),
    ouisyncDebugLog: document.getElementById("ouisync-debug-log"),
    providerFrameStatus: document.getElementById("provider-frame-status"),
    providerIframe: document.getElementById("provider-iframe"),
    providerOpenExternalBtn: document.getElementById(
      "provider-open-external-btn",
    ),
    statusDescription: document.getElementById("status-description"),
    statusOverview: document.getElementById("status-overview"),
    statusProvidersTitle: document.getElementById("status-providers-title"),
    statusProvidersDescription: document.getElementById(
      "status-providers-description",
    ),
    statusProviderList: document.getElementById("status-provider-list"),
    statusLanGamesSection: document.getElementById("status-lan-games-section"),
    statusLanGamesTitle: document.getElementById("status-lan-games-title"),
    statusLanGamesDescription: document.getElementById(
      "status-lan-games-description",
    ),
    statusLanGamesRefreshBtn: document.getElementById(
      "status-lan-games-refresh-btn",
    ),
    statusLanGamesRoot: document.getElementById("status-lan-games-root"),
    statusLanGamesStatus: document.getElementById("status-lan-games-status"),
    statusLanGamesList: document.getElementById(
      "status-lan-games-folder-list",
    ),
    labelLanguage: document.getElementById("label-language"),
    searchInput: document.getElementById("search-input"),
    sortSelect: document.getElementById("sort-select"),
    installedSelect: document.getElementById("installed-select"),
    catalogContextMenu: document.getElementById("catalog-context-menu"),
    genreSelect: document.getElementById("genre-select"),
    labelGridSize: document.getElementById("label-grid-size"),
    gridSizeSelect: document.getElementById("grid-size-select"),
    rescanBtn: document.getElementById("rescan-btn"),
    installCheckBtn: document.getElementById("install-check-btn"),
    gameList: document.getElementById("game-list"),
    viewListBtn: document.getElementById("view-list-btn"),
    viewGridBtn: document.getElementById("view-grid-btn"),
    detailEmpty: document.getElementById("detail-empty"),
    detailCard: document.getElementById("detail-card"),
    detailVideo: document.getElementById("detail-video"),
    detailImage: document.getElementById("detail-image"),
    detailGameTitle: document.getElementById("detail-game-title"),
    detailInstallingBadge: document.getElementById("detail-installing-badge"),
    detailDownloadingBadge: document.getElementById("detail-downloading-badge"),
    detailSyncingBadge: document.getElementById("detail-syncing-badge"),
    detailFullySyncedBadge: document.getElementById(
      "detail-fully-synced-badge",
    ),
    detailUpdateBadge: document.getElementById("detail-update-badge"),
    detailUpToDateBadge: document.getElementById("detail-up-to-date-badge"),
    detailProviderBadge: document.getElementById("detail-provider-badge"),
    detailGenre: document.getElementById("detail-genre"),
    detailMeta: document.getElementById("detail-meta"),
    detailDownloadProgress: document.getElementById("detail-download-progress"),
    detailDownloadProgressLabel: document.getElementById(
      "detail-download-progress-label",
    ),
    detailDownloadProgressValue: document.getElementById(
      "detail-download-progress-value",
    ),
    detailDownloadProgressTrack: document.getElementById(
      "detail-download-progress-track",
    ),
    detailDownloadProgressFill: document.getElementById(
      "detail-download-progress-fill",
    ),
    detailLinks: document.getElementById("detail-links"),
    detailLinksTitle: document.getElementById("detail-links-title"),
    detailLinksList: document.getElementById("detail-links-list"),
    detailReadme: document.getElementById("detail-readme"),
    syncStart: document.getElementById("sync-start"),
    syncStop: document.getElementById("sync-stop"),
    syncRemoveData: document.getElementById("sync-remove-data"),
    openLibrary: document.getElementById("open-library"),
    openGameFolder: document.getElementById("open-game-folder"),
    installAnywayBtn: document.getElementById("install-anyway-btn"),
    labelDetailLinuxRuntime: document.getElementById(
      "label-detail-linux-runtime",
    ),
    detailLinuxRuntimeSelect: document.getElementById(
      "detail-linux-runtime-select",
    ),
    labelDetailLinuxLeaveTerminalOpen: document.getElementById(
      "label-detail-linux-leave-terminal-open",
    ),
    labelDetailLinuxLeaveTerminalOpenInline: document.getElementById(
      "label-detail-linux-leave-terminal-open-inline",
    ),
    detailLinuxLeaveTerminalOpenCheckbox: document.getElementById(
      "detail-linux-leave-terminal-open-checkbox",
    ),
    startGameBtn: document.getElementById("start-game-btn"),
    startServerBtn: document.getElementById("start-server-btn"),
    deleteGameBtn: document.getElementById("delete-game-btn"),
    installProtonCommonDepsBtn: document.getElementById(
      "install-proton-common-deps-btn",
    ),
    editLocalGameBtn: document.getElementById("edit-local-game-btn"),
    detailWinetricksPanel: document.getElementById("detail-winetricks-panel"),
    detailWinetricksTitle: document.getElementById("detail-winetricks-title"),
    detailWinetricksNote: document.getElementById("detail-winetricks-note"),
    detailWinetricksPackages: document.getElementById(
      "detail-winetricks-packages",
    ),
    detailWinetricksSelectCommon: document.getElementById(
      "detail-winetricks-select-common",
    ),
    detailWinetricksSelectAll: document.getElementById(
      "detail-winetricks-select-all",
    ),
    detailWinetricksSelectNone: document.getElementById(
      "detail-winetricks-select-none",
    ),
    detailWinetricksSaveBtn: document.getElementById(
      "detail-winetricks-save-btn",
    ),
    detailLocalNote: document.getElementById("detail-local-note"),
    detailWinetricksInstallBtn: document.getElementById(
      "detail-winetricks-install-btn",
    ),
    detailWinetricksRemoveBtn: document.getElementById(
      "detail-winetricks-remove-btn",
    ),
    startGameConsole: document.getElementById("start-game-console"),
    syncState: document.getElementById("sync-state"),
    syncSpeed: document.getElementById("sync-speed"),
    settingsTitle: document.getElementById("settings-title"),
    settingsSectionGeneralTitle: document.getElementById(
      "settings-section-general-title",
    ),
    settingsSectionLibraryTitle: document.getElementById(
      "settings-section-library-title",
    ),
    settingsSectionNetworkTitle: document.getElementById(
      "settings-section-network-title",
    ),
    settingsSection: document.querySelector(
      'section.settings[aria-labelledby="settings-title"]',
    ),
    settingsGeneralSection: document.getElementById("settings-section-general"),
    settingsBody: document.getElementById("settings-body"),
    settingsToggleBtn: document.getElementById("settings-toggle-btn"),
    labelAppVersion: document.getElementById("label-app-version"),
    appVersionValue: document.getElementById("app-version-value"),
    labelNickname: document.getElementById("label-nickname"),
    nicknameInput: document.getElementById("nickname-input"),
    labelTheme: document.getElementById("label-theme"),
    themeSelect: document.getElementById("theme-select"),
    labelLogLevel: document.getElementById("label-log-level"),
    logLevelSelect: document.getElementById("log-level-select"),
    autoSyncCheckbox: document.getElementById("auto-sync-checkbox"),
    labelAutoSync: document.getElementById("label-auto-sync"),
    syncOnlyModeCheckbox: document.getElementById("sync-only-mode-checkbox"),
    labelSyncOnlyMode: document.getElementById("label-sync-only-mode"),
    lanModeSelect: document.getElementById(
      "lan-mode-select",
    ),
    labelLanMode: document.getElementById(
      "label-lan-mode",
    ),
    lanModeHint: document.getElementById(
      "lan-mode-hint",
    ),
    lanDiscoverySection: document.getElementById("lan-discovery-section"),
    lanDiscoveryAddressLabel: document.getElementById("lan-discovery-address-label"),
    lanDiscoveryAddress: document.getElementById("lan-discovery-address"),
    lanDiscoveryScan: document.getElementById("lan-discovery-scan"),
    lanDiscoveryStatus: document.getElementById("lan-discovery-status"),
    lanServerLabel: document.getElementById("lan-server-label"),
    lanServerSelect: document.getElementById("lan-server-select"),
    lanPairCodeLabel: document.getElementById("lan-pair-code-label"),
    lanPairCode: document.getElementById("lan-pair-code"),
    lanPairConnect: document.getElementById("lan-pair-connect"),
    lanPairStatus: document.getElementById("lan-pair-status"),
    lanPairServerSection: document.getElementById("lan-pair-server-section"),
    lanPairBegin: document.getElementById("lan-pair-begin"),
    lanPairRenew: document.getElementById("lan-pair-renew"),
    lanPairServerStatus: document.getElementById("lan-pair-server-status"),
    lanServerSettingsSection: document.getElementById("lan-server-settings-section"),
    lanServerSettingsTitle: document.getElementById("lan-server-settings-title"),
    lanServerSettingsHint: document.getElementById("lan-server-settings-hint"),
    lanServerTitleLabel: document.getElementById("lan-server-title-label"),
    lanServerTitle: document.getElementById("lan-server-title"),
    lanServerUrlLabel: document.getElementById("lan-server-url-label"),
    lanServerUrl: document.getElementById("lan-server-url"),
    lanServerStatsUrlLabel: document.getElementById("lan-server-stats-url-label"),
    lanServerStatsUrl: document.getElementById("lan-server-stats-url"),
    lanServerDiscordUrlLabel: document.getElementById("lan-server-discord-url-label"),
    lanServerDiscordUrl: document.getElementById("lan-server-discord-url"),
    lanServerTs3Label: document.getElementById("lan-server-ts3-label"),
    lanServerTs3Server: document.getElementById("lan-server-ts3-server"),
    lanServerLinksTitle: document.getElementById("lan-server-links-title"),
    lanServerLinksList: document.getElementById("lan-server-links-list"),
    lanServerAssetsTitle: document.getElementById("lan-server-assets-title"),
    lanServerAssetsHint: document.getElementById("lan-server-assets-hint"),
    lanServerAssetsList: document.getElementById("lan-server-assets-list"),
    lanServerSettingsSave: document.getElementById("lan-server-settings-save"),
    lanServerSettingsStatus: document.getElementById("lan-server-settings-status"),
    labelStorage: document.getElementById("label-storage"),
    storageInput: document.getElementById("storage-input"),
    ouisyncStorageInput: document.getElementById("ouisync-storage-input"),
    labelOuisyncStorage: document.getElementById("label-ouisync-storage"),
    storageSelect: document.getElementById("storage-select"),
    labelLinuxRuntime: document.getElementById("label-linux-runtime"),
    linuxRuntimeSelect: document.getElementById("linux-runtime-select"),
    labelLinuxProtonPath: document.getElementById("label-linux-proton-path"),
    linuxProtonPathInput: document.getElementById("linux-proton-path-input"),
    labelLinuxProtonGePath: document.getElementById(
      "label-linux-proton-ge-path",
    ),
    linuxProtonGePathInput: document.getElementById(
      "linux-proton-ge-path-input",
    ),
    saveSettingsBtn: document.getElementById("save-settings-btn"),
    updateRollbackBtn: document.getElementById("update-rollback-btn"),
    installPrereqBtn: document.getElementById("install-prereq-btn"),
    installWineCommonDepsBtn: document.getElementById(
      "install-wine-common-deps-btn",
    ),
    syncModeLanBtn: document.getElementById("sync-mode-lan-btn"),
    syncModeInternetBtn: document.getElementById("sync-mode-internet-btn"),
    setNetworkPrivateBtn: document.getElementById("set-network-private-btn"),
    serviceSyncStart: document.getElementById("service-sync-start"),
    serviceSyncStop: document.getElementById("service-sync-stop"),
    serviceSyncWebui: document.getElementById("service-sync-webui"),
    extraSyncTitle: document.getElementById("extra-sync-title"),
    extraSyncAddBtn: document.getElementById("extra-sync-add-btn"),
    extraSyncImportBtn: document.getElementById("extra-sync-import-btn"),
    extraSyncImportFile: document.getElementById("extra-sync-import-file"),
    extraSyncList: document.getElementById("extra-sync-list"),
    extraSyncModal: document.getElementById("extra-sync-modal"),
    extraSyncModalTitle: document.getElementById("extra-sync-modal-title"),
    extraSyncLabelGameId: document.getElementById("extra-sync-label-game-id"),
    extraSyncGameId: document.getElementById("extra-sync-game-id"),
    extraSyncLabelKey: document.getElementById("extra-sync-label-key"),
    extraSyncKey: document.getElementById("extra-sync-key"),
    extraSyncLabelTitleEn: document.getElementById("extra-sync-label-title-en"),
    extraSyncTitleEn: document.getElementById("extra-sync-title-en"),
    extraSyncLabelTitleDe: document.getElementById("extra-sync-label-title-de"),
    extraSyncTitleDe: document.getElementById("extra-sync-title-de"),
    extraSyncLabelReleaseYear: document.getElementById(
      "extra-sync-label-release-year",
    ),
    extraSyncReleaseYear: document.getElementById("extra-sync-release-year"),
    extraSyncLabelPublisher: document.getElementById(
      "extra-sync-label-publisher",
    ),
    extraSyncPublisher: document.getElementById("extra-sync-publisher"),
    extraSyncLabelSize: document.getElementById("extra-sync-label-size"),
    extraSyncSize: document.getElementById("extra-sync-size"),
    extraSyncLabelPersons: document.getElementById("extra-sync-label-persons"),
    extraSyncPersons: document.getElementById("extra-sync-persons"),
    extraSyncLabelVersion: document.getElementById("extra-sync-label-version"),
    extraSyncVersion: document.getElementById("extra-sync-version"),
    extraSyncLabelReadmeEn: document.getElementById(
      "extra-sync-label-readme-en",
    ),
    extraSyncReadmeEn: document.getElementById("extra-sync-readme-en"),
    extraSyncLabelReadmeDe: document.getElementById(
      "extra-sync-label-readme-de",
    ),
    extraSyncReadmeDe: document.getElementById("extra-sync-readme-de"),
    extraSyncMasterRequired: document.getElementById(
      "extra-sync-master-required",
    ),
    extraSyncLabelMasterRequired: document.getElementById(
      "extra-sync-label-master-required",
    ),
    extraSyncVisible: document.getElementById("extra-sync-visible"),
    extraSyncLabelVisible: document.getElementById("extra-sync-label-visible"),
    extraSyncEnabled: document.getElementById("extra-sync-enabled"),
    extraSyncLabelEnabled: document.getElementById("extra-sync-label-enabled"),
    extraSyncIsProvider: document.getElementById("extra-sync-is-provider"),
    extraSyncLabelIsProvider: document.getElementById(
      "extra-sync-label-is-provider",
    ),
    extraSyncProviderType: document.getElementById("extra-sync-provider-type"),
    extraSyncLabelProviderType: document.getElementById(
      "extra-sync-label-provider-type",
    ),
    extraSyncHasGameDb: document.getElementById("extra-sync-has-game-db"),
    extraSyncLabelHasGameDb: document.getElementById(
      "extra-sync-label-has-game-db",
    ),
    extraSyncPackedImagePath: document.getElementById(
      "extra-sync-packed-image-path",
    ),
    extraSyncLabelPackedImagePath: document.getElementById(
      "extra-sync-label-packed-image-path",
    ),
    extraSyncPackedImagePassword: document.getElementById(
      "extra-sync-packed-image-password",
    ),
    extraSyncLabelPackedImagePassword: document.getElementById(
      "extra-sync-label-packed-image-password",
    ),
    localGameModal: document.getElementById("local-game-modal"),
    localGameModalTitle: document.getElementById("local-game-modal-title"),
    localGameModalNote: document.getElementById("local-game-modal-note"),
    localGameLabelId: document.getElementById("local-game-label-id"),
    localGameId: document.getElementById("local-game-id"),
    localGameLabelTitleEn: document.getElementById("local-game-label-title-en"),
    localGameTitleEn: document.getElementById("local-game-title-en"),
    localGameLabelTitleDe: document.getElementById("local-game-label-title-de"),
    localGameTitleDe: document.getElementById("local-game-title-de"),
    localGameLabelGenre: document.getElementById("local-game-label-genre"),
    localGameGenre: document.getElementById("local-game-genre"),
    localGameLabelReleaseYear: document.getElementById(
      "local-game-label-release-year",
    ),
    localGameReleaseYear: document.getElementById("local-game-release-year"),
    localGameLabelPublisher: document.getElementById("local-game-label-publisher"),
    localGamePublisher: document.getElementById("local-game-publisher"),
    localGameLabelSize: document.getElementById("local-game-label-size"),
    localGameSize: document.getElementById("local-game-size"),
    localGameLabelMaxPlayers: document.getElementById(
      "local-game-label-max-players",
    ),
    localGameMaxPlayers: document.getElementById("local-game-max-players"),
    localGameLabelVersion: document.getElementById("local-game-label-version"),
    localGameVersion: document.getElementById("local-game-version"),
    localGameLabelStartFile: document.getElementById("local-game-label-start-file"),
    localGameStartFile: document.getElementById("local-game-start-file"),
    localGameLabelStartArgs: document.getElementById("local-game-label-start-args"),
    localGameStartArgs: document.getElementById("local-game-start-args"),
    localGameLabelReadmeEn: document.getElementById("local-game-label-readme-en"),
    localGameReadmeEn: document.getElementById("local-game-readme-en"),
    localGameLabelReadmeDe: document.getElementById("local-game-label-readme-de"),
    localGameReadmeDe: document.getElementById("local-game-readme-de"),
    serverCoverDownload: document.getElementById("server-cover-download"),
    serverCoverUrlLabel: document.getElementById("server-cover-url-label"),
    serverCoverUrl: document.getElementById("server-cover-url"),
    serverCoverDownloadBtn: document.getElementById("server-cover-download-btn"),
    serverCoverDownloadStatus: document.getElementById("server-cover-download-status"),
    localGameLabelImage: document.getElementById("local-game-label-image"),
    localGameModalStatus: document.getElementById("local-game-modal-status"),
    localGameImage: document.getElementById("local-game-image"),
    localGameCancelBtn: document.getElementById("local-game-cancel-btn"),
    localGameSaveBtn: document.getElementById("local-game-save-btn"),
    extraSyncCancelBtn: document.getElementById("extra-sync-cancel-btn"),
    extraSyncSaveBtn: document.getElementById("extra-sync-save-btn"),
    shutdownUpdateModal: document.getElementById("shutdown-update-modal"),
    shutdownUpdateTitle: document.getElementById("shutdown-update-title"),
    shutdownUpdateText: document.getElementById("shutdown-update-text"),
    shutdownUpdateStatus: document.getElementById("shutdown-update-status"),
    shutdownUpdateConsole: document.getElementById("shutdown-update-console"),
    shutdownUpdateResumeBtn: document.getElementById(
      "shutdown-update-resume-btn",
    ),
    shutdownUpdateAbortBtn: document.getElementById(
      "shutdown-update-abort-btn",
    ),
    shutdownUpdateConfirmBtn: document.getElementById(
      "shutdown-update-confirm-btn",
    ),
    settingsStatus: document.getElementById("settings-status"),
    startupScreen: document.getElementById("startup-screen"),
    startupTitle: document.getElementById("startup-title"),
    startupText: document.getElementById("startup-text"),
    logsTitle: document.getElementById("logs-title"),
    logsToggleBtn: document.getElementById("logs-toggle-btn"),
    logsSourceFilterLabel: document.getElementById("logs-source-filter-label"),
    logsSourceFilterSelect: document.getElementById("logs-source-filter-select"),
    logsLengthLabel: document.getElementById("logs-length-label"),
    logsLengthSelect: document.getElementById("logs-length-select"),
    logsLevelLabel: document.getElementById("logs-level-label"),
    logsLevelSelect: document.getElementById("logs-level-select"),
    logsPauseBtn: document.getElementById("logs-pause-btn"),
    logsRefreshBtn: document.getElementById("logs-refresh-btn"),
    logsOutput: document.getElementById("logs-output"),
    welcomeWizard: document.getElementById("welcome-wizard"),
    wizardTitle: document.getElementById("wizard-title"),
    wizardText: document.getElementById("wizard-text"),
    wizardProviderGuidanceTitle: document.getElementById(
      "wizard-provider-guidance-title",
    ),
    wizardProviderGlobal: document.getElementById("wizard-provider-global"),
    wizardProviderLegacy: document.getElementById("wizard-provider-legacy"),
    wizardProviderLan: document.getElementById("wizard-provider-lan"),
    wizardLabelNickname: document.getElementById("wizard-label-nickname"),
    wizardNicknameInput: document.getElementById("wizard-nickname-input"),
    wizardLabelStorage: document.getElementById("wizard-label-storage"),
    wizardStorageInput: document.getElementById("wizard-storage-input"),
    wizardStorageSelect: document.getElementById("wizard-storage-select"),
    wizardSaveBtn: document.getElementById("wizard-save-btn"),
    wizardConsole: document.getElementById("wizard-console"),
  };

  function t(key, fallback = "") {
    return state.dictionary[key] || fallback || key;
  }

  function providerErrorLabel(errorText) {
    const raw = String(errorText || "").trim();
    if (!raw) {
      return "";
    }
    const separator = raw.indexOf(":");
    const code = separator < 0 ? raw : raw.slice(0, separator);
    const detail = separator < 0 ? "" : raw.slice(separator + 1).trim();
    const translated = t(`status.error_${code}`, "");
    if (!translated) {
      return raw;
    }
    return detail ? `${translated} (${detail})` : translated;
  }

  function localizedText(raw, locale) {
    if (raw && typeof raw === "object" && !Array.isArray(raw)) {
      const normalized = String(locale || "").trim().toLowerCase();
      const preferred = String(raw[normalized] || "").trim();
      if (preferred) {
        return preferred;
      }
      const fallback = String(raw.en || raw.de || "").trim();
      if (fallback) {
        return fallback;
      }
    }
    return String(raw || "").trim();
  }

  function isRemoteHttpUrl(value) {
    return /^https?:\/\//i.test(String(value || "").trim());
  }

  function launcherDisabledGameSet() {
    const source = Array.isArray(state.launcherSite?.disable_games)
      ? state.launcherSite.disable_games
      : [];
    return new Set(
      source
        .map((id) =>
          String(id || "")
            .trim()
            .toLowerCase(),
        )
        .filter((id) => id.length > 0),
    );
  }

  function isGameDisabledByLauncher(gameId) {
    const normalized = String(gameId || "")
      .trim()
      .toLowerCase();
    if (!normalized) {
      return false;
    }
    if (!launcherDisabledGameSet().has(normalized)) {
      return false;
    }
    return !(
      state.launcherSite?.managed_by_lan_server &&
      state.catalogItems.some(
        (item) =>
          String(item?.id || "").trim().toLowerCase() === normalized &&
          String(item?.install_state || "").toLowerCase() === "installed",
      )
    );
  }

  function filterVisibleCatalogItems(items) {
    const list = Array.isArray(items) ? items : [];
    const disabled = launcherDisabledGameSet();
    if (!disabled.size) {
      return list;
    }
    return list.filter((item) => {
      const gameId = String(item?.id || "").trim().toLowerCase();
      if (!disabled.has(gameId)) return true;
      return Boolean(
        state.launcherSite?.managed_by_lan_server &&
          String(item?.install_state || "").toLowerCase() === "installed",
      );
    });
  }

  function applyLauncherSiteBranding() {
    const baseTitle = t("app.title", "LANLauncherNG");
    const lanTitle = String(state.launcherSite?.lan_title || "").trim();
    const mergedTitle = lanTitle ? `${baseTitle} - ${lanTitle}` : baseTitle;
    if (el.appTitle) {
      el.appTitle.textContent = mergedTitle;
    }
    if (el.appTitleLegacy) {
      el.appTitleLegacy.textContent = mergedTitle;
    }
    document.title = mergedTitle;
  }

  function renderLauncherLinksDropdown() {
    if (!el.topLinksSelect) {
      return;
    }
    const links = Array.isArray(state.launcherSite?.links)
      ? state.launcherSite.links
      : [];
    el.topLinksSelect.innerHTML = "";
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = t("ui.lan_links", "LAN Links");
    el.topLinksSelect.append(placeholder);
    for (const link of links) {
      const url = String(link?.url || "").trim();
      if (!url) {
        continue;
      }
      const label = String(link?.label || "").trim() || url;
      const option = document.createElement("option");
      option.value = url;
      option.textContent = label;
      el.topLinksSelect.append(option);
    }
    el.topLinksSelect.disabled = links.length === 0;
    el.topLinksSelect.value = "";
  }

  async function apiGet(path) {
    const response = await fetch(path, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    return response.json();
  }

  async function apiPost(path, payload) {
    const response = await fetch(path, {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await response.json();
    if (!response.ok) {
      throw new Error(body?.result?.message || `HTTP ${response.status}`);
    }
    return body;
  }

  function selectedGameWinetricksStorageKey(gameId) {
    return `llng.winetricks.packages.${String(gameId || "")
      .trim()
      .toLowerCase()}`;
  }

  function availableWinetricksPackageIds() {
    return (state.winetricksCatalog?.packages || [])
      .map((item) =>
        String(item?.id || "")
          .trim()
          .toLowerCase(),
      )
      .filter((item) => item);
  }

  function currentDefaultWinetricksPackages() {
    const metadataRecommended = recommendedWinetricksPackagesFromMetadata();
    if (metadataRecommended.length > 0) {
      return metadataRecommended;
    }
    const configured = Array.isArray(state.winetricksCatalog?.default_selected)
      ? state.winetricksCatalog.default_selected
      : [];
    const normalized = configured
      .map((item) =>
        String(item || "")
          .trim()
          .toLowerCase(),
      )
      .filter((item) => item);
    if (normalized.length > 0) {
      return normalized;
    }
    return ["d3dx9", "vcrun2008", "vcrun2010", "xact", "corefonts"];
  }

  function recommendedWinetricksPackagesFromMetadata() {
    const allowed = new Set(availableWinetricksPackageIds());
    const metadata = state.selectedGame?.metadata || {};
    const installer = metadata?.installer || {};
    const tasks = Array.isArray(installer?.tasks) ? installer.tasks : [];
    const selected = [];
    for (const task of tasks) {
      const name = String(task?.name || task?.action || "")
        .trim()
        .toLowerCase();
      if (name !== "winetricks" && name !== "protontricks") {
        continue;
      }
      const app = String(task?.app || "")
        .trim()
        .toLowerCase();
      if (app && allowed.has(app)) {
        selected.push(app);
      }
    }
    return [...new Set(selected)];
  }

  async function ensureWinetricksCatalogLoaded() {
    if ((state.winetricksCatalog?.packages || []).length > 0) {
      return;
    }
    try {
      const payload = await apiGet("/platform/winetricks-packages");
      const catalog = payload?.winetricks || {};
      state.winetricksCatalog = {
        packages: Array.isArray(catalog.packages) ? catalog.packages : [],
        default_selected: Array.isArray(catalog.default_selected)
          ? catalog.default_selected
          : [],
      };
    } catch (_err) {
      state.winetricksCatalog = {
        packages: [],
        default_selected: [],
      };
    }
  }

  function loadSelectedGameWinetricksPackages() {
    const allowed = new Set(availableWinetricksPackageIds());
    if (!state.selectedGameId || allowed.size === 0) {
      state.selectedGameWinetricksPackages = [];
      renderDetailWinetricksPackages();
      return;
    }
    const storageKey = selectedGameWinetricksStorageKey(state.selectedGameId);
    let selected = [];
    try {
      const raw = localStorage.getItem(storageKey);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) {
          selected = parsed
            .map((item) =>
              String(item || "")
                .trim()
                .toLowerCase(),
            )
            .filter((item) => allowed.has(item));
        }
      }
    } catch (_err) {
      selected = [];
    }
    if (!selected.length) {
      selected = currentDefaultWinetricksPackages().filter((item) =>
        allowed.has(item),
      );
    }
    state.selectedGameWinetricksPackages = [...new Set(selected)];
    renderDetailWinetricksPackages();
  }

  function persistSelectedGameWinetricksPackages() {
    if (!state.selectedGameId) {
      return;
    }
    localStorage.setItem(
      selectedGameWinetricksStorageKey(state.selectedGameId),
      JSON.stringify(state.selectedGameWinetricksPackages),
    );
  }

  function setSelectedGameWinetricksPackages(nextPackages) {
    const allowed = new Set(availableWinetricksPackageIds());
    state.selectedGameWinetricksPackages = Array.isArray(nextPackages)
      ? [
          ...new Set(
            nextPackages
              .map((item) =>
                String(item || "")
                  .trim()
                  .toLowerCase(),
              )
              .filter((item) => allowed.has(item)),
          ),
        ]
      : [];
    persistSelectedGameWinetricksPackages();
    renderDetailWinetricksPackages();
    updateDetailActionStates();
  }

  function renderDetailWinetricksPackages() {
    if (!el.detailWinetricksPackages) {
      return;
    }
    el.detailWinetricksPackages.innerHTML = "";
    const packages = Array.isArray(state.winetricksCatalog?.packages)
      ? state.winetricksCatalog.packages
      : [];
    for (const item of packages) {
      const packageId = String(item?.id || "")
        .trim()
        .toLowerCase();
      if (!packageId) {
        continue;
      }
      const label = document.createElement("label");
      label.className = "checkbox-inline";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked =
        state.selectedGameWinetricksPackages.includes(packageId);
      checkbox.addEventListener("change", () => {
        const next = checkbox.checked
          ? [...state.selectedGameWinetricksPackages, packageId]
          : state.selectedGameWinetricksPackages.filter(
              (entry) => entry !== packageId,
            );
        setSelectedGameWinetricksPackages(next);
      });
      const text = document.createElement("span");
      text.textContent = packageId;
      label.append(checkbox, text);
      el.detailWinetricksPackages.append(label);
    }
  }

  function formatSpeed(bps) {
    const kb = bps / 1024;
    if (kb < 1) return "0 KB/s";
    if (kb < 1024) return `${Math.round(kb)} KB/s`;
    return `${(kb / 1024).toFixed(2)} MB/s`;
  }

  function normalizeTrafficSample(raw) {
    const sample = raw || {};
    return {
      download_bps: Math.max(0, Number(sample.download_bps || 0)),
      upload_bps: Math.max(0, Number(sample.upload_bps || 0)),
      disk_read_bps: Math.max(0, Number(sample.disk_read_bps || 0)),
      disk_write_bps: Math.max(0, Number(sample.disk_write_bps || 0)),
      disk_total_bps: Math.max(
        0,
        Number(sample.disk_total_bps || sample.disk_activity_bps || 0),
      ),
    };
  }

  function trafficSummaryText(sample) {
    const value = normalizeTrafficSample(sample);
    return t(
      "topbar.traffic_summary",
      "DL {download} | UL {upload} | Disk {disk}",
    )
      .replace("{download}", formatSpeed(value.download_bps))
      .replace("{upload}", formatSpeed(value.upload_bps))
      .replace("{disk}", formatSpeed(value.disk_total_bps));
  }

  function trafficHintText() {
    return t("topbar.traffic_toggle_hint", "Click to switch chart type");
  }

  function trafficSeriesLegend() {
    return [
      {
        key: "download_bps",
        color: "var(--accent)",
        label: t("topbar.traffic_download", "Download"),
      },
      {
        key: "upload_bps",
        color: "var(--accent-2)",
        label: t("topbar.traffic_upload", "Upload"),
      },
      {
        key: "disk_read_bps",
        color: "#6fb7ff",
        label: t("topbar.traffic_disk_read", "Disk read"),
      },
      {
        key: "disk_write_bps",
        color: "#f4c15d",
        label: t("topbar.traffic_disk_write", "Disk write"),
      },
    ];
  }

  function updateTopbarUpdateState() {
    if (!document.body) {
      return;
    }
    document.body.classList.toggle(
      "topbar-update-available",
      Boolean(state.updateAvailable),
    );
    updateTopbarTrafficSizing();
  }

  function updateTopbarTrafficSizing() {
    if (!el.topTrafficToggle || !el.topActions) {
      return;
    }
    const topActionsWidth = Math.max(
      0,
      Math.floor(el.topActions.getBoundingClientRect().width || 0),
    );
    if (!topActionsWidth) {
      return;
    }
    const visibleChildren = Array.from(el.topActions.children).filter(
      (child) => child instanceof HTMLElement && !child.hidden,
    );
    const gapValue = Number.parseFloat(
      getComputedStyle(el.topActions).columnGap ||
        getComputedStyle(el.topActions).gap ||
        "0",
    );
    let reservedWidth = 0;
    for (const child of visibleChildren) {
      if (child === el.topTrafficToggle) {
        continue;
      }
      reservedWidth += Math.ceil(child.getBoundingClientRect().width || 0);
    }
    const gapWidth = Math.max(0, visibleChildren.length - 1) * Math.max(
      0,
      gapValue || 0,
    );
    const minWidth = state.updateAvailable ? 148 : 160;
    const maxWidth = state.updateAvailable ? 184 : 196;
    const availableWidth = Math.max(
      minWidth,
      topActionsWidth - reservedWidth - gapWidth - 2,
    );
    const basisWidth = Math.max(minWidth, Math.min(maxWidth, availableWidth));
    el.topTrafficToggle.style.setProperty(
      "--top-traffic-basis",
      `${basisWidth}px`,
    );
    el.topTrafficToggle.style.setProperty(
      "--top-traffic-min-width",
      `${minWidth}px`,
    );
    el.topTrafficToggle.style.setProperty(
      "--top-traffic-max-width",
      `${maxWidth}px`,
    );
  }

  function trafficValueRows(sample) {
    const value = normalizeTrafficSample(sample);
    return [
      {
        label: t("topbar.traffic_download", "Download"),
        value: formatSpeed(value.download_bps),
      },
      {
        label: t("topbar.traffic_upload", "Upload"),
        value: formatSpeed(value.upload_bps),
      },
      {
        label: t("topbar.traffic_disk_read", "Disk read"),
        value: formatSpeed(value.disk_read_bps),
      },
      {
        label: t("topbar.traffic_disk_write", "Disk write"),
        value: formatSpeed(value.disk_write_bps),
      },
    ];
  }

  function topTrafficHistoryMax(history) {
    const list = Array.isArray(history) ? history : [];
    const values = [];
    for (const entry of list) {
      const sample = normalizeTrafficSample(entry);
      values.push(
        sample.download_bps,
        sample.upload_bps,
        sample.disk_read_bps,
        sample.disk_write_bps,
        sample.disk_total_bps,
      );
    }
    return Math.max(1, ...values);
  }

  function chartPolylinePoints(values, maxValue, width, height, padding) {
    const series = Array.isArray(values) ? values : [];
    if (!series.length) {
      return "";
    }
    const left = padding;
    const right = width - padding;
    const top = padding;
    const bottom = height - padding;
    const innerWidth = Math.max(1, right - left);
    const innerHeight = Math.max(1, bottom - top);
    const step = series.length === 1 ? 0 : innerWidth / (series.length - 1);
    return series
      .map((rawValue, index) => {
        const value = Math.max(0, Number(rawValue || 0));
        const normalized = Math.min(1, value / maxValue);
        const x = left + step * index;
        const y = bottom - normalized * innerHeight;
        return `${x.toFixed(2)},${y.toFixed(2)}`;
      })
      .join(" ");
  }

  function renderTopTrafficChart() {
    if (!el.topTrafficChart) {
      return;
    }
    const mode = state.topTrafficMode === "bar" ? "bar" : "line";
    const history = Array.isArray(state.topTrafficHistory)
      ? state.topTrafficHistory.map(normalizeTrafficSample)
      : [];
    const current = normalizeTrafficSample(state.topTrafficSample);
    const chartWidth = Math.max(
      240,
      Math.floor(
        el.topTrafficToggle?.getBoundingClientRect?.().width ||
          el.topTrafficChart?.clientWidth ||
          320,
      ),
    );
    const paddingX = 8;
    const paddingY = 5;
    const visibleCount = Math.max(
      12,
      Math.floor((chartWidth - paddingX * 2) / 5),
    );
    const visibleHistory = history.slice(-visibleCount);
    const maxValue = topTrafficHistoryMax(visibleHistory);
    const width = chartWidth;
    const height = 32;
    el.topTrafficChart.setAttribute("viewBox", `0 0 ${width} ${height}`);
    const gridLines = [8, 16, 24]
      .map(
        (y) =>
          `<line class="top-traffic-grid" x1="${paddingX}" y1="${y}" x2="${width - paddingX}" y2="${y}" />`,
      )
      .join("");
    const legend = trafficSeriesLegend();
    let body = "";
    if (mode === "bar") {
      const bars = legend.map((item, lane) => ({ ...item, lane }));
      const sampleCount = Math.max(1, visibleHistory.length);
      const innerWidth = Math.max(1, width - paddingX * 2);
      const innerHeight = Math.max(1, height - paddingY * 2);
      const groupWidth = innerWidth / sampleCount;
      const barWidth = Math.max(1.8, Math.min(5.2, groupWidth * 0.16));
      // Keep every series on the same x coordinate so the compact widget reads
      // as a layered sparkline instead of four side-by-side bars.
      body = visibleHistory
        .map((sample, sampleIndex) => {
          const groupX = paddingX + groupWidth * sampleIndex;
          const barX = groupX + Math.max(0, (groupWidth - barWidth) / 2);
          return bars
            .map((bar) => {
              const value = Math.max(0, Number(sample[bar.key] || 0));
              const barHeight =
                maxValue > 0
                  ? Math.max(2, (value / maxValue) * innerHeight)
                  : 2;
              const opacity = [0.86, 0.68, 0.56, 0.42][bar.lane] || 0.5;
              const y = height - paddingY - barHeight;
              return `
                <rect
                  class="top-traffic-bar"
                  x="${barX.toFixed(2)}"
                  y="${y.toFixed(2)}"
                  width="${barWidth.toFixed(2)}"
                  height="${barHeight.toFixed(2)}"
                  fill="${bar.color}"
                  opacity="${opacity}"
                />
              `;
            })
            .join("");
        })
        .join("");
    } else {
      body = legend
        .map((series) => {
          const points = chartPolylinePoints(
            visibleHistory.map((sample) => sample[series.key] || 0),
            maxValue,
            width,
            height,
            5,
          );
          return `
            <polyline
              class="top-traffic-line"
              points="${points}"
              stroke="${series.color}"
            />
          `;
        })
        .join("");
    }
    el.topTrafficChart.innerHTML = `
      <rect x="0" y="0" width="${width}" height="${height}" fill="transparent"></rect>
      ${gridLines}
      ${body}
    `;
    if (el.topTrafficToggle) {
      el.topTrafficToggle.dataset.mode = mode;
      el.topTrafficToggle.removeAttribute("title");
      el.topTrafficToggle.setAttribute("aria-label", trafficHintText());
    }
    if (el.topTrafficInfoHint) {
      el.topTrafficInfoHint.textContent = trafficHintText();
    }
    const rows = trafficValueRows(current);
    const rowBindings = [
      [el.topTrafficInfoDownloadLabel, el.topTrafficInfoDownloadValue],
      [el.topTrafficInfoUploadLabel, el.topTrafficInfoUploadValue],
      [el.topTrafficInfoDiskReadLabel, el.topTrafficInfoDiskReadValue],
      [el.topTrafficInfoDiskWriteLabel, el.topTrafficInfoDiskWriteValue],
    ];
    rowBindings.forEach(([labelEl, valueEl], index) => {
      if (!labelEl || !valueEl) return;
      labelEl.textContent = rows[index]?.label || "";
      valueEl.textContent = rows[index]?.value || "";
    });
    if (el.topTrafficInfo) {
      el.topTrafficInfo.setAttribute(
        "aria-label",
        [trafficHintText(), ...rows.map((row) => `${row.label} ${row.value}`)].join(". "),
      );
    }
  }

  function updateTopTrafficSample(sample) {
    state.topTrafficSample = normalizeTrafficSample(sample);
    state.topTrafficHistory = [
      ...state.topTrafficHistory.slice(-TOP_TRAFFIC_HISTORY_LIMIT),
      state.topTrafficSample,
    ];
    renderTopTrafficChart();
  }

  function toggleTopTrafficMode() {
    state.topTrafficMode = state.topTrafficMode === "bar" ? "line" : "bar";
    localStorage.setItem("llng.top_traffic_mode", state.topTrafficMode);
    renderTopTrafficChart();
  }

  function applyTheme(theme) {
    document.body.setAttribute(
      "data-theme",
      theme === "light" ? "light" : "dark",
    );
  }

  function gameImageUrl(gameId) {
    return `/media/image/${encodeURIComponent(gameId)}`;
  }

  function placeholderImageUrl() {
    return "/assets/games/placeholder.svg";
  }

  function applyImageFallback(imageEl) {
    if (!imageEl) {
      return;
    }
    if (imageEl.dataset.fallbackBound === "1") {
      return;
    }
    imageEl.dataset.fallbackBound = "1";
    imageEl.addEventListener("error", () => {
      if (imageEl.dataset.fallbackApplied === "1") {
        return;
      }
      imageEl.dataset.fallbackApplied = "1";
      imageEl.src = placeholderImageUrl();
    });
    imageEl.addEventListener("load", () => {
      if (imageEl.src.includes("/assets/games/placeholder.svg")) {
        return;
      }
      imageEl.dataset.fallbackApplied = "0";
    });
  }

  function gameVideoUrl(gameId) {
    return `/media/video/${encodeURIComponent(gameId)}`;
  }

  function isInstalled(installState) {
    return String(installState || "").toLowerCase() === "installed";
  }

  function isInstalling(installState) {
    return String(installState || "").toLowerCase() === "installing";
  }

  function isDownloading(installState) {
    return String(installState || "").toLowerCase() === "downloading";
  }

  function isSyncing(syncState) {
    return String(syncState || "").toLowerCase() === "syncing";
  }

  function isReadyToInstall(syncState) {
    return String(syncState || "").toLowerCase() === "ready_to_install";
  }

  function selectedGameProviderType() {
    return String(state.selectedGame?.game_provider_type || "")
      .trim()
      .toLowerCase();
  }

  function selectedGameProviderLabel() {
    const providerType = selectedGameProviderType() || "resilio";
    return t(
      providerType === "ouisync"
        ? "game.provider_ouisync"
        : providerType === "local"
          ? "game.provider_local"
          : "game.provider_resilio",
      providerType === "ouisync"
        ? "Ouisync"
        : providerType === "local"
          ? "Local"
          : "Resilio",
    );
  }

  function formatEta(seconds) {
    const value = Number(seconds || 0);
    if (!Number.isFinite(value) || value <= 0) {
      return "-";
    }
    if (value < 60) {
      return `${Math.round(value)}s`;
    }
    if (value < 3600) {
      return `${Math.round(value / 60)}m`;
    }
    return `${Math.round(value / 3600)}h`;
  }

  function formatLogTimestamp(raw) {
    const value = String(raw || "").trim();
    if (!value) {
      return "";
    }
    const dt = new Date(value);
    if (Number.isNaN(dt.getTime())) {
      return value;
    }
    const yyyy = dt.getFullYear();
    const mm = String(dt.getMonth() + 1).padStart(2, "0");
    const dd = String(dt.getDate()).padStart(2, "0");
    const hh = String(dt.getHours()).padStart(2, "0");
    const mi = String(dt.getMinutes()).padStart(2, "0");
    const ss = String(dt.getSeconds()).padStart(2, "0");
    return `${yyyy}/${mm}/${dd} ${hh}:${mi}:${ss}`;
  }

  function normalizeLogSource(raw) {
    const value = String(raw || "").trim().toLowerCase();
    if (
      value === "app" ||
      value === "lanlauncherng" ||
      value === "sync" ||
      value === "resilio" ||
      value === "ouisync" ||
      value === "unknown"
    ) {
      if (value === "app") {
        return "lanlauncherng";
      }
      if (value === "sync") {
        return "resilio";
      }
      return value;
    }
    return "unknown";
  }

  function normalizeLogFilter(raw) {
    const value = String(raw || "").trim().toLowerCase();
    if (
      value === "all" ||
      value === "app" ||
      value === "lanlauncherng" ||
      value === "sync" ||
      value === "resilio" ||
      value === "ouisync" ||
      value === "unknown"
    ) {
      if (value === "app") {
        return "lanlauncherng";
      }
      if (value === "sync") {
        return "resilio";
      }
      return value;
    }
    return "all";
  }

  function normalizeLogLimit(raw) {
    const value = String(raw || "").trim();
    return ["200", "500", "1000", "2000"].includes(value) ? value : "200";
  }

  function logSourceLabel(source) {
    switch (normalizeLogSource(source)) {
      case "lanlauncherng":
        return t("logs.source_lanlauncherng", "LANLauncherNG");
      case "resilio":
        return t("logs.source_resilio", "Resilio");
      case "ouisync":
        return t("logs.source_ouisync", "Ouisync");
      default:
        return t("logs.source_unknown", "Unknown");
    }
  }

  function formatLogLine(entry) {
    const normalizedSource = normalizeLogSource(entry?.source || "");
    const ts = formatLogTimestamp(entry?.ts || "");
    const msg = String(
      entry?.msg || entry?.message || entry?.line || entry?.text || "",
    ).trim();
    const label = logSourceLabel(normalizedSource).toUpperCase();
    if (normalizedSource === "lanlauncherng") {
      const level = String(entry?.level || "").trim();
      return `${ts} [${label}] ${level} ${msg}`.trim();
    }
    return `${ts} [${label}] ${msg}`.trim();
  }

  function logEntryMatchesFilter(entry, filter) {
    const normalizedFilter = normalizeLogFilter(filter);
    if (normalizedFilter === "all") {
      return true;
    }
    return normalizeLogSource(entry?.source || "") === normalizedFilter;
  }

  function logEntrySortTime(entry) {
    const parsed = Date.parse(String(entry?.ts || "").trim());
    return Number.isFinite(parsed) ? parsed : Number.MAX_SAFE_INTEGER;
  }

  function buildLogEntries(payload) {
    const timeline = Array.isArray(payload?.entries) ? payload.entries : [];
    const entries = [];
    const seen = new Set();
    const pushEntry = (item) => {
      const entry = {
        source: normalizeLogSource(item?.source || "unknown"),
        ts: String(item?.ts || "").trim(),
        level: String(item?.level || "").trim(),
        msg: String(
          item?.msg || item?.message || item?.line || item?.text || "",
        ).trim(),
      };
      if (!entry.msg) {
        return;
      }
      const signature = `${entry.source}|${entry.ts}|${entry.level}|${entry.msg}`;
      if (seen.has(signature)) {
        return;
      }
      seen.add(signature);
      entries.push(entry);
    };

    for (const item of timeline) {
      pushEntry(item);
    }
    return entries;
  }

  function renderLogsFromCache() {
    const filter = normalizeLogFilter(state.logsSourceFilter);
    const filteredEntries = state.logsEntries.filter((entry) =>
      logEntryMatchesFilter(entry, filter),
    );
    if (!filteredEntries.length) {
      el.logsOutput.textContent = t(
        "logs.empty_filtered",
        "No logs match the selected filter.",
      );
      return;
    }
    const fragment = document.createDocumentFragment();
    for (const entry of filteredEntries) {
      const line = document.createElement("span");
      line.className = `logs-line logs-line-source-${entry.source}`;
      line.textContent = formatLogLine(entry);
      fragment.append(line, document.createTextNode("\n"));
    }
    el.logsOutput.replaceChildren(fragment);
    if (!state.logsPaused) {
      el.logsOutput.scrollTop = el.logsOutput.scrollHeight;
    }
  }

  function normalizeGridTileSize(value) {
    const key = String(value || "").toLowerCase();
    return Object.prototype.hasOwnProperty.call(GRID_TILE_SIZE_PRESETS, key)
      ? key
      : "medium";
  }

  function gridTileSizeConfig() {
    return GRID_TILE_SIZE_PRESETS[normalizeGridTileSize(state.gridTileSize)];
  }

  function parseCssPx(raw) {
    const value = Number.parseFloat(String(raw || "0"));
    return Number.isFinite(value) ? value : 0;
  }

  function updateCatalogGridSizing() {
    if (!el.gameList || state.viewMode !== "grid") {
      return;
    }
    const bounds = el.gameList.getBoundingClientRect();
    const width = Math.max(
      0,
      Math.floor(bounds.width || el.gameList.clientWidth || 0),
    );
    if (!width) {
      return;
    }
    const config = gridTileSizeConfig();
    const styles = getComputedStyle(el.gameList);
    const gap = Math.max(
      0,
      parseCssPx(styles.columnGap || styles.gap || "0"),
    );
    const trackWidth = (columns) => (width - gap * (columns - 1)) / columns;
    let columns = Math.max(
      1,
      Math.round((width + gap) / (config.preferredWidth + gap)),
    );
    let tileWidth = trackWidth(columns);
    while (columns > 1 && tileWidth < config.minWidth) {
      columns -= 1;
      tileWidth = trackWidth(columns);
    }
    while (tileWidth > config.maxWidth) {
      const nextColumns = columns + 1;
      const nextTileWidth = trackWidth(nextColumns);
      if (nextTileWidth >= tileWidth || nextTileWidth < config.minWidth) {
        break;
      }
      columns = nextColumns;
      tileWidth = nextTileWidth;
    }
    el.gameList.style.setProperty("--grid-cols", String(columns));
  }

  function applyViewMode() {
    const mode = state.viewMode === "grid" ? "grid" : "list";
    state.viewMode = mode;
    localStorage.setItem("llng.view_mode", mode);
    el.gameList.classList.toggle("grid-mode", mode === "grid");
    el.viewListBtn.classList.toggle("active", mode === "list");
    el.viewGridBtn.classList.toggle("active", mode === "grid");
    if (el.gridSizeSelect) {
      const sizeKey = normalizeGridTileSize(state.gridTileSize);
      state.gridTileSize = sizeKey;
      localStorage.setItem(GRID_TILE_SIZE_STORAGE_KEY, sizeKey);
      if (el.gridSizeSelect.value !== sizeKey) {
        el.gridSizeSelect.value = sizeKey;
      }
    }
    updateCatalogGridSizing();
  }

  function updateDetailActionStates() {
    const syncBlocked = !state.settings.library_path_initialized;
    const gameInstalled = isInstalled(state.selectedGame?.install_state);
    const gameInstalling = isInstalling(state.selectedGame?.install_state);
    const gameDownloading = isDownloading(state.selectedGame?.install_state);
    const gameBusy = gameInstalling || gameDownloading;
    const syncOnlyMode = Boolean(state.settings.sync_only_mode);
    const hasSelectedGame = Boolean(state.selectedGameId);
    const isLocalGame = selectedGameProviderType() === "local";
    const canUseGameActions =
      hasSelectedGame && !gameBusy && (gameInstalled || isLocalGame);
    const serverStartExists = Boolean(
      state.selectedGameStatus?.server_start_exists,
    );
    const gameSyncActive = Boolean(state.selectedGameSync?.active);
    const syncProgress = Math.max(
      0,
      Math.min(100, Number(state.selectedGameSync?.progress_percent || 0)),
    );
    const manualInstallNeeded =
      hasSelectedGame &&
      syncOnlyMode &&
      syncProgress >= 100 &&
      !gameInstalling &&
      (!gameInstalled || Boolean(state.selectedGame?.needs_update));
    const canStartSync =
      hasSelectedGame && !syncBlocked && !gameSyncActive && !gameBusy;
    const canStopSync =
      hasSelectedGame &&
      !syncBlocked &&
      (gameSyncActive || gameDownloading) &&
      !gameInstalling;
    const canEditLocalGame = isLocalGame && hasSelectedGame && !gameBusy;
    const canDeleteGame = hasSelectedGame && !gameBusy;

    const effectiveRuntime = String(
      state.selectedGameLaunchSettings?.effective_linux_runtime ||
        state.settings.linux_windows_runtime ||
        "wine",
    ).toLowerCase();
    const showPrefixDeps =
      state.settings.platform === "linux" &&
      hasSelectedGame &&
      (gameInstalled || isLocalGame) &&
      (effectiveRuntime === "wine" ||
        effectiveRuntime === "proton" ||
        effectiveRuntime === "proton-ge");

    el.syncStart.hidden = isLocalGame;
    el.syncStop.hidden = isLocalGame;
    const isOuisyncGame = selectedGameProviderType() === "ouisync";
    if (el.syncRemoveData) {
      el.syncRemoveData.hidden = isLocalGame || !isOuisyncGame || !state.selectedGameSync?.repository_present;
      el.syncRemoveData.disabled = !isOuisyncGame || gameBusy;
    }
    el.syncStart.disabled = !canStartSync || isLocalGame;
    el.syncStop.disabled = !canStopSync || isLocalGame;
    el.serviceSyncStart.disabled = syncBlocked || state.syncRunning;
    el.serviceSyncStop.disabled = !state.syncRunning;
    el.openGameFolder.disabled = !hasSelectedGame || gameBusy;
    if (el.installAnywayBtn) {
      el.installAnywayBtn.hidden = !manualInstallNeeded;
      el.installAnywayBtn.disabled = !manualInstallNeeded;
    }
    if (el.editLocalGameBtn) {
      el.editLocalGameBtn.hidden = !isLocalGame;
      el.editLocalGameBtn.disabled = !canEditLocalGame;
    }
    el.startGameBtn.disabled = !canUseGameActions;
    el.startServerBtn.hidden = !serverStartExists;
    el.startServerBtn.disabled = !canUseGameActions;
    el.deleteGameBtn.disabled = !canUseGameActions;
    if (isLocalGame) {
      el.deleteGameBtn.disabled = !canDeleteGame;
    }
    if (el.installProtonCommonDepsBtn) {
      el.installProtonCommonDepsBtn.hidden = !showPrefixDeps;
      el.installProtonCommonDepsBtn.disabled = !showPrefixDeps || gameBusy;
    }
    if (el.detailWinetricksPanel) {
      el.detailWinetricksPanel.hidden = !showPrefixDeps;
    }
    if (el.detailWinetricksInstallBtn) {
      el.detailWinetricksInstallBtn.disabled =
        !showPrefixDeps ||
        gameBusy ||
        state.selectedGameWinetricksPackages.length === 0;
    }
    if (el.detailWinetricksRemoveBtn) {
      el.detailWinetricksRemoveBtn.disabled = !showPrefixDeps || gameBusy;
    }
    if (el.detailWinetricksSaveBtn) {
      el.detailWinetricksSaveBtn.disabled = !showPrefixDeps || gameBusy;
    }
    if (el.detailLocalNote) {
      el.detailLocalNote.hidden = !isLocalGame;
    }
    if (el.detailWinetricksSelectCommon) {
      const hasRecommended =
        recommendedWinetricksPackagesFromMetadata().length > 0;
      el.detailWinetricksSelectCommon.disabled =
        !showPrefixDeps || !hasRecommended;
    }
    if (el.detailWinetricksSelectAll) {
      el.detailWinetricksSelectAll.disabled = !showPrefixDeps;
    }
    if (el.detailWinetricksSelectNone) {
      el.detailWinetricksSelectNone.disabled = !showPrefixDeps;
    }
    el.syncStart.textContent =
      gameInstalled || syncOnlyMode
        ? t("sync.start", "Start Sync")
        : t("sync.install_game", "Install Game");
    updateDetailLinuxRuntimeControl();
  }

  function updateDetailLinuxRuntimeControl() {
    if (!el.detailLinuxRuntimeSelect || !el.labelDetailLinuxRuntime) {
      return;
    }
    const show =
      state.settings.platform === "linux" &&
      Boolean(state.selectedGameId) &&
      !isInstalling(state.selectedGame?.install_state);
    el.labelDetailLinuxRuntime.hidden = !show;
    el.detailLinuxRuntimeSelect.hidden = !show;
    el.detailLinuxRuntimeSelect.disabled = !show;
    if (el.labelDetailLinuxLeaveTerminalOpen) {
      el.labelDetailLinuxLeaveTerminalOpen.hidden = !show;
    }
    if (el.detailLinuxLeaveTerminalOpenCheckbox) {
      el.detailLinuxLeaveTerminalOpenCheckbox.hidden = !show;
      el.detailLinuxLeaveTerminalOpenCheckbox.disabled = !show;
    }
    if (!show) {
      return;
    }
    const selectedOverride = String(
      state.selectedGameLaunchSettings?.linux_runtime_override || "",
    );
    el.detailLinuxRuntimeSelect.value = selectedOverride;
    if (el.detailLinuxLeaveTerminalOpenCheckbox) {
      el.detailLinuxLeaveTerminalOpenCheckbox.checked = Boolean(
        state.selectedGameLaunchSettings?.linux_leave_terminal_open,
      );
    }
    const effectiveRuntime = String(
      state.selectedGameLaunchSettings?.effective_linux_runtime ||
        state.settings.linux_windows_runtime ||
        "wine",
    ).toLowerCase();
    const labelTemplate = selectedOverride
      ? t(
          "game.detail_linux_runtime_effective",
          "Runtime for this game (effective: {runtime})",
        )
      : t(
          "game.detail_linux_runtime_global_fallback",
          "Runtime for this game (using global: {runtime})",
        );
    el.labelDetailLinuxRuntime.textContent = labelTemplate.replace(
      "{runtime}",
      runtimeLabel(effectiveRuntime),
    );
  }

  function runtimeLabel(runtime) {
    const value = String(runtime || "wine").toLowerCase();
    if (value === "native") {
      return t("settings.linux_runtime_native", "Native preferred");
    }
    if (value === "proton") {
      return t("settings.linux_runtime_proton", "Proton");
    }
    if (value === "proton-ge") {
      return t("settings.linux_runtime_proton_ge", "Proton GE");
    }
    return t("settings.linux_runtime_wine", "Wine");
  }

  function launchMethodLabel(method) {
    const value = String(method || "")
      .trim()
      .toLowerCase();
    if (value === "linux_native_script") {
      return t(
        "game.console_method_linux_native_script",
        "Linux native script",
      );
    }
    if (value === "linux_cmd_wrapper") {
      return t("game.console_method_linux_cmd_wrapper", "Linux CMD wrapper");
    }
    if (value === "windows_cmd") {
      return t("game.console_method_windows_cmd", "Windows CMD");
    }
    return value || t("ui.unknown", "unknown");
  }

  function renderDetailMeta() {
    if (!state.selectedGame) {
      return;
    }
    if (!el.detailMeta) {
      return;
    }
    const installedVersion = String(
      state.selectedGame.installed_version || "",
    ).trim();
    const latestVersion = String(state.selectedGame.version || "").trim();
    const badges = [];
    badges.push(
      `${t("ui.players", "Players")}: ${state.selectedGame.max_players || "-"}`,
    );
    badges.push(`${t("ui.size", "Size")}: ${state.selectedGame.size_gb} GB`);
    badges.push(
      `${t("ui.installed_version", "Installed")}: ${installedVersion || "-"}`,
    );
    if (latestVersion && latestVersion !== installedVersion) {
      badges.push(`${t("ui.latest_version", "Latest")}: ${latestVersion}`);
    }
    badges.push(
      `${t("sync.item_progress", "Sync progress")}: ${Math.max(0, Math.min(100, Number(state.selectedGameSync.progress_percent || 0)))}%`,
    );
    if (selectedGameProviderType() === "local") {
      badges.push(t("game.local_detail_badge", "Local entry"));
    }

    el.detailMeta.innerHTML = "";
    for (const text of badges) {
      const badge = document.createElement("span");
      badge.className = "meta-badge";
      badge.textContent = text;
      el.detailMeta.append(badge);
    }
  }

  function renderDetailLinks() {
    if (!el.detailLinks || !el.detailLinksList) {
      return;
    }
    const links = Array.isArray(state.selectedGame?.metadata?.links)
      ? state.selectedGame.metadata.links
      : [];
    el.detailLinksList.innerHTML = "";
    if (!links.length) {
      el.detailLinks.hidden = true;
      return;
    }
    if (el.detailLinksTitle) {
      el.detailLinksTitle.textContent = t("game.links", "Links");
    }
    for (const entry of links) {
      const url = String(entry?.url || "").trim();
      if (!url) {
        continue;
      }
      const label = localizedText(entry?.label, state.locale) || url;
      const anchor = document.createElement("a");
      anchor.className = "detail-link";
      anchor.href = url;
      anchor.target = "_blank";
      anchor.rel = "noopener noreferrer";
      anchor.textContent = label;
      el.detailLinksList.append(anchor);
    }
    el.detailLinks.hidden = el.detailLinksList.childElementCount === 0;
  }

  function updateDetailBadges() {
    if (!state.selectedGame) {
      updateDetailDownloadProgress(false);
      if (el.detailDownloadingBadge) {
        el.detailDownloadingBadge.hidden = true;
      }
      if (el.detailSyncingBadge) {
        el.detailSyncingBadge.hidden = true;
      }
      if (el.detailFullySyncedBadge) {
        el.detailFullySyncedBadge.hidden = true;
      }
      el.detailUpdateBadge.hidden = true;
      el.detailUpToDateBadge.hidden = true;
      if (el.detailProviderBadge) {
        el.detailProviderBadge.hidden = true;
      }
      if (el.detailInstallingBadge) {
        el.detailInstallingBadge.hidden = true;
      }
      return;
    }
    const installing = isInstalling(state.selectedGame.install_state);
    const downloading =
      isDownloading(state.selectedGame.install_state) ||
      String(state.selectedGameSync?.sync_state || "").toLowerCase() ===
        "downloading";
    const syncing = isSyncing(state.selectedGameSync?.sync_state);
    const readyToInstall = isReadyToInstall(state.selectedGameSync?.sync_state);
    const installed = isInstalled(state.selectedGame.install_state);
    const needsUpdate = Boolean(state.selectedGame.needs_update);
    updateDetailDownloadProgress(downloading || syncing);
    if (el.detailDownloadingBadge) {
      el.detailDownloadingBadge.textContent = t(
        "game.downloading",
        "Downloading",
      );
      el.detailDownloadingBadge.hidden = !downloading;
    }
    if (el.detailSyncingBadge) {
      el.detailSyncingBadge.textContent = t("game.syncing", "Syncing");
      el.detailSyncingBadge.hidden = !syncing;
    }
    if (el.detailFullySyncedBadge) {
      el.detailFullySyncedBadge.textContent = t(
        "game.fully_synced",
        "Fully synced",
      );
      el.detailFullySyncedBadge.hidden = !readyToInstall;
    }
    if (el.detailInstallingBadge) {
      el.detailInstallingBadge.hidden = !installing;
      const label = el.detailInstallingBadge.querySelector(".installing-label");
      if (label) {
        label.textContent = t("game.installing", "Installing");
      }
    }
    el.detailUpdateBadge.textContent = t(
      "game.update_available",
      "Update available",
    );
    el.detailUpdateBadge.hidden =
      installing || downloading || syncing || readyToInstall || !needsUpdate;
    el.detailUpToDateBadge.textContent = t("game.up_to_date", "Up to date");
    el.detailUpToDateBadge.hidden =
      installing ||
      downloading ||
      syncing ||
      readyToInstall ||
      !installed ||
      needsUpdate;
    if (el.detailProviderBadge) {
      el.detailProviderBadge.textContent = t(
        "game.provider_detail_badge",
        "Provider: {provider}",
      ).replace("{provider}", selectedGameProviderLabel());
      el.detailProviderBadge.hidden = false;
    }
  }

  function updateDetailDownloadProgress(showDownloading) {
    if (
      !el.detailDownloadProgress ||
      !el.detailDownloadProgressLabel ||
      !el.detailDownloadProgressValue ||
      !el.detailDownloadProgressTrack ||
      !el.detailDownloadProgressFill
    ) {
      return;
    }
    const progress = Math.max(
      0,
      Math.min(
        100,
        Math.round(Number(state.selectedGameSync?.progress_percent || 0)),
      ),
    );
    el.detailDownloadProgress.hidden = !showDownloading;
    if (!showDownloading) {
      el.detailDownloadProgressValue.textContent = "0%";
      el.detailDownloadProgressFill.style.width = "0%";
      el.detailDownloadProgressTrack.setAttribute("aria-valuenow", "0");
      return;
    }
    const progressLabel = t("sync.item_progress", "Sync progress");
    el.detailDownloadProgressLabel.textContent = progressLabel;
    el.detailDownloadProgressValue.textContent = `${progress}%`;
    el.detailDownloadProgressFill.style.width = `${progress}%`;
    el.detailDownloadProgressTrack.setAttribute("aria-label", progressLabel);
    el.detailDownloadProgressTrack.setAttribute(
      "aria-valuenow",
      String(progress),
    );
  }

  function updateDetailArtworkState() {
    if (!el.detailImage) {
      return;
    }
    const visuallyInstalled =
      isInstalled(state.selectedGame?.install_state) ||
      isReadyToInstall(state.selectedGameSync?.sync_state);
    el.detailImage.classList.toggle("grayscale", !visuallyInstalled);
  }

  function updateInstallPrereqButtonState() {
    if (!el.installPrereqBtn) {
      return;
    }
    const isWindows = state.settings.platform === "windows";
    el.installPrereqBtn.disabled = !isWindows;
    if (el.installWineCommonDepsBtn) {
      const isLinux = state.settings.platform === "linux";
      el.installWineCommonDepsBtn.disabled = !isLinux;
      el.installWineCommonDepsBtn.hidden = !isLinux;
    }
  }

  function updateNetworkModeButtonState() {
    const syncBlocked = !state.settings.library_path_initialized;
    const supported =
      state.settings.platform === "windows" ||
      state.settings.platform === "linux";
    const disabled = syncBlocked || !supported;
    if (el.syncModeLanBtn) {
      el.syncModeLanBtn.disabled = disabled;
    }
    if (el.syncModeInternetBtn) {
      el.syncModeInternetBtn.disabled = disabled;
    }
    if (el.setNetworkPrivateBtn) {
      el.setNetworkPrivateBtn.disabled = state.settings.platform !== "windows";
    }
  }

  function setLaunchConsoleLines(lines = []) {
    if (!el.startGameConsole) {
      return;
    }
    el.startGameConsole.textContent = lines.join("\n").trim();
  }

  function setWizardConsoleLines(lines = []) {
    if (!el.wizardConsole) {
      return;
    }
    el.wizardConsole.textContent = lines.join("\n").trim();
  }

  function appendWizardConsoleLine(line) {
    if (!el.wizardConsole) {
      return;
    }
    const message = String(line || "").trim();
    if (!message) {
      return;
    }
    const existing = el.wizardConsole.textContent
      ? el.wizardConsole.textContent.split("\n")
      : [];
    existing.push(message);
    // Keep the wizard console short and focused on latest setup steps.
    const visible = existing.slice(-12);
    el.wizardConsole.textContent = visible.join("\n");
    el.wizardConsole.scrollTop = el.wizardConsole.scrollHeight;
  }

  function updateStartupScreen() {
    if (!el.startupScreen) {
      return;
    }
    el.startupScreen.hidden = state.backendReady;
    if (el.startupTitle) {
      el.startupTitle.textContent = t(
        "startup.title",
        "Starting LANLauncherNG",
      );
    }
    if (el.startupText) {
      el.startupText.textContent = t(
        "startup.text",
        "Waiting for backend services...",
      );
    }
  }

  function setShutdownUpdateConsoleLines(lines = []) {
    state.shutdownUpdateLines = lines
      .map((line) => String(line || "").trim())
      .filter((line) => line.length > 0)
      .slice(-80);
    if (!el.shutdownUpdateConsole) {
      return;
    }
    el.shutdownUpdateConsole.textContent = state.shutdownUpdateLines.join("\n");
    el.shutdownUpdateConsole.scrollTop = el.shutdownUpdateConsole.scrollHeight;
  }

  function setShutdownUpdateModalVisible(visible) {
    if (!el.shutdownUpdateModal) {
      return;
    }
    el.shutdownUpdateModal.hidden = !visible;
  }

  function setShutdownUpdateConfirmVisible(visible) {
    if (!el.shutdownUpdateConfirmBtn) {
      return;
    }
    el.shutdownUpdateConfirmBtn.hidden = !visible;
    el.shutdownUpdateConfirmBtn.disabled = !visible;
  }

  function setShutdownUpdateRecoveryButtonsVisible(visible) {
    const show = Boolean(visible);
    if (el.shutdownUpdateResumeBtn) {
      el.shutdownUpdateResumeBtn.hidden = !show;
      el.shutdownUpdateResumeBtn.disabled = !show;
    }
    if (el.shutdownUpdateAbortBtn) {
      el.shutdownUpdateAbortBtn.hidden = !show;
      el.shutdownUpdateAbortBtn.disabled = !show;
    }
  }

  function stopShutdownUpdatePolling() {
    if (state.shutdownUpdatePollTimer) {
      window.clearInterval(state.shutdownUpdatePollTimer);
      state.shutdownUpdatePollTimer = 0;
    }
  }

  function stopShutdownUpdateAutoClose() {
    if (state.shutdownUpdateAutoCloseTimer) {
      window.clearInterval(state.shutdownUpdateAutoCloseTimer);
      state.shutdownUpdateAutoCloseTimer = 0;
    }
  }

  function formatTemplate(template, values = {}) {
    let text = String(template || "");
    for (const [key, value] of Object.entries(values)) {
      text = text.replaceAll(`{${key}}`, String(value));
    }
    return text;
  }

  function closeFrontendWindow() {
    attemptWindowClose();
    window.setTimeout(() => {
      attemptWindowClose();
    }, 120);
  }

  function sendShutdownKeepaliveOnWindowClose() {
    if (state.shutdownSignalSent) {
      return;
    }
    state.shutdownSignalSent = true;
    try {
      fetch("/app/shutdown", {
        method: "GET",
        cache: "no-store",
        keepalive: true,
      }).catch(() => {});
    } catch (_err) {
      // Best-effort unload signal only.
    }
  }

  function startShutdownUpdateAutoClose(seconds) {
    const totalSeconds = Math.max(1, Number(seconds) || 0);
    if (!totalSeconds) {
      return;
    }
    stopShutdownUpdatePolling();
    stopShutdownUpdateAutoClose();
    setShutdownUpdateConfirmVisible(false);
    setShutdownUpdateRecoveryButtonsVisible(false);
    let remaining = totalSeconds;
    if (el.shutdownUpdateText) {
      el.shutdownUpdateText.textContent = formatTemplate(
        t(
          "app.shutdown_update_handoff_countdown",
          "Updater launched in a separate window. This frontend will close in {seconds} seconds.",
        ),
        { seconds: remaining },
      );
    }
    state.shutdownUpdateAutoCloseTimer = window.setInterval(() => {
      remaining -= 1;
      if (remaining <= 0) {
        stopShutdownUpdateAutoClose();
        closeFrontendWindow();
        return;
      }
      if (el.shutdownUpdateText) {
        el.shutdownUpdateText.textContent = formatTemplate(
          t(
            "app.shutdown_update_handoff_countdown",
            "Updater launched in a separate window. This frontend will close in {seconds} seconds.",
          ),
          { seconds: remaining },
        );
      }
    }, 1000);
  }

  function formatShutdownUpdateStatus(shutdown) {
    const resultCode = String(shutdown?.updater_result_code || "")
      .trim()
      .toLowerCase();
    const phase = String(shutdown?.updater_phase || shutdown?.phase || "")
      .trim()
      .toLowerCase();
    const status = String(shutdown?.updater_status || "")
      .trim()
      .toLowerCase();
    const detail = String(shutdown?.updater_detail || "")
      .trim()
      .toLowerCase();
    const rollback = Boolean(shutdown?.rollback_performed);
    const exitCodeRaw = Number(shutdown?.updater_exit_code);
    const hasExitCode = Number.isFinite(exitCodeRaw) && exitCodeRaw !== -1;
    const exitCode = hasExitCode ? exitCodeRaw : null;
    const phaseText = t(
      `app.shutdown_update_phase_${phase || "unknown"}`,
      phase || t("app.shutdown_update_phase_unknown", "unknown"),
    );
    const statusText = status
      ? t(`app.shutdown_update_status_${status}`, status)
      : t("app.shutdown_update_status_unknown", "unknown");
    const detailText = detail
      ? t(`app.shutdown_update_detail_${detail}`, detail)
      : "";
    const rollbackText = rollback
      ? t("app.shutdown_update_rollback_yes", "Rollback: yes")
      : t("app.shutdown_update_rollback_no", "Rollback: no");
    const exitCodeText =
      exitCode === null
        ? ""
        : t("app.shutdown_update_exit_code", "Exit code: {code}").replace(
            "{code}",
            String(exitCode),
          );
    const resultText = resultCode
      ? t(`app.shutdown_update_result_${resultCode}`, resultCode)
      : "";
    return [
      resultText,
      phaseText,
      statusText,
      detailText,
      rollbackText,
      exitCodeText,
    ]
      .filter((entry) => String(entry || "").trim().length > 0)
      .join(" | ");
  }

  function setShutdownUpdateStatusText(shutdown) {
    if (!el.shutdownUpdateStatus) {
      return;
    }
    el.shutdownUpdateStatus.textContent = formatShutdownUpdateStatus(shutdown);
  }

  function isInitialSetupComplete() {
    const nickname = String(state.settings.nickname || "").trim();
    return (
      nickname.length > 0 && Boolean(state.settings.library_path_initialized)
    );
  }

  function shouldShowWelcomeWizard() {
    const nickname = String(state.settings.nickname || "").trim();
    return nickname.length === 0 || !state.settings.library_path_initialized;
  }

  function setSettingsCollapsed(collapsed, persist = true) {
    state.settingsCollapsed = Boolean(collapsed);
    if (persist) {
      localStorage.setItem(
        "llng.settings_collapsed",
        state.settingsCollapsed ? "1" : "0",
      );
    }
    if (el.settingsSection) {
      el.settingsSection.classList.toggle("collapsed", state.settingsCollapsed);
    }
    if (el.settingsToggleBtn) {
      el.settingsToggleBtn.textContent = state.settingsCollapsed
        ? t("settings.expand", "Expand")
        : t("settings.collapse", "Collapse");
    }
  }

  function setLogsCollapsed(collapsed, persist = true) {
    state.logsCollapsed = Boolean(collapsed);
    if (persist) {
      localStorage.setItem(
        "llng.logs_collapsed",
        state.logsCollapsed ? "1" : "0",
      );
    }
    if (el.logsOutput) {
      const logsSection = el.logsOutput.closest(
        'section[aria-labelledby="logs-title"]',
      );
      if (logsSection) {
        logsSection.classList.toggle("logs-collapsed", state.logsCollapsed);
      }
    }
    if (el.logsToggleBtn) {
      el.logsToggleBtn.textContent = state.logsCollapsed
        ? t("logs.expand", "Expand")
        : t("logs.collapse", "Collapse");
    }
  }

  function normalizeTabName(raw) {
    const value = String(raw || "").trim().toLowerCase();
    if (["home", "status", "providers", "settings", "logs"].includes(value)) {
      return value;
    }
    return "home";
  }

  function normalizeProviderTabName(raw) {
    const value = String(raw || "").trim().toLowerCase();
    if (value === "ouisync") {
      return value;
    }
    return "resilio";
  }

  function providerInterfaceList() {
    const items = Array.isArray(state.settings.provider_interfaces)
      ? state.settings.provider_interfaces
      : [];
    return items
      .map((item) => {
        const providerType = normalizeProviderTabName(item?.provider_type);
        return {
          provider_type: providerType,
          title: String(item?.title || "").trim(),
          iframe_url: String(item?.iframe_url || "").trim(),
          open_url: String(item?.open_url || "").trim(),
          running: Boolean(item?.running),
          available: Boolean(item?.available),
          state: String(item?.state || "").trim().toLowerCase(),
          pid:
            item?.pid === null || item?.pid === undefined
              ? null
              : Number(item.pid),
          last_error: String(item?.last_error || "").trim(),
        };
      })
      .filter((item) => item.provider_type);
  }

  function providerInterfaceForType(providerType) {
    const normalized = normalizeProviderTabName(providerType);
    return (
      providerInterfaceList().find(
        (item) => item.provider_type === normalized,
      ) || {
        provider_type: normalized,
        title: normalized === "ouisync" ? "Ouisync" : "Resilio",
        iframe_url: "",
        open_url: "",
        running: false,
        available: false,
        state: "stopped",
        pid: null,
        last_error: "",
      }
    );
  }

  function normalizeProviderState(raw) {
    const value = String(raw || "").trim().toLowerCase();
    if (
      [
        "running",
        "starting",
        "stopped",
        "stopping",
        "blocked",
        "failed",
        "disabled",
        "unknown",
      ].includes(value)
    ) {
      return value;
    }
    return "unknown";
  }

  function providerStateLabel(stateName) {
    const normalized = normalizeProviderState(stateName);
    if (normalized === "running") {
      return t("sync.provider_running", "running");
    }
    if (normalized === "starting") {
      return t("sync.provider_starting", "starting");
    }
    if (normalized === "stopping") {
      return t("sync.provider_stopping", "stopping");
    }
    if (normalized === "blocked") {
      return t("sync.provider_blocked", "blocked");
    }
    if (normalized === "failed") {
      return t("sync.provider_failed", "failed");
    }
    if (normalized === "disabled") {
      return t("sync.provider_disabled", "disabled");
    }
    if (normalized === "stopped") {
      return t("sync.provider_stopped", "stopped");
    }
    return t("sync.provider_unknown", "unknown");
  }

  function providerStateClass(stateName) {
    const normalized = normalizeProviderState(stateName);
    if (normalized === "running") {
      return "is-running";
    }
    if (normalized === "starting") {
      return "is-starting";
    }
    if (normalized === "stopping") {
      return "is-stopping";
    }
    if (normalized === "blocked") {
      return "is-blocked";
    }
    if (normalized === "failed") {
      return "is-failed";
    }
    if (normalized === "disabled") {
      return "is-disabled";
    }
    return "is-stopped";
  }

  function providerActionDisabled(provider, action) {
    const stateName = String(provider?.state || "").trim().toLowerCase();
    const running = Boolean(provider?.running);
    if (action === "start") {
      return running || stateName === "starting" || stateName === "stopping";
    }
    if (action === "stop") {
      return stateName === "stopping" || (!running && stateName !== "starting");
    }
    if (action === "restart") {
      return stateName === "stopping";
    }
    return true;
  }

  function setActiveStatusProvider(providerType, persist = true) {
    const normalized = normalizeProviderTabName(providerType);
    state.activeStatusProvider = normalized;
    if (persist) {
      localStorage.setItem("llng.active_status_provider", normalized);
    }
    renderStatusPanel();
  }

  function setActiveTab(tab, persist = true) {
    const normalized = normalizeTabName(tab);
    state.activeTab = normalized;
    if (persist) {
      localStorage.setItem("llng.active_tab", normalized);
    }
    const buttons = [
      [el.tabHomeBtn, "home"],
      [el.tabStatusBtn, "status"],
      [el.tabProvidersBtn, "providers"],
      [el.tabSettingsBtn, "settings"],
      [el.tabLogsBtn, "logs"],
    ];
    for (const [button, buttonTab] of buttons) {
      if (!button) {
        continue;
      }
      button.classList.toggle("is-active", buttonTab === normalized);
      button.setAttribute(
        "aria-selected",
        buttonTab === normalized ? "true" : "false",
      );
    }
    const panels = [
      [el.homePanel, "home"],
      [el.statusPanel, "status"],
      [el.providersPanel, "providers"],
      [el.settingsPanel, "settings"],
      [el.logsPanel, "logs"],
    ];
    for (const [panel, panelTab] of panels) {
      if (!panel) {
        continue;
      }
      panel.hidden = panelTab !== normalized;
    }
    if (normalized === "status") {
      renderStatusPanel();
    }
    if (
      normalized === "settings" &&
      String(state.settings.lan_mode || "").toLowerCase() ===
        "server"
    ) {
      loadLanGameInventory().catch(() => {});
    }
    if (normalized === "settings" && currentLanMode() === "client") {
      scanLanServers().catch(() => {});
    }
    if (normalized === "providers") {
      setActiveProviderTab(state.activeProviderTab, false);
      refreshProviderPanel(true);
    }
  }

  function setActiveProviderTab(providerTab, persist = true) {
    const normalized = normalizeProviderTabName(providerTab);
    state.activeProviderTab = normalized;
    if (persist) {
      localStorage.setItem("llng.active_provider_tab", normalized);
    }
    for (const [providerType, button] of Object.entries(el.providerTabs)) {
      if (!button) {
        continue;
      }
      button.classList.toggle("is-active", providerType === normalized);
      button.setAttribute(
        "aria-selected",
        providerType === normalized ? "true" : "false",
      );
    }
  }

  function renderOuisyncInventory(payload) {
    if (!el.ouisyncInventoryStatus || !el.ouisyncRepositoryList) {
      return;
    }
    const repositories = Array.isArray(payload?.repositories)
      ? payload.repositories
      : [];
    const catalog = Array.isArray(payload?.catalog) ? payload.catalog : [];
    const repositoryByHash = new Map(
      repositories.map((item) => [String(item.info_hash || "").toLowerCase(), item]),
    );
    const network = payload?.network || {};
    const provider = payload?.provider || {};
    if (el.ouisyncHealthSummary) {
      const runtime = provider.running
        ? t("ui.ouisync_runtime_running", "Ouisync process is running")
        : t("ui.ouisync_runtime_stopped", "Ouisync process is stopped");
      el.ouisyncHealthSummary.textContent = `${runtime} · ${repositories.length} ${t("ui.ouisync_repository_count", "repositories")} · ${Number(payload?.connected_peer_count || 0)}/${Number(payload?.peer_count || 0)} ${t("ui.ouisync_peers_active", "active/known peers")} · ${t("ui.ouisync_download", "Download")}: ${formatSpeed(Number(network.throughput_rx || 0))} · ${t("ui.ouisync_upload", "Upload")}: ${formatSpeed(Number(network.throughput_tx || 0))}${provider.last_error ? ` · ${provider.last_error}` : ""}`;
    }
    if (!payload?.available || payload?.error) {
      const error = String(payload?.error || "ouisync_session_unavailable");
      el.ouisyncInventoryStatus.textContent = providerErrorLabel(error) || t(
        "status.ouisync_unavailable",
        "Ouisync repository inventory is unavailable.",
      );
    } else {
      el.ouisyncInventoryStatus.textContent = `${t("ui.ouisync_network", "Ouisync network")}: ${formatSpeed(Number(network.throughput_rx || 0))} ${t("sync.down", "down")} / ${formatSpeed(Number(network.throughput_tx || 0))} ${t("sync.up", "up")}`;
    }

    if (el.ouisyncCatalogList) {
      el.ouisyncCatalogList.replaceChildren();
      if (!catalog.length) {
        const empty = document.createElement("li");
        empty.textContent = t("ui.ouisync_catalog_empty", "No verified Ouisync games are in the local catalog.");
        el.ouisyncCatalogList.append(empty);
      }
      for (const item of catalog) {
        const row = document.createElement("li");
        const title = document.createElement("span");
        title.textContent = String(item.title || item.game_id || "");
        const repository = repositoryByHash.get(String(item.info_hash || "").toLowerCase());
        const stateLabel = document.createElement("small");
        stateLabel.textContent = repository
          ? t("ui.ouisync_repository_present", "Repository available")
          : t("ui.ouisync_repository_not_joined", "Not downloaded");
        row.append(title, stateLabel);
        el.ouisyncCatalogList.append(row);
      }
    }

    el.ouisyncRepositoryList.replaceChildren();
    if (!repositories.length) {
      const empty = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 6;
      cell.className = "ouisync-empty-state";
      cell.textContent = payload?.available
        ? t("ui.ouisync_repositories_empty", "No Ouisync repositories are currently imported.")
        : t("ui.ouisync_inventory_waiting", "Start Ouisync to inspect imported repositories.");
      empty.append(cell);
      el.ouisyncRepositoryList.append(empty);
    }
    for (const repository of repositories) {
      const row = document.createElement("tr");
      row.className = "ouisync-repository-row";
      row.title = String(repository.local_path || "");
      row.classList.toggle(
        "is-selected",
        String(repository.info_hash || "").toLowerCase() === state.ouisyncSelectedRepositoryHash,
      );
      row.addEventListener("click", () => {
        state.ouisyncSelectedRepositoryHash = String(repository.info_hash || "").toLowerCase();
        state.ouisyncDirectoryPath = "/";
        refreshOuisyncInventory(true);
      });
      const cells = [
        String(repository.label || repository.game_id || repository.info_hash || ""),
        `${Number(repository.connected_peer_count ?? payload?.connected_peer_count ?? 0)}/${Number(repository.peer_count ?? payload?.peer_count ?? 0)}`,
        `${Number(repository.local_block_count || 0).toLocaleString()} ${t("ui.ouisync_blocks", "blocks")}`,
        `${Number(repository.repository_block_count || 0).toLocaleString()} ${t("ui.ouisync_blocks", "blocks")}`,
        formatSpeed(Number(repository.throughput_rx || 0)),
        formatSpeed(Number(repository.throughput_tx || 0)),
      ];
      for (const [index, value] of cells.entries()) {
        const cell = document.createElement("td");
        if (index === 0) {
          const name = document.createElement("strong");
          name.textContent = value;
          const nameButton = document.createElement("button");
          nameButton.type = "button";
          nameButton.className = "ouisync-repository-select";
          nameButton.append(name);
          const progress = document.createElement("small");
          const total = Number(repository.repository_block_count || 0);
          const done = Number(repository.local_block_count || 0);
          // 0/0 blocks means no snapshot index has arrived yet, not a finished sync.
          const percent = total > 0 ? Math.min(100, Math.floor(done * 100 / total)) : 0;
          const progressText = repository.content_verified
            ? t("ui.ouisync_content_verified", "content complete (verified)")
            : `${percent}%`;
          progress.textContent = `${repository.sync_enabled ? t("ui.ouisync_syncing", "Sync enabled") : t("ui.ouisync_paused", "Paused")} · ${progressText} · ${done.toLocaleString()}/${total.toLocaleString()} ${t("ui.ouisync_blocks", "blocks")}`;
          if (repository.content_verified) {
            progress.title = t("ui.ouisync_content_verified_hint", "Ouisync's block counter stalled, but every file of the current snapshot was read successfully. The remaining blocks belong to older snapshots.");
          }
          cell.append(nameButton, document.createElement("br"), progress);
        } else {
          cell.textContent = value;
        }
        row.append(cell);
      }
      el.ouisyncRepositoryList.append(row);
    }

    const selected = repositories.find(
      (item) => String(item.info_hash || "").toLowerCase() === state.ouisyncSelectedRepositoryHash,
    );
    const selectedSettings = selected?.settings || {};
    if (el.ouisyncSettingsRepository) {
      el.ouisyncSettingsRepository.textContent = selected
        ? `${t("ui.ouisync_settings_for", "Settings for")}: ${String(selected.game_id || selected.label || selected.info_hash)}`
        : t("ui.ouisync_select_repository", "Select a repository to browse its files.");
    }
    for (const [input, key] of [
      [el.ouisyncSettingDht, "dht_enabled"],
      [el.ouisyncSettingPex, "peer_exchange_enabled"],
      [el.ouisyncSettingCache, "cache_servers_enabled"],
    ]) {
      if (!input) continue;
      input.checked = Boolean(selectedSettings[key]);
      input.disabled = !selected || !selectedSettings.available ||
        (key === "cache_servers_enabled" &&
          (!selectedSettings.cache_servers_writable || selectedSettings.cache_servers_enabled == null));
    }
    if (el.ouisyncSettingsHint) {
      el.ouisyncSettingsHint.textContent = selected && !selectedSettings.cache_servers_writable
        ? t("ui.ouisync_cache_servers_read_only", "Cache server settings require a repository opened with write access.")
        : selected && selectedSettings.available && selectedSettings.cache_servers_enabled == null
          ? t("ui.ouisync_cache_servers_unreachable", "The cache server is unreachable; its setting is unavailable offline.")
        : selected && !selectedSettings.available
          ? t("ui.ouisync_settings_sync_disabled", "Enable repository sync to change DHT and Peer Exchange settings.")
          : "";
    }
    if (el.ouisyncDirectoryList) {
      el.ouisyncDirectoryList.replaceChildren();
      if (!selected) {
        const empty = document.createElement("li");
        empty.textContent = t("ui.ouisync_select_repository", "Select a repository to browse its files.");
        el.ouisyncDirectoryList.append(empty);
      } else if (selected.directory_error) {
        const error = document.createElement("li");
        error.textContent = providerErrorLabel(selected.directory_error) || t("ui.ouisync_directory_unavailable", "Directory contents are unavailable.");
        el.ouisyncDirectoryList.append(error);
      } else if (!selected.entries?.length) {
        const empty = document.createElement("li");
        empty.textContent = t("ui.ouisync_directory_empty", "This directory is empty.");
        el.ouisyncDirectoryList.append(empty);
      } else {
        for (const entry of selected.entries) {
          const row = document.createElement("li");
          const entryContent = document.createElement("span");
          if (entry.type === "directory") {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "ouisync-directory-entry";
            button.textContent = `▸ ${entry.name}`;
            button.addEventListener("click", () => {
              state.ouisyncDirectoryPath = String(entry.path || "/");
              refreshOuisyncInventory(true);
            });
            entryContent.append(button);
          } else {
            entryContent.textContent = `📄 ${String(entry.name || "")}`;
          }
          const copyButton = document.createElement("button");
          copyButton.type = "button";
          copyButton.className = "ouisync-copy-entry";
          copyButton.textContent = t("ui.ouisync_copy_to_disk", "Copy to disk");
          copyButton.title = t("ui.ouisync_copy_to_disk", "Copy to disk");
          copyButton.disabled = !selected.game_id || selected.access_mode === "blind";
          copyButton.addEventListener("click", (event) => {
            event.stopPropagation();
            copyOuisyncRepositoryEntry(entry.path, copyButton);
          });
          row.append(entryContent, copyButton);
          el.ouisyncDirectoryList.append(row);
        }
      }
    }
    if (el.ouisyncDirectoryPath) {
      el.ouisyncDirectoryPath.textContent = selected ? state.ouisyncDirectoryPath : "/";
    }
    if (el.ouisyncDirectoryUp) {
      el.ouisyncDirectoryUp.disabled =
        !selected || state.ouisyncDirectoryPath === "/";
    }
    const mountPath = String(selected?.mount_point || "");
    const readOnlyRepository = selected?.access_mode === "read";
    if (el.ouisyncMountStatus) {
      el.ouisyncMountStatus.textContent = mountPath
        ? `${t("ui.ouisync_mounted_at", "Mounted at")}: ${mountPath}`
        : selected && !readOnlyRepository
          ? t("ui.ouisync_mount_read_only_required", "Mount requires a repository opened with read-only access.")
          : selected
            ? t("ui.ouisync_not_mounted", "Repository is not mounted.")
            : "";
    }
    if (el.ouisyncMountStart) el.ouisyncMountStart.disabled = !selected || !readOnlyRepository || Boolean(mountPath);
    if (el.ouisyncMountStop) el.ouisyncMountStop.disabled = !selected || !mountPath;
    if (el.ouisyncMountForceStop) el.ouisyncMountForceStop.disabled = !selected || !mountPath;
    if (el.ouisyncCopyStatus && !state.ouisyncCopyBusy) el.ouisyncCopyStatus.textContent = "";
    if (el.ouisyncNudgeSync) el.ouisyncNudgeSync.disabled = !selected || state.ouisyncNudgeBusy;
    if (el.ouisyncNudgeStatus && !selected) el.ouisyncNudgeStatus.textContent = "";
    renderOuisyncPeers(payload, Boolean(selected));
  }

  function formatBytes(value) {
    const units = ["B", "KB", "MB", "GB", "TB"];
    let amount = Math.max(0, Number(value || 0));
    let unit = 0;
    while (amount >= 1024 && unit < units.length - 1) {
      amount /= 1024;
      unit += 1;
    }
    return `${amount.toLocaleString(undefined, { maximumFractionDigits: unit ? 1 : 0 })} ${units[unit]}`;
  }

  function renderOuisyncPeers(payload, repositorySelected) {
    if (!el.ouisyncPeersCard || !el.ouisyncPeerList) return;
    // Peers are session-wide in Ouisync; show them once a repository is selected.
    el.ouisyncPeersCard.hidden = !repositorySelected;
    if (!repositorySelected) return;
    const peers = Array.isArray(payload?.peers) ? payload.peers : [];
    const stateOrder = { active: 0, handshaking: 1, connecting: 2, known: 3 };
    peers.sort((a, b) =>
      (stateOrder[a.state] ?? 4) - (stateOrder[b.state] ?? 4) ||
      String(a.addr || "").localeCompare(String(b.addr || "")));
    el.ouisyncPeerList.replaceChildren();
    if (!peers.length) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 8;
      cell.textContent = t("ui.ouisync_peers_empty", "No peers are known yet.");
      row.append(cell);
      el.ouisyncPeerList.append(row);
    }
    for (const peer of peers) {
      const row = document.createElement("tr");
      const protocol = String(peer.protocol || "").toUpperCase();
      const values = [
        protocol ? `${String(peer.address || "")} (${protocol})` : String(peer.addr || ""),
        t(`ui.ouisync_peer_source_${peer.source}`, String(peer.source || "")),
        t(`ui.ouisync_peer_state_${peer.state}`, String(peer.state || "")),
        formatSpeed(Number(peer.throughput_rx || 0)),
        formatSpeed(Number(peer.throughput_tx || 0)),
        formatBytes(peer.bytes_rx),
        formatBytes(peer.bytes_tx),
      ];
      for (const value of values) {
        const cell = document.createElement("td");
        cell.textContent = value;
        row.append(cell);
      }
      const actionCell = document.createElement("td");
      if (peer.user_provided) {
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "ouisync-peer-remove";
        remove.textContent = t("ui.ouisync_peer_remove", "Remove");
        remove.addEventListener("click", () => runOuisyncPeerAction("remove", String(peer.addr || ""), remove));
        actionCell.append(remove);
      }
      row.append(actionCell);
      el.ouisyncPeerList.append(row);
    }
    if (el.ouisyncPeerListeners) {
      const listeners = Array.isArray(payload?.listener_addrs) ? payload.listener_addrs : [];
      el.ouisyncPeerListeners.textContent = listeners.length
        ? `${t("ui.ouisync_peer_listeners", "This device listens on")}: ${listeners.join(", ")} · ${t("ui.ouisync_peer_listeners_hint", "On another device, add this device's LAN IP address with this port.")}`
        : "";
    }
  }

  async function nudgeOuisyncRepository() {
    if (!state.ouisyncSelectedRepositoryHash || state.ouisyncNudgeBusy) return;
    state.ouisyncNudgeBusy = true;
    if (el.ouisyncNudgeSync) el.ouisyncNudgeSync.disabled = true;
    if (el.ouisyncNudgeStatus) el.ouisyncNudgeStatus.textContent = t("ui.ouisync_nudge_working", "Nudging repository sync…");
    try {
      const response = await apiPost("/sync/providers/ouisync/repository-action", {
        action: "nudge",
        info_hash: state.ouisyncSelectedRepositoryHash,
      });
      const result = response?.result || {};
      if (!result.ok) throw new Error(result.message || "ouisync_repository_nudge_failed");
      const actions = (Array.isArray(result.actions) ? result.actions : [])
        .map((action) => t(`ui.ouisync_nudge_action_${action}`, action));
      if (el.ouisyncNudgeStatus) {
        el.ouisyncNudgeStatus.textContent = `${t("ui.ouisync_nudge_done", "Sync nudged")}: ${actions.join(", ") || "-"}`;
      }
    } catch (error) {
      if (el.ouisyncNudgeStatus) {
        el.ouisyncNudgeStatus.textContent = `${t("ui.ouisync_nudge_failed", "Could not nudge sync")}: ${providerErrorLabel(String(error?.message || error)) || String(error?.message || error)}`;
      }
    } finally {
      state.ouisyncNudgeBusy = false;
      await refreshOuisyncInventory(true);
    }
  }

  async function runOuisyncPeerAction(action, address, button) {
    if (!address) return;
    if (button) button.disabled = true;
    if (el.ouisyncPeerStatus) el.ouisyncPeerStatus.textContent = t("ui.ouisync_peer_working", "Updating peers…");
    try {
      const response = await apiPost("/sync/providers/ouisync/peers", { action, address });
      const result = response?.result || {};
      if (!result.ok) throw new Error(result.message || "ouisync_peer_action_failed");
      if (el.ouisyncPeerStatus) {
        el.ouisyncPeerStatus.textContent = `${t(action === "add" ? "ui.ouisync_peer_added" : "ui.ouisync_peer_removed", action === "add" ? "Peer added" : "Peer removed")}: ${result.address || address}`;
      }
      if (action === "add" && el.ouisyncPeerAddInput) el.ouisyncPeerAddInput.value = "";
    } catch (error) {
      if (el.ouisyncPeerStatus) {
        el.ouisyncPeerStatus.textContent = `${t("ui.ouisync_peer_action_failed", "Peer update failed")}: ${providerErrorLabel(String(error?.message || error)) || String(error?.message || error)}`;
      }
    } finally {
      if (button) button.disabled = false;
      await refreshOuisyncInventory(true);
    }
  }

  async function refreshOuisyncInventory(force = false) {
    if (!el.ouisyncNativePanel || el.ouisyncNativePanel.hidden) {
      return;
    }
    if (state.ouisyncInventoryLoading) {
      state.ouisyncInventoryRefreshPending =
        state.ouisyncInventoryRefreshPending || force;
      return;
    }
    if (!force && Date.now() - state.ouisyncInventoryLastRefresh < 5000) {
      return;
    }
    state.ouisyncInventoryLoading = true;
    state.ouisyncInventoryLastRefresh = Date.now();
    try {
      const query = new URLSearchParams({ locale: state.locale || "en" });
      if (state.ouisyncSelectedRepositoryHash) {
        query.set("info_hash", state.ouisyncSelectedRepositoryHash);
        query.set("path", state.ouisyncDirectoryPath || "/");
      }
      const payload = await apiGet(`/sync/providers/ouisync/repositories?${query.toString()}`);
      renderOuisyncInventory(payload);
    } catch (error) {
      renderOuisyncInventory({
        available: false,
        error: String(error?.message || "ouisync_session_unavailable"),
        repositories: [],
        catalog: [],
        network: {},
      });
    } finally {
      state.ouisyncInventoryLoading = false;
      if (state.ouisyncInventoryRefreshPending) {
        state.ouisyncInventoryRefreshPending = false;
        refreshOuisyncInventory(true);
      }
    }
  }

  async function updateOuisyncRepositorySetting(key, value, input) {
    if (!state.ouisyncSelectedRepositoryHash || !input) return;
    input.disabled = true;
    if (el.ouisyncSettingsHint) {
      el.ouisyncSettingsHint.textContent = t("ui.ouisync_settings_saving", "Saving repository settings…");
    }
    try {
      const response = await apiPost("/sync/providers/ouisync/settings", {
        info_hash: state.ouisyncSelectedRepositoryHash,
        settings: { [key]: value },
      });
      const result = response?.result || {};
      if (!result.ok) throw new Error(result.message || "ouisync_repository_settings_update_failed");
      if (el.ouisyncSettingsHint) {
        el.ouisyncSettingsHint.textContent = t("ui.ouisync_settings_saved", "Repository setting updated.");
      }
      await refreshOuisyncInventory(true);
    } catch (error) {
      if (el.ouisyncSettingsHint) {
        el.ouisyncSettingsHint.textContent = `${t("ui.ouisync_settings_failed", "Could not update repository setting")}: ${providerErrorLabel(String(error?.message || error)) || String(error?.message || error)}`;
      }
      await refreshOuisyncInventory(true);
    }
  }

  async function runOuisyncMountAction(action) {
    if (!state.ouisyncSelectedRepositoryHash) return;
    if (action === "force-unmount" && !window.confirm(t("ui.ouisync_force_unmount_confirm", "This restarts Ouisync and briefly interrupts synchronization to release open mount handles. Continue?"))) return;
    for (const button of [el.ouisyncMountStart, el.ouisyncMountStop, el.ouisyncMountForceStop]) {
      if (button) button.disabled = true;
    }
    if (el.ouisyncMountStatus) el.ouisyncMountStatus.textContent = t("ui.ouisync_mount_working", "Applying mount action…");
    try {
      const response = await apiPost("/sync/providers/ouisync/repository-action", {
        action,
        info_hash: state.ouisyncSelectedRepositoryHash,
      });
      const result = response?.result || {};
      if (!result.ok) throw new Error(result.message || "ouisync_mount_action_failed");
      await refreshOuisyncInventory(true);
    } catch (error) {
      if (el.ouisyncMountStatus) el.ouisyncMountStatus.textContent = providerErrorLabel(String(error?.message || error)) || String(error?.message || error);
      await refreshOuisyncInventory(true);
    }
  }

  async function copyOuisyncRepositoryEntry(entryPath, button) {
    if (!state.ouisyncSelectedRepositoryHash || !button) return;
    state.ouisyncCopyBusy = true;
    button.disabled = true;
    if (el.ouisyncCopyStatus) el.ouisyncCopyStatus.textContent = t("ui.ouisync_copying", "Copying repository entry to disk…");
    try {
      const response = await apiPost("/sync/providers/ouisync/copy-entry", {
        info_hash: state.ouisyncSelectedRepositoryHash,
        path: entryPath,
        destination_directory: el.ouisyncCopyTarget?.value || ".",
      });
      const result = response?.result || {};
      if (!result.ok) throw new Error(result.message || "ouisync_repository_entry_copy_failed");
      if (el.ouisyncCopyStatus) el.ouisyncCopyStatus.textContent = `${t("ui.ouisync_copied_to", "Copied to")}: ${result.destination || ""}`;
    } catch (error) {
      if (el.ouisyncCopyStatus) el.ouisyncCopyStatus.textContent = `${t("ui.ouisync_copy_failed", "Copy failed")}: ${providerErrorLabel(String(error?.message || error)) || String(error?.message || error)}`;
    } finally {
      state.ouisyncCopyBusy = false;
      button.disabled = false;
    }
  }

  async function runOuisyncDebugAction(action) {
    if (!el.ouisyncDebugModal || !el.ouisyncDebugLog) return;
    const labels = {
      health: t("ui.ouisync_debug_health_title", "Checking Ouisync"),
      "ng-provider": t("ui.ouisync_debug_seed_title", "Checking ng_provider"),
      "reset-ng-provider": t("ui.ouisync_debug_reset_title", "Resetting ng_provider"),
    };
    el.ouisyncDebugLog.textContent = `${labels[action] || action}…\n`;
    if (!el.ouisyncDebugModal.open) el.ouisyncDebugModal.showModal();
    const buttons = [el.ouisyncDebugHealth, el.ouisyncDebugSeed, el.ouisyncResetSeed];
    buttons.forEach((button) => { if (button) button.disabled = true; });
    const seenProviderLines = new Set();
    const providerLogTimer = window.setInterval(async () => {
      try {
        const payload = await apiGet("/debug/log?limit=30");
        const entries = payload?.logs?.providers || payload?.logs?.sync || [];
        for (const entry of entries) {
          const message = String(entry?.msg || entry?.message || "").trim();
          if (!message || seenProviderLines.has(message)) continue;
          seenProviderLines.add(message);
          el.ouisyncDebugLog.textContent += `${t("ui.ouisync_debug_provider_log", "Ouisync log")}: ${message}\n`;
          el.ouisyncDebugLog.scrollTop = el.ouisyncDebugLog.scrollHeight;
        }
      } catch (_error) {
        // Keep the action modal usable when provider logs are temporarily unavailable.
      }
    }, 500);
    try {
      const response = await fetch("/sync/providers/ouisync/debug", {
        method: "POST",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      const payload = await response.json();
      const result = payload?.result || {};
      const lines = Array.isArray(result.lines) ? result.lines : [];
      for (const line of lines) {
        const label = t(String(line.key || ""), String(line.key || ""));
        let value = String(line.value || "");
        if (value === "true") value = t("ui.yes", "yes");
        else if (value === "false") value = t("ui.no", "no");
        else if (value === "present") value = t("ui.ouisync_present", "present");
        else if (value === "missing") value = t("ui.ouisync_missing", "missing");
        else if (value === "connected") value = t("ui.ouisync_connected", "connected");
        else if (value === "unavailable") value = t("ui.ouisync_unavailable", "unavailable");
        else if (value === "available") value = t("ui.ouisync_available", "available");
        else if (value.startsWith("ui.")) value = t(value, value);
        const lineState = String(line.state || "");
        if (lineState === "present") value += ` (${t("ui.ouisync_present", "present")})`;
        else if (lineState === "missing") value += ` (${t("ui.ouisync_missing", "missing")})`;
        el.ouisyncDebugLog.textContent += `${label}${value ? `: ${value}` : ""}\n`;
        el.ouisyncDebugLog.scrollTop = el.ouisyncDebugLog.scrollHeight;
      }
      const outcome = response.ok && result.ok
        ? t("ui.ouisync_debug_complete", "Completed successfully.")
        : `${t("ui.ouisync_debug_failed", "Check failed")}: ${result.message || `HTTP ${response.status}`}`;
      el.ouisyncDebugLog.textContent += `${outcome}\n`;
      if (action === "reset-ng-provider") refreshOuisyncInventory(true);
    } catch (error) {
      el.ouisyncDebugLog.textContent += `${t("ui.ouisync_debug_request_failed", "Request failed")}: ${String(error?.message || error)}\n`;
    } finally {
      window.clearInterval(providerLogTimer);
      buttons.forEach((button) => { if (button) button.disabled = false; });
    }
  }

  function refreshProviderPanel(navigateIframe = false) {
    if (!el.providerFrameStatus) {
      return;
    }
    const isOuisync = state.activeProviderTab === "ouisync";
    if (el.ouisyncNativePanel) {
      el.ouisyncNativePanel.hidden = !isOuisync;
    }
    if (el.providerIframe) {
      el.providerIframe.hidden = isOuisync;
    }
    el.providerFrameStatus.hidden = isOuisync;
    if (isOuisync) {
      refreshOuisyncInventory();
      if (el.providerOpenExternalBtn) {
        el.providerOpenExternalBtn.disabled = true;
        el.providerOpenExternalBtn.dataset.url = "";
      }
      return;
    }
    if (!el.providerIframe) {
      return;
    }
    const provider = providerInterfaceForType(state.activeProviderTab);
    const title = provider.title || (provider.provider_type === "ouisync" ? "Ouisync" : "Resilio");
    const iframeUrl = provider.iframe_url || "";
    const openUrl = provider.open_url || iframeUrl;
    const runningText = providerStateLabel(provider.state);
    el.providerFrameStatus.textContent = `${title}: ${runningText}. ${t("ui.provider_embed_hint", "If the embedded view is blocked, open the provider externally.")}`;
    el.providerIframe.title = title;
    const currentProvider = el.providerIframe.dataset.providerType || "";
    const currentUrl = el.providerIframe.dataset.currentUrl || "";
    const shouldNavigate =
      navigateIframe ||
      currentProvider !== state.activeProviderTab ||
      (!currentUrl && Boolean(iframeUrl));
    if (shouldNavigate) {
      // Background status polling must never navigate the iframe: embedded
      // provider menus, scroll position, and expanded panels stay untouched.
      el.providerIframe.src = iframeUrl || "about:blank";
      el.providerIframe.dataset.currentUrl = iframeUrl || "";
      el.providerIframe.dataset.providerType = state.activeProviderTab;
    }
    if (el.providerOpenExternalBtn) {
      el.providerOpenExternalBtn.disabled = !openUrl;
      el.providerOpenExternalBtn.dataset.url = openUrl;
    }
  }

  function openActiveProviderExternally() {
    const provider = providerInterfaceForType(state.activeProviderTab);
    const url = provider.open_url || provider.iframe_url || "";
    if (url) {
      window.open(url, "_blank", "noopener,noreferrer");
    }
  }

  function openProvidersTab(providerType = state.activeProviderTab) {
    setActiveTab("providers");
    setActiveProviderTab(providerType);
    refreshProviderPanel(true);
  }

  async function loadLanGameInventory({
    serverRolePreview = false,
    showLoading = false,
  } = {}) {
    if (showLoading) {
      state.lanGameInventory = {
        ...state.lanGameInventory,
        folders: [],
        message: "loading",
      };
      renderLanGameSharePanel();
    }
    try {
      const suffix = serverRolePreview ? "?role=server" : "";
      const payload = await apiGet(`/lan/games${suffix}`);
      const inventory = payload?.lan || {};
      state.lanGameInventory = {
        root_path: String(inventory.root_path || ""),
        folders: Array.isArray(inventory.folders) ? inventory.folders : [],
        message: String(inventory.message || ""),
      };
    } catch (_err) {
      state.lanGameInventory = {
        root_path: "",
        folders: [],
      };
    }
    renderLanGameSharePanel();
  }

  function currentLanMode() {
    return String(
      el.lanModeSelect?.value ||
        state.settings.lan_mode ||
        "client",
    )
      .trim()
      .toLowerCase();
  }

  let lanDiscoveryGeneration = 0;
  let lanPairGeneration = 0;
  let lanServers = [];
  let lanPairExpiryTimer = 0;

  function renderLanDiscoveryVisibility() {
    if (!el.lanDiscoverySection) return;
    const client = currentLanMode() === "client";
    el.lanDiscoverySection.hidden = !client;
    el.lanPairServerSection.hidden = client;
    lanPairGeneration += 1;
    clearTimeout(lanPairExpiryTimer);
    el.lanPairServerStatus.textContent = "";
    el.lanPairBegin.disabled = false;
    el.lanPairRenew.disabled = false;
    el.lanPairConnect.disabled = !client || lanServers.length === 0;
    if (!client) {
      lanDiscoveryGeneration += 1;
      el.lanDiscoveryScan.disabled = false;
      el.lanPairCode.value = "";
      el.lanPairStatus.textContent = "";
    }
    renderLanServerSettingsVisibility();
  }

  function renderLanServerSettingsVisibility() {
    if (!el.lanServerSettingsSection) return;
    const visible = currentLanMode() === "server";
    el.lanServerSettingsSection.hidden = !visible;
    if (visible && !state.lanServerSettings.settings) {
      loadLanServerSettings().catch(() => {});
    }
  }

  function renderLanServerSettings() {
    const settings = state.lanServerSettings.settings || {};
    el.lanServerTitle.value = String(settings.lan_title || "");
    el.lanServerUrl.value = String(settings.lan_url || "");
    el.lanServerStatsUrl.value = String(settings.stats_url || "");
    el.lanServerDiscordUrl.value = String(settings.discord_url || "");
    el.lanServerTs3Server.value = String(settings.ts3_server || "");
    const configuredLinks = new Map(
      (Array.isArray(settings.links) ? settings.links : []).map((item) => [
        String(item?.key || ""),
        item,
      ]),
    );
    el.lanServerLinksList.replaceChildren();
    for (let index = 1; index <= 5; index += 1) {
      const key = `link_${index}`;
      const configured = configuredLinks.get(key) || {};
      const row = document.createElement("div");
      row.className = "lan-server-link-row";
      const label = document.createElement("label");
      label.textContent = t("settings.lan_server_link_label", "Link {n} label").replace("{n}", String(index));
      label.dataset.linkLabelText = key;
      const labelInput = document.createElement("input");
      labelInput.type = "text";
      labelInput.maxLength = 128;
      labelInput.dataset.linkLabel = key;
      labelInput.value = String(configured.label || "");
      label.append(labelInput);
      const urlLabel = document.createElement("label");
      urlLabel.textContent = t("settings.lan_server_link_url", "Link {n} URL").replace("{n}", String(index));
      urlLabel.dataset.linkUrlText = key;
      const urlInput = document.createElement("input");
      urlInput.type = "url";
      urlInput.maxLength = 2048;
      urlInput.dataset.linkUrl = key;
      urlInput.value = String(configured.url || "");
      urlLabel.append(urlInput);
      row.append(label, urlLabel);
      el.lanServerLinksList.append(row);
    }
    const disabled = new Set(
      (Array.isArray(settings.disable_games) ? settings.disable_games : []).map((id) => String(id).toLowerCase()),
    );
    el.lanServerAssetsList.replaceChildren();
    for (const asset of state.lanServerSettings.assets) {
      const gameId = String(asset?.game_id || "").trim();
      if (!gameId) continue;
      const label = document.createElement("label");
      label.className = "inline-check lan-server-asset";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.dataset.gameId = gameId;
      checkbox.checked = !disabled.has(gameId.toLowerCase());
      const title = document.createElement("span");
      title.textContent = localizedText(
        { en: asset?.title_en, de: asset?.title_de },
        state.locale,
      ) || gameId;
      label.append(checkbox, title);
      el.lanServerAssetsList.append(label);
    }
    el.lanServerSettingsSave.classList.remove("is-dirty");
  }

  async function loadLanServerSettings() {
    if (currentLanMode() !== "server") return;
    el.lanServerSettingsStatus.textContent = t("settings.lan_server_loading", "Loading LAN server settings...");
    try {
      const payload = await apiGet("/settings/lan-server");
      const result = payload?.result || {};
      if (!result.ok) throw new Error(String(result.message || "lan_server_settings_unavailable"));
      state.lanServerSettings = {
        settings: result.settings || {},
        assets: Array.isArray(result.assets) ? result.assets : [],
      };
      renderLanServerSettings();
      el.lanServerSettingsStatus.textContent = "";
    } catch (_err) {
      el.lanServerSettingsStatus.textContent = t("settings.lan_server_load_failed", "Could not load LAN server settings.");
    }
  }

  async function saveLanServerSettings() {
    if (currentLanMode() !== "server") return;
    if (String(state.settings.lan_mode || "client").toLowerCase() !== "server") {
      el.lanServerSettingsStatus.textContent = t("settings.lan_server_save_server_first", "Save Server mode before publishing these settings.");
      return;
    }
    const links = [];
    for (let index = 1; index <= 5; index += 1) {
      const key = `link_${index}`;
      const url = String(el.lanServerLinksList.querySelector(`[data-link-url="${key}"]`)?.value || "").trim();
      if (!url) continue;
      const label = String(el.lanServerLinksList.querySelector(`[data-link-label="${key}"]`)?.value || "").trim() || `Link ${index}`;
      links.push({ key, label, url });
    }
    const disabled = Array.from(el.lanServerAssetsList.querySelectorAll("input[data-game-id]"))
      .filter((checkbox) => !checkbox.checked)
      .map((checkbox) => checkbox.dataset.gameId);
    el.lanServerSettingsSave.disabled = true;
    el.lanServerSettingsStatus.textContent = t("settings.lan_server_saving", "Saving and sharing LAN server settings...");
    try {
      const payload = await apiPost("/settings/lan-server", {
        lan_title: String(el.lanServerTitle.value || "").trim(),
        lan_url: String(el.lanServerUrl.value || "").trim(),
        stats_url: String(el.lanServerStatsUrl.value || "").trim(),
        discord_url: String(el.lanServerDiscordUrl.value || "").trim(),
        ts3_server: String(el.lanServerTs3Server.value || "").trim(),
        links,
        disable_games: disabled,
      });
      const result = payload?.result || {};
      if (!result.ok) throw new Error(String(result.message || "lan_settings_save_failed"));
      state.lanServerSettings.settings = result.settings || {};
      el.lanServerSettingsSave.classList.remove("is-dirty");
      el.lanServerSettingsStatus.textContent = t("settings.lan_server_saved", "LAN server settings saved and shared.");
      await loadLauncherSite();
    } catch (_err) {
      el.lanServerSettingsStatus.textContent = t("settings.lan_server_save_failed", "Could not save LAN server settings. Check the URLs and try again.");
    } finally {
      el.lanServerSettingsSave.disabled = false;
    }
  }

  async function scanLanServers() {
    if (!el.lanDiscoverySection || currentLanMode() !== "client") return;
    const generation = ++lanDiscoveryGeneration;
    lanServers = [];
    el.lanServerSelect.replaceChildren();
    el.lanServerSelect.disabled = true;
    el.lanPairConnect.disabled = true;
    if (String(state.settings.lan_mode || "client").toLowerCase() !== "client") {
      el.lanDiscoveryScan.disabled = false;
      el.lanDiscoveryStatus.textContent = t("settings.lan_discovery_save_first", "Save client mode before searching.");
      return;
    }
    el.lanDiscoveryScan.disabled = true;
    el.lanDiscoveryStatus.textContent = t("settings.lan_discovery_searching", "Searching for LAN servers...");
    try {
      const payload = await apiPost("/lan/games", {
        action: "discover_servers",
        address: el.lanDiscoveryAddress.value.trim(),
      });
      if (generation !== lanDiscoveryGeneration) return;
      lanServers = Array.isArray(payload?.result?.servers) ? payload.result.servers : [];
      for (const [index, server] of lanServers.entries()) {
        const item = document.createElement("option");
        item.value = String(index);
        item.textContent = `${server.name} — ${server.address} (${server.device_id})`;
        el.lanServerSelect.append(item);
      }
      el.lanServerSelect.disabled = lanServers.length === 0;
      el.lanPairConnect.disabled = lanServers.length === 0;
      el.lanDiscoveryStatus.textContent = lanServers.length
        ? t("settings.lan_discovery_found", "Select a server and enter its approval code.")
        : t("settings.lan_discovery_empty", "No LAN servers found. Try an IPv4 address.");
    } catch (_err) {
      if (generation === lanDiscoveryGeneration) {
        el.lanDiscoveryStatus.textContent = t("settings.lan_discovery_failed", "Server search failed. Check the IPv4 address and network.");
      }
    } finally {
      if (generation === lanDiscoveryGeneration) el.lanDiscoveryScan.disabled = false;
    }
  }

  async function beginLanPairing(renew = false) {
    if (currentLanMode() !== "server") return;
    const generation = ++lanPairGeneration;
    clearTimeout(lanPairExpiryTimer);
    el.lanPairServerStatus.textContent = "";
    if (String(state.settings.lan_mode || "client").toLowerCase() !== "server") {
      el.lanPairServerStatus.textContent = t("settings.lan_pair_save_server", "Save server mode first.");
      return;
    }
    const button = renew ? el.lanPairRenew : el.lanPairBegin;
    button.disabled = true;
    try {
      const payload = await apiPost("/lan/games", {
        action: renew ? "renew_pairing" : "begin_pairing",
      });
      if (generation !== lanPairGeneration) return;
      const code = String(payload?.result?.code || "");
      if (!/^[0-9]{4}$/.test(code)) throw new Error("invalid code");
      const seconds = Number(payload?.result?.expires_in);
      if (!Number.isFinite(seconds) || seconds <= 0 || seconds > 259200) throw new Error("invalid expiry");
      const expires = new Date(Date.now() + seconds * 1000).toLocaleString(state.locale);
      el.lanPairServerStatus.textContent = `${t("settings.lan_pair_show_code", "Approval code")}: ${code} — ${t("settings.lan_pair_valid_until", "Valid until")}: ${expires}`;
      lanPairExpiryTimer = setTimeout(() => {
        if (generation === lanPairGeneration) el.lanPairServerStatus.textContent = t("settings.lan_pair_expired", "Approval code expired.");
      }, seconds * 1000);
    } catch (_err) {
      if (generation === lanPairGeneration) el.lanPairServerStatus.textContent = t("settings.lan_pair_begin_failed", "Could not create a code. Check that Ouisync is running.");
    } finally {
      if (generation === lanPairGeneration) button.disabled = false;
    }
  }

  async function renewLanPairing() {
    return beginLanPairing(true);
  }

  async function connectLanServer() {
    if (currentLanMode() !== "client") return;
    const server = lanServers[Number(el.lanServerSelect.value)];
    const code = el.lanPairCode.value.trim();
    if (!server || !/^[0-9]{4}$/.test(code)) {
      el.lanPairStatus.textContent = t("settings.lan_pair_invalid", "Select a server and enter its four-digit code.");
      return;
    }
    const generation = ++lanPairGeneration;
    el.lanPairConnect.disabled = true;
    el.lanDiscoveryScan.disabled = true;
    el.lanPairStatus.textContent = t("settings.lan_pair_connecting", "Connecting to server...");
    try {
      await apiPost("/lan/games", {
        action: "pair_server", address: server.address, device_id: server.device_id, tcp_port: server.tcp_port, code,
      });
      if (generation !== lanPairGeneration) return;
      el.lanPairCode.value = "";
      el.lanPairStatus.textContent = t("settings.lan_pair_success", "Server connected. The local game catalog will sync automatically.");
    } catch (_err) {
      if (generation === lanPairGeneration) el.lanPairStatus.textContent = t("settings.lan_pair_failed", "Connection failed. Check the code, server and Ouisync status.");
    } finally {
      if (generation === lanPairGeneration) {
        el.lanPairConnect.disabled = lanServers.length === 0;
        el.lanDiscoveryScan.disabled = false;
      }
    }
  }

  async function onLanGameShareToggle(folder, shared, button) {
    if (!button) {
      return;
    }
    button.disabled = true;
    button.classList.add("is-loading");
    button.setAttribute("aria-busy", "true");
    try {
      const payload = await apiPost("/lan/games", {
        folder_path: String(folder?.path || ""),
        shared,
      });
      const inventory = payload?.result?.lan || payload?.lan || {};
      state.lanGameInventory = {
        root_path: String(inventory.root_path || ""),
        folders: Array.isArray(inventory.folders) ? inventory.folders : [],
        message: String(inventory.message || ""),
      };
      if (el.statusLanGamesStatus) {
        el.statusLanGamesStatus.textContent = t(
          "status.lan_game_updated",
          "LAN game selection updated.",
        );
      }
      renderStatusPanel();
    } catch (err) {
      const backendMessage = String(err?.message || "error");
      if (el.statusLanGamesStatus) {
        el.statusLanGamesStatus.textContent = `${t(
          "status.lan_game_update_failed",
          "LAN game selection could not be updated.",
        )} (${t(`status.error_${backendMessage}`, backendMessage)})`;
      }
    } finally {
      button.classList.remove("is-loading");
      button.setAttribute("aria-busy", "false");
      button.disabled = false;
    }
  }

  function renderTopProviderBadges() {
    if (!el.topProviderBadges) {
      return;
    }
    const providers = providerInterfaceList();
    el.topProviderBadges.innerHTML = "";
    if (!providers.length) {
      const placeholder = document.createElement("span");
      placeholder.className = "provider-badge provider-badge-empty";
      placeholder.textContent = t(
        "status.providers_unavailable",
        "Sync providers unavailable",
      );
      el.topProviderBadges.append(placeholder);
      return;
    }
    for (const provider of providers) {
      const badge = document.createElement("button");
      badge.type = "button";
      badge.className = `provider-badge ${providerStateClass(provider.state)}`;
      badge.title = provider.last_error
        ? `${provider.title || provider.provider_type}: ${providerStateLabel(provider.state)} | ${providerErrorLabel(provider.last_error)}`
        : `${provider.title || provider.provider_type}: ${providerStateLabel(provider.state)}`;
      badge.dataset.providerType = provider.provider_type;
      badge.innerHTML = "";

      const title = document.createElement("span");
      title.className = "provider-badge-title";
      title.textContent = provider.title || provider.provider_type;

      const state = document.createElement("span");
      state.className = "provider-badge-state";
      state.textContent = providerStateLabel(provider.state);

      badge.append(title, state);
      badge.addEventListener("click", () => {
        setActiveStatusProvider(provider.provider_type);
        setActiveTab("status");
      });
      el.topProviderBadges.append(badge);
    }
  }

  function renderStatusPanel() {
    if (!el.statusOverview || !el.statusProviderList) {
      return;
    }
    const providers = providerInterfaceList();
    const overall = state.syncStatus || {
      provider: "none",
      running: false,
      state: "disabled",
      pid: null,
      last_error: "",
    };
    const download = formatSpeed(state.topTrafficSample?.download_bps || 0);
    const upload = formatSpeed(state.topTrafficSample?.upload_bps || 0);
    const disk = formatSpeed(state.topTrafficSample?.disk_total_bps || 0);
    const runningCount = providers.filter((item) => item.running).length;
    const availableCount = providers.filter((item) => item.available).length;
    const activeProvider = providerInterfaceForType(state.activeStatusProvider);
    const providerPid = (providerType) => {
      const pid = providers.find((item) => item.provider_type === providerType)?.pid;
      return pid === null || pid === undefined || !Number.isFinite(pid)
        ? "-"
        : String(pid);
    };

    el.statusOverview.innerHTML = "";
    const overviewCards = [
      {
        label: t("status.overall_title", "Overall sync service"),
        value: providerStateLabel(overall.state),
        meta: [
          `${t("status.provider_name", "Provider")}: ${overall.provider || "-"}`,
          `${t("status.running", "Running")}: ${overall.running ? t("ui.yes", "yes") : t("ui.no", "no")}`,
          `${t("status.resilio_pid", "Resilio PID")}: ${providerPid("resilio")}`,
          `${t("status.ouisync_pid", "Ouisync PID")}: ${providerPid("ouisync")}`,
          `${t("status.last_error", "Last error")}: ${providerErrorLabel(overall.last_error) || t("status.no_error", "none")}`,
        ],
      },
      {
        label: t("status.traffic_title", "Global traffic"),
        value: `${download} / ${upload}`,
        meta: [
          `${t("status.disk_total", "Disk")}: ${disk}`,
          `${t("status.provider_game", "Selected provider")}: ${activeProvider.title || activeProvider.provider_type}`,
        ],
      },
      {
        label: t("status.providers_title", "Providers"),
        value: `${runningCount}/${providers.length || 0}`,
        meta: [
          `${t("status.available", "Available")}: ${availableCount}/${providers.length || 0}`,
          `${t("status.active_provider", "Focused")}: ${activeProvider.title || activeProvider.provider_type}`,
        ],
      },
    ];
    for (const cardInfo of overviewCards) {
      const card = document.createElement("article");
      card.className = "status-card status-card-overview";
      const heading = document.createElement("h3");
      heading.textContent = cardInfo.label;
      const value = document.createElement("div");
      value.className = "status-card-value";
      value.textContent = cardInfo.value;
      const meta = document.createElement("ul");
      meta.className = "status-card-meta";
      for (const line of cardInfo.meta) {
        const item = document.createElement("li");
        item.textContent = line;
        meta.append(item);
      }
      card.append(heading, value, meta);
      el.statusOverview.append(card);
    }

    el.statusProviderList.innerHTML = "";
    if (!providers.length) {
      const empty = document.createElement("p");
      empty.className = "status-empty";
      empty.textContent = t(
        "status.providers_unavailable",
        "Sync providers unavailable",
      );
      el.statusProviderList.append(empty);
      return;
    }
    for (const provider of providers) {
      const card = document.createElement("article");
      card.className = `status-provider-card ${provider.provider_type === state.activeStatusProvider ? "is-selected" : ""}`;
      const head = document.createElement("div");
      head.className = "status-provider-card-head";

      const titleWrap = document.createElement("div");
      const title = document.createElement("h4");
      title.textContent = provider.title || provider.provider_type;
      const statusLabel = document.createElement("p");
      statusLabel.className = "status-provider-state";
      statusLabel.textContent = providerStateLabel(provider.state);
      titleWrap.append(title, statusLabel);

      const actionWrap = document.createElement("div");
      actionWrap.className = "status-provider-actions";
      const startBtn = document.createElement("button");
      startBtn.type = "button";
      startBtn.textContent = t("status.service_start", "Start");
      startBtn.disabled = providerActionDisabled(provider, "start");
      startBtn.addEventListener("click", () => {
        onProviderServiceAction(provider.provider_type, "start", startBtn);
      });
      actionWrap.append(startBtn);

      const stopBtn = document.createElement("button");
      stopBtn.type = "button";
      stopBtn.textContent = t("status.service_stop", "Stop");
      stopBtn.disabled = providerActionDisabled(provider, "stop");
      stopBtn.addEventListener("click", () => {
        onProviderServiceAction(provider.provider_type, "stop", stopBtn);
      });
      actionWrap.append(stopBtn);

      const restartBtn = document.createElement("button");
      restartBtn.type = "button";
      restartBtn.textContent = t("status.service_restart", "Restart");
      restartBtn.disabled = providerActionDisabled(provider, "restart");
      restartBtn.addEventListener("click", () => {
        onProviderServiceAction(
          provider.provider_type,
          "restart",
          restartBtn,
        );
      });
      actionWrap.append(restartBtn);

      if (provider.open_url) {
        const openBtn = document.createElement("button");
        openBtn.type = "button";
        openBtn.textContent = t(
          "status.open_provider_ui",
          "Open Provider UI",
        );
        openBtn.addEventListener("click", () => {
          setActiveProviderTab(provider.provider_type);
          setActiveTab("providers");
        });
        actionWrap.append(openBtn);
      }
      const focusBtn = document.createElement("button");
      focusBtn.type = "button";
      focusBtn.textContent = t("status.focus_provider", "Focus");
      focusBtn.addEventListener("click", () => {
        setActiveStatusProvider(provider.provider_type);
      });
      actionWrap.append(focusBtn);

      head.append(titleWrap, actionWrap);

      const details = document.createElement("dl");
      details.className = "status-provider-details";
      const entries = [
        [t("status.provider_type", "Provider type"), provider.provider_type],
        [t("status.provider_available", "Available"), provider.available ? t("ui.yes", "yes") : t("ui.no", "no")],
        [t("status.provider_running", "Running"), provider.running ? t("ui.yes", "yes") : t("ui.no", "no")],
        [t("status.provider_pid", "PID"), provider.pid === null || provider.pid === undefined ? "-" : String(provider.pid)],
        [t("status.provider_url", "Web UI"), provider.open_url || "-"],
        [t("status.provider_error", "Last error"), providerErrorLabel(provider.last_error) || t("status.no_error", "none")],
      ];
      for (const [labelText, valueText] of entries) {
        const dt = document.createElement("dt");
        dt.textContent = labelText;
        const dd = document.createElement("dd");
        dd.textContent = valueText;
        details.append(dt, dd);
      }
      if (provider.provider_type === state.activeStatusProvider) {
        const note = document.createElement("p");
        note.className = "status-provider-note";
        note.textContent = t(
          "status.active_provider_note",
          "This provider is highlighted by the header badge.",
        );
        card.append(head, details, note);
      } else {
        card.append(head, details);
      }
      el.statusProviderList.append(card);
    }
  }

  function renderLanGameSharePanel() {
    if (!el.statusLanGamesSection || !el.statusLanGamesList) {
      return;
    }
    const isServer = currentLanMode() === "server";
    if (!isServer) {
      el.statusLanGamesSection.hidden = true;
      el.statusLanGamesList.innerHTML = "";
      return;
    }
    const inventory = state.lanGameInventory || {
      root_path: "",
      folders: [],
    };
    const folders = Array.isArray(inventory.folders) ? inventory.folders : [];
    const rootPath = String(inventory.root_path || "").trim();
    el.statusLanGamesSection.hidden = false;
    if (el.statusLanGamesRoot) {
      el.statusLanGamesRoot.textContent = `${t(
        "status.lan_root_label",
        "Root folder",
      )}: ${rootPath || t("status.lan_root_missing", "-")}`;
    }
    el.statusLanGamesList.innerHTML = "";
    if (inventory.message === "loading") {
      const loading = document.createElement("p");
      loading.className = "status-empty";
      loading.textContent = t(
        "status.lan_games_loading",
        "Refreshing folder list...",
      );
      el.statusLanGamesList.append(loading);
      return;
    }
    if (!rootPath) {
      const empty = document.createElement("p");
      empty.className = "status-empty";
      empty.textContent = t(
        "status.lan_root_unavailable",
        "Choose a library path in Settings to share LAN games.",
      );
      el.statusLanGamesList.append(empty);
      return;
    }
    if (inventory.message === "lan_game_inventory_unavailable") {
      const empty = document.createElement("p");
      empty.className = "status-empty";
      empty.textContent = t(
        "status.lan_game_inventory_unavailable",
        "LAN game folders could not be read. Check the library and local database.",
      );
      el.statusLanGamesList.append(empty);
      return;
    }
    if (!folders.length) {
      const empty = document.createElement("p");
      empty.className = "status-empty";
      empty.textContent = t(
        "status.lan_games_empty",
        "No game folders were found in the library.",
      );
      el.statusLanGamesList.append(empty);
      return;
    }
    for (const folder of folders) {
      const card = document.createElement("article");
      card.className = `status-lan-games-folder-card ${folder.shared ? "is-shared" : "is-local"}`;
      const head = document.createElement("div");
      head.className = "status-lan-games-folder-head";
      const titleWrap = document.createElement("div");
      const title = document.createElement("h4");
      title.textContent = String(folder.name || folder.path || "-");
      const status = document.createElement("p");
      status.className = "status-lan-games-folder-state";
      status.textContent = folder.shared
        ? t("status.lan_shared", "shared")
        : t("status.lan_local_only", "local only");
      titleWrap.append(title, status);

      const actions = document.createElement("div");
      actions.className = "status-lan-games-folder-actions";
      const toggleBtn = document.createElement("button");
      toggleBtn.type = "button";
      toggleBtn.textContent = folder.shared
        ? t("status.lan_keep_local", "Keep local")
        : t("status.lan_share_folder", "Share folder");
      toggleBtn.addEventListener("click", () => {
        if (!folder.shared && !folder.metadata_available) {
          openServerFolderEditor(folder, true, toggleBtn);
          return;
        }
        onLanGameShareToggle(folder, !folder.shared, toggleBtn);
      });
      const editBtn = document.createElement("button");
      editBtn.type = "button";
      editBtn.textContent = folder.metadata_available
        ? t("status.lan_edit_metadata", "Edit metadata")
        : t("status.lan_add_metadata", "Create metadata");
      editBtn.addEventListener("click", () => openServerFolderEditor(folder, false, toggleBtn));
      actions.append(editBtn);
      actions.append(toggleBtn);
      head.append(titleWrap, actions);

      const details = document.createElement("dl");
      details.className = "status-lan-games-folder-details";
      const entries = [
        [t("status.lan_game_path", "Path"), folder.path || "-"],
        [
          t("status.lan_game_configured", "Configured"),
          folder.configured ? t("ui.yes", "yes") : t("ui.no", "no"),
        ],
        [
          t("status.lan_game_paused", "Paused"),
          folder.paused ? t("ui.yes", "yes") : t("ui.no", "no"),
        ],
      ];
      for (const [labelText, valueText] of entries) {
        const dt = document.createElement("dt");
        dt.textContent = labelText;
        const dd = document.createElement("dd");
        dd.textContent = valueText;
        details.append(dt, dd);
      }
      card.append(head, details);
      el.statusLanGamesList.append(card);
    }
  }

  function syncWizardInputsFromSettings() {
    if (!el.wizardNicknameInput || !el.wizardStorageInput) {
      return;
    }
    el.wizardNicknameInput.value = state.settings.nickname || "";
    const isWindows = state.settings.platform === "windows";
    if (
      isWindows &&
      state.storageLocations.length > 0 &&
      el.wizardStorageSelect
    ) {
      el.wizardStorageSelect.value = state.settings.windows_game_drive_letter;
      if (!el.wizardStorageSelect.value) {
        el.wizardStorageSelect.value = state.storageLocations[0].id;
      }
      return;
    }
    el.wizardStorageInput.value = isWindows
      ? state.settings.windows_game_drive_letter
      : state.settings.linux_install_path;
  }

  function updateWizardStorageControl() {
    const isWindows = state.settings.platform === "windows";
    const hasWindowsLocations = state.storageLocations.length > 0;
    if (!el.wizardStorageInput || !el.wizardStorageSelect) {
      return;
    }

    if (isWindows && hasWindowsLocations) {
      if (el.wizardLabelStorage) {
        el.wizardLabelStorage.setAttribute("for", "wizard-storage-select");
      }
      el.wizardStorageInput.hidden = true;
      el.wizardStorageSelect.hidden = false;
      el.wizardStorageSelect.innerHTML = "";
      for (const location of state.storageLocations) {
        const option = document.createElement("option");
        option.value = location.id;
        option.textContent = location.display;
        el.wizardStorageSelect.append(option);
      }
      el.wizardStorageSelect.disabled = false;
      const currentDrive = String(
        state.settings.windows_game_drive_letter || "",
      );
      el.wizardStorageSelect.value =
        currentDrive &&
        state.storageLocations.some((item) => item.id === currentDrive)
          ? currentDrive
          : state.storageLocations[0].id;
      return;
    }

    el.wizardStorageSelect.hidden = true;
    el.wizardStorageSelect.disabled = true;
    el.wizardStorageSelect.innerHTML = "";
    if (el.wizardLabelStorage) {
      el.wizardLabelStorage.setAttribute("for", "wizard-storage-input");
    }
    el.wizardStorageInput.hidden = false;
    el.wizardStorageInput.value = isWindows
      ? state.settings.windows_game_drive_letter
      : state.settings.linux_install_path;
  }

  function wizardStorageValue() {
    const isWindows = state.settings.platform === "windows";
    if (
      isWindows &&
      state.storageLocations.length > 0 &&
      el.wizardStorageSelect
    ) {
      return String(el.wizardStorageSelect.value || "").trim();
    }
    return String(el.wizardStorageInput?.value || "").trim();
  }

  function updateSettingsStorageControl() {
    const isWindows = state.settings.platform === "windows";
    const hasWindowsLocations = state.storageLocations.length > 0;
    if (!el.storageInput || !el.storageSelect) {
      return;
    }
    if (isWindows && hasWindowsLocations) {
      if (el.labelStorage) {
        el.labelStorage.setAttribute("for", "storage-select");
      }
      el.storageInput.hidden = true;
      el.storageSelect.hidden = false;
      el.storageSelect.innerHTML = "";
      for (const location of state.storageLocations) {
        const option = document.createElement("option");
        option.value = location.id;
        option.textContent = location.display;
        el.storageSelect.append(option);
      }
      el.storageSelect.disabled = false;
      const currentDrive = String(
        state.settings.windows_game_drive_letter || "",
      );
      el.storageSelect.value =
        currentDrive &&
        state.storageLocations.some((item) => item.id === currentDrive)
          ? currentDrive
          : state.storageLocations[0].id;
      return;
    }
    el.storageSelect.hidden = true;
    el.storageSelect.disabled = true;
    el.storageSelect.innerHTML = "";
    if (el.labelStorage) {
      el.labelStorage.setAttribute("for", "storage-input");
    }
    el.storageInput.hidden = false;
    el.storageInput.value = isWindows
      ? state.settings.windows_game_drive_letter
      : state.settings.linux_install_path;
    if (el.ouisyncStorageInput) {
      el.ouisyncStorageInput.value = state.settings.ouisync_storage_path || "";
    }
  }

  function updateLinuxRuntimeControl() {
    const isLinux = state.settings.platform === "linux";
    const runtime = String(state.settings.linux_windows_runtime || "wine");
    const showProtonPath = isLinux && runtime === "proton";
    const showProtonGePath = isLinux && runtime === "proton-ge";

    if (el.labelLinuxRuntime) {
      el.labelLinuxRuntime.hidden = !isLinux;
    }
    if (el.linuxRuntimeSelect) {
      el.linuxRuntimeSelect.hidden = !isLinux;
      el.linuxRuntimeSelect.disabled = !isLinux;
      el.linuxRuntimeSelect.value = runtime;
    }
    if (el.labelLinuxProtonPath) {
      el.labelLinuxProtonPath.hidden = !showProtonPath;
    }
    if (el.linuxProtonPathInput) {
      el.linuxProtonPathInput.hidden = !showProtonPath;
      el.linuxProtonPathInput.disabled = !showProtonPath;
      el.linuxProtonPathInput.value = state.settings.linux_proton_path || "";
    }
    if (el.labelLinuxProtonGePath) {
      el.labelLinuxProtonGePath.hidden = !showProtonGePath;
    }
    if (el.linuxProtonGePathInput) {
      el.linuxProtonGePathInput.hidden = !showProtonGePath;
      el.linuxProtonGePathInput.disabled = !showProtonGePath;
      el.linuxProtonGePathInput.value =
      state.settings.linux_proton_ge_path || "";
    }
  }

  function renderLocalGameGenreOptions(selectedValue = "all") {
    if (!el.localGameGenre) {
      return;
    }
    const currentValue = String(selectedValue || "all");
    el.localGameGenre.innerHTML = "";

    const noneOption = document.createElement("option");
    noneOption.value = "";
    noneOption.textContent = t("ui.filter_genre_all", "All genres");
    el.localGameGenre.append(noneOption);

    for (const genre of state.genres) {
      const id = Number(genre?.id || 0);
      if (!Number.isFinite(id) || id <= 0) {
        continue;
      }
      const option = document.createElement("option");
      option.value = String(id);
      option.textContent = String(genre?.name || "").trim() || String(id);
      el.localGameGenre.append(option);
    }

    el.localGameGenre.value = currentValue;
  }

  function localGameStartArgsValue() {
    return String(el.localGameStartArgs?.value || "")
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line.length > 0);
  }

  function setLocalGameModalVisible(visible) {
    if (!el.localGameModal) {
      return;
    }
    el.localGameModal.hidden = !visible;
  }

  function openServerFolderEditor(folder, shareAfter, button) {
    const metadata = folder.metadata || {};
    const title = metadata.title && typeof metadata.title === "object"
      ? metadata.title : { en: String(metadata.title || ""), de: String(metadata.title || "") };
    const description = metadata.description && typeof metadata.description === "object"
      ? metadata.description : { en: String(metadata.description || ""), de: String(metadata.description || "") };
    openLocalGameModal({ ...metadata, id: folder.name, title: title.en, readme: description.en,
      metadata: { ...metadata, title, description } }, { folder, shareAfter, button });
  }

  let downloadedServerCover = "";
  let serverCoverGeneration = 0;

  function openLocalGameModal(game = null, serverFolder = null) {
    state.serverFolderEditing = serverFolder;
    downloadedServerCover = "";
    serverCoverGeneration += 1;
    if (el.serverCoverDownload) el.serverCoverDownload.hidden = !serverFolder;
    if (el.serverCoverDownloadStatus) el.serverCoverDownloadStatus.textContent = "";
    if (el.serverCoverDownloadBtn) el.serverCoverDownloadBtn.disabled = false;
    if (el.serverCoverUrl) {
      const candidate = String(game?.metadata?.media?.image_url || game?.metadata?.media?.image || game?.metadata?.image || "");
      el.serverCoverUrl.value = /^https?:\/\//i.test(candidate) ? candidate : "";
    }
    if (el.localGameModalStatus) el.localGameModalStatus.textContent = "";
    state.localGameEditingOriginalId = String(game?.id || "").trim();
    if (el.localGameModalTitle) {
      el.localGameModalTitle.textContent = game
        ? t("game.local_modal_edit_title", "Edit Local Game")
        : t("game.local_modal_add_title", "Add Local Game");
    }
    if (el.localGameSaveBtn) {
      el.localGameSaveBtn.disabled = false;
      el.localGameSaveBtn.textContent = game
        ? t("game.local_modal_save_changes", "Save Changes")
        : t("game.local_modal_save", "Save Local Game");
    }
    if (el.localGameModalNote) {
      el.localGameModalNote.textContent = t(
        "game.local_modal_note",
        "Local entries are stored in the launcher database and are not synced to the network.",
      );
    }
    if (serverFolder) {
      if (el.localGameModalTitle) el.localGameModalTitle.textContent = t("game.server_modal_title", "Game folder metadata");
      if (el.localGameSaveBtn) el.localGameSaveBtn.textContent = t("game.server_modal_save", "Save metadata");
      if (el.localGameModalNote) el.localGameModalNote.textContent = t("game.server_modal_note", "Metadata is stored in this game folder and published when it is shared.");
    }
    const metadata = game?.metadata || {};
    const startMeta = metadata?.game_start || {};
    if (el.localGameId) {
      el.localGameId.value = String(game?.id || "");
      el.localGameId.disabled = Boolean(game);
    }
    if (el.localGameTitleEn) {
      el.localGameTitleEn.value = String(metadata?.title?.en || game?.title || "");
    }
    if (el.localGameTitleDe) {
      el.localGameTitleDe.value = String(metadata?.title?.de || game?.title || "");
    }
    renderLocalGameGenreOptions(String(game?.genre_id || metadata?.genre_id || ""));
    if (el.localGameReleaseYear) {
      el.localGameReleaseYear.value = String(game?.release_year || metadata?.release_year || "");
    }
    if (el.localGamePublisher) {
      el.localGamePublisher.value = String(game?.publisher || metadata?.publisher || "");
    }
    if (el.localGameSize) {
      el.localGameSize.value = String(game?.size_gb ?? metadata?.size_gb ?? 0);
    }
    if (el.localGameMaxPlayers) {
      el.localGameMaxPlayers.value = String(game?.max_players || metadata?.max_players || "");
    }
    if (el.localGameVersion) {
      el.localGameVersion.value = String(game?.version || metadata?.version || "");
    }
    if (el.localGameStartFile) {
      el.localGameStartFile.value = String(
        startMeta?.file || metadata?.game_start_file || "",
      );
    }
    if (el.localGameStartArgs) {
      const args = Array.isArray(startMeta?.args)
        ? startMeta.args
        : Array.isArray(metadata?.game_start_args)
          ? metadata.game_start_args
          : [];
      el.localGameStartArgs.value = args.join("\n");
    }
    if (el.localGameReadmeEn) {
      el.localGameReadmeEn.value = String(game?.readme || metadata?.description?.en || "");
    }
    if (el.localGameReadmeDe) {
      el.localGameReadmeDe.value = String(metadata?.description?.de || game?.readme || "");
    }
    if (el.localGameImage) {
      el.localGameImage.value = "";
    }
    setLocalGameModalVisible(true);
  }

  function closeLocalGameModal() {
    serverCoverGeneration += 1;
    downloadedServerCover = "";
    setLocalGameModalVisible(false);
    state.localGameEditingOriginalId = "";
    state.serverFolderEditing = null;
    if (el.localGameImage) {
      el.localGameImage.value = "";
    }
  }

  function buildLocalGamePayload(imageDataUrl = "", imageName = "") {
    return {
      original_game_id: state.localGameEditingOriginalId,
      item: {
        game_id: String(el.localGameId?.value || "").trim(),
        key: String(el.localGameId?.value || "").trim(),
        title_en: String(el.localGameTitleEn?.value || "").trim(),
        title_de: String(el.localGameTitleDe?.value || "").trim(),
        genre_id: String(el.localGameGenre?.value || "").trim(),
        release_year: String(el.localGameReleaseYear?.value || "").trim(),
        publisher: String(el.localGamePublisher?.value || "").trim(),
        size_gb: Number(el.localGameSize?.value || 0),
        max_players: String(el.localGameMaxPlayers?.value || "").trim(),
        version: String(el.localGameVersion?.value || "").trim(),
        game_start_file: String(el.localGameStartFile?.value || "").trim(),
        game_start_args: String(el.localGameStartArgs?.value || ""),
        readme_en: String(el.localGameReadmeEn?.value || "").trim(),
        readme_de: String(el.localGameReadmeDe?.value || "").trim(),
        master_required: false,
        game_provider_type: "local",
        game_image_data_url: imageDataUrl,
        game_image_name: imageName,
      },
    };
  }

  async function fileToDataUrl(file) {
    if (!file) {
      return "";
    }
    return await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(new Error("file_read_failed"));
      reader.onload = () => resolve(String(reader.result || ""));
      reader.readAsDataURL(file);
    });
  }

  async function convertServerCover(dataUrl) {
    const response = await fetch(dataUrl);
    const bitmap = await createImageBitmap(await response.blob());
    try {
      if (!bitmap.width || !bitmap.height || bitmap.width * bitmap.height > 60000000) throw new Error("image_dimensions_invalid");
      const scale = Math.min(1, 1600 / bitmap.width, 1600 / bitmap.height);
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(bitmap.width * scale));
      canvas.height = Math.max(1, Math.round(bitmap.height * scale));
      const context = canvas.getContext("2d");
      if (!context) throw new Error("image_conversion_failed");
      context.fillStyle = "#ffffff";
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      const result = canvas.toDataURL("image/jpeg", 0.85);
      if (!result.startsWith("data:image/jpeg;base64,")) throw new Error("image_conversion_failed");
      return result;
    } finally {
      bitmap.close();
    }
  }

  async function downloadServerCover() {
    if (!state.serverFolderEditing || !el.serverCoverDownloadBtn) return;
    const generation = ++serverCoverGeneration;
    downloadedServerCover = "";
    el.serverCoverDownloadBtn.disabled = true;
    el.localGameSaveBtn.disabled = true;
    el.serverCoverDownloadStatus.textContent = t("game.server_cover_downloading", "Downloading and resizing cover...");
    try {
      const payload = await apiPost("/lan/games", {
        action: "download_cover", url: String(el.serverCoverUrl.value || "").trim(),
      });
      const cover = await convertServerCover(String(payload?.result?.data_url || ""));
      if (generation !== serverCoverGeneration) return;
      downloadedServerCover = cover;
      el.localGameImage.value = "";
      el.serverCoverDownloadStatus.textContent = t("game.server_cover_ready", "Cover ready; save metadata to store it locally.");
    } catch (_err) {
      if (generation === serverCoverGeneration) el.serverCoverDownloadStatus.textContent = t("game.server_cover_failed", "Cover download or conversion failed. Check the public image URL.");
    } finally {
      if (generation === serverCoverGeneration) {
        el.serverCoverDownloadBtn.disabled = false;
        el.localGameSaveBtn.disabled = false;
      }
    }
  }

  async function onLocalGameSave() {
    if (!el.localGameSaveBtn) {
      return;
    }
    const imageFile = el.localGameImage?.files?.[0] || null;
    let imageDataUrl = state.serverFolderEditing ? downloadedServerCover : "";
    let imageName = "";
    try {
      if (imageFile) {
        imageDataUrl = await fileToDataUrl(imageFile);
        imageName = imageFile.name || "";
      }
      el.localGameSaveBtn.disabled = true;
      el.localGameSaveBtn.classList.add("is-loading");
      el.localGameSaveBtn.setAttribute("aria-busy", "true");
      const payload = buildLocalGamePayload(imageDataUrl, imageName);
      const serverEdit = state.serverFolderEditing;
      const response = serverEdit
        ? await apiPost("/lan/games", { action: "save_metadata", folder_path: serverEdit.folder.path, item: payload.item })
        : await apiPost("/catalog/games/local-settings", payload);
      if (response?.result?.ok) {
        if (serverEdit) {
          state.lanGameInventory = response.result.lan || state.lanGameInventory;
          closeLocalGameModal();
          renderStatusPanel();
          if (serverEdit.shareAfter) await onLanGameShareToggle(serverEdit.folder, true, serverEdit.button);
          return;
        }
        el.settingsStatus.textContent = t(
          "game.local_game_saved",
          "Local game saved.",
        );
        const gameId = String(response?.result?.game_id || payload.item.game_id || "").trim();
        closeLocalGameModal();
        await loadCatalog();
        if (gameId) {
          state.selectedGameId = gameId;
          await loadGameDetail(gameId);
        }
        return;
      }
      const backendMessage = String(response?.result?.message || "error");
      if (el.localGameModalStatus) {
        el.localGameModalStatus.textContent = t(`game.local_game_error_${backendMessage}`, backendMessage);
      }
      el.settingsStatus.textContent = `${t(
        "game.local_game_save_failed",
        "Local game could not be saved.",
      )} (${t(`game.local_game_error_${backendMessage}`, backendMessage)})`;
    } catch (err) {
      const backendMessage = String(err?.message || "error");
      if (el.localGameModalStatus) {
        el.localGameModalStatus.textContent = t(`game.local_game_error_${backendMessage}`, backendMessage);
      }
      el.settingsStatus.textContent = `${t(
        "game.local_game_save_failed",
        "Local game could not be saved.",
      )} (${t(`game.local_game_error_${backendMessage}`, backendMessage)})`;
    } finally {
      if (el.localGameSaveBtn) {
        el.localGameSaveBtn.classList.remove("is-loading");
        el.localGameSaveBtn.setAttribute("aria-busy", "false");
        el.localGameSaveBtn.disabled = false;
      }
    }
  }

  function settingsStorageValue() {
    const isWindows = state.settings.platform === "windows";
    if (isWindows && state.storageLocations.length > 0 && el.storageSelect) {
      return String(el.storageSelect.value || "").trim();
    }
    return String(el.storageInput?.value || "").trim();
  }

  function onLinuxRuntimeChange() {
    if (!el.linuxRuntimeSelect) {
      return;
    }
    state.settings.linux_windows_runtime = String(
      el.linuxRuntimeSelect.value || "wine",
    );
    updateLinuxRuntimeControl();
  }

  async function loadStorageLocations() {
    if (state.settings.platform !== "windows") {
      state.storageLocations = [];
      return;
    }
    try {
      const payload = await apiGet("/platform/storage-locations");
      const locations = Array.isArray(payload.storage_locations)
        ? payload.storage_locations
        : [];
      state.storageLocations = locations
        .map((item) => {
          const id = String(item?.id || "")
            .toUpperCase()
            .slice(0, 1);
          const display = String(item?.display || "").trim();
          return { id, display: display || `${id}:` };
        })
        .filter((item) => item.id);
    } catch (_err) {
      state.storageLocations = [];
    }
  }

  async function loadExtraSyncItems() {
    try {
      const payload = await apiGet("/settings/extra-sync-items");
      state.extraSyncItems = Array.isArray(payload.items) ? payload.items : [];
    } catch (_err) {
      state.extraSyncItems = [];
    }
    renderExtraSyncItems();
  }

  function renderExtraSyncItems() {
    if (!el.extraSyncList) {
      return;
    }
    el.extraSyncList.innerHTML = "";
    if (!state.extraSyncItems.length) {
      const row = document.createElement("li");
      row.className = "extra-sync-item-meta";
      row.textContent = t("settings.extra_sync_empty", "No manual sync items.");
      el.extraSyncList.append(row);
      return;
    }
    for (const item of state.extraSyncItems) {
      const isLocked = Boolean(item.is_seeded_default);
      const row = document.createElement("li");
      row.className = "extra-sync-item";
      const title = document.createElement("div");
      title.className = "extra-sync-item-title";
      title.textContent = `${item.title_en || item.game_id} (${item.game_id})`;

      const meta = document.createElement("div");
      meta.className = "extra-sync-item-meta";
      const enabled = item.sync_enabled
        ? t("settings.extra_sync_enabled", "enabled")
        : t("settings.extra_sync_disabled", "disabled");
      const provider = item.is_game_provider
        ? t("settings.extra_sync_is_provider_enabled", "provider")
        : t("settings.extra_sync_is_provider_disabled", "regular");
      const providerType = String(item.game_provider_type || "resilio").toLowerCase();
      const providerTypeLabel = providerType === "ouisync"
        ? t("settings.extra_sync_provider_type_ouisync", "Ouisync")
        : t("settings.extra_sync_provider_type_resilio", "Resilio");
      const hasGameDb = item.has_game_db
        ? t("settings.extra_sync_has_game_db_enabled", "game.db")
        : t("settings.extra_sync_has_game_db_disabled", "no game.db");
      const packedImagePath = String(item.packed_image_path || "").trim();
      const packedImagePassword = String(
        item.packed_image_password || "",
      ).trim();
      const packedImageState = packedImagePath
        ? `${t("settings.extra_sync_packed_image_path", "Packed image path")}: ${packedImagePath}`
        : t(
            "settings.extra_sync_packed_image_path_empty",
            "Packed image path: none",
          );
      const packedPasswordState = packedImagePassword
        ? t("settings.extra_sync_packed_image_password_set", "password set")
        : t(
            "settings.extra_sync_packed_image_password_empty",
            "password empty",
          );
      meta.textContent = `${t("settings.extra_sync_key", "Key")}: ${item.game_key} | ${t("settings.extra_sync_state", "Sync")}: ${enabled} | ${t("settings.extra_sync_provider_type", "Provider Type")}: ${providerTypeLabel} | ${provider} | ${hasGameDb} | ${packedImageState} | ${packedPasswordState}`;

      const actions = document.createElement("div");
      actions.className = "extra-sync-item-actions";

      const editBtn = document.createElement("button");
      editBtn.type = "button";
      editBtn.textContent = t("settings.extra_sync_edit", "Edit");
      if (!isLocked) {
        editBtn.addEventListener("click", () => openExtraSyncModal(item));
      } else {
        editBtn.disabled = true;
      }
      actions.append(editBtn);

      const toggleBtn = document.createElement("button");
      toggleBtn.type = "button";
      toggleBtn.textContent = item.sync_enabled
        ? t("settings.extra_sync_disable", "Disable Sync")
        : t("settings.extra_sync_enable", "Enable Sync");
      toggleBtn.addEventListener("click", () =>
        onExtraSyncToggle(item.game_id, !item.sync_enabled),
      );
      actions.append(toggleBtn);

      if (item.is_game_provider) {
        const refreshImagesBtn = document.createElement("button");
        refreshImagesBtn.type = "button";
        refreshImagesBtn.textContent = t(
          "settings.extra_sync_update_images",
          "Update Images",
        );
        refreshImagesBtn.addEventListener("click", () =>
          onExtraSyncRefreshImages(item.game_id),
        );
        actions.append(refreshImagesBtn);
      }

      const deleteItemBtn = document.createElement("button");
      deleteItemBtn.type = "button";
      deleteItemBtn.textContent = t(
        "settings.extra_sync_delete_item",
        "Delete Item",
      );
      if (!isLocked) {
        deleteItemBtn.addEventListener("click", () =>
          onExtraSyncDeleteItem(item.game_id),
        );
      } else {
        deleteItemBtn.disabled = true;
      }
      actions.append(deleteItemBtn);

      const deleteDataBtn = document.createElement("button");
      deleteDataBtn.type = "button";
      deleteDataBtn.textContent = t(
        "settings.extra_sync_delete_data",
        "Delete Data",
      );
      if (!isLocked) {
        deleteDataBtn.addEventListener("click", () =>
          onExtraSyncDeleteData(item.game_id),
        );
      } else {
        deleteDataBtn.disabled = true;
      }
      actions.append(deleteDataBtn);

      const wipeBtn = document.createElement("button");
      wipeBtn.type = "button";
      wipeBtn.textContent = t("settings.extra_sync_wipe", "Wipe");
      if (!isLocked) {
        wipeBtn.addEventListener("click", () => onExtraSyncWipe(item.game_id));
      } else {
        wipeBtn.disabled = true;
      }
      actions.append(wipeBtn);

      row.append(title, meta, actions);
      el.extraSyncList.append(row);
    }
  }

  function openExtraSyncModal(item = null) {
    state.extraSyncEditingOriginalId = item?.game_id || "";
    el.extraSyncModalTitle.textContent = item
      ? t("settings.extra_sync_modal_edit", "Edit Provider")
      : t("settings.extra_sync_modal_add", "Add Provider");
    el.extraSyncGameId.value = item?.game_id || "";
    el.extraSyncGameId.disabled = Boolean(item);
    el.extraSyncKey.value = item?.game_key || "";
    el.extraSyncTitleEn.value = item?.title_en || "";
    el.extraSyncTitleDe.value = item?.title_de || "";
    el.extraSyncReleaseYear.value = item?.release_year || "";
    el.extraSyncPublisher.value = item?.publisher || "";
    el.extraSyncSize.value = String(item?.size_gb ?? 0);
    el.extraSyncPersons.value = item?.max_players || "";
    el.extraSyncVersion.value = item?.version || "";
    el.extraSyncReadmeEn.value = item?.readme_en || "";
    el.extraSyncReadmeDe.value = item?.readme_de || "";
    el.extraSyncMasterRequired.checked = Boolean(item?.master_required);
    el.extraSyncVisible.checked = item
      ? Boolean(item.visible_in_gamelist)
      : true;
    el.extraSyncEnabled.checked = item ? Boolean(item.sync_enabled) : true;
    el.extraSyncProviderType.value = item?.game_provider_type || "resilio";
    el.extraSyncIsProvider.checked = item
      ? Boolean(item.is_game_provider)
      : true;
    el.extraSyncHasGameDb.checked = item ? Boolean(item.has_game_db) : false;
    el.extraSyncPackedImagePath.value = item?.packed_image_path || "";
    el.extraSyncPackedImagePassword.value = item?.packed_image_password || "";
    el.extraSyncModal.hidden = false;
  }

  function closeExtraSyncModal() {
    el.extraSyncModal.hidden = true;
    state.extraSyncEditingOriginalId = "";
  }

  function buildExtraSyncItemPayload() {
    return {
      game_id: String(el.extraSyncGameId.value || "").trim(),
      game_key: String(el.extraSyncKey.value || "").trim(),
      title_en: String(el.extraSyncTitleEn.value || "").trim(),
      title_de: String(el.extraSyncTitleDe.value || "").trim(),
      release_year: String(el.extraSyncReleaseYear.value || "").trim(),
      publisher: String(el.extraSyncPublisher.value || "").trim(),
      size_gb: Number(el.extraSyncSize.value || "0"),
      max_players: String(el.extraSyncPersons.value || "").trim(),
      version: String(el.extraSyncVersion.value || "").trim(),
      readme_en: String(el.extraSyncReadmeEn.value || "").trim(),
      readme_de: String(el.extraSyncReadmeDe.value || "").trim(),
      master_required: Boolean(el.extraSyncMasterRequired.checked),
      visible_in_gamelist: Boolean(el.extraSyncVisible.checked),
      sync_enabled: Boolean(el.extraSyncEnabled.checked),
      game_provider_type: String(el.extraSyncProviderType.value || "resilio")
        .trim()
        .toLowerCase(),
      is_game_provider: Boolean(el.extraSyncIsProvider.checked),
      has_game_db: Boolean(el.extraSyncHasGameDb.checked),
      packed_image_path: String(el.extraSyncPackedImagePath.value || "").trim(),
      packed_image_password: String(
        el.extraSyncPackedImagePassword.value || "",
      ).trim(),
    };
  }

  async function onExtraSyncSave() {
    const payload = {
      original_game_id: state.extraSyncEditingOriginalId,
      item: buildExtraSyncItemPayload(),
    };
    try {
      const response = await apiPost("/settings/extra-sync-items", payload);
      state.extraSyncItems = response.result.items || [];
      renderExtraSyncItems();
      closeExtraSyncModal();
      el.settingsStatus.textContent = t("settings.saved", "Settings saved.");
      await loadCatalog();
    } catch (err) {
      const backendMessage = String(err?.message || "error");
      el.settingsStatus.textContent = `${t("settings.save_failed", "Saving settings failed.")} (${t(`settings.error_${backendMessage}`, backendMessage)})`;
    }
  }

  async function onExtraSyncBootstrapImport() {
    const file = el.extraSyncImportFile?.files?.[0];
    if (!file) return;
    el.extraSyncImportBtn.disabled = true;
    try {
      const bootstrap = JSON.parse(await file.text());
      if (!Array.isArray(bootstrap?.items)) {
        throw new Error("extra_sync_bootstrap_invalid");
      }
      const response = await apiPost(
        "/settings/extra-sync-items/import-bootstrap",
        { items: bootstrap.items },
      );
      const result = response.result || {};
      if (result.ok === false) {
        throw new Error(String(result.message || "provider_import_failed"));
      }
      state.extraSyncItems = Array.isArray(result.items) ? result.items : [];
      renderExtraSyncItems();
      el.settingsStatus.textContent = `${t("settings.provider_imported", "Providers imported")}: ${Number(result.imported || 0)}`;
      await loadCatalog();
    } catch (err) {
      const errorKey = String(err?.message || "provider_import_failed").split(":", 1)[0];
      el.settingsStatus.textContent = t(
        `settings.error_${errorKey}`,
        t("settings.provider_import_failed", "Provider import failed."),
      );
    } finally {
      el.extraSyncImportFile.value = "";
      el.extraSyncImportBtn.disabled = false;
    }
  }

  async function onExtraSyncToggle(gameId, enabled) {
    try {
      const response = await apiPost("/settings/extra-sync-items/toggle-sync", {
        game_id: gameId,
        sync_enabled: enabled,
      });
      state.extraSyncItems = response.result.items || [];
      renderExtraSyncItems();
      el.settingsStatus.textContent = t("settings.saved", "Settings saved.");
    } catch (err) {
      const errorMessage = String(err?.message || "");
      const errorKey = errorMessage.split(":", 1)[0];
      const localizedError = t(`status.error_${errorKey}`, errorMessage);
      el.settingsStatus.textContent = `${t("settings.save_failed", "Saving settings failed.")} (${localizedError})`;
    }
  }

  async function onExtraSyncRefreshImages(gameId) {
    try {
      const response = await apiPost(
        "/settings/extra-sync-items/refresh-images",
        {
          game_id: gameId,
        },
      );
      state.extraSyncItems = response.result.items || [];
      renderExtraSyncItems();
      el.settingsStatus.textContent = t(
        "settings.images_refreshed",
        "Images refreshed.",
      );
    } catch (err) {
      const backendMessage = String(err?.message || "error");
      el.settingsStatus.textContent = `${t("settings.image_refresh_failed", "Image refresh failed.")} (${t(`settings.error_${backendMessage}`, backendMessage)})`;
    }
  }

  async function onExtraSyncDeleteItem(gameId) {
    if (
      !window.confirm(
        t(
          "settings.extra_sync_confirm_delete_item",
          "Delete item from settings and sync?",
        ),
      )
    ) {
      return;
    }
    try {
      const response = await apiPost("/settings/extra-sync-items/delete-item", {
        game_id: gameId,
      });
      state.extraSyncItems = response.result.items || [];
      renderExtraSyncItems();
      await loadCatalog();
      el.settingsStatus.textContent = t("settings.saved", "Settings saved.");
    } catch (err) {
      el.settingsStatus.textContent = `${t("settings.save_failed", "Saving settings failed.")} (${err.message})`;
    }
  }

  async function onExtraSyncDeleteData(gameId) {
    if (
      !window.confirm(
        t(
          "settings.extra_sync_confirm_delete_data",
          "Delete local data and remove from sync?",
        ),
      )
    ) {
      return;
    }
    try {
      const response = await apiPost("/settings/extra-sync-items/delete-data", {
        game_id: gameId,
      });
      state.extraSyncItems = response.result.items || [];
      renderExtraSyncItems();
      await loadCatalog();
      el.settingsStatus.textContent = t("settings.saved", "Settings saved.");
    } catch (err) {
      el.settingsStatus.textContent = `${t("settings.save_failed", "Saving settings failed.")} (${err.message})`;
    }
  }

  async function onExtraSyncWipe(gameId) {
    if (
      !window.confirm(
        t(
          "settings.extra_sync_confirm_wipe",
          "Wipe item from settings, sync, and disk?",
        ),
      )
    ) {
      return;
    }
    try {
      const response = await apiPost("/settings/extra-sync-items/wipe", {
        game_id: gameId,
      });
      state.extraSyncItems = response.result.items || [];
      renderExtraSyncItems();
      await loadCatalog();
      el.settingsStatus.textContent = t("settings.saved", "Settings saved.");
    } catch (err) {
      el.settingsStatus.textContent = `${t("settings.save_failed", "Saving settings failed.")} (${err.message})`;
    }
  }

  function updateWelcomeWizardState() {
    if (!el.welcomeWizard) {
      return;
    }
    if (!state.backendReady) {
      el.welcomeWizard.hidden = true;
      return;
    }
    const visible = shouldShowWelcomeWizard();
    el.welcomeWizard.hidden = !visible;
    if (visible) {
      if (!String(el.wizardConsole?.textContent || "").trim()) {
        setWizardConsoleLines([
          t(
            "wizard.console_idle",
            "Ready. Press Save And Continue to start setup.",
          ),
        ]);
      }
    }
  }

  function applySettingsToForm() {
    el.nicknameInput.value = state.settings.nickname || "";
    el.themeSelect.value = state.settings.theme || "dark";
    el.logLevelSelect.value = state.settings.log_level || "WARNING";
    if (el.logsLevelSelect) {
      el.logsLevelSelect.value = state.settings.log_level || "WARNING";
    }
    el.autoSyncCheckbox.checked = Boolean(state.settings.auto_start_sync);
    if (el.syncOnlyModeCheckbox) {
      el.syncOnlyModeCheckbox.checked = Boolean(state.settings.sync_only_mode);
    }
    if (el.lanModeSelect) {
      el.lanModeSelect.value =
        state.settings.lan_mode || "client";
    }
    const isWindows = state.settings.platform === "windows";
    el.storageInput.value = isWindows
      ? state.settings.windows_game_drive_letter
      : state.settings.linux_install_path;
    if (el.linuxRuntimeSelect) {
      el.linuxRuntimeSelect.value =
        state.settings.linux_windows_runtime || "wine";
    }
    if (el.linuxProtonPathInput) {
      el.linuxProtonPathInput.value = state.settings.linux_proton_path || "";
    }
    if (el.linuxProtonGePathInput) {
      el.linuxProtonGePathInput.value =
        state.settings.linux_proton_ge_path || "";
    }
    updateSettingsStorageControl();
    updateLinuxRuntimeControl();
    renderLanGameSharePanel();
    renderLanDiscoveryVisibility();
    if (el.logsSourceFilterSelect) {
      el.logsSourceFilterSelect.value = normalizeLogFilter(
        state.logsSourceFilter,
      );
    }
    if (el.logsLengthSelect) {
      el.logsLengthSelect.value = normalizeLogLimit(state.logsLimit);
    }
    const syncBlocked = !state.settings.library_path_initialized;
    if (syncBlocked) {
      el.settingsStatus.textContent = t(
        "settings.first_run_path_required",
        "First run: save library path in settings before starting sync.",
      );
    }
    updateDetailActionStates();
    updateInstallPrereqButtonState();
    updateNetworkModeButtonState();
    syncWizardInputsFromSettings();
    setSettingsDirty(false);
    updateWelcomeWizardState();
  }

  function setSettingsDirty(dirty) {
    state.settingsDirty = Boolean(dirty);
    el.saveSettingsBtn?.classList.toggle("is-dirty", state.settingsDirty);
  }

  function applyStaticText() {
    document.documentElement.lang = state.locale;
    applyLauncherSiteBranding();
    el.appSubtitle.textContent = t(
      "app.subtitle",
      "Cross-platform LAN game launcher",
    );
    if (el.topUpdateHint) {
      el.topUpdateHint.textContent = t(
        "app.update_available_hint",
        "Restart to install update",
      );
      el.topUpdateHint.hidden = !state.updateAvailable;
    }
    updateTopbarUpdateState();
    if (el.topHelpDocs) {
      const helpText = t("ui.open_local_docs", "Open local documentation");
      el.topHelpDocs.textContent = "?";
      el.topHelpDocs.title = helpText;
      el.topHelpDocs.setAttribute("aria-label", helpText);
    }
    if (el.topTrafficToggle) {
      const hoverText = trafficHintText();
      el.topTrafficToggle.removeAttribute("title");
      el.topTrafficToggle.setAttribute("aria-label", hoverText);
    }
    updateTopbarTrafficSizing();
    renderLauncherLinksDropdown();
    el.labelLanguage.textContent = t("ui.language", "Language");
    el.stopAppBtn.textContent = t("app.stop", "Stop App");
    el.searchInput.placeholder = t("ui.search_placeholder", "Search games");

    el.sortSelect.options[0].text = t("ui.sort_title_asc", "Title A-Z");
    el.sortSelect.options[1].text = t("ui.sort_title_desc", "Title Z-A");
    el.sortSelect.options[2].text = t(
      "ui.sort_version_desc",
      "Newest update date",
    );
    el.sortSelect.options[3].text = t("ui.sort_size_desc", "Largest first");
    el.sortSelect.options[4].text = t("ui.sort_players_desc", "Most players");
    el.sortSelect.options[5].text = t(
      "ui.sort_sync_progress_asc",
      "Sync Progress 0-100%",
    );
    el.sortSelect.options[6].text = t(
      "ui.sort_sync_progress_desc",
      "Sync Progress 100-0%",
    );

    el.installedSelect.options[0].text = t("ui.filter_all", "All");
    el.installedSelect.options[1].text = t("ui.filter_installed", "Installed");
    el.installedSelect.options[2].text = t("ui.filter_missing", "Missing");
    el.installedSelect.options[3].text = t(
      "ui.filter_downloading",
      "Downloading",
    );
    el.installedSelect.options[4].text = t(
      "ui.filter_updates",
      "Updates Available",
    );
    if (el.installedSelect.options.length >= 6) {
      el.installedSelect.options[5].text = t("ui.filter_hidden", "Hidden");
    }
    renderGenreOptions();

    el.rescanBtn.textContent = t("ui.rescan", "Rescan");
    el.rescanBtn.title = t(
      "ui.rescan_help",
      "Rescan updates installed/missing state by checking local game folders and markers.",
    );
    el.installCheckBtn.textContent = t(
      "ui.install_check",
      "Re-Add Games to Sync",
    );
    if (el.labelGridSize) {
      el.labelGridSize.textContent = t("ui.tile_size", "Tile size");
    }
    if (el.gridSizeSelect) {
      el.gridSizeSelect.setAttribute(
        "aria-label",
        t("ui.tile_size", "Tile size"),
      );
      el.gridSizeSelect.options[0].text = t(
        "ui.tile_size_very_small",
        "Very small",
      );
      el.gridSizeSelect.options[1].text = t("ui.tile_size_small", "Small");
      el.gridSizeSelect.options[2].text = t("ui.tile_size_medium", "Medium");
      el.gridSizeSelect.options[3].text = t("ui.tile_size_big", "Big");
      el.gridSizeSelect.options[4].text = t(
        "ui.tile_size_very_big",
        "Very big",
      );
    }
    el.viewListBtn.textContent = t("ui.view_list", "List");
    el.viewGridBtn.textContent = t("ui.view_grid", "Grid");
    el.detailEmpty.textContent = t(
      "ui.detail_empty",
      "Select a game to view details.",
    );
    el.syncStart.textContent = t("sync.start", "Start Sync");
    el.syncStop.textContent = t("sync.stop", "Stop Sync");
    el.openLibrary.textContent = t("ui.open_library", "Open Library Folder");
    el.openGameFolder.textContent = t(
      "ui.open_game_folder",
      "Open Game Folder",
    );
    if (el.installAnywayBtn) {
      el.installAnywayBtn.textContent = t(
        "game.install_anyway",
        "Install Anyway",
      );
    }
    if (el.editLocalGameBtn) {
      el.editLocalGameBtn.textContent = t(
        "game.edit_local_game",
        "Edit Local Game",
      );
    }
    if (el.labelDetailLinuxRuntime) {
      el.labelDetailLinuxRuntime.textContent = t(
        "game.detail_linux_runtime_label",
        "Runtime for this game",
      );
    }
    if (el.detailLinuxRuntimeSelect) {
      el.detailLinuxRuntimeSelect.options[0].text = t(
        "game.detail_linux_runtime_use_global",
        "Use global runtime",
      );
      el.detailLinuxRuntimeSelect.options[1].text = t(
        "settings.linux_runtime_native",
        "Native preferred",
      );
      el.detailLinuxRuntimeSelect.options[2].text = t(
        "settings.linux_runtime_wine",
        "Wine",
      );
      el.detailLinuxRuntimeSelect.options[3].text = t(
        "settings.linux_runtime_proton",
        "Proton",
      );
      el.detailLinuxRuntimeSelect.options[4].text = t(
        "settings.linux_runtime_proton_ge",
        "Proton GE",
      );
    }
    if (el.labelDetailLinuxLeaveTerminalOpenInline) {
      el.labelDetailLinuxLeaveTerminalOpenInline.textContent = t(
        "game.detail_linux_leave_terminal_open",
        "Leave terminal open after start",
      );
    }
    el.startGameBtn.textContent = t("game.start", "Start Game");
    el.startServerBtn.textContent = t("game.start_server", "Start Server");
    el.deleteGameBtn.textContent = t("game.delete", "Delete Game");
    if (el.installProtonCommonDepsBtn) {
      el.installProtonCommonDepsBtn.textContent = t(
        "game.install_prefix_common_deps_btn",
        "Install Common Prefix Dependencies",
      );
    }
    if (el.detailWinetricksTitle) {
      el.detailWinetricksTitle.textContent = t(
        "game.winetricks_title",
        "Prefix Dependencies",
      );
    }
    if (el.detailWinetricksNote) {
      el.detailWinetricksNote.textContent = t(
        "game.winetricks_note",
        "Select packages to install into this game prefix. Removal opens the prefix uninstaller.",
      );
    }
    if (el.detailWinetricksSelectCommon) {
      el.detailWinetricksSelectCommon.textContent = t(
        "game.winetricks_select_recommended",
        "Select Recommended For Game",
      );
    }
    if (el.detailWinetricksSelectAll) {
      el.detailWinetricksSelectAll.textContent = t(
        "game.winetricks_select_all",
        "Select All",
      );
    }
    if (el.detailWinetricksSelectNone) {
      el.detailWinetricksSelectNone.textContent = t(
        "game.winetricks_select_none",
        "Clear",
      );
    }
    if (el.detailWinetricksSaveBtn) {
      el.detailWinetricksSaveBtn.textContent = t(
        "game.winetricks_save_metadata",
        "Save current dependency config",
      );
    }
    if (el.detailWinetricksInstallBtn) {
      el.detailWinetricksInstallBtn.textContent = t(
        "game.winetricks_install_selected",
        "Install Selected",
      );
    }
    if (el.detailWinetricksRemoveBtn) {
      el.detailWinetricksRemoveBtn.textContent = t(
        "game.winetricks_open_uninstaller",
        "Open Prefix Uninstaller",
      );
    }
    if (el.detailLocalNote) {
      el.detailLocalNote.textContent = t(
        "game.local_detail_hint",
        "Local entries are not synced to the network.",
      );
    }
    renderDetailWinetricksPackages();

    if (el.tabHomeBtn) {
      el.tabHomeBtn.textContent = t("ui.tab_home", "Home");
    }
    if (el.tabStatusBtn) {
      el.tabStatusBtn.textContent = t("ui.tab_status", "Status");
    }
    if (el.statusTitle) {
      el.statusTitle.textContent = t("ui.tab_status", "Status");
    }
    if (el.tabProvidersBtn) {
      el.tabProvidersBtn.textContent = t(
        "ui.tab_providers",
        "Provider UIs",
      );
    }
    if (el.tabSettingsBtn) {
      el.tabSettingsBtn.textContent = t("ui.tab_settings", "Settings");
    }
    if (el.tabLogsBtn) {
      el.tabLogsBtn.textContent = t("ui.tab_logs", "Logs");
    }
    if (el.providersPanel) {
      el.providersPanel.setAttribute(
        "aria-label",
        t("ui.providers_title", "Provider UIs"),
      );
    }
    if (el.statusDescription) {
      el.statusDescription.textContent = t(
        "status.description",
        "Overall sync health, provider details, and live metrics.",
      );
    }
    if (el.statusProvidersTitle) {
      el.statusProvidersTitle.textContent = t(
        "status.providers_heading",
        "Provider details",
      );
    }
    if (el.statusProvidersDescription) {
      el.statusProvidersDescription.textContent = t(
        "status.providers_description",
        "Current state, process IDs, and errors for each sync provider.",
      );
    }
    if (el.providerOpenExternalBtn) {
      el.providerOpenExternalBtn.textContent = t(
        "ui.provider_open_external",
        "Open Provider Externally",
      );
    }
    if (el.providerFrameStatus) {
      el.providerFrameStatus.textContent = t(
        "ui.provider_embed_hint",
        "If the embedded view is blocked, open the provider externally.",
      );
    }
    if (el.providerTabs.ouisync) {
      el.providerTabs.ouisync.textContent = t("ui.provider_ouisync", "Ouisync");
    }
    const ouisyncCatalogTitle = document.getElementById("ouisync-catalog-title");
    if (ouisyncCatalogTitle) {
      ouisyncCatalogTitle.textContent = t("ui.ouisync_catalog_title", "Open Source Game Index");
    }
    const ouisyncRepositoriesTitle = document.getElementById("ouisync-repositories-title");
    if (ouisyncRepositoriesTitle) {
      ouisyncRepositoriesTitle.textContent = t("ui.ouisync_repositories_title", "Repositories");
    }
    const ouisyncDirectoryTitle = document.getElementById("ouisync-directory-title");
    if (ouisyncDirectoryTitle) {
      ouisyncDirectoryTitle.textContent = t("ui.ouisync_directory_title", "Repository contents");
    }
    if (el.ouisyncDirectoryUp) {
      el.ouisyncDirectoryUp.textContent = t("ui.ouisync_directory_up", "Up");
    }
    const ouiText = (id, key, fallback) => {
      const node = document.getElementById(id);
      if (node) node.textContent = t(key, fallback);
    };
    ouiText("ouisync-health-title", "ui.ouisync_health_title", "Ouisync status");
    ouiText("ouisync-settings-title", "ui.ouisync_settings_title", "Repository settings");
    ouiText("ouisync-setting-dht-label", "ui.ouisync_setting_dht", "DHT");
    ouiText("ouisync-setting-pex-label", "ui.ouisync_setting_pex", "Peer Exchange");
    ouiText("ouisync-setting-cache-label", "ui.ouisync_setting_cache", "Use Cache Servers");
    ouiText("ouisync-mount-title", "ui.ouisync_mount_title", "Read-only mount");
    ouiText("ouisync-mount-start", "ui.ouisync_mount_start", "Mount");
    ouiText("ouisync-mount-stop", "ui.ouisync_mount_stop", "Unmount");
    ouiText("ouisync-mount-force-stop", "ui.ouisync_mount_force_stop", "Force unmount");
    ouiText("ouisync-directory-up", "ui.ouisync_directory_arrow", "↑");
    if (el.ouisyncDirectoryUp) {
      el.ouisyncDirectoryUp.textContent = "↑";
      const upLabel = t("ui.ouisync_directory_up", "Up one directory");
      el.ouisyncDirectoryUp.title = upLabel;
      el.ouisyncDirectoryUp.setAttribute("aria-label", upLabel);
    }
    const copyTargetLabel = document.querySelector('label[for="ouisync-copy-target"]');
    if (copyTargetLabel) copyTargetLabel.textContent = t("ui.ouisync_copy_destination", "Copy destination directory");
    ouiText("ouisync-debug-health", "ui.ouisync_debug_health_button", "Check Ouisync");
    ouiText("ouisync-debug-seed", "ui.ouisync_debug_seed_button", "Check ng_provider");
    ouiText("ouisync-reset-seed", "ui.ouisync_debug_reset_button", "Reset and reconnect ng_provider");
    ouiText("ouisync-th-repository", "ui.ouisync_column_repository", "Repository");
    ouiText("ouisync-th-peers", "ui.ouisync_column_peers", "Peers");
    ouiText("ouisync-th-local", "ui.ouisync_column_local", "Local");
    ouiText("ouisync-th-size", "ui.ouisync_column_size", "Total blocks");
    ouiText("ouisync-th-download", "ui.ouisync_download", "Download");
    ouiText("ouisync-th-upload", "ui.ouisync_upload", "Upload");
    ouiText("ouisync-debug-modal-title", "ui.ouisync_debug_modal_title", "Ouisync diagnostics");
    ouiText("ouisync-peers-title", "ui.ouisync_peers_title", "Peers");
    ouiText("ouisync-nudge-sync", "ui.ouisync_nudge_button", "Nudge sync");
    if (el.ouisyncNudgeSync) el.ouisyncNudgeSync.title = t("ui.ouisync_nudge_hint", "Re-adds known peers, restarts the DHT lookup and reconnects this repository. LLNG also does this automatically when a repository still has no local block after 60 seconds.");
    ouiText("ouisync-peers-hint", "ui.ouisync_peers_session_hint", "Ouisync reports peers for the whole session, not per repository, so this list applies to all repositories.");
    ouiText("ouisync-peer-th-address", "ui.ouisync_peer_column_address", "Address");
    ouiText("ouisync-peer-th-source", "ui.ouisync_peer_column_source", "Source");
    ouiText("ouisync-peer-th-state", "ui.ouisync_peer_column_state", "State");
    ouiText("ouisync-peer-th-download", "ui.ouisync_download", "Download");
    ouiText("ouisync-peer-th-upload", "ui.ouisync_upload", "Upload");
    ouiText("ouisync-peer-th-received", "ui.ouisync_peer_column_received", "Received");
    ouiText("ouisync-peer-th-sent", "ui.ouisync_peer_column_sent", "Sent");
    ouiText("ouisync-peer-add-label", "ui.ouisync_peer_add_label", "Add peer manually (IP:port or quic/IP:port; Ouisync keeps it across restarts)");
    ouiText("ouisync-peer-add-button", "ui.ouisync_peer_add", "Add");
    ouiText("ouisync-debug-modal-close", "ui.close", "Close");

    el.settingsTitle.textContent = t("settings.title", "Settings");
    el.settingsSectionGeneralTitle.textContent = t(
      "settings.section_general",
      "General",
    );
    el.settingsSectionLibraryTitle.textContent = t(
      "settings.section_library_scan",
      "Library and Scan",
    );
    el.settingsSectionNetworkTitle.textContent = t(
      "settings.section_network_service",
      "Network and Service",
    );
    el.wizardTitle.textContent = t("wizard.title", "Welcome");
    el.wizardText.textContent = t(
      "wizard.text",
      "Please configure nickname and install path.",
    );
    el.wizardProviderGuidanceTitle.textContent = t(
      "wizard.provider_guidance_title",
      "Game distribution",
    );
    el.wizardProviderGlobal.textContent = t("wizard.provider_global");
    el.wizardProviderLegacy.textContent = t("wizard.provider_legacy");
    el.wizardProviderLan.textContent = t("wizard.provider_lan");
    el.wizardLabelNickname.textContent = t("settings.nickname", "Nickname");
    el.wizardNicknameInput.placeholder = t(
      "settings.nickname_placeholder",
      "Player name",
    );
    el.wizardLabelStorage.textContent =
      state.settings.platform === "windows"
        ? t("settings.storage_windows", "Windows drive letter")
        : t("settings.storage_linux", "Install path");
    if (state.settings.platform === "windows") {
      el.wizardStorageInput.placeholder = "D";
    } else {
      el.wizardStorageInput.placeholder = "/media/library";
    }
    el.wizardSaveBtn.textContent = t("wizard.save", "Save And Continue");
    if (!String(el.wizardConsole?.textContent || "").trim()) {
      setWizardConsoleLines([
        t(
          "wizard.console_idle",
          "Ready. Press Save And Continue to start setup.",
        ),
      ]);
    }
    el.labelAppVersion.textContent = t("settings.app_version", "Version");
    el.labelNickname.textContent = t("settings.nickname", "Nickname");
    el.nicknameInput.placeholder = t(
      "settings.nickname_placeholder",
      "Player name",
    );
    el.labelTheme.textContent = t("settings.theme", "Theme");
    el.themeSelect.options[0].text = t("settings.theme_dark", "Dark");
    el.themeSelect.options[1].text = t("settings.theme_light", "Light");
    el.labelLogLevel.textContent = t("settings.log_level", "Log level");
    el.logLevelSelect.options[0].text = t("settings.log_warning", "Warning");
    el.logLevelSelect.options[1].text = t("settings.log_error", "Error");
    el.logLevelSelect.options[2].text = t("settings.log_info", "Info");
    el.logLevelSelect.options[3].text = t("settings.log_debug", "Debug");
    if (el.logLevelSelect.options.length >= 5) {
      el.logLevelSelect.options[4].text = t(
        "settings.log_critical",
        "Critical",
      );
    }
    if (el.logsLevelLabel) {
      el.logsLevelLabel.textContent = t(
        "logs.log_level",
        "Live log level",
      );
    }
    if (el.logsLevelSelect?.options?.length >= 5) {
      el.logsLevelSelect.options[0].text = t("settings.log_warning", "Warning");
      el.logsLevelSelect.options[1].text = t("settings.log_error", "Error");
      el.logsLevelSelect.options[2].text = t("settings.log_info", "Info");
      el.logsLevelSelect.options[3].text = t("settings.log_debug", "Debug");
      el.logsLevelSelect.options[4].text = t(
        "settings.log_critical",
        "Critical",
      );
    }
    if (el.logsSourceFilterLabel) {
      el.logsSourceFilterLabel.textContent = t(
        "logs.source_filter",
        "Log source",
      );
    }
    if (el.logsLengthLabel) {
      el.logsLengthLabel.textContent = t("logs.length", "Log length");
    }
    if (el.logsLengthSelect?.options?.length >= 4) {
      el.logsLengthSelect.options[0].text = t("logs.length_200", "200 lines");
      el.logsLengthSelect.options[1].text = t("logs.length_500", "500 lines");
      el.logsLengthSelect.options[2].text = t("logs.length_1000", "1000 lines");
      el.logsLengthSelect.options[3].text = t("logs.length_2000", "2000 lines");
    }
    if (el.logsSourceFilterSelect?.options?.length >= 5) {
      el.logsSourceFilterSelect.options[0].text = t(
        "logs.filter_all",
        "All logs",
      );
      el.logsSourceFilterSelect.options[1].text = t(
        "logs.source_lanlauncherng",
        "LANLauncherNG",
      );
      el.logsSourceFilterSelect.options[2].text = t(
        "logs.source_resilio",
        "Resilio",
      );
      el.logsSourceFilterSelect.options[3].text = t(
        "logs.source_ouisync",
        "Ouisync",
      );
      el.logsSourceFilterSelect.options[4].text = t(
        "logs.source_unknown",
        "Unknown",
      );
    }
    el.labelAutoSync.textContent = t(
      "settings.auto_sync",
      "Auto-start sync on launch",
    );
    if (el.labelSyncOnlyMode) {
      el.labelSyncOnlyMode.textContent = t(
        "settings.sync_only_mode",
        "Sync archives only",
      );
    }
    if (el.labelLanMode) {
      el.labelLanMode.textContent = t(
        "settings.lan_mode",
        "Launcher mode",
      );
    }
    if (el.lanModeSelect?.options?.length >= 2) {
      el.lanModeSelect.options[0].text = t(
        "settings.lan_mode_client",
        "Client",
      );
      el.lanModeSelect.options[1].text = t(
        "settings.lan_mode_server",
        "Server",
      );
    }
    if (el.lanModeHint) {
      el.lanModeHint.textContent = t(
        "settings.lan_mode_hint",
        "Client mode manages game downloads on request. Server mode shares selected folders; new devices require explicit approval.",
      );
    }
    if (el.lanDiscoveryAddressLabel) el.lanDiscoveryAddressLabel.textContent = t("settings.lan_discovery_address", "Server IPv4 address (optional)");
    if (el.lanDiscoveryScan) el.lanDiscoveryScan.textContent = t("settings.lan_discovery_scan", "Find LAN servers");
    if (el.lanServerLabel) el.lanServerLabel.textContent = t("settings.lan_server_label", "Available servers");
    if (el.lanPairCodeLabel) el.lanPairCodeLabel.textContent = t("settings.lan_pair_code", "Approval code");
    if (el.lanPairConnect) el.lanPairConnect.textContent = t("settings.lan_pair_connect", "Connect to server");
    if (el.lanPairBegin) el.lanPairBegin.textContent = t("settings.lan_pair_begin", "Show approval code");
    if (el.lanPairRenew) el.lanPairRenew.textContent = t("settings.lan_pair_renew", "Renew approval code");
    if (el.lanServerSettingsTitle) el.lanServerSettingsTitle.textContent = t("settings.lan_server_settings_title", "LAN server settings");
    if (el.lanServerSettingsHint) el.lanServerSettingsHint.textContent = t("settings.lan_server_settings_hint", "These settings are shared with every connected client.");
    if (el.lanServerTitleLabel) el.lanServerTitleLabel.textContent = t("settings.lan_server_title", "LAN title");
    if (el.lanServerUrlLabel) el.lanServerUrlLabel.textContent = t("settings.lan_server_url", "LAN page URL");
    if (el.lanServerStatsUrlLabel) el.lanServerStatsUrlLabel.textContent = t("settings.lan_server_stats_url", "Statistics URL");
    if (el.lanServerDiscordUrlLabel) el.lanServerDiscordUrlLabel.textContent = t("settings.lan_server_discord_url", "Discord URL");
    if (el.lanServerTs3Label) el.lanServerTs3Label.textContent = t("settings.lan_server_ts3", "TeamSpeak address");
    if (el.lanServerLinksTitle) el.lanServerLinksTitle.textContent = t("settings.lan_server_links_title", "LAN links");
    if (el.lanServerAssetsTitle) el.lanServerAssetsTitle.textContent = t("settings.lan_server_assets_title", "Available games");
    if (el.lanServerAssetsHint) el.lanServerAssetsHint.textContent = t("settings.lan_server_assets_hint", "Unchecked games are hidden on clients until already installed there.");
    if (el.lanServerSettingsSave) el.lanServerSettingsSave.textContent = t("settings.lan_server_save", "Save server settings");
    for (const label of el.lanServerLinksList?.querySelectorAll("[data-link-label-text]") || []) {
      const index = Number(String(label.dataset.linkLabelText || "").replace("link_", ""));
      if (label.firstChild) label.firstChild.textContent = t("settings.lan_server_link_label", "Link {n} label").replace("{n}", String(index));
    }
    for (const label of el.lanServerLinksList?.querySelectorAll("[data-link-url-text]") || []) {
      const index = Number(String(label.dataset.linkUrlText || "").replace("link_", ""));
      if (label.firstChild) label.firstChild.textContent = t("settings.lan_server_link_url", "Link {n} URL").replace("{n}", String(index));
    }
    for (const checkbox of el.lanServerAssetsList?.querySelectorAll("input[data-game-id]") || []) {
      const asset = state.lanServerSettings.assets.find(
        (item) => String(item?.game_id || "").toLowerCase() === String(checkbox.dataset.gameId || "").toLowerCase(),
      );
      const title = checkbox.parentElement?.querySelector("span");
      if (title) {
        title.textContent = localizedText(
          { en: asset?.title_en, de: asset?.title_de },
          state.locale,
        ) || String(asset?.game_id || "");
      }
    }
    el.labelStorage.textContent =
      state.settings.platform === "windows"
        ? t("settings.storage_windows", "Windows drive letter")
        : t("settings.storage_linux", "Install path");
    if (el.labelOuisyncStorage) {
      el.labelOuisyncStorage.textContent = t(
        "settings.ouisync_storage_path",
        "Ouisync repository storage (optional)",
      );
      el.ouisyncStorageInput.placeholder = t(
        "settings.ouisync_storage_path_placeholder",
        "Leave empty to use the install path",
      );
    }
    el.storageInput.placeholder =
      state.settings.platform === "windows" ? "D" : "/media/library";
    if (el.labelLinuxRuntime) {
      el.labelLinuxRuntime.textContent = t(
        "settings.linux_runtime",
        "Windows runtime on Linux",
      );
    }
    if (el.linuxRuntimeSelect) {
      el.linuxRuntimeSelect.options[0].text = t(
        "settings.linux_runtime_native",
        "Native preferred",
      );
      el.linuxRuntimeSelect.options[1].text = t(
        "settings.linux_runtime_wine",
        "Wine",
      );
      el.linuxRuntimeSelect.options[2].text = t(
        "settings.linux_runtime_proton",
        "Proton",
      );
      el.linuxRuntimeSelect.options[3].text = t(
        "settings.linux_runtime_proton_ge",
        "Proton GE",
      );
    }
    if (el.labelLinuxProtonPath) {
      el.labelLinuxProtonPath.textContent = t(
        "settings.linux_proton_path",
        "Proton path",
      );
    }
    if (el.linuxProtonPathInput) {
      el.linuxProtonPathInput.placeholder = t(
        "settings.linux_proton_path_placeholder",
        "proton",
      );
    }
    if (el.labelLinuxProtonGePath) {
      el.labelLinuxProtonGePath.textContent = t(
        "settings.linux_proton_ge_path",
        "Proton GE path",
      );
    }
    if (el.linuxProtonGePathInput) {
      el.linuxProtonGePathInput.placeholder = t(
        "settings.linux_proton_ge_path_placeholder",
        "/opt/proton-ge/proton",
      );
    }
    el.saveSettingsBtn.textContent = t("settings.save", "Save Settings");
    el.updateRollbackBtn.textContent = t(
      "settings.update_rollback_btn",
      "Rollback Last Update",
    );
    el.installPrereqBtn.textContent = t(
      "settings.install_prereq_btn",
      "Install the Pre-Requirements Bundle",
    );
    if (el.installWineCommonDepsBtn) {
      el.installWineCommonDepsBtn.textContent = t(
        "settings.install_wine_common_deps_btn",
        "Install Common Wine Dependencies",
      );
    }
    el.syncModeLanBtn.textContent = t(
      "settings.sync_mode_lan_btn",
      "Resilio LAN Mode",
    );
    el.syncModeInternetBtn.textContent = t(
      "settings.sync_mode_internet_btn",
      "Resilio Internet Mode",
    );
    el.setNetworkPrivateBtn.textContent = t(
      "settings.network_private_btn",
      "Set Local Network To Private",
    );
    el.extraSyncTitle.textContent = t(
      "settings.extra_sync_title",
      "Provider",
    );
    el.extraSyncAddBtn.textContent = t(
      "settings.extra_sync_add",
      "Add Provider",
    );
    el.extraSyncImportBtn.textContent = t(
      "settings.provider_import_bootstrap",
      "Import bootstrap.json",
    );
    el.extraSyncModalTitle.textContent = t(
      "settings.extra_sync_modal_add",
      "Add Provider",
    );
    if (el.localGameModalTitle) {
      el.localGameModalTitle.textContent = t(
        "game.local_modal_add_title",
        "Add Local Game",
      );
    }
    if (el.localGameModalNote) {
      el.localGameModalNote.textContent = t(
        "game.local_modal_note",
        "Local entries are stored in the launcher database and are not synced to the network.",
      );
    }
    if (el.localGameCancelBtn) {
      el.localGameCancelBtn.textContent = t("ui.cancel", "Cancel");
    }
    if (el.localGameSaveBtn) {
      el.localGameSaveBtn.textContent = t(
        "game.local_modal_save",
        "Save Local Game",
      );
    }
    if (el.localGameLabelId) el.localGameLabelId.textContent = t("game.local_field_id", "Game ID");
    if (el.localGameLabelTitleEn) el.localGameLabelTitleEn.textContent = t("game.local_field_title_en", "Title (EN)");
    if (el.localGameLabelTitleDe) el.localGameLabelTitleDe.textContent = t("game.local_field_title_de", "Title (DE)");
    if (el.localGameLabelGenre) el.localGameLabelGenre.textContent = t("ui.genre", "Genre");
    if (el.localGameLabelReleaseYear) el.localGameLabelReleaseYear.textContent = t("game.local_field_release_year", "Release Year");
    if (el.localGameLabelPublisher) el.localGameLabelPublisher.textContent = t("game.local_field_publisher", "Publisher");
    if (el.localGameLabelSize) el.localGameLabelSize.textContent = t("game.local_field_size", "Size (GB)");
    if (el.localGameLabelMaxPlayers) el.localGameLabelMaxPlayers.textContent = t("game.local_field_max_players", "Max Players");
    if (el.localGameLabelVersion) el.localGameLabelVersion.textContent = t("game.local_field_version", "Version");
    if (el.localGameLabelStartFile) el.localGameLabelStartFile.textContent = t("game.local_field_start_file", "Start File");
    if (el.localGameLabelStartArgs) el.localGameLabelStartArgs.textContent = t("game.local_field_start_args", "Start Arguments");
    if (el.localGameLabelReadmeEn) el.localGameLabelReadmeEn.textContent = t("game.local_field_readme_en", "Description (EN)");
    if (el.localGameLabelReadmeDe) el.localGameLabelReadmeDe.textContent = t("game.local_field_readme_de", "Description (DE)");
    if (el.localGameLabelImage) el.localGameLabelImage.textContent = t("game.local_field_image", "Game Picture");
    if (el.serverCoverUrlLabel) el.serverCoverUrlLabel.textContent = t("game.server_cover_url", "Cover image URL");
    if (el.serverCoverDownloadBtn) el.serverCoverDownloadBtn.textContent = t("game.server_cover_download", "Download and resize cover");
    el.extraSyncLabelGameId.textContent = t(
      "settings.extra_sync_game_id",
      "Game-ID",
    );
    el.extraSyncLabelKey.textContent = t(
      "settings.extra_sync_game_key",
      "Game-Key",
    );
    el.extraSyncLabelTitleEn.textContent = t(
      "settings.extra_sync_title_en",
      "Title (EN)",
    );
    el.extraSyncLabelTitleDe.textContent = t(
      "settings.extra_sync_title_de",
      "Title (DE)",
    );
    el.extraSyncLabelReleaseYear.textContent = t(
      "settings.extra_sync_release_year",
      "Release Year",
    );
    el.extraSyncLabelPublisher.textContent = t(
      "settings.extra_sync_publisher",
      "Publisher",
    );
    el.extraSyncLabelSize.textContent = t(
      "settings.extra_sync_size",
      "Size (GB)",
    );
    el.extraSyncLabelPersons.textContent = t(
      "settings.extra_sync_persons",
      "Persons",
    );
    el.extraSyncLabelVersion.textContent = t(
      "settings.extra_sync_version",
      "Version",
    );
    el.extraSyncLabelReadmeEn.textContent = t(
      "settings.extra_sync_readme_en",
      "Description (EN)",
    );
    el.extraSyncLabelReadmeDe.textContent = t(
      "settings.extra_sync_readme_de",
      "Description (DE)",
    );
    el.extraSyncLabelMasterRequired.textContent = t(
      "settings.extra_sync_master_required",
      "Master Required",
    );
    el.extraSyncLabelVisible.textContent = t(
      "settings.extra_sync_visible",
      "Visible in Game List",
    );
    el.extraSyncLabelEnabled.textContent = t(
      "settings.extra_sync_sync_enabled",
      "Sync Enabled",
    );
    el.extraSyncLabelProviderType.textContent = t(
      "settings.extra_sync_provider_type",
      "Provider Type",
    );
    if (el.extraSyncProviderType?.options?.length >= 2) {
      el.extraSyncProviderType.options[0].textContent = t(
        "settings.extra_sync_provider_type_ouisync",
        "Ouisync",
      );
      el.extraSyncProviderType.options[1].textContent = t(
        "settings.extra_sync_provider_type_resilio",
        "Resilio",
      );
    }
    el.extraSyncLabelIsProvider.textContent = t(
      "settings.extra_sync_is_provider",
      "Is Provider",
    );
    el.extraSyncLabelHasGameDb.textContent = t(
      "settings.extra_sync_has_game_db",
      "Has game.db",
    );
    el.extraSyncLabelPackedImagePath.textContent = t(
      "settings.extra_sync_packed_image_path",
      "Packed Image Path",
    );
    el.extraSyncPackedImagePath.placeholder = t(
      "settings.extra_sync_packed_image_path_placeholder",
      "image/images.rar",
    );
    el.extraSyncLabelPackedImagePassword.textContent = t(
      "settings.extra_sync_packed_image_password",
      "Packed Image Password",
    );
    el.extraSyncCancelBtn.textContent = t(
      "settings.extra_sync_cancel",
      "Cancel",
    );
    el.extraSyncSaveBtn.textContent = t("settings.extra_sync_save", "Save");
    el.serviceSyncStart.textContent = t(
      "sync.start_service",
      "Start Sync Service",
    );
    el.serviceSyncStop.textContent = t(
      "sync.stop_service",
      "Stop Sync Service",
    );
    el.serviceSyncWebui.textContent = t(
      "sync.open_status_details",
      "Open Status Details",
    );
    renderTopTrafficChart();
    el.logsTitle.textContent = t("logs.title", "Logs");
    el.logsPauseBtn.textContent = state.logsPaused
      ? t("logs.continue", "Continue")
      : t("logs.pause", "Pause");
    el.logsRefreshBtn.textContent = t("logs.refresh", "Refresh Logs");
    if (el.statusLanGamesTitle) {
      el.statusLanGamesTitle.textContent = t(
        "status.lan_games_title",
        "LAN games",
      );
    }
    if (el.statusLanGamesDescription) {
      el.statusLanGamesDescription.textContent = t(
        "status.lan_games_description",
        "Choose which local game folders to publish for this LAN event.",
      );
    }
    if (el.statusLanGamesRefreshBtn) {
      el.statusLanGamesRefreshBtn.textContent = t(
        "status.lan_refresh_folders",
        "Refresh Folder List",
      );
    }
    if (el.shutdownUpdateTitle) {
      el.shutdownUpdateTitle.textContent = t(
        "app.shutdown_update_title",
        "Applying Update",
      );
    }
    if (el.shutdownUpdateText) {
      el.shutdownUpdateText.textContent = t(
        "app.shutdown_update_text",
        "Applying a newer launcher version before shutdown.",
      );
    }
    if (el.shutdownUpdateStatus) {
      el.shutdownUpdateStatus.textContent = t(
        "app.shutdown_update_status_idle",
        "Waiting for updater status...",
      );
    }
    if (el.shutdownUpdateConfirmBtn) {
      el.shutdownUpdateConfirmBtn.textContent = t(
        "app.shutdown_update_confirm_close",
        "Close App",
      );
    }
    if (el.shutdownUpdateResumeBtn) {
      el.shutdownUpdateResumeBtn.textContent = t(
        "app.shutdown_update_resume",
        "Resume Update",
      );
    }
    if (el.shutdownUpdateAbortBtn) {
      el.shutdownUpdateAbortBtn.textContent = t(
        "app.shutdown_update_abort",
        "Abort Update",
      );
    }
    if (!state.shutdownUpdateLines.length) {
      setShutdownUpdateConsoleLines([
        t(
          "app.shutdown_update_console_idle",
          "Waiting for shutdown update session...",
        ),
      ]);
    }
    updateWizardStorageControl();
    renderExtraSyncItems();
    applyViewMode();
    updateWelcomeWizardState();
    updateDetailActionStates();
    updateDetailBadges();
    updateStartupScreen();
  }

  async function loadLocale(locale) {
    const raw = await fetch(`/app/locales/${locale}/ui.json`, {
      cache: "no-store",
    });
    if (!raw.ok) {
      throw new Error(`locale-load-failed:${locale}`);
    }
    state.dictionary = await raw.json();
    state.locale = locale;
    localStorage.setItem("llng.locale", locale);
    el.localeSelect.value = locale;
    applyStaticText();
  }

  async function waitForBackendReady(maxAttempts = 80, delayMs = 150) {
    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      try {
        const raw = await fetch("/health", {
          cache: "no-store",
        });
        if (raw.ok) {
          const payload = await raw.json();
          if (String(payload?.status || "").toLowerCase() === "ok") {
            return true;
          }
        }
      } catch (_err) {
        // Backend may still be warming up while static UI is already being served.
      }
      await new Promise((resolve) => window.setTimeout(resolve, delayMs));
    }
    return false;
  }

  async function loadSettings() {
    let payload = await apiGet("/settings");
    let nextSettings = payload.settings || state.settings;
    // The backend serves static assets before bootstrap has finished. Retry once
    // the service reports platform "unknown" so the welcome wizard does not
    // temporarily fall back to the Linux-style path field on Windows.
    if (String(nextSettings.platform || "").toLowerCase() === "unknown") {
      const ready = await waitForBackendReady(20, 150);
      if (ready) {
        payload = await apiGet("/settings");
        nextSettings = payload.settings || nextSettings;
      }
    }
    state.settings = nextSettings;
    state.settings.provider_interfaces = Array.isArray(
      nextSettings.provider_interfaces,
    )
      ? nextSettings.provider_interfaces
      : [];
    state.backendReady = true;
    await loadStorageLocations();
    await loadExtraSyncItems();
    applyTheme(state.settings.theme);
    applySettingsToForm();
    applyStaticText();
    setActiveTab(state.activeTab, false);
    setActiveStatusProvider(state.activeStatusProvider, false);
    setActiveProviderTab(state.activeProviderTab, false);
    renderTopProviderBadges();
    renderStatusPanel();
    if (state.activeTab === "providers") {
      refreshProviderPanel();
    }
  }

  async function loadLauncherSite() {
    const priorPolicy = `${Boolean(state.launcherSite?.managed_by_lan_server)}:${launcherDisabledGameSet().size}:${[...launcherDisabledGameSet()].sort().join(",")}`;
    try {
      const payload = await apiGet("/launcher-site");
      const site = payload?.launcher_site || {};
      state.launcherSite = {
        ...state.launcherSite,
        ...site,
      };
    } catch (_err) {
      // Keep last known launcher-site state on transient connectivity failures.
    }
    const currentDisabled = launcherDisabledGameSet();
    const nextPolicy = `${Boolean(state.launcherSite?.managed_by_lan_server)}:${currentDisabled.size}:${[...currentDisabled].sort().join(",")}`;
    state.catalogItems = filterVisibleCatalogItems(state.catalogItems);
    if (
      state.selectedGameId &&
      isGameDisabledByLauncher(state.selectedGameId)
    ) {
      state.selectedGameId = "";
      state.selectedGame = null;
      state.selectedGameProviderType = "";
      state.selectedGameLaunchSettings = {
        linux_runtime_override: "",
        linux_leave_terminal_open: false,
        effective_linux_runtime: "wine",
      };
      state.selectedGameWinetricksPackages = [];
      el.detailEmpty.hidden = false;
      el.detailCard.hidden = true;
      setLaunchConsoleLines([]);
      updateDetailLinuxRuntimeControl();
    }
    applyLauncherSiteBranding();
    renderLauncherLinksDropdown();
    if (priorPolicy !== nextPolicy) {
      loadCatalog().catch(() => {});
    }
  }

  async function loadVersion() {
    try {
      const payload = await apiGet("/version");
      el.appVersionValue.textContent = payload.version || "-";
    } catch (_err) {
      el.appVersionValue.textContent = "-";
    }
  }

  async function refreshUpdateAvailabilityHint() {
    try {
      const payload = await apiGet("/app/update/check");
      const update = payload?.update || {};
      state.updateAvailable = Boolean(update?.update_available);
    } catch (_err) {
      state.updateAvailable = false;
    }
    if (el.topUpdateHint) {
      el.topUpdateHint.hidden = !state.updateAvailable;
    }
    updateTopbarUpdateState();
  }

  function renderLogs(payload) {
    state.logsEntries = buildLogEntries(payload);
    renderLogsFromCache();
  }

  async function loadLogs(force = false) {
    if (state.logsPaused && !force) {
      return;
    }
    if (state.logsLoading) return;
    state.logsLoading = true;
    try {
      const payload = await apiGet(
        `/logs?limit=${normalizeLogLimit(state.logsLimit)}`,
      );
      renderLogs(payload?.logs || {});
    } catch (_err) {
      if (!state.logsEntries.length) {
        el.logsOutput.textContent = t("logs.load_failed", "Could not load logs.");
      }
    } finally {
      state.logsLoading = false;
    }
  }

  function onLogsSourceFilterChange(event) {
    state.logsSourceFilter = normalizeLogFilter(event.target.value);
    localStorage.setItem("llng.logs_source_filter", state.logsSourceFilter);
    renderLogsFromCache();
  }

  function onLogsLimitChange(event) {
    state.logsLimit = normalizeLogLimit(event.target.value);
    localStorage.setItem("llng.logs_limit", state.logsLimit);
    loadLogs(true).catch(() => {});
  }

  async function onLogsLevelChange(event) {
    const level = String(event.target.value || "").trim().toUpperCase();
    if (!level) {
      return;
    }
    try {
      const payload = await apiPost("/app/log-level", { level });
      const settings = payload?.result?.settings || {};
      state.settings = {
        ...state.settings,
        ...settings,
      };
      if (el.logLevelSelect) {
        el.logLevelSelect.value = state.settings.log_level || level;
      }
      if (el.logsLevelSelect) {
        el.logsLevelSelect.value = state.settings.log_level || level;
      }
      el.settingsStatus.textContent = t(
        "logs.level_updated",
        "Log level updated.",
      );
    } catch (_err) {
      if (el.logsLevelSelect) {
        el.logsLevelSelect.value = state.settings.log_level || "WARNING";
      }
      if (el.logLevelSelect) {
        el.logLevelSelect.value = state.settings.log_level || "WARNING";
      }
      el.settingsStatus.textContent = t(
        "logs.level_update_failed",
        "Log level could not be updated.",
      );
    }
  }

  function renderGenreOptions() {
    if (!el.genreSelect) {
      return;
    }
    const selectedId = String(state.genreId || "all");
    el.genreSelect.innerHTML = "";

    const allOption = document.createElement("option");
    allOption.value = "all";
    allOption.textContent = t("ui.filter_genre_all", "All genres");
    el.genreSelect.append(allOption);

    for (const genre of state.genres) {
      const id = Number(genre?.id || 0);
      if (!Number.isFinite(id) || id <= 0) {
        continue;
      }
      const option = document.createElement("option");
      option.value = String(id);
      option.textContent = String(genre?.name || "").trim() || String(id);
      el.genreSelect.append(option);
    }

    const availableValues = new Set(
      Array.from(el.genreSelect.options).map((option) => option.value),
    );
    state.genreId = availableValues.has(selectedId) ? selectedId : "all";
    el.genreSelect.value = state.genreId;
    renderLocalGameGenreOptions(el.localGameGenre?.value || "");
  }

  async function loadGenres() {
    try {
      const payload = await apiGet(`/catalog/genres?locale=${state.locale}`);
      state.genres = Array.isArray(payload?.items) ? payload.items : [];
    } catch (_err) {
      state.genres = [];
    }
    renderGenreOptions();
  }

  function buildCatalogQuery() {
    const params = new URLSearchParams();
    params.set("locale", state.locale);
    params.set("q", state.query);
    // Sync progress sort is resolved from live sync-status polling on frontend.
    params.set("sort", state.sort === "sync_progress" ? "title" : state.sort);
    params.set("order", state.order);
    params.set("page", String(state.page));
    params.set("page_size", String(state.pageSize));
    if (state.installed === "hidden") {
      params.set("visibility", "hidden");
    } else if (state.installed !== "all" && state.installed !== "downloading") {
      params.set("installed", state.installed);
    }
    if (state.genreId !== "all") {
      params.set("genre_id", state.genreId);
    }
    return `/catalog/games?${params.toString()}`;
  }

  function sortBySyncProgressEnabled() {
    return state.sort === "sync_progress";
  }

  function effectiveInstallState(item) {
    const gameId = String(item?.id || "");
    const sync = state.listSyncStatus?.[gameId] || {};
    const catalogState = String(item?.install_state || "missing").toLowerCase();
    const syncState = String(
      sync.sync_state || sync.install_state || "",
    ).toLowerCase();
    if (syncState === "installing" || syncState === "downloading") {
      return syncState;
    }
    return catalogState;
  }

  function effectiveSyncState(item) {
    const gameId = String(item?.id || "");
    const sync = state.listSyncStatus?.[gameId] || {};
    return String(
      sync.sync_state || item?.sync_state || item?.install_state || "",
    ).toLowerCase();
  }

  function itemMatchesInstalledFilter(item) {
    if (state.installed === "hidden") {
      return true;
    }
    if (state.installed === "all") {
      return true;
    }
    const installState = effectiveInstallState(item);
    if (state.installed === "downloading") {
      return installState === "downloading";
    }
    if (state.installed === "installed") {
      return installState === "installed";
    }
    if (state.installed === "missing") {
      return installState !== "installed";
    }
    if (state.installed === "updates") {
      return installState === "installed" && Boolean(item?.needs_update);
    }
    return true;
  }

  function listSyncProgressState(item) {
    const gameId = String(item?.id || "");
    const sync = state.listSyncStatus?.[gameId] || {};
    const progress = Math.max(
      0,
      Math.min(100, Number(sync.progress_percent || 0)),
    );
    const installState = effectiveInstallState(item);
    const showForState =
      installState === "installed" ||
      installState === "downloading" ||
      isSyncing(sync.sync_state);
    const active = Boolean(sync.active);
    return {
      show: showForState && active,
      progress_percent: progress,
    };
  }

  function sortCatalogItemsBySyncProgress(items, order) {
    const normalizedOrder =
      String(order || "asc").toLowerCase() === "desc" ? "desc" : "asc";
    return [...items].sort((a, b) => {
      const aState = listSyncProgressState(a);
      const bState = listSyncProgressState(b);
      if (aState.show !== bState.show) {
        return aState.show ? -1 : 1;
      }
      if (aState.show && bState.show) {
        if (aState.progress_percent !== bState.progress_percent) {
          return normalizedOrder === "desc"
            ? bState.progress_percent - aState.progress_percent
            : aState.progress_percent - bState.progress_percent;
        }
      }
      return String(a?.title || "").localeCompare(String(b?.title || ""));
    });
  }

  function catalogItemsForRender() {
    const items = (
      Array.isArray(state.catalogItems) ? state.catalogItems : []
    ).filter(itemMatchesInstalledFilter);
    if (!sortBySyncProgressEnabled()) {
      return items;
    }
    return sortCatalogItemsBySyncProgress(items, state.order);
  }

  function createLocalGameTile() {
    const li = document.createElement("li");
    li.className = "game-card game-card-add-local";
    li.dataset.gameId = "__add_local_game__";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "game-card-btn game-card-btn-add-local";
    btn.setAttribute(
      "aria-label",
      t("game.add_local_game", "Add local game"),
    );
    const symbol = document.createElement("span");
    symbol.className = "game-card-add-symbol";
    symbol.textContent = "+";
    const overlay = document.createElement("div");
    overlay.className = "game-card-overlay game-card-overlay-add-local";
    const title = document.createElement("span");
    title.className = "game-title";
    title.textContent = t("game.add_local_game", "Add local game");
    const note = document.createElement("span");
    note.className = "meta-badge";
    note.textContent = t(
      "game.add_local_game_hint",
      "Create a local launcher entry",
    );
    overlay.append(title, note);
    btn.append(symbol, overlay);
    btn.addEventListener("click", () => openLocalGameModal(null));
    li.append(btn);
    return li;
  }

  function hideCatalogContextMenu() {
    if (!el.catalogContextMenu) {
      return;
    }
    el.catalogContextMenu.hidden = true;
    el.catalogContextMenu.replaceChildren();
  }

  function catalogContextMenuButton(label, action) {
    const button = document.createElement("button");
    button.type = "button";
    button.setAttribute("role", "menuitem");
    button.textContent = label;
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      hideCatalogContextMenu();
      await action();
    });
    return button;
  }

  async function updateCatalogVisibility(item, hidden) {
    const gameId = String(item?.id || "").trim();
    if (!gameId) {
      return;
    }
    const title = String(item?.title || gameId);
    const confirmKey = hidden
      ? "game.catalog_hide_confirm"
      : "game.catalog_unhide_confirm";
    if (!window.confirm(t(confirmKey, "Update catalog visibility for {title}?").replace("{title}", title))) {
      return;
    }
    try {
      const response = await apiPost(
        `/catalog/games/${encodeURIComponent(gameId)}/visibility`,
        { hidden },
      );
      if (!response?.result?.ok) {
        throw new Error(response?.result?.message || "visibility_update_failed");
      }
      if (state.selectedGameId === gameId && hidden) {
        state.selectedGameId = "";
        state.selectedGame = null;
        el.detailEmpty.hidden = false;
        el.detailCard.hidden = true;
      }
      await loadCatalog();
    } catch (err) {
      el.settingsStatus.textContent = `${t(
        "game.catalog_visibility_failed",
        "Catalog visibility could not be updated.",
      )} (${String(err?.message || "error")})`;
    }
  }

  async function deleteCatalogEntry(item) {
    const gameId = String(item?.id || "").trim();
    if (!gameId) {
      return;
    }
    const title = String(item?.title || gameId);
    if (!window.confirm(t(
      "game.catalog_delete_local_confirm",
      "Delete the local entry for {title}? Game data will be preserved.",
    ).replace("{title}", title))) {
      return;
    }
    try {
      const response = await apiGet(
        `/catalog/games/${encodeURIComponent(gameId)}/delete`,
      );
      if (!response?.result?.ok) {
        throw new Error(response?.result?.message || "delete_failed");
      }
      if (state.selectedGameId === gameId) {
        state.selectedGameId = "";
        state.selectedGame = null;
        el.detailEmpty.hidden = false;
        el.detailCard.hidden = true;
      }
      await loadCatalog();
    } catch (err) {
      el.settingsStatus.textContent = `${t(
        "game.catalog_delete_failed",
        "Game entry could not be deleted.",
      )} (${String(err?.message || "error")})`;
    }
  }

  function showCatalogContextMenu(item, event) {
    if (!el.catalogContextMenu || !item?.id) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    const hidden = Boolean(item.hidden);
    const isLocal = String(item.game_provider_type || "").toLowerCase() === "local";
    el.catalogContextMenu.replaceChildren();
    el.catalogContextMenu.append(
      catalogContextMenuButton(
        t(hidden ? "game.catalog_unhide" : "game.catalog_hide", hidden ? "Show again" : "Hide permanently"),
        () => updateCatalogVisibility(item, !hidden),
      ),
    );
    if (isLocal) {
      el.catalogContextMenu.append(
        catalogContextMenuButton(
          t("game.catalog_delete_local", "Delete local entry"),
          () => deleteCatalogEntry(item),
        ),
      );
    }
    const menuWidth = 220;
    const menuHeight = isLocal ? 90 : 52;
    el.catalogContextMenu.style.left = `${Math.max(8, Math.min(event.clientX, window.innerWidth - menuWidth - 8))}px`;
    el.catalogContextMenu.style.top = `${Math.max(8, Math.min(event.clientY, window.innerHeight - menuHeight - 8))}px`;
    el.catalogContextMenu.hidden = false;
  }

  async function refreshCatalogSyncProgress() {
    if (state.listSyncPollBusy) {
      return;
    }
    if (shouldShowWelcomeWizard()) {
      return;
    }
    if (!Array.isArray(state.catalogItems) || state.catalogItems.length === 0) {
      state.listSyncStatus = {};
      return;
    }
    state.listSyncPollBusy = true;
    try {
      const gameIds = state.catalogItems
        .filter(
          (item) =>
            String(item?.game_provider_type || "").trim().toLowerCase() !==
            "local",
        )
        .map((item) => String(item?.id || ""))
        .filter((id) => id.length > 0);
      const nextStatus = { ...state.listSyncStatus };
      const concurrency = 8;
      for (let index = 0; index < gameIds.length; index += concurrency) {
        const batch = gameIds.slice(index, index + concurrency);
        const requests = batch.map((gameId) =>
          apiGet(`/catalog/games/${encodeURIComponent(gameId)}/sync-status`)
            .then((payload) => ({ gameId, result: payload?.result || {} }))
            .catch(() => ({ gameId, result: null })),
        );
        const settled = await Promise.all(requests);
        for (const row of settled) {
          if (!row || !row.gameId || !row.result) {
            continue;
          }
          nextStatus[row.gameId] = {
            active: Boolean(row.result.active),
            progress_percent: Math.max(
              0,
              Math.min(100, Number(row.result.progress_percent || 0)),
            ),
            install_state: String(row.result.install_state || "").toLowerCase(),
            sync_state: String(
              row.result.sync_state || row.result.install_state || "",
            ).toLowerCase(),
          };
        }
      }
      state.listSyncStatus = nextStatus;
      renderGameList(catalogItemsForRender());
    } finally {
      state.listSyncPollBusy = false;
    }
  }

  function renderGameList(items) {
    el.gameList.innerHTML = "";

    for (const item of items) {
      const li = document.createElement("li");
      li.className = state.viewMode === "grid" ? "game-card" : "game-row";
      li.dataset.gameId = item.id;
      // The global guard permits native/custom menus only on explicit opt-in areas.
      li.dataset.contextMenuEnabled = "true";
      li.classList.toggle("is-selected", item.id === state.selectedGameId);
      const installState = effectiveInstallState(item);
      const syncState = effectiveSyncState(item);
      const installed = isInstalled(installState);
      const readyToInstall = isReadyToInstall(syncState);
      const visuallyInstalled = installed || readyToInstall;
      const installing = isInstalling(installState);
      li.classList.toggle("installed", visuallyInstalled);
      li.classList.toggle("not-installed", !visuallyInstalled);
      li.classList.toggle("is-installing", installing);

      const btn = document.createElement("button");
      btn.className =
        state.viewMode === "grid" ? "game-card-btn" : "game-row-btn";
      btn.type = "button";
      btn.setAttribute(
        "aria-label",
        `${t("ui.open_detail", "Open detail")}: ${item.title}`,
      );

      const image = document.createElement("img");
      image.className =
        state.viewMode === "grid" ? "game-card-image" : "game-thumb";
      image.src = gameImageUrl(item.id);
      image.alt = `${item.title} artwork`;
      image.loading = "lazy";
      image.decoding = "async";
      image.classList.toggle("grayscale", !visuallyInstalled);
      applyImageFallback(image);
      const downloading = isDownloading(installState);
      const spinnerOverlay = document.createElement("div");
      spinnerOverlay.className =
        state.viewMode === "grid"
          ? "download-overlay download-overlay-grid"
          : "download-overlay download-overlay-list";
      spinnerOverlay.hidden = !downloading;
      spinnerOverlay.innerHTML = `<span class="inline-spinner" aria-hidden="true"></span><span>${t("game.downloading", "Downloading")}</span>`;

      const title = document.createElement("span");
      title.className = "game-title";
      title.textContent = item.title;

      const playersBadge = document.createElement("span");
      playersBadge.className = "meta-badge";
      playersBadge.textContent = `${t("ui.players", "Players")}: ${item.max_players || "-"}`;

      const sizeBadge = document.createElement("span");
      sizeBadge.className = "meta-badge";
      sizeBadge.textContent = `${item.size_gb} GB`;

      const badges = document.createElement("div");
      badges.className = "meta-badges";
      badges.append(playersBadge, sizeBadge);
      if (String(item?.game_provider_type || "").toLowerCase() === "local") {
        const localBadge = document.createElement("span");
        localBadge.className = "meta-badge meta-badge-local";
        localBadge.textContent = t("game.local_label", "Local");
        badges.append(localBadge);
      }
      if (installing) {
        const installingBadge = document.createElement("span");
        installingBadge.className = "meta-badge installing-badge-inline";
        installingBadge.innerHTML = `<span class="inline-spinner" aria-hidden="true"></span>${t("game.installing", "Installing")}`;
        badges.append(installingBadge);
      } else if (isDownloading(installState)) {
        const downloadingBadge = document.createElement("span");
        downloadingBadge.className = "meta-badge";
        downloadingBadge.textContent = t("game.downloading", "Downloading");
        badges.append(downloadingBadge);
      } else if (readyToInstall) {
        const readyBadge = document.createElement("span");
        readyBadge.className = "meta-badge";
        readyBadge.textContent = t("game.fully_synced", "Fully synced");
        badges.append(readyBadge);
      } else if (item.needs_update) {
        const updateBadge = document.createElement("span");
        updateBadge.className = "update-badge";
        updateBadge.textContent = t(
          "game.update_available",
          "Update available",
        );
        badges.append(updateBadge);
      }

      if (state.viewMode === "grid") {
        const overlay = document.createElement("div");
        overlay.className = "game-card-overlay";
        overlay.append(title, badges);
        btn.append(image, spinnerOverlay, overlay);
      } else {
        const thumbWrap = document.createElement("div");
        thumbWrap.className = "game-thumb-wrap";
        thumbWrap.append(image, spinnerOverlay);
        const meta = document.createElement("span");
        meta.className = "game-meta";
        meta.textContent = item.genre || "-";
        const progressState = listSyncProgressState(item);
        const syncProgress = document.createElement("div");
        syncProgress.className = "list-sync-progress";
        syncProgress.hidden = !progressState.show;
        if (progressState.show) {
          const progressLabel = document.createElement("span");
          progressLabel.className = "list-sync-progress-label";
          progressLabel.textContent = `${t("sync.item_progress", "Sync progress")}: ${progressState.progress_percent}%`;
          const progressTrack = document.createElement("div");
          progressTrack.className = "list-sync-progress-track";
          const progressFill = document.createElement("div");
          progressFill.className = "list-sync-progress-fill";
          progressFill.style.width = `${progressState.progress_percent}%`;
          progressTrack.append(progressFill);
          syncProgress.append(progressLabel, progressTrack);
        }
        const textWrap = document.createElement("div");
        textWrap.className = "game-row-text";
        textWrap.append(title, meta, badges, syncProgress);
        btn.append(thumbWrap, textWrap);
      }

      btn.addEventListener("click", async () => {
        state.selectedGameId = item.id;
        highlightSelectedGameInList();
        await loadGameDetail(item.id);
      });

      li.addEventListener("contextmenu", (event) =>
        showCatalogContextMenu(item, event),
      );

      li.append(btn);
      el.gameList.append(li);
    }

    const localGameTile =
      state.viewMode === "grid" ? createLocalGameTile() : null;
    if (localGameTile && state.installed !== "hidden") {
      el.gameList.append(localGameTile);
    }

    if (!items.length && state.viewMode !== "grid") {
      const empty = document.createElement("li");
      empty.className = "empty-row";
      empty.textContent = t("ui.no_results", "No games found.");
      el.gameList.append(empty);
    }
    highlightSelectedGameInList();
  }

  function highlightSelectedGameInList() {
    const selectedId = String(state.selectedGameId || "");
    const rows = el.gameList.querySelectorAll(".game-row, .game-card");
    for (const row of rows) {
      const rowGameId = String(row.dataset.gameId || "");
      row.classList.toggle(
        "is-selected",
        !!selectedId && rowGameId === selectedId,
      );
    }
  }

  async function loadCatalog() {
    if (!state.catalogLoaded && state.catalogLoadAttempts < 10) {
      state.catalogLoadAttempts += 1;
      el.gameList.innerHTML = `<li class="empty-row">${t(
        "ui.catalog_loading",
        "Loading catalog...",
      )}</li>`;
    }
    try {
      const payload = await apiGet(buildCatalogQuery());
      if (state.catalogRetryTimer) {
        window.clearTimeout(state.catalogRetryTimer);
        state.catalogRetryTimer = 0;
      }
      state.catalogLoaded = true;
      state.catalogLoadAttempts = 0;
      state.total = payload.total || 0;
      state.catalogItems = filterVisibleCatalogItems(
        Array.isArray(payload.items) ? payload.items : [],
      );
      renderGameList(catalogItemsForRender());
      if (state.catalogSyncRefreshTimer) {
        window.clearTimeout(state.catalogSyncRefreshTimer);
      }
      state.catalogSyncRefreshTimer = window.setTimeout(() => {
        state.catalogSyncRefreshTimer = 0;
        refreshCatalogSyncProgress().catch(() => {});
      }, 0);
    } catch (err) {
      if (!state.catalogLoaded) {
        if (state.catalogLoadAttempts >= 10) {
          el.gameList.innerHTML = `<li class="empty-row">${t("ui.catalog_error", "Catalog unavailable.")}</li>`;
        } else {
          el.gameList.innerHTML = `<li class="empty-row">${t(
            "ui.catalog_loading",
            "Loading catalog...",
          )}</li>`;
        }
      }
      // Repository initialization can outlast the initial readiness window.
      // Keep retrying transient startup/network failures without replacing the
      // first-load progress message with an error immediately.
      if (!state.catalogRetryTimer) {
        state.catalogRetryTimer = window.setTimeout(() => {
          state.catalogRetryTimer = 0;
          loadCatalog().catch(() => {});
        }, !state.catalogLoaded && state.catalogLoadAttempts < 10 ? 900 : 3000);
      }
    }
  }

  async function loadSelectedGameLaunchSettings() {
    if (!state.selectedGameId) {
      state.selectedGameLaunchSettings = {
        linux_runtime_override: "",
        linux_leave_terminal_open: false,
        effective_linux_runtime: "wine",
      };
      state.selectedGameWinetricksPackages = [];
      renderDetailWinetricksPackages();
      updateDetailLinuxRuntimeControl();
      return;
    }
    try {
      const payload = await apiGet(
        `/catalog/games/${encodeURIComponent(state.selectedGameId)}/launch-settings`,
      );
      const result = payload?.result || {};
      state.selectedGameLaunchSettings = {
        linux_runtime_override: String(
          result.linux_runtime_override || "",
        ).toLowerCase(),
        linux_leave_terminal_open: Boolean(result.linux_leave_terminal_open),
        effective_linux_runtime: String(
          result.effective_linux_runtime || "wine",
        ).toLowerCase(),
      };
    } catch (_err) {
      state.selectedGameLaunchSettings = {
        linux_runtime_override: "",
        linux_leave_terminal_open: false,
        effective_linux_runtime: "wine",
      };
    }
    updateDetailLinuxRuntimeControl();
  }

  async function onDetailLinuxRuntimeChange() {
    if (
      !state.selectedGameId ||
      state.settings.platform !== "linux" ||
      !el.detailLinuxRuntimeSelect
    ) {
      return;
    }
    const override = String(
      el.detailLinuxRuntimeSelect.value || "",
    ).toLowerCase();
    const leaveTerminalOpen = Boolean(
      el.detailLinuxLeaveTerminalOpenCheckbox?.checked,
    );
    try {
      const payload = await apiPost(
        `/catalog/games/${encodeURIComponent(state.selectedGameId)}/launch-settings`,
        {
          linux_runtime_override: override,
          linux_leave_terminal_open: leaveTerminalOpen,
        },
      );
      const result = payload?.result || {};
      state.selectedGameLaunchSettings = {
        linux_runtime_override: String(
          result.linux_runtime_override || "",
        ).toLowerCase(),
        linux_leave_terminal_open: Boolean(result.linux_leave_terminal_open),
        effective_linux_runtime: String(
          result.effective_linux_runtime || "wine",
        ).toLowerCase(),
      };
      updateDetailLinuxRuntimeControl();
      el.settingsStatus.textContent = t(
        "game.launch_runtime_saved",
        "Game runtime setting saved.",
      );
    } catch (err) {
      await loadSelectedGameLaunchSettings();
      const backendMessage = String(err?.message || "error");
      el.settingsStatus.textContent = `${t(
        "game.launch_runtime_save_failed",
        "Game runtime setting could not be saved.",
      )} (${t(`game.error_${backendMessage}`, backendMessage)})`;
    }
  }

  async function onDetailLinuxLeaveTerminalOpenChange() {
    if (
      !state.selectedGameId ||
      state.settings.platform !== "linux" ||
      !el.detailLinuxLeaveTerminalOpenCheckbox
    ) {
      return;
    }
    const override = String(
      state.selectedGameLaunchSettings?.linux_runtime_override || "",
    ).toLowerCase();
    const leaveTerminalOpen = Boolean(
      el.detailLinuxLeaveTerminalOpenCheckbox.checked,
    );
    try {
      const payload = await apiPost(
        `/catalog/games/${encodeURIComponent(state.selectedGameId)}/launch-settings`,
        {
          linux_runtime_override: override,
          linux_leave_terminal_open: leaveTerminalOpen,
        },
      );
      const result = payload?.result || {};
      state.selectedGameLaunchSettings = {
        linux_runtime_override: String(
          result.linux_runtime_override || "",
        ).toLowerCase(),
        linux_leave_terminal_open: Boolean(result.linux_leave_terminal_open),
        effective_linux_runtime: String(
          result.effective_linux_runtime || "wine",
        ).toLowerCase(),
      };
      updateDetailLinuxRuntimeControl();
      el.settingsStatus.textContent = t(
        "game.launch_runtime_saved",
        "Game runtime setting saved.",
      );
    } catch (err) {
      await loadSelectedGameLaunchSettings();
      const backendMessage = String(err?.message || "error");
      el.settingsStatus.textContent = `${t(
        "game.launch_runtime_save_failed",
        "Game runtime setting could not be saved.",
      )} (${t(`game.error_${backendMessage}`, backendMessage)})`;
    }
  }

  async function loadSelectedGameSyncStatus() {
    if (!state.selectedGameId) {
      state.selectedGameSync = {
        active: false,
        progress_percent: 0,
        install_state: "missing",
        sync_state: "missing",
        installed: false,
        needs_update: false,
        down_eta: 0,
        down_speed: 0,
        upload_speed: 0,
        down_status: 0,
        install_console_lines: [],
      };
      updateDetailActionStates();
      return;
    }
    try {
      const [statusPayload, speedPayload] = await Promise.all([
        apiGet(
          `/catalog/games/${encodeURIComponent(state.selectedGameId)}/sync-status`,
        ),
        apiGet(
          `/sync/speed?game_id=${encodeURIComponent(state.selectedGameId)}`,
        ),
      ]);
      const payload = statusPayload;
      const result = payload?.result || {};
      const speed = normalizeTrafficSample(speedPayload?.speed || {});
      const previousInstallState = String(
        state.selectedGame?.install_state || "",
      ).toLowerCase();
      const previousNeedsUpdate = Boolean(state.selectedGame?.needs_update);
      const installConsoleLines = Array.isArray(result.install_console_lines)
        ? result.install_console_lines
            .map((line) => String(line || "").trim())
            .filter((line) => line.length > 0)
        : [];
      state.selectedGameSync = {
        active: Boolean(result.active),
        repository_present: Boolean(result.repository_present),
        progress_percent: Number(result.progress_percent || 0),
        install_state: String(result.install_state || "missing").toLowerCase(),
        sync_state: String(
          result.sync_state || result.install_state || "missing",
        ).toLowerCase(),
        installed: Boolean(result.installed),
        needs_update: Boolean(result.needs_update),
        down_eta: Number(result.down_eta || 0),
        down_speed: Number(speed.download_bps || result.down_speed || 0),
        upload_speed: Number(speed.upload_bps || 0),
        down_status: Number(result.down_status || 0),
        install_console_lines: installConsoleLines,
      };
      if (state.selectedGame) {
        state.selectedGame.install_state = state.selectedGameSync.install_state;
        state.selectedGame.needs_update = state.selectedGameSync.needs_update;
        state.selectedGame.installed_version = String(
          result.installed_version ||
            state.selectedGame.installed_version ||
            "",
        );
        state.selectedGame.version = String(
          result.version || state.selectedGame.version || "",
        );
        if (
          previousInstallState !== state.selectedGame.install_state ||
          previousNeedsUpdate !== state.selectedGame.needs_update
        ) {
          await loadCatalog();
        }
      }
      if (
        installConsoleLines.length > 0 &&
        (state.selectedGameSync.install_state === "installing" ||
          isReadyToInstall(state.selectedGameSync.sync_state))
      ) {
        setLaunchConsoleLines(installConsoleLines);
      } else if (
        state.selectedGameSync.sync_state === "downloading" ||
        state.selectedGameSync.sync_state === "syncing"
      ) {
        const downStatusLabel =
          state.selectedGameSync.down_status > 0
            ? t("sync.down_status_active", "downloading")
            : t("sync.down_status_idle", "idle");
        setLaunchConsoleLines([
          `${t("sync.down_speed", "Download speed")}: ${formatSpeed(state.selectedGameSync.down_speed)} | ${t("sync.upload_speed", "Upload speed")}: ${formatSpeed(state.selectedGameSync.upload_speed)} | ${t("sync.down_eta", "Download ETA")}: ${formatEta(state.selectedGameSync.down_eta)} | ${t("sync.down_status", "Download status")}: ${downStatusLabel} | ${t("sync.item_progress", "Sync progress")}: ${Math.max(0, Math.min(100, Number(state.selectedGameSync.progress_percent || 0)))}%`,
        ]);
      }
    } catch (_err) {
      // Keep the last known detail sync state on transient polling failures so
      // the progress bar does not jump to 0% between refresh ticks.
    }
    updateDetailArtworkState();
    updateDetailBadges();
    renderDetailMeta();
    updateDetailActionStates();
    highlightSelectedGameInList();
  }

  async function loadGameDetail(gameId) {
    if (isGameDisabledByLauncher(gameId)) {
      state.selectedGameId = "";
      state.selectedGame = null;
      state.selectedGameProviderType = "";
      state.selectedGameLaunchSettings = {
        linux_runtime_override: "",
        linux_leave_terminal_open: false,
        effective_linux_runtime: "wine",
      };
      el.detailEmpty.hidden = false;
      el.detailCard.hidden = true;
      setLaunchConsoleLines([]);
      updateDetailLinuxRuntimeControl();
      updateDetailBadges();
      updateDetailActionStates();
      return;
    }
    setLaunchConsoleLines([]);
    try {
      const payload = await apiGet(
        `/catalog/games/${encodeURIComponent(gameId)}?locale=${state.locale}`,
      );
      const previousSync =
        state.selectedGameId === gameId && state.selectedGameSync
          ? state.selectedGameSync
          : null;
      state.selectedGame = payload;
      state.selectedGameProviderType = String(
        payload.game_provider_type || "",
      ).toLowerCase();
      state.selectedGameSync = {
        active: Boolean(previousSync?.active),
        progress_percent: Number(previousSync?.progress_percent || 0),
        install_state: String(payload.install_state || "missing").toLowerCase(),
        sync_state: String(
          payload.sync_state || payload.install_state || "missing",
        ).toLowerCase(),
        installed: isInstalled(payload.install_state),
        needs_update: Boolean(payload.needs_update),
        down_eta: Number(previousSync?.down_eta || 0),
        down_speed: Number(previousSync?.down_speed || 0),
        down_status: Number(previousSync?.down_status || 0),
        install_console_lines: Array.isArray(
          previousSync?.install_console_lines,
        )
          ? previousSync.install_console_lines
          : [],
      };
      state.selectedGameStatus = {
        server_start_exists: false,
      };

      el.detailEmpty.hidden = true;
      el.detailCard.hidden = false;
      const metadataImage = String(payload?.metadata?.image || "").trim();
      const metadataVideo = String(payload?.metadata?.video || "").trim();
      const videoSrc = isRemoteHttpUrl(metadataVideo)
        ? metadataVideo
        : gameVideoUrl(payload.id);
      el.detailVideo.hidden = true;
      el.detailVideo.src = videoSrc;
      el.detailVideo.load();
      el.detailVideo.onloadeddata = () => {
        el.detailVideo.hidden = false;
        el.detailImage.hidden = true;
        const playPromise = el.detailVideo.play();
        if (playPromise && typeof playPromise.catch === "function") {
          playPromise.catch(() => {});
        }
      };
      el.detailVideo.onerror = () => {
        el.detailVideo.hidden = true;
        el.detailImage.hidden = false;
      };
      el.detailImage.hidden = false;
      el.detailImage.dataset.fallbackApplied = "0";
      el.detailImage.src = isRemoteHttpUrl(metadataImage)
        ? metadataImage
        : gameImageUrl(payload.id);
      el.detailImage.alt = `${payload.title} artwork`;
      updateDetailArtworkState();
      applyImageFallback(el.detailImage);
      el.detailGameTitle.textContent = payload.title;
      await ensureWinetricksCatalogLoaded();
      loadSelectedGameWinetricksPackages();
      try {
        const localStatusPayload = await apiGet(
          `/catalog/games/${encodeURIComponent(gameId)}/status-local`,
        );
        const details = localStatusPayload?.result?.details || {};
        state.selectedGameStatus.server_start_exists = Boolean(
          details.server_start_exists,
        );
      } catch (_err) {
        state.selectedGameStatus.server_start_exists = false;
      }
      updateDetailBadges();
      el.detailGenre.textContent = `${t("ui.genre", "Genre")}: ${payload.genre || "-"}`;
      await loadSelectedGameLaunchSettings();
      await loadSelectedGameSyncStatus();
      renderDetailMeta();
      renderDetailLinks();
      el.detailReadme.textContent =
        payload.readme || t("ui.no_readme", "No description available.");
      if (el.detailLocalNote) {
        el.detailLocalNote.textContent = t(
          "game.local_detail_hint",
          "Local entries are not synced to the network.",
        );
      }
      updateDetailActionStates();
    } catch (_err) {
      state.selectedGame = null;
      state.selectedGameLaunchSettings = {
        linux_runtime_override: "",
        linux_leave_terminal_open: false,
        effective_linux_runtime: "wine",
      };
      state.selectedGameWinetricksPackages = [];
      state.selectedGameSync = {
        active: false,
        progress_percent: 0,
        install_state: "missing",
        sync_state: "missing",
        installed: false,
        needs_update: false,
        down_eta: 0,
        down_speed: 0,
        upload_speed: 0,
        down_status: 0,
        install_console_lines: [],
      };
      if (el.detailLinks) {
        el.detailLinks.hidden = true;
      }
      if (el.detailLinksList) {
        el.detailLinksList.innerHTML = "";
      }
      state.selectedGameStatus = {
        server_start_exists: false,
      };
      el.detailEmpty.hidden = false;
      el.detailCard.hidden = true;
      setLaunchConsoleLines([]);
      updateDetailLinuxRuntimeControl();
      updateDetailArtworkState();
      updateDetailBadges();
      updateDetailActionStates();
    }
  }

  async function refreshSyncWidgets() {
    try {
      const [statusResult, speedResult, providersResult] = await Promise.allSettled([
        apiGet("/sync/status"),
        apiGet("/sync/speed"),
        apiGet("/sync/providers"),
      ]);
      const statusPayload =
        statusResult.status === "fulfilled" ? statusResult.value : null;
      const speedPayload =
        speedResult.status === "fulfilled" ? speedResult.value : null;
      const providerItems =
        providersResult.status === "fulfilled" &&
        Array.isArray(providersResult.value?.providers)
          ? providersResult.value.providers
          : null;
      state.syncRunning = Boolean(statusPayload?.sync?.running);
      const syncPid = Number(statusPayload?.sync?.pid);
      state.syncStatus = {
        provider: String(statusPayload?.sync?.provider || "none"),
        running: Boolean(statusPayload?.sync?.running),
        state: String(statusPayload?.sync?.state || "disabled"),
        pid: Number.isFinite(syncPid) ? syncPid : null,
        last_error: String(statusPayload?.sync?.last_error || ""),
      };
      el.syncState.textContent = `${t("sync.state", "sync")}: ${statusPayload?.sync?.state || t("sync.unavailable", "unavailable")}`;
      const trafficSample = normalizeTrafficSample(speedPayload?.speed || {});
      updateTopTrafficSample(trafficSample);
      el.syncSpeed.textContent = trafficSummaryText(trafficSample);
      if (providerItems) {
        state.settings.provider_interfaces = providerItems;
        renderTopProviderBadges();
        renderStatusPanel();
        if (state.activeTab === "providers") {
          refreshProviderPanel(false);
        }
      }
      if (!providerItems) {
        renderTopProviderBadges();
        renderStatusPanel();
      }
      if (state.activeTab === "status") {
        loadLanGameInventory().catch(() => {});
      }
      if (state.selectedGameId) {
        await loadSelectedGameSyncStatus();
      }
      updateDetailActionStates();
      if (state.viewMode === "list" || sortBySyncProgressEnabled()) {
        await refreshCatalogSyncProgress();
      }
      updateWelcomeWizardState();
    } catch (_err) {
      state.syncRunning = false;
      state.syncStatus = {
        provider: "none",
        running: false,
        state: "disabled",
        pid: null,
        last_error: "",
      };
      el.syncState.textContent = `${t("sync.state", "sync")}: ${t("sync.unavailable", "unavailable")}`;
      const fallbackSample = normalizeTrafficSample({});
      updateTopTrafficSample(fallbackSample);
      el.syncSpeed.textContent = trafficSummaryText(fallbackSample);
      renderTopProviderBadges();
      renderStatusPanel();
      if (state.activeTab === "status") {
        loadLanGameInventory().catch(() => {});
      }
      if (state.selectedGameId) {
        await loadSelectedGameSyncStatus();
      }
      if (state.viewMode === "list" || sortBySyncProgressEnabled()) {
        await refreshCatalogSyncProgress();
      }
      updateDetailActionStates();
      updateWelcomeWizardState();
    }
  }

  async function onRescan() {
    await apiGet("/catalog/scan?force=true");
    await loadCatalog();
  }

  async function onInstallCheck() {
    await startInstallCheckBackground(true);
  }

  async function refreshInstallStateBackground() {
    try {
      await apiGet("/catalog/scan?force=false");
      await loadCatalog();
      if (state.selectedGameId) {
        // Avoid full detail reload here to prevent transient progress reset flicker.
        await loadSelectedGameSyncStatus();
      }
    } catch (_err) {
      // Keep silent for periodic refresh.
    }
  }

  async function startInstallCheckBackground(refreshCatalogAfterStart = false) {
    if (state.rescanMonitorRunning || state.rescanStartBusy) {
      return;
    }
    state.rescanStartBusy = true;
    try {
      const payload = await apiGet("/catalog/rescan?force=true");
      const scan = payload.scan || {};
      if (refreshCatalogAfterStart) {
        await loadCatalog();
      }
      el.settingsStatus.textContent = `${t("settings.install_check_background_started", "Install check started in background.")} ${scan.installed || 0}/${scan.scanned || 0}`;
      pollRescanProgressInBackground().catch(() => {});
    } catch (_err) {
      el.settingsStatus.textContent = t(
        "settings.install_check_failed",
        "Install check failed.",
      );
    } finally {
      state.rescanStartBusy = false;
    }
  }

  async function pollRescanProgressInBackground() {
    if (state.rescanMonitorRunning) {
      return;
    }
    state.rescanMonitorRunning = true;
    const startedAt = Date.now();
    const timeoutMs = 5 * 60 * 1000;
    try {
      while (Date.now() - startedAt < timeoutMs) {
        let payload;
        try {
          payload = await apiGet("/catalog/rescan-status");
        } catch (_err) {
          return;
        }
        const sync = payload?.resync || {};
        const total = Number(sync.total || 0);
        const processed = Number(sync.processed || 0);
        const percent = Number(sync.percent || 0);
        const current = String(
          sync.current_title || sync.current_game_id || "",
        );
        if (sync.running) {
          if (current) {
            el.settingsStatus.textContent = `${t("settings.rescan_progress", "Resync")}: ${percent}% (${processed}/${total}) - ${current}`;
          } else {
            el.settingsStatus.textContent = `${t("settings.rescan_progress", "Resync")}: ${percent}% (${processed}/${total})`;
          }
          await new Promise((resolve) => window.setTimeout(resolve, 400));
          continue;
        }
        el.settingsStatus.textContent = `${t("settings.rescan_done", "Resync done")}: ${percent}% | ${t("settings.rescan_added", "added")} ${sync.added || 0}, ${t("settings.rescan_skipped", "skipped")} ${sync.skipped || 0}, ${t("settings.rescan_failed", "failed")} ${sync.failed || 0}`;
        await loadCatalog();
        if (state.selectedGameId) {
          await loadGameDetail(state.selectedGameId);
        }
        return;
      }
    } finally {
      state.rescanMonitorRunning = false;
    }
  }

  async function onSaveSettings(
    collapseWhenComplete = false,
    progressReporter = null,
  ) {
    const reportProgress = (key, fallback) => {
      if (typeof progressReporter !== "function") {
        return;
      }
      progressReporter(t(key, fallback));
    };
    reportProgress("wizard.console_saving_settings", "Saving settings...");
    reportProgress(
      "wizard.console_background_services",
      "Starting Background Provider Services ...",
    );
    const wasFirstRun =
      !state.settings.library_path_initialized ||
      String(state.settings.nickname || "").trim().length === 0;
    const isWindows = state.settings.platform === "windows";
    const storageValue = settingsStorageValue();
    const payload = {
      nickname: el.nicknameInput.value.trim(),
      theme: el.themeSelect.value,
      log_level: el.logLevelSelect.value,
      auto_start_sync: el.autoSyncCheckbox.checked,
      sync_only_mode: Boolean(el.syncOnlyModeCheckbox?.checked),
      lan_mode: String(
        el.lanModeSelect?.value || state.settings.lan_mode || "client",
      ),
      windows_game_drive_letter: isWindows
        ? storageValue.toUpperCase().slice(0, 1)
        : state.settings.windows_game_drive_letter,
      linux_install_path: isWindows
        ? state.settings.linux_install_path
        : storageValue,
      linux_windows_runtime:
        state.settings.platform === "linux"
          ? String(el.linuxRuntimeSelect?.value || "wine")
          : state.settings.linux_windows_runtime,
      linux_proton_path:
        state.settings.platform === "linux"
          ? String(el.linuxProtonPathInput?.value || "").trim()
          : state.settings.linux_proton_path,
      linux_proton_ge_path:
        state.settings.platform === "linux"
          ? String(el.linuxProtonGePathInput?.value || "").trim()
          : state.settings.linux_proton_ge_path,
      ouisync_storage_path: String(el.ouisyncStorageInput?.value || "").trim(),
    };

    try {
      const response = await apiPost("/settings", payload);
      reportProgress(
        "wizard.console_settings_saved",
        "Settings saved. Refreshing catalog...",
      );
      state.settings = response.result.settings;
      await loadStorageLocations();
      applyTheme(state.settings.theme);
      applySettingsToForm();
      applyStaticText();
      if (state.activeTab === "settings" && currentLanMode() === "client") scanLanServers().catch(() => {});
      el.settingsStatus.textContent = t("settings.saved", "Settings saved.");
      updateWelcomeWizardState();
      reportProgress(
        "wizard.console_scan_started",
        "Scanning installed games from local library...",
      );
      if (wasFirstRun) {
        await apiGet("/catalog/scan?force=true");
        await loadCatalog();
        if (state.selectedGameId) {
          await loadGameDetail(state.selectedGameId);
        }
        reportProgress(
          "wizard.console_catalog_ready",
          "Catalog loaded. Starting background sync reconciliation...",
        );
        startInstallCheckBackground(false).catch(() => {});
      } else {
        await apiGet("/catalog/scan?force=true");
        await loadCatalog();
        if (state.selectedGameId) {
          await loadGameDetail(state.selectedGameId);
        }
      }
      await refreshSyncWidgets();
      await loadLogs();
      return true;
    } catch (err) {
      el.settingsStatus.textContent = `${t("settings.save_failed", "Saving settings failed.")} (${err.message})`;
      reportProgress(
        "wizard.console_failed",
        "Setup failed. Please check your configuration and try again.",
      );
      return false;
    }
  }

  async function onWizardSave() {
    if (!el.wizardNicknameInput || !el.wizardStorageInput) {
      return;
    }
    el.wizardSaveBtn.disabled = true;
    el.wizardSaveBtn.classList.add("is-loading");
    el.wizardSaveBtn.setAttribute("aria-busy", "true");
    setWizardConsoleLines([t("wizard.console_start", "Setup started...")]);
    try {
      el.nicknameInput.value = el.wizardNicknameInput.value.trim();
      el.storageInput.value = wizardStorageValue();
      const ok = await onSaveSettings(true, appendWizardConsoleLine);
      if (!ok) {
        updateWelcomeWizardState();
        return;
      }
      if (isInitialSetupComplete()) {
        el.welcomeWizard.hidden = true;
      } else {
        updateWelcomeWizardState();
      }
    } finally {
      el.wizardSaveBtn.disabled = false;
      el.wizardSaveBtn.classList.remove("is-loading");
      el.wizardSaveBtn.setAttribute("aria-busy", "false");
    }
  }

  function onWizardEnterSubmit(event) {
    if (event.key !== "Enter") {
      return;
    }
    if (el.welcomeWizard?.hidden || el.wizardSaveBtn?.disabled) {
      return;
    }
    event.preventDefault();
    onWizardSave();
  }

  async function onSyncStart() {
    if (!state.selectedGameId) {
      return;
    }
    const payload = await apiGet(
      `/catalog/games/${encodeURIComponent(state.selectedGameId)}/sync-start`,
    );
    if (!payload?.result?.ok) {
      const detailKey = {
        lan_game_unavailable: "sync.lan_game_unavailable",
      }[String(payload?.result?.message || "")];
      el.settingsStatus.textContent = detailKey
        ? t(detailKey, "Could not start item sync.")
        : t("sync.item_start_failed", "Could not start item sync.");
    } else {
      el.settingsStatus.textContent = t(
        "sync.item_started",
        "Item sync started.",
      );
    }
    await loadSelectedGameSyncStatus();
    renderDetailMeta();
    await refreshSyncWidgets();
    await loadLogs();
    await loadCatalog();
  }

  async function onSyncStop() {
    if (!state.selectedGameId) {
      return;
    }
    const payload = await apiGet(
      `/catalog/games/${encodeURIComponent(state.selectedGameId)}/sync-stop`,
    );
    if (!payload?.result?.ok) {
      el.settingsStatus.textContent = t(
        "sync.item_stop_failed",
        "Could not stop item sync.",
      );
    } else {
      el.settingsStatus.textContent = t(
        "sync.item_stopped",
        "Item sync stopped.",
      );
    }
    await loadSelectedGameSyncStatus();
    renderDetailMeta();
    await refreshSyncWidgets();
    await loadLogs();
    await loadCatalog();
  }

  async function onSyncRemoveData() {
    if (!state.selectedGameId) return;
    const confirmed = window.confirm(
      t("sync.remove_downloaded_data_confirm", "Remove this game's downloaded Ouisync data? The installed game will remain."),
    );
    if (!confirmed) return;
    el.syncRemoveData.disabled = true;
    try {
      const payload = await apiGet(
        `/catalog/games/${encodeURIComponent(state.selectedGameId)}/sync-remove`,
      );
      if (!payload?.result?.ok) {
        el.settingsStatus.textContent = t(
          `status.error_${String(payload?.result?.message || "ouisync_error")}`,
          "Could not remove downloaded Ouisync data.",
        );
      } else {
        el.settingsStatus.textContent = t(
          "sync.remove_downloaded_data_done",
          "Downloaded Ouisync data removed. The installed game was kept.",
        );
      }
      await loadSelectedGameSyncStatus();
      await refreshSyncWidgets();
      await loadCatalog();
    } finally {
      updateDetailActionStates();
    }
  }

  async function onInstallAnyway() {
    if (!state.selectedGameId || !el.installAnywayBtn) {
      return;
    }
    const action =
      isInstalled(state.selectedGame?.install_state) &&
      Boolean(state.selectedGame?.needs_update)
        ? "update"
        : "install";
    el.installAnywayBtn.disabled = true;
    el.installAnywayBtn.classList.add("is-loading");
    el.installAnywayBtn.setAttribute("aria-busy", "true");
    try {
      const payload = await apiGet(
        `/catalog/games/${encodeURIComponent(state.selectedGameId)}/${action}`,
      );
      if (payload?.result?.ok) {
        el.settingsStatus.textContent = t(
          "game.install_anyway_ok",
          "Manual extraction completed.",
        );
      } else {
        const backendMessage = String(payload?.result?.message || "error");
        el.settingsStatus.textContent = `${t(
          "game.install_anyway_failed",
          "Manual extraction could not be completed.",
        )} (${t(`game.install_error_${backendMessage}`, backendMessage)})`;
      }
      await loadSelectedGameSyncStatus();
      renderDetailMeta();
      await refreshSyncWidgets();
      await loadLogs();
      await loadCatalog();
    } catch (err) {
      const backendMessage = String(err?.message || "error");
      el.settingsStatus.textContent = `${t(
        "game.install_anyway_failed",
        "Manual extraction could not be completed.",
      )} (${t(`game.install_error_${backendMessage}`, backendMessage)})`;
    } finally {
      el.installAnywayBtn.classList.remove("is-loading");
      el.installAnywayBtn.setAttribute("aria-busy", "false");
      updateDetailActionStates();
    }
  }

  async function onServiceSyncStart() {
    const payload = await apiGet("/sync/start");
    if (payload?.sync?.state === "blocked") {
      el.settingsStatus.textContent = t(
        "settings.first_run_path_required",
        "First run: save library path in settings before starting sync.",
      );
    }
    await refreshSyncWidgets();
    await loadLogs();
    await loadSelectedGameSyncStatus();
  }

  async function onServiceSyncStop() {
    await apiGet("/sync/stop");
    await refreshSyncWidgets();
    await loadLogs();
    await loadSelectedGameSyncStatus();
  }

  async function onProviderServiceAction(providerType, action, sourceButton) {
    if (!sourceButton) {
      return;
    }
    const provider = providerInterfaceForType(providerType);
    sourceButton.disabled = true;
    sourceButton.classList.add("is-loading");
    sourceButton.setAttribute("aria-busy", "true");
    try {
      const payload = await apiGet(
        `/sync/providers/${encodeURIComponent(provider.provider_type)}/${encodeURIComponent(action)}`,
      );
      const sync = payload?.sync || {};
      const providerLabel =
        provider.title || provider.provider_type || t("status.provider_name", "Provider");
      if (sync.state === "blocked") {
        el.settingsStatus.textContent = t(
          "settings.first_run_path_required",
          "First run: save library path in settings before starting sync.",
        );
      } else if (action === "stop" && !sync.running) {
        el.settingsStatus.textContent = `${providerLabel} ${t(
          "status.service_stop_ok",
          "stopped.",
        )}`;
      } else if (action !== "stop" && sync.running) {
        el.settingsStatus.textContent = `${providerLabel} ${t(
          action === "restart"
            ? "status.service_restart_ok"
            : "status.service_start_ok",
          action === "restart" ? "restarted." : "started.",
        )}`;
      } else {
        const backendMessage = String(sync.last_error || sync.state || "error");
        el.settingsStatus.textContent = `${providerLabel} ${t(
          "status.service_action_failed",
          "action failed.",
        )} (${t(`sync.provider_${backendMessage}`, backendMessage)})`;
      }
      await refreshSyncWidgets();
      await loadLogs();
      if (state.selectedGameId) {
        await loadSelectedGameSyncStatus();
      }
    } catch (err) {
      const backendMessage = String(err?.message || "error");
      const providerLabel =
        provider.title || provider.provider_type || t("status.provider_name", "Provider");
      el.settingsStatus.textContent = `${providerLabel} ${t(
        "status.service_action_failed",
        "action failed.",
      )} (${backendMessage})`;
    } finally {
      sourceButton.classList.remove("is-loading");
      sourceButton.setAttribute("aria-busy", "false");
      sourceButton.disabled = providerActionDisabled(
        providerInterfaceForType(providerType),
        action,
      );
    }
  }

  async function onOpenLibrary() {
    try {
      const payload = await apiGet("/platform/open-folder?path=library");
      if (!payload.action.ok) {
        alert(t("ui.open_folder_failed", "Could not open folder."));
      }
    } catch (_err) {
      alert(t("ui.open_folder_failed", "Could not open folder."));
    }
  }

  async function onOpenGameFolder() {
    if (!state.selectedGameId) {
      return;
    }
    const library = state.settings.effective_library_path || "";
    const path = `${library}/${state.selectedGameId}`;
    try {
      const payload = await apiGet(
        `/platform/open-folder?path=${encodeURIComponent(path)}`,
      );
      if (!payload.action.ok) {
        alert(t("ui.open_folder_failed", "Could not open folder."));
      }
    } catch (_err) {
      alert(t("ui.open_folder_failed", "Could not open folder."));
    }
  }

  function onOpenLocalDocs() {
    const target = String(state.settings.local_docs_file_url || "").trim();
    const localPath = String(state.settings.local_docs_file_path || "").trim();
    if (!target && !localPath) {
      alert(
        t(
          "ui.local_docs_unavailable",
          "Local documentation is not available on this installation.",
        ),
      );
      return;
    }
    let openedDirectly = false;
    if (target) {
      try {
        const popup = window.open(target, "_blank", "noopener,noreferrer");
        openedDirectly = Boolean(popup);
      } catch (_err) {}
    }
    if (openedDirectly || !localPath) {
      return;
    }
    apiGet(`/platform/open-folder?path=${encodeURIComponent(localPath)}`)
      .then((payload) => {
        if (!payload?.action?.ok) {
          alert(
            t(
              "ui.local_docs_unavailable",
              "Local documentation is not available on this installation.",
            ),
          );
        }
      })
      .catch(() => {
        alert(
          t(
            "ui.local_docs_unavailable",
            "Local documentation is not available on this installation.",
          ),
        );
      });
  }

  async function onStartGame() {
    if (!state.selectedGameId) {
      return;
    }
    const gameTitle = state.selectedGame?.title || state.selectedGameId;
    setLaunchConsoleLines([
      t("game.console_starting", "starting the game {title} ...").replace(
        "{title}",
        gameTitle,
      ),
      t("game.console_wait_window", "opening interactive launcher window ..."),
    ]);
    el.startGameBtn.disabled = true;
    el.startGameBtn.classList.add("is-loading");
    el.startGameBtn.setAttribute("aria-busy", "true");
    try {
      const payload = await apiGet(
        `/catalog/games/${encodeURIComponent(state.selectedGameId)}/start?locale=${encodeURIComponent(state.locale)}`,
      );
      const ok = Boolean(payload?.result?.ok);
      const launchDetails = payload?.result?.details || {};
      const lines = [];
      lines.push(
        ok
          ? t("game.console_started", "game launch command sent.")
          : t("game.console_failed", "game launch failed."),
      );
      const launchMethod = String(launchDetails.launch_method || "");
      const launchCall = String(launchDetails.launch_command_display || "");
      if (launchMethod) {
        lines.push(
          `${t("game.console_launch_method", "launch method")}: ${launchMethodLabel(launchMethod)}`,
        );
      }
      if (launchCall) {
        lines.push(
          `${t("game.console_execution_call", "execution call")}: ${launchCall}`,
        );
      } else {
        const binaryPath = String(launchDetails.script || "");
        if (binaryPath) {
          lines.push(
            `${t("game.console_call_binary", "call binary")}: ${binaryPath}`,
          );
        }
      }
      setLaunchConsoleLines(lines);
      const backendMessage = String(payload?.result?.message || "error");
      el.settingsStatus.textContent = ok
        ? t("game.start_ok", "Game started.")
        : `${t("game.start_failed", "Game could not be started.")} (${t(`game.error_${backendMessage}`, backendMessage)})`;
      await loadLogs();
    } catch (_err) {
      setLaunchConsoleLines([t("game.console_failed", "game launch failed.")]);
      el.settingsStatus.textContent = t(
        "game.start_failed",
        "Game could not be started.",
      );
    } finally {
      el.startGameBtn.classList.remove("is-loading");
      el.startGameBtn.setAttribute("aria-busy", "false");
      updateDetailActionStates();
    }
  }

  async function onStartServer() {
    if (!state.selectedGameId) {
      return;
    }
    const gameTitle = state.selectedGame?.title || state.selectedGameId;
    setLaunchConsoleLines([
      t(
        "game.console_starting_server",
        "starting the server for {title} ...",
      ).replace("{title}", gameTitle),
      t("game.console_wait_window", "opening interactive launcher window ..."),
    ]);
    el.startServerBtn.disabled = true;
    el.startServerBtn.classList.add("is-loading");
    el.startServerBtn.setAttribute("aria-busy", "true");
    try {
      const payload = await apiGet(
        `/catalog/games/${encodeURIComponent(state.selectedGameId)}/start-server?locale=${encodeURIComponent(state.locale)}`,
      );
      const ok = Boolean(payload?.result?.ok);
      const launchDetails = payload?.result?.details || {};
      const lines = [];
      lines.push(
        ok
          ? t("game.console_started", "game launch command sent.")
          : t("game.console_failed", "game launch failed."),
      );
      const launchMethod = String(launchDetails.launch_method || "");
      const launchCall = String(launchDetails.launch_command_display || "");
      if (launchMethod) {
        lines.push(
          `${t("game.console_launch_method", "launch method")}: ${launchMethodLabel(launchMethod)}`,
        );
      }
      if (launchCall) {
        lines.push(
          `${t("game.console_execution_call", "execution call")}: ${launchCall}`,
        );
      } else {
        const binaryPath = String(launchDetails.script || "");
        if (binaryPath) {
          lines.push(
            `${t("game.console_call_binary", "call binary")}: ${binaryPath}`,
          );
        }
      }
      setLaunchConsoleLines(lines);
      const backendMessage = String(payload?.result?.message || "error");
      el.settingsStatus.textContent = ok
        ? t("game.server_start_ok", "Server started.")
        : `${t("game.server_start_failed", "Server could not be started.")} (${t(`game.error_${backendMessage}`, backendMessage)})`;
      await loadLogs();
    } catch (_err) {
      setLaunchConsoleLines([t("game.console_failed", "game launch failed.")]);
      el.settingsStatus.textContent = t(
        "game.server_start_failed",
        "Server could not be started.",
      );
    } finally {
      el.startServerBtn.classList.remove("is-loading");
      el.startServerBtn.setAttribute("aria-busy", "false");
      updateDetailActionStates();
    }
  }

  async function onDeleteGame() {
    if (!state.selectedGameId || !state.selectedGame) {
      return;
    }
    const gameTitle = String(state.selectedGame.title || state.selectedGameId);
    const isLocalGame = selectedGameProviderType() === "local";
    const confirmed = window.confirm(
      t(
        isLocalGame ? "game.delete_local_confirm" : "game.delete_confirm",
        "Do you really want to delete {title}?",
      ).replace("{title}", gameTitle),
    );
    if (!confirmed) {
      return;
    }
    setLaunchConsoleLines([
      t(
        isLocalGame
          ? "game.delete_local_console_start"
          : "game.delete_console_start",
        "deleting game {title} ...",
      ).replace("{title}", gameTitle),
      ...(
        isLocalGame
          ? []
          : [t("game.delete_console_sync", "removing folder from sync ...")]
      ),
      t(
        isLocalGame
          ? "game.delete_local_console_database"
          : "game.delete_console_disk",
        isLocalGame
          ? "deleting local database entry ..."
          : "deleting game data from disk ...",
      ),
    ]);
    try {
      const payload = await apiGet(
        `/catalog/games/${encodeURIComponent(state.selectedGameId)}/delete`,
      );
      const ok = Boolean(payload?.result?.ok);
      if (ok) {
        const details = payload?.result?.details || {};
        const folder = String(details.folder || "");
        const syncDetail = String(details.sync_detail || "ok");
        const lines = [
          ...(
            isLocalGame
              ? []
              : [
                  t(
                    "game.delete_console_sync_result",
                    "sync remove result: {result}",
                  ).replace("{result}", syncDetail),
                ]
          ),
        ];
        if (folder && !isLocalGame) {
          lines.push(
            t(
              "game.delete_console_disk_result",
              "deleted folder: {path}",
            ).replace("{path}", folder),
          );
        }
        lines.push(t("game.delete_console_done", "delete completed."));
        setLaunchConsoleLines(lines);
        el.settingsStatus.textContent = t(
          isLocalGame ? "game.delete_local_ok" : "game.delete_ok",
          "Game deleted from sync and disk.",
        );
      } else {
        const message = String(payload?.result?.message || "error");
        setLaunchConsoleLines([
          t("game.delete_console_failed", "delete failed: {reason}").replace(
            "{reason}",
            message,
          ),
        ]);
        el.settingsStatus.textContent = `${t(
          "game.delete_failed_with_title",
          "Game {title} could not be deleted.",
        ).replace("{title}", gameTitle)} (${message})`;
      }
      await loadCatalog();
      await loadGameDetail(state.selectedGameId);
      await refreshSyncWidgets();
      await loadLogs();
    } catch (_err) {
      setLaunchConsoleLines([
        t("game.delete_console_failed", "delete failed: {reason}").replace(
          "{reason}",
          "request_error",
        ),
      ]);
      el.settingsStatus.textContent = t(
        isLocalGame ? "game.delete_local_failed_with_title" : "game.delete_failed_with_title",
        "Game {title} could not be deleted.",
      ).replace("{title}", gameTitle);
    }
  }

  function onEditLocalGame() {
    if (selectedGameProviderType() !== "local" || !state.selectedGame) {
      return;
    }
    openLocalGameModal(state.selectedGame);
  }

  async function onInstallPrerequisitesBundle() {
    try {
      const payload = await apiGet("/platform/install-prerequisites");
      const ok = Boolean(payload?.result?.ok);
      if (ok) {
        el.settingsStatus.textContent = t(
          "settings.install_prereq_ok",
          "Pre-requirements installer started.",
        );
        return;
      }
      el.settingsStatus.textContent = `${t(
        "settings.install_prereq_failed",
        "Could not start pre-requirements installer.",
      )} (${payload?.result?.message || "error"})`;
    } catch (_err) {
      el.settingsStatus.textContent = t(
        "settings.install_prereq_failed",
        "Could not start pre-requirements installer.",
      );
    }
  }

  async function onInstallWineCommonDependencies() {
    if (!el.installWineCommonDepsBtn) {
      return;
    }
    el.installWineCommonDepsBtn.disabled = true;
    el.installWineCommonDepsBtn.classList.add("is-loading");
    el.installWineCommonDepsBtn.setAttribute("aria-busy", "true");
    try {
      const payload = await apiGet("/platform/install-wine-common-deps");
      const ok = Boolean(payload?.result?.ok);
      if (ok) {
        el.settingsStatus.textContent = t(
          "settings.install_wine_common_deps_ok",
          "Common Wine dependencies installation started.",
        );
        return;
      }
      const backendMessage = String(payload?.result?.message || "error");
      el.settingsStatus.textContent = `${t(
        "settings.install_wine_common_deps_failed",
        "Could not start common Wine dependencies installation.",
      )} (${t(`settings.install_wine_common_deps_error_${backendMessage}`, backendMessage)})`;
    } catch (err) {
      const backendMessage = String(err?.message || "error");
      el.settingsStatus.textContent = `${t(
        "settings.install_wine_common_deps_failed",
        "Could not start common Wine dependencies installation.",
      )} (${t(`settings.install_wine_common_deps_error_${backendMessage}`, backendMessage)})`;
    } finally {
      el.installWineCommonDepsBtn.classList.remove("is-loading");
      el.installWineCommonDepsBtn.setAttribute("aria-busy", "false");
      updateInstallPrereqButtonState();
    }
  }

  async function onInstallGameProtonCommonDependencies() {
    if (!state.selectedGameId || !el.installProtonCommonDepsBtn) {
      return;
    }
    el.installProtonCommonDepsBtn.disabled = true;
    el.installProtonCommonDepsBtn.classList.add("is-loading");
    el.installProtonCommonDepsBtn.setAttribute("aria-busy", "true");
    try {
      const payload = await apiPost(
        `/catalog/games/${encodeURIComponent(state.selectedGameId)}/prefix-wine-dependencies`,
        {
          action: "install",
          packages: currentDefaultWinetricksPackages(),
        },
      );
      const ok = Boolean(payload?.result?.ok);
      if (ok) {
        el.settingsStatus.textContent = t(
          "game.install_prefix_common_deps_ok",
          "Common prefix dependencies installation started.",
        );
        return;
      }
      const backendMessage = String(payload?.result?.message || "error");
      el.settingsStatus.textContent = `${t(
        "game.install_prefix_common_deps_failed",
        "Could not start common prefix dependencies installation.",
      )} (${t(`game.install_prefix_common_deps_error_${backendMessage}`, backendMessage)})`;
    } catch (err) {
      const backendMessage = String(err?.message || "error");
      el.settingsStatus.textContent = `${t(
        "game.install_prefix_common_deps_failed",
        "Could not start common prefix dependencies installation.",
      )} (${t(`game.install_prefix_common_deps_error_${backendMessage}`, backendMessage)})`;
    } finally {
      el.installProtonCommonDepsBtn.classList.remove("is-loading");
      el.installProtonCommonDepsBtn.setAttribute("aria-busy", "false");
      updateDetailActionStates();
    }
  }

  async function onInstallSelectedGameWinetricksPackages() {
    if (
      !state.selectedGameId ||
      !el.detailWinetricksInstallBtn ||
      state.selectedGameWinetricksPackages.length === 0
    ) {
      return;
    }
    el.detailWinetricksInstallBtn.disabled = true;
    el.detailWinetricksInstallBtn.classList.add("is-loading");
    el.detailWinetricksInstallBtn.setAttribute("aria-busy", "true");
    try {
      const payload = await apiPost(
        `/catalog/games/${encodeURIComponent(state.selectedGameId)}/prefix-wine-dependencies`,
        {
          action: "install",
          packages: state.selectedGameWinetricksPackages,
        },
      );
      if (payload?.result?.ok) {
        el.settingsStatus.textContent = t(
          "game.winetricks_install_selected_ok",
          "Selected prefix dependencies installation started.",
        );
        return;
      }
      const backendMessage = String(payload?.result?.message || "error");
      el.settingsStatus.textContent = `${t(
        "game.winetricks_install_selected_failed",
        "Could not start selected prefix dependencies installation.",
      )} (${t(`game.install_prefix_common_deps_error_${backendMessage}`, backendMessage)})`;
    } catch (err) {
      const backendMessage = String(err?.message || "error");
      el.settingsStatus.textContent = `${t(
        "game.winetricks_install_selected_failed",
        "Could not start selected prefix dependencies installation.",
      )} (${t(`game.install_prefix_common_deps_error_${backendMessage}`, backendMessage)})`;
    } finally {
      el.detailWinetricksInstallBtn.classList.remove("is-loading");
      el.detailWinetricksInstallBtn.setAttribute("aria-busy", "false");
      updateDetailActionStates();
    }
  }

  async function onOpenSelectedGamePrefixUninstaller() {
    if (!state.selectedGameId || !el.detailWinetricksRemoveBtn) {
      return;
    }
    el.detailWinetricksRemoveBtn.disabled = true;
    el.detailWinetricksRemoveBtn.classList.add("is-loading");
    el.detailWinetricksRemoveBtn.setAttribute("aria-busy", "true");
    try {
      const payload = await apiPost(
        `/catalog/games/${encodeURIComponent(state.selectedGameId)}/prefix-wine-dependencies`,
        {
          action: "remove",
          packages:
            state.selectedGameWinetricksPackages.length > 0
              ? state.selectedGameWinetricksPackages
              : currentDefaultWinetricksPackages(),
        },
      );
      if (payload?.result?.ok) {
        el.settingsStatus.textContent = t(
          "game.winetricks_open_uninstaller_ok",
          "Prefix uninstaller started.",
        );
        return;
      }
      const backendMessage = String(payload?.result?.message || "error");
      el.settingsStatus.textContent = `${t(
        "game.winetricks_open_uninstaller_failed",
        "Could not start the prefix uninstaller.",
      )} (${t(`game.install_prefix_common_deps_error_${backendMessage}`, backendMessage)})`;
    } catch (err) {
      const backendMessage = String(err?.message || "error");
      el.settingsStatus.textContent = `${t(
        "game.winetricks_open_uninstaller_failed",
        "Could not start the prefix uninstaller.",
      )} (${t(`game.install_prefix_common_deps_error_${backendMessage}`, backendMessage)})`;
    } finally {
      el.detailWinetricksRemoveBtn.classList.remove("is-loading");
      el.detailWinetricksRemoveBtn.setAttribute("aria-busy", "false");
      updateDetailActionStates();
    }
  }

  async function onSaveSelectedGameWinetricksMetadata() {
    if (!state.selectedGameId || !el.detailWinetricksSaveBtn) {
      return;
    }
    el.detailWinetricksSaveBtn.disabled = true;
    el.detailWinetricksSaveBtn.classList.add("is-loading");
    el.detailWinetricksSaveBtn.setAttribute("aria-busy", "true");
    try {
      const payload = await apiPost(
        `/catalog/games/${encodeURIComponent(state.selectedGameId)}/metadata`,
        {
          packages: state.selectedGameWinetricksPackages,
        },
      );
      if (payload?.result?.ok) {
        el.settingsStatus.textContent = t(
          "game.winetricks_save_metadata_ok",
          "Current dependency config saved.",
        );
        await loadGameDetail(state.selectedGameId);
        return;
      }
      const backendMessage = String(payload?.result?.message || "error");
      el.settingsStatus.textContent = `${t(
        "game.winetricks_save_metadata_failed",
        "Could not save current dependency config.",
      )} (${t(`game.save_game_metadata_error_${backendMessage}`, backendMessage)})`;
    } catch (err) {
      const backendMessage = String(err?.message || "error");
      el.settingsStatus.textContent = `${t(
        "game.winetricks_save_metadata_failed",
        "Could not save current dependency config.",
      )} (${t(`game.save_game_metadata_error_${backendMessage}`, backendMessage)})`;
    } finally {
      el.detailWinetricksSaveBtn.classList.remove("is-loading");
      el.detailWinetricksSaveBtn.setAttribute("aria-busy", "false");
      updateDetailActionStates();
    }
  }

  async function onManualUpdateRollback() {
    if (!el.updateRollbackBtn) {
      return;
    }
    el.updateRollbackBtn.disabled = true;
    el.updateRollbackBtn.classList.add("is-loading");
    el.updateRollbackBtn.setAttribute("aria-busy", "true");
    try {
      const payload = await apiGet("/app/update/rollback");
      if (payload?.result?.ok) {
        el.settingsStatus.textContent = t(
          "settings.update_rollback_ok",
          "Rollback applied.",
        );
      } else {
        const backendMessage = String(payload?.result?.message || "error");
        el.settingsStatus.textContent = `${t(
          "settings.update_rollback_failed",
          "Rollback could not be applied.",
        )} (${t(`settings.update_rollback_error_${backendMessage}`, backendMessage)})`;
      }
    } catch (err) {
      const backendMessage = String(err.message || "error");
      el.settingsStatus.textContent = `${t(
        "settings.update_rollback_failed",
        "Rollback could not be applied.",
      )} (${t(`settings.update_rollback_error_${backendMessage}`, backendMessage)})`;
    } finally {
      el.updateRollbackBtn.classList.remove("is-loading");
      el.updateRollbackBtn.setAttribute("aria-busy", "false");
      el.updateRollbackBtn.disabled = false;
    }
  }

  async function onSetResilioNetworkMode(mode, sourceButton) {
    if (!sourceButton) {
      return;
    }
    sourceButton.disabled = true;
    sourceButton.classList.add("is-loading");
    sourceButton.setAttribute("aria-busy", "true");
    try {
      const payload = await apiPost("/platform/resilio-network-mode", { mode });
      if (payload?.result?.ok) {
        el.settingsStatus.textContent =
          mode === "lan"
            ? t(
                "settings.sync_mode_lan_ok",
                "Resilio LAN mode has been enabled.",
              )
            : t(
                "settings.sync_mode_internet_ok",
                "Resilio Internet mode has been enabled.",
              );
      } else {
        const backendMessage = String(payload?.result?.message || "error");
        el.settingsStatus.textContent = `${t(
          "settings.sync_mode_apply_failed",
          "Could not apply Resilio network mode.",
        )} (${t(`settings.sync_mode_error_${backendMessage}`, backendMessage)})`;
      }
    } catch (err) {
      const backendMessage = String(err.message || "error");
      el.settingsStatus.textContent = `${t(
        "settings.sync_mode_apply_failed",
        "Could not apply Resilio network mode.",
      )} (${t(`settings.sync_mode_error_${backendMessage}`, backendMessage)})`;
    } finally {
      sourceButton.classList.remove("is-loading");
      sourceButton.setAttribute("aria-busy", "false");
      updateNetworkModeButtonState();
    }
  }

  async function onSetLocalNetworkPrivate() {
    if (!el.setNetworkPrivateBtn) {
      return;
    }
    el.setNetworkPrivateBtn.disabled = true;
    el.setNetworkPrivateBtn.classList.add("is-loading");
    el.setNetworkPrivateBtn.setAttribute("aria-busy", "true");
    try {
      const payload = await apiPost("/platform/set-local-network-private", {});
      if (payload?.result?.ok) {
        el.settingsStatus.textContent = t(
          "settings.network_private_ok",
          "Tried to switch connected public networks to private mode.",
        );
      } else {
        const backendMessage = String(payload?.result?.message || "error");
        el.settingsStatus.textContent = `${t(
          "settings.network_private_failed",
          "Could not switch local network profile.",
        )} (${t(`settings.network_private_error_${backendMessage}`, backendMessage)})`;
      }
    } catch (err) {
      const backendMessage = String(err.message || "error");
      el.settingsStatus.textContent = `${t(
        "settings.network_private_failed",
        "Could not switch local network profile.",
      )} (${t(`settings.network_private_error_${backendMessage}`, backendMessage)})`;
    } finally {
      el.setNetworkPrivateBtn.classList.remove("is-loading");
      el.setNetworkPrivateBtn.setAttribute("aria-busy", "false");
      updateNetworkModeButtonState();
    }
  }

  function openStatusTab(providerType = state.activeStatusProvider) {
    setActiveStatusProvider(providerType);
    setActiveTab("status");
  }

  function attemptWindowClose() {
    try {
      window.close();
    } catch (_err) {}
    try {
      self.close();
    } catch (_err) {}
  }

  async function startShutdownUpdateAction(sessionId, action = "start") {
    const payload = await apiGet(
      `/app/shutdown/apply?session_id=${encodeURIComponent(sessionId)}&action=${encodeURIComponent(action)}`,
    );
    const shutdown = payload?.shutdown || {};
    setShutdownUpdateRecoveryButtonsVisible(false);
    state.shutdownUpdateRecoveryRequired = false;
    return shutdown;
  }

  async function onStopApp() {
    state.shutdownSignalSent = true;
    el.stopAppBtn.disabled = true;
    el.stopAppBtn.textContent = t("app.stopping", "Stopping...");
    el.settingsStatus.textContent = t("app.stopping", "Stopping...");
    try {
      stopShutdownUpdatePolling();
      stopShutdownUpdateAutoClose();
      const preparePayload = await apiGet("/app/shutdown/prepare");
      const shutdown = preparePayload?.shutdown || {};
      const sessionId = String(shutdown?.session_id || "").trim();
      const willApplyUpdate = Boolean(shutdown?.will_apply_update);
      const initialLines = Array.isArray(shutdown?.console_lines)
        ? shutdown.console_lines
        : [];

      if (!willApplyUpdate || !sessionId) {
        setShutdownUpdateModalVisible(false);
        attemptWindowClose();
        window.setTimeout(() => {
          attemptWindowClose();
        }, 120);
        return;
      }

      state.shutdownUpdateSessionId = sessionId;
      state.shutdownUpdateRecoveryRequired = Boolean(
        shutdown?.recovery_required,
      );
      setShutdownUpdateConfirmVisible(false);
      setShutdownUpdateRecoveryButtonsVisible(false);
      setShutdownUpdateConsoleLines(
        initialLines.length
          ? initialLines
          : [t("app.shutdown_update_checking", "Checking update...")],
      );
      setShutdownUpdateStatusText(shutdown);
      setShutdownUpdateModalVisible(true);
      if (state.shutdownUpdateRecoveryRequired) {
        if (el.shutdownUpdateText) {
          el.shutdownUpdateText.textContent = t(
            "app.shutdown_update_recovery_required",
            "An interrupted update was detected. Resume or abort recovery.",
          );
        }
        setShutdownUpdateRecoveryButtonsVisible(true);
      } else {
        const applyState = await startShutdownUpdateAction(sessionId, "start");
        const autoCloseSeconds = Number(
          applyState?.frontend_auto_close_seconds || 0,
        );
        if (
          Boolean(applyState?.detached_handoff_pending) &&
          autoCloseSeconds > 0
        ) {
          setShutdownUpdateConsoleLines([
            ...state.shutdownUpdateLines,
            t(
              "app.shutdown_update_handoff_log",
              "detached updater launched; stopping app for Windows file swap",
            ),
          ]);
          setShutdownUpdateStatusText({
            ...applyState,
            phase: "handoff",
          });
          startShutdownUpdateAutoClose(autoCloseSeconds);
          return;
        }
      }
      state.shutdownUpdatePollTimer = window.setInterval(async () => {
        try {
          const statusPayload = await apiGet(
            `/app/shutdown/status?session_id=${encodeURIComponent(state.shutdownUpdateSessionId)}`,
          );
          const status = statusPayload?.shutdown || {};
          const phase = String(status?.phase || "").toLowerCase();
          const lines = Array.isArray(status?.console_lines)
            ? status.console_lines
            : [];
          setShutdownUpdateConsoleLines(lines);
          setShutdownUpdateStatusText(status);
          const recoveryRequired = Boolean(status?.recovery_required);
          const autoCloseSeconds = Number(
            status?.frontend_auto_close_seconds || 0,
          );
          if (
            Boolean(status?.detached_handoff_pending) &&
            autoCloseSeconds > 0
          ) {
            startShutdownUpdateAutoClose(autoCloseSeconds);
            return;
          }
          if (recoveryRequired && !state.shutdownUpdateRecoveryRequired) {
            state.shutdownUpdateRecoveryRequired = true;
            setShutdownUpdateRecoveryButtonsVisible(true);
            if (el.shutdownUpdateText) {
              el.shutdownUpdateText.textContent = t(
                "app.shutdown_update_recovery_required",
                "An interrupted update was detected. Resume or abort recovery.",
              );
            }
          }
          if (
            phase === "done" ||
            phase === "failed" ||
            phase === "no_update" ||
            phase === "aborted"
          ) {
            stopShutdownUpdatePolling();
            state.shutdownUpdateRecoveryRequired = false;
            if (el.shutdownUpdateText) {
              el.shutdownUpdateText.textContent = t(
                "app.shutdown_update_waiting_confirm",
                "Update step finished. Confirm to close the app.",
              );
            }
            setShutdownUpdateRecoveryButtonsVisible(false);
            setShutdownUpdateConfirmVisible(true);
          }
        } catch (_pollErr) {
          // Ignore transient read errors while backend is stopping.
        }
      }, 700);
    } catch (_err) {
      // Fallback: keep previous immediate shutdown behavior if prep flow fails.
      try {
        await fetch("/app/shutdown", {
          method: "GET",
          cache: "no-store",
          keepalive: true,
        });
      } catch (_shutdownErr) {}
      closeFrontendWindow();
    }
  }

  async function onShutdownUpdateResume() {
    const sessionId = String(state.shutdownUpdateSessionId || "").trim();
    if (!sessionId) {
      return;
    }
    try {
      const applyState = await startShutdownUpdateAction(sessionId, "resume");
      if (el.shutdownUpdateText) {
        el.shutdownUpdateText.textContent = t(
          "app.shutdown_update_text",
          "Applying a newer launcher version before shutdown.",
        );
      }
      const autoCloseSeconds = Number(
        applyState?.frontend_auto_close_seconds || 0,
      );
      if (
        Boolean(applyState?.detached_handoff_pending) &&
        autoCloseSeconds > 0
      ) {
        setShutdownUpdateStatusText({
          ...applyState,
          phase: "handoff",
        });
        setShutdownUpdateConsoleLines([
          ...state.shutdownUpdateLines,
          t(
            "app.shutdown_update_handoff_log",
            "detached updater launched; stopping app for Windows file swap",
          ),
        ]);
        startShutdownUpdateAutoClose(autoCloseSeconds);
      }
    } catch (_err) {
      // Keep modal open and continue polling existing status.
    }
  }

  async function onShutdownUpdateAbort() {
    const sessionId = String(state.shutdownUpdateSessionId || "").trim();
    if (!sessionId) {
      return;
    }
    try {
      await startShutdownUpdateAction(sessionId, "abort");
      if (el.shutdownUpdateText) {
        el.shutdownUpdateText.textContent = t(
          "app.shutdown_update_waiting_confirm",
          "Update step finished. Confirm to close the app.",
        );
      }
    } catch (_err) {
      // Keep modal open and continue polling existing status.
    }
  }

  async function onShutdownUpdateConfirm() {
    state.shutdownSignalSent = true;
    const sessionId = String(state.shutdownUpdateSessionId || "").trim();
    if (el.shutdownUpdateConfirmBtn) {
      el.shutdownUpdateConfirmBtn.disabled = true;
      el.shutdownUpdateConfirmBtn.textContent = t(
        "app.shutdown_update_finalizing",
        "Closing...",
      );
    }
    try {
      if (sessionId) {
        await apiGet(
          `/app/shutdown/finalize?session_id=${encodeURIComponent(sessionId)}`,
        );
      } else {
        await apiGet("/app/shutdown");
      }
    } catch (_err) {
      try {
        await fetch("/app/shutdown", {
          method: "GET",
          cache: "no-store",
          keepalive: true,
        });
      } catch (_shutdownErr) {}
    }
    closeFrontendWindow();
  }

  function bindEvents() {
    // App-mode browsers may still expose browser shortcuts to the page. Block
    // the common fullscreen, source-view and DevTools shortcuts when delivered.
    document.addEventListener(
      "keydown",
      (event) => {
        const key = String(event.key || "").toLowerCase();
        const devToolsShortcut =
          event.key === "F12" ||
          (event.ctrlKey &&
            event.shiftKey &&
            ["i", "j", "c", "m"].includes(key)) ||
          (event.ctrlKey && key === "u");
        if (event.key === "F11" || devToolsShortcut) {
          event.preventDefault();
          event.stopImmediatePropagation();
        }
      },
      true,
    );

    // Best-effort app shutdown when the UI process/window is closed outside the
    // in-app stop button flow (browser window close, process exit, tab close).
    window.addEventListener("pagehide", () => {
      sendShutdownKeepaliveOnWindowClose();
    });
    window.addEventListener("beforeunload", () => {
      sendShutdownKeepaliveOnWindowClose();
    });
    document.addEventListener("contextmenu", (event) => {
      const target = event.target instanceof Element ? event.target : null;
      if (
        !target?.closest(
          "[data-context-menu-enabled=\"true\"], #catalog-context-menu",
        )
      ) {
        event.preventDefault();
      }
    });

    el.localeSelect.addEventListener("change", async (event) => {
      await loadLocale(event.target.value);
      await loadGenres();
      await loadCatalog();
      if (state.selectedGameId) {
        await loadGameDetail(state.selectedGameId);
      }
    });

    const markGeneralSettingsDirty = (event) => {
      const target = event.target;
      if (
        !(target instanceof Element) ||
        !target.matches("input, select, textarea")
      ) {
        return;
      }
      if (target.closest("#lan-discovery-section, #lan-pair-server-section, #lan-server-settings-section")) {
        return;
      }
      setSettingsDirty(true);
    };
    el.settingsGeneralSection?.addEventListener(
      "input",
      markGeneralSettingsDirty,
    );
    el.settingsGeneralSection?.addEventListener(
      "change",
      markGeneralSettingsDirty,
    );
    const markLanSettingsDirty = (event) => {
      if (event.target.closest("#lan-server-settings-section")) {
        el.lanServerSettingsSave?.classList.add("is-dirty");
      }
    };
    el.lanServerSettingsSection?.addEventListener("input", markLanSettingsDirty);
    el.lanServerSettingsSection?.addEventListener("change", markLanSettingsDirty);

    el.searchInput.addEventListener("input", async (event) => {
      state.query = event.target.value.trim();
      state.page = 1;
      await loadCatalog();
    });

    el.sortSelect.addEventListener("change", async (event) => {
      const [sort, order] = event.target.value.split(":");
      state.sort = sort;
      state.order = order;
      await loadCatalog();
    });

    el.installedSelect.addEventListener("change", async (event) => {
      state.installed = event.target.value;
      state.page = 1;
      await loadCatalog();
    });
    document.addEventListener("pointerdown", (event) => {
      if (!el.catalogContextMenu?.contains(event.target)) {
        hideCatalogContextMenu();
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        hideCatalogContextMenu();
      }
    });
    window.addEventListener("scroll", hideCatalogContextMenu, true);
    el.genreSelect.addEventListener("change", async (event) => {
      state.genreId = event.target.value || "all";
      state.page = 1;
      await loadCatalog();
    });

    el.rescanBtn.addEventListener("click", onRescan);
    el.installCheckBtn.addEventListener("click", onInstallCheck);
    el.syncStart.addEventListener("click", onSyncStart);
    el.syncStop.addEventListener("click", onSyncStop);
    el.syncRemoveData?.addEventListener("click", onSyncRemoveData);
    el.openLibrary.addEventListener("click", onOpenLibrary);
    el.openGameFolder.addEventListener("click", onOpenGameFolder);
    if (el.installAnywayBtn) {
      el.installAnywayBtn.addEventListener("click", onInstallAnyway);
    }
    if (el.editLocalGameBtn) {
      el.editLocalGameBtn.addEventListener("click", onEditLocalGame);
    }
    if (el.detailLinuxRuntimeSelect) {
      el.detailLinuxRuntimeSelect.addEventListener(
        "change",
        onDetailLinuxRuntimeChange,
      );
    }
    if (el.detailLinuxLeaveTerminalOpenCheckbox) {
      el.detailLinuxLeaveTerminalOpenCheckbox.addEventListener(
        "change",
        onDetailLinuxLeaveTerminalOpenChange,
      );
    }
    el.startGameBtn.addEventListener("click", onStartGame);
    el.startServerBtn.addEventListener("click", onStartServer);
    el.deleteGameBtn.addEventListener("click", onDeleteGame);
    if (el.localGameCancelBtn) {
      el.localGameCancelBtn.addEventListener("click", closeLocalGameModal);
    }
    el.serverCoverDownloadBtn?.addEventListener("click", downloadServerCover);
    if (el.localGameSaveBtn) {
      el.localGameSaveBtn.addEventListener("click", onLocalGameSave);
    }
    if (el.localGameModal) {
      el.localGameModal.addEventListener("click", (event) => {
        if (event.target === el.localGameModal) {
          closeLocalGameModal();
        }
      });
    }
    el.ouisyncDebugHealth?.addEventListener("click", () => runOuisyncDebugAction("health"));
    el.ouisyncSettingDht?.addEventListener("change", (event) => updateOuisyncRepositorySetting("dht_enabled", event.currentTarget.checked, event.currentTarget));
    el.ouisyncSettingPex?.addEventListener("change", (event) => updateOuisyncRepositorySetting("peer_exchange_enabled", event.currentTarget.checked, event.currentTarget));
    el.ouisyncSettingCache?.addEventListener("change", (event) => updateOuisyncRepositorySetting("cache_servers_enabled", event.currentTarget.checked, event.currentTarget));
    el.ouisyncMountStart?.addEventListener("click", () => runOuisyncMountAction("mount"));
    el.ouisyncNudgeSync?.addEventListener("click", () => nudgeOuisyncRepository());
    el.ouisyncPeerAddForm?.addEventListener("submit", (event) => {
      event.preventDefault();
      runOuisyncPeerAction("add", String(el.ouisyncPeerAddInput?.value || "").trim(), el.ouisyncPeerAddButton);
    });
    el.ouisyncMountStop?.addEventListener("click", () => runOuisyncMountAction("unmount"));
    el.ouisyncMountForceStop?.addEventListener("click", () => runOuisyncMountAction("force-unmount"));
    el.ouisyncDebugSeed?.addEventListener("click", () => runOuisyncDebugAction("ng-provider"));
    el.ouisyncResetSeed?.addEventListener("click", () => {
      if (window.confirm(t("ui.ouisync_debug_reset_confirm", "This deletes the local ng_provider cache and reconnects its trusted repository. Continue?"))) {
        runOuisyncDebugAction("reset-ng-provider");
      }
    });
    el.ouisyncDebugModalClose?.addEventListener("click", () => el.ouisyncDebugModal?.close());
    if (el.installProtonCommonDepsBtn) {
      el.installProtonCommonDepsBtn.addEventListener(
        "click",
        onInstallGameProtonCommonDependencies,
      );
    }
    if (el.detailWinetricksSelectCommon) {
      el.detailWinetricksSelectCommon.addEventListener("click", () =>
        setSelectedGameWinetricksPackages(currentDefaultWinetricksPackages()),
      );
    }
    if (el.detailWinetricksSelectAll) {
      el.detailWinetricksSelectAll.addEventListener("click", () =>
        setSelectedGameWinetricksPackages(availableWinetricksPackageIds()),
      );
    }
    if (el.detailWinetricksSelectNone) {
      el.detailWinetricksSelectNone.addEventListener("click", () =>
        setSelectedGameWinetricksPackages([]),
      );
    }
    if (el.detailWinetricksSaveBtn) {
      el.detailWinetricksSaveBtn.addEventListener(
        "click",
        onSaveSelectedGameWinetricksMetadata,
      );
    }
    if (el.detailWinetricksInstallBtn) {
      el.detailWinetricksInstallBtn.addEventListener(
        "click",
        onInstallSelectedGameWinetricksPackages,
      );
    }
    if (el.detailWinetricksRemoveBtn) {
      el.detailWinetricksRemoveBtn.addEventListener(
        "click",
        onOpenSelectedGamePrefixUninstaller,
      );
    }
    if (el.linuxRuntimeSelect) {
      el.linuxRuntimeSelect.addEventListener("change", onLinuxRuntimeChange);
    }
    if (el.lanModeSelect) {
      el.lanModeSelect.addEventListener("change", () => {
        renderLanGameSharePanel();
        renderLanDiscoveryVisibility();
        if (currentLanMode() === "client") scanLanServers().catch(() => {});
        if (currentLanMode() === "server") {
          loadLanGameInventory({
            serverRolePreview: true,
            showLoading: true,
          }).catch(() => {});
        }
      });
    }
    el.lanDiscoveryScan?.addEventListener("click", () => scanLanServers());
    el.lanPairBegin?.addEventListener("click", () => beginLanPairing());
    el.lanPairRenew?.addEventListener("click", () => renewLanPairing());
    el.lanPairConnect?.addEventListener("click", () => connectLanServer());
    el.lanServerSettingsSave?.addEventListener("click", () => saveLanServerSettings());
    el.saveSettingsBtn.addEventListener("click", () => onSaveSettings(false));
    el.updateRollbackBtn.addEventListener("click", onManualUpdateRollback);
    el.installPrereqBtn.addEventListener("click", onInstallPrerequisitesBundle);
    if (el.installWineCommonDepsBtn) {
      el.installWineCommonDepsBtn.addEventListener(
        "click",
        onInstallWineCommonDependencies,
      );
    }
    el.syncModeLanBtn.addEventListener("click", () =>
      onSetResilioNetworkMode("lan", el.syncModeLanBtn),
    );
    el.syncModeInternetBtn.addEventListener("click", () =>
      onSetResilioNetworkMode("internet", el.syncModeInternetBtn),
    );
    el.setNetworkPrivateBtn.addEventListener("click", onSetLocalNetworkPrivate);
    if (el.statusLanGamesRefreshBtn) {
      el.statusLanGamesRefreshBtn.addEventListener("click", () =>
        loadLanGameInventory(),
      );
    }
    el.extraSyncAddBtn.addEventListener("click", () =>
      openExtraSyncModal(null),
    );
    el.extraSyncImportBtn.addEventListener("click", () =>
      el.extraSyncImportFile.click(),
    );
    el.extraSyncImportFile.addEventListener("change", onExtraSyncBootstrapImport);
    el.extraSyncCancelBtn.addEventListener("click", closeExtraSyncModal);
    el.extraSyncSaveBtn.addEventListener("click", onExtraSyncSave);
    el.extraSyncModal.addEventListener("click", (event) => {
      if (event.target === el.extraSyncModal) {
        closeExtraSyncModal();
      }
    });
    el.wizardSaveBtn.addEventListener("click", onWizardSave);
    el.wizardNicknameInput.addEventListener("keydown", onWizardEnterSubmit);
    el.wizardStorageInput.addEventListener("keydown", onWizardEnterSubmit);
    el.wizardStorageSelect.addEventListener("keydown", onWizardEnterSubmit);
    el.serviceSyncStart.addEventListener("click", onServiceSyncStart);
    el.serviceSyncStop.addEventListener("click", onServiceSyncStop);
    el.serviceSyncWebui.addEventListener("click", () => openStatusTab());
    if (el.tabHomeBtn) {
      el.tabHomeBtn.addEventListener("click", () => setActiveTab("home"));
    }
    if (el.tabStatusBtn) {
      el.tabStatusBtn.addEventListener("click", () => setActiveTab("status"));
    }
    if (el.tabProvidersBtn) {
      el.tabProvidersBtn.addEventListener("click", () =>
        setActiveTab("providers"),
      );
    }
    if (el.tabSettingsBtn) {
      el.tabSettingsBtn.addEventListener("click", () =>
        setActiveTab("settings"),
      );
    }
    if (el.tabLogsBtn) {
      el.tabLogsBtn.addEventListener("click", () => setActiveTab("logs"));
    }
    for (const [providerType, button] of Object.entries(el.providerTabs)) {
      if (!button) {
        continue;
      }
      button.addEventListener("click", () => {
        setActiveProviderTab(providerType);
        refreshProviderPanel(true);
      });
    }
    if (el.ouisyncDirectoryUp) {
      el.ouisyncDirectoryUp.addEventListener("click", () => {
        const parts = String(state.ouisyncDirectoryPath || "/")
          .split("/")
          .filter(Boolean);
        parts.pop();
        state.ouisyncDirectoryPath = parts.length ? `/${parts.join("/")}` : "/";
        refreshOuisyncInventory(true);
      });
    }
    if (el.providerOpenExternalBtn) {
      el.providerOpenExternalBtn.addEventListener(
        "click",
        openActiveProviderExternally,
      );
    }
    if (el.logsSourceFilterSelect) {
      el.logsSourceFilterSelect.addEventListener(
        "change",
        onLogsSourceFilterChange,
      );
    }
    if (el.logsLengthSelect) {
      el.logsLengthSelect.addEventListener("change", onLogsLimitChange);
    }
    if (el.logsLevelSelect) {
      el.logsLevelSelect.addEventListener("change", onLogsLevelChange);
    }
    if (el.topTrafficToggle) {
      el.topTrafficToggle.addEventListener("click", toggleTopTrafficMode);
    }
    if ((el.topTrafficToggle || el.topActions) && "ResizeObserver" in window) {
      topTrafficResizeObserver = new ResizeObserver(() => {
        updateTopbarTrafficSizing();
        renderTopTrafficChart();
      });
      if (el.topTrafficToggle) {
        topTrafficResizeObserver.observe(el.topTrafficToggle);
      }
      if (el.topActions) {
        topTrafficResizeObserver.observe(el.topActions);
      }
    } else {
      window.addEventListener("resize", () => {
        updateTopbarTrafficSizing();
        renderTopTrafficChart();
      });
    }
    if (el.gameList && "ResizeObserver" in window) {
      catalogResizeObserver = new ResizeObserver(() => {
        updateCatalogGridSizing();
      });
      catalogResizeObserver.observe(el.gameList);
    } else {
      window.addEventListener("resize", updateCatalogGridSizing);
    }
    if (el.topHelpDocs) {
      el.topHelpDocs.addEventListener("click", onOpenLocalDocs);
    }
    if (el.topLinksSelect) {
      el.topLinksSelect.addEventListener("change", (event) => {
        const url = String(event.target?.value || "").trim();
        if (url) {
          window.open(url, "_blank", "noopener,noreferrer");
        }
        el.topLinksSelect.value = "";
      });
    }
    el.stopAppBtn.addEventListener("click", onStopApp);
    if (el.shutdownUpdateResumeBtn) {
      el.shutdownUpdateResumeBtn.addEventListener(
        "click",
        onShutdownUpdateResume,
      );
    }
    if (el.shutdownUpdateAbortBtn) {
      el.shutdownUpdateAbortBtn.addEventListener(
        "click",
        onShutdownUpdateAbort,
      );
    }
    if (el.shutdownUpdateConfirmBtn) {
      el.shutdownUpdateConfirmBtn.addEventListener(
        "click",
        onShutdownUpdateConfirm,
      );
    }
    el.viewListBtn.addEventListener("click", async () => {
      state.viewMode = "list";
      applyViewMode();
      await loadCatalog();
    });
    el.viewGridBtn.addEventListener("click", async () => {
      state.viewMode = "grid";
      applyViewMode();
      await loadCatalog();
    });
    el.gridSizeSelect.addEventListener("change", async (event) => {
      state.gridTileSize = normalizeGridTileSize(event.target.value);
      applyViewMode();
      await loadCatalog();
    });
    el.logsRefreshBtn.addEventListener("click", () => loadLogs(true));
    el.logsPauseBtn.addEventListener("click", async () => {
      state.logsPaused = !state.logsPaused;
      el.logsPauseBtn.textContent = state.logsPaused
        ? t("logs.continue", "Continue")
        : t("logs.pause", "Pause");
      if (!state.logsPaused) {
        await loadLogs(true);
      }
    });
  }

  async function bootstrap() {
    bindEvents();
    await loadLocale(state.locale);
    updateStartupScreen();
    await waitForBackendReady();
    await loadVersion();
    await loadSettings();
    // Render the locally available catalog first; remote/site enrichment can
    // catch up in the background without delaying first paint.
    loadLauncherSite().catch(() => {});
    ensureWinetricksCatalogLoaded().catch(() => {});
    loadGenres().catch(() => {});
    setActiveTab(state.activeTab, false);
    setActiveProviderTab(state.activeProviderTab, false);
    applyViewMode();
    await loadCatalog();
    refreshSyncWidgets().catch(() => {});
    refreshUpdateAvailabilityHint().catch(() => {});
    loadLogs().catch(() => {});

    window.setInterval(() => {
      refreshSyncWidgets().catch(() => {});
    }, 1500);
    window.setInterval(() => {
      loadLogs().catch(() => {});
    }, 3000);
    window.setInterval(() => {
      refreshCatalogSyncProgress().catch(() => {});
    }, 4000);
    window.setInterval(refreshInstallStateBackground, 30000);
    window.setInterval(() => {
      refreshUpdateAvailabilityHint().catch(() => {});
    }, 15000);
    window.setInterval(() => {
      loadLauncherSite().catch(() => {});
    }, 15000);
  }

  bootstrap().catch((err) => {
    console.error(err);
  });
})();
