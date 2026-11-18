# Using LANLauncherNG

This guide covers the normal player workflow and the quickest way to share a game library at a LAN party. The interface is available in English and German; choose a language in the top bar.

## First setup

1. On the first launch, complete the Welcome wizard. Afterwards, open **Settings** to review your setup.
2. Set your player name and choose the library location. On Windows, choose the drive letter; on Linux, choose a path with enough free space.
3. Leave **Launcher mode** set to **Client** unless you are preparing the computer that will host the LAN catalog.
4. Save the settings. If your installation uses a sync provider, check its status badge at the top of the window. A stopped provider cannot download game files.

The library is where synchronized game data is stored. Changing the library path later does not move existing files for you.

The first-run wizard summarizes the distribution choices. OpenSourceGameIndex games use the bundled Ouisync provider and do not require pairing with an owner. Resilio/ETI remains an optional legacy provider when supplied and configured for your event. Custom games shared by an LLNG computer use the separate private LAN Server mode and its pairing code.

## Find and play a game

1. Use the search, category, and status filters above the game list. Select a game to see its description, version, links, and current state.
2. For a game that is not on disk, choose **Start Sync**. LAN games download when requested; the launcher then installs them automatically when synchronization finishes. With **Sync archives only** enabled, use **Install Anyway** after the archive is ready.
3. When installation is complete, choose **Start Game**. Use **Start Server** when the game provides a separate server launch action.
4. If a game offers an update, synchronize it before launching the updated version.

You can open the library or the selected game folder from its detail panel. The game list distinguishes downloading, installing, installed, and update-available states.

## Join a LAN game library

The LAN host must be running LANLauncherNG with Ouisync available, have its library ready, and be on the same reachable network as the clients. LLNG handles discovery and pairing directly; Ouisync carries the catalog and selected game repositories.

1. On the client, open **Settings**, choose **Client** under **Launcher mode**, and save.
2. Select **Find LAN servers**. If automatic discovery does not find the host, enter its IPv4 address and search again.
3. Select the intended server, enter the four-digit approval code shown in that server's settings, then choose **Connect to server**.
4. Wait for Ouisync to download the private catalog. The shared catalog appears in the game list. Select a game and choose **Start Sync** to fetch its files from the per-game Ouisync repository.

Ask the host for the code over a trusted channel. A code is valid for three days and can be used by multiple clients. The host can renew it from Server settings; renewal immediately invalidates the old code. Pairing requires the server to be online, but once synchronized the client keeps its catalog copy and can use it while the server is offline.

Ouisync game repositories are read-only on clients. Metadata, media, and the original archive stay in `.ouisync`; LLNG extracts the archive into writable `local/`. Local settings and extracted files are not sent back to the server. A client with a complete repository can seed another client after the host goes offline, if Ouisync can reach that peer.

## Host a LAN game library

Use a computer with the game files already present and enough disk space to serve clients. Server mode includes the normal client features.

1. In **Settings**, change **Launcher mode** to **Server** and save. The server must remain running while new clients pair.
2. In the LAN game list, choose **Share folder** for each game folder you want to offer. LLNG hides folders already owned by another provider or by a local game entry.
3. For a folder without metadata, choose **Create metadata**. Fill in at least a unique game ID and title; add a description, version, launch file, links, and cover as needed. Save the metadata, then share the folder. LLNG writes `metadata.json` in the game folder and publishes it in the LAN catalog.
4. In LAN server settings, select which catalog games clients can see, set event links, and save. A disabled game is hidden from clients unless it is already installed there.
5. Choose **Show approval code** and provide the displayed code to players. Use **Renew approval code** to replace it.

The server's LAN catalog and server settings are published through Ouisync under `locallansync/.ouisync`. Clients receive game descriptions and images from that catalog; game repositories are downloaded only when requested. You do not need to edit `game.db` or distribute database updates for LAN-only entries.

To stop offering a game, choose **Keep local** for its folder. Clients stop seeing it as available; installed copies and their files are preserved. Re-sharing the folder makes it available again.

## Add a game that is already installed

Choose **Add local game** in the catalog and enter a unique ID, title, and optional start file and artwork. A local entry is stored only on this computer; it does not publish or sync the game to other users. To make a game available to LAN clients, use a server-shared game folder and its metadata editor instead.

## Common problems

| What you see | What to check |
| --- | --- |
| No games appear | Check the selected library, catalog availability, and provider status. A new LAN client must complete pairing and receive `locallansync` first. |
| The LAN server is not found | Confirm both computers are on the same reachable LAN. Try the server's IPv4 address and check that Ouisync is running on the host. |
| The code is rejected | Select the right server and enter its current four-digit code. Codes expire after three days; the host can issue a new one. |
| A shared game is missing | Ask the host to share the folder and create valid metadata. The game ID must not collide with an existing catalog entry. |
| Sync does not start | Check the Ouisync status badge and free disk space. Ask the host whether the game is still shared. |
| A Windows game will not start on Linux | Install/configure a compatible Wine or Proton runtime in Settings, then select it for the game if needed. |

For folder sharing and provider behavior, see the [sync provider reference](sync-provider.md). For Linux runtime options, see the [game workflow reference](game-workflow.md).
