# LANLauncherNG

LANLauncherNG brings a game catalog, synchronized game files, and launch controls together for Windows and Linux. It can use an existing provider catalog, a LAN server's shared catalog, or entries that you add for games already on your computer.

## Start here

- [Using LANLauncherNG](using-lanlauncher.md) explains first setup, finding and playing games, and joining a LAN server.
- [Game workflow reference](game-workflow.md) describes supported game folders and launch behavior.
- [Sync provider reference](sync-provider.md) explains provider roles and LAN sharing for administrators.

## Developer reference

The remaining pages document architecture, APIs, packaging, metadata formats, and development workflows. They are intended for contributors and administrators who need implementation details. See the navigation under **Developer reference**.

## What LANLauncherNG does

The launcher presents games from configured catalogs, manages their synchronized files, and starts them with the available platform runtime. It does not provide game licenses or host official game downloads. A game must be available from a configured sync provider or already be present on disk.

The same library folder holds synchronized game files. Choose a drive with enough free space before you start downloading games.
