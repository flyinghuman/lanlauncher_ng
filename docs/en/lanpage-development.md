# LANPage Development Setup (English)

This guide configures a development machine so `LANPage` is served locally as `http://launcher.lan/` on standard HTTP port `80`.

## Prerequisites
- Docker Engine and Docker Compose plugin installed.
- Repository checked out at `LANLauncherNG` root.
- `LANPage` folder present in the repository root.

## 1. Configure local hostname
Add this line to your hosts file:

```text
127.0.0.1 launcher.lan
```

Common hosts file locations:
- Windows: `C:\Windows\System32\drivers\etc\hosts`
- Linux: `/etc/hosts`

## 2. Start LANPage container
From repository root:

```bash
docker compose up -d --build
```

This starts the `lanpage` service defined in `docker-compose.yml` and exposes container port `80` as host port `80`.

## 3. Open the site
Navigate to:

```text
http://launcher.lan/
```

## 4. Daily development commands
- Start in background:
  - `docker compose up -d`
- View logs:
  - `docker compose logs -f lanpage`
- Stop:
  - `docker compose down`

## 5. Validation checks
- `docker compose ps` shows `lanpage` as running.
- `curl http://launcher.lan/` returns HTML content.

## Notes
- Root `.gitignore` excludes `/LANPage/` so the external LANPage project is not tracked in LANLauncherNG.
- If port `80` is already in use, stop the conflicting service before starting compose.

## launcher.ini Integration in LANLauncherNG
- LANLauncherNG polls `http://launcher.lan/launcher.ini` regularly.
- If LANPage is temporarily unreachable, LANLauncherNG keeps the last known valid launcher.ini state.
- On fresh startup without reachable LANPage and without cache, LANLauncherNG uses default behavior (no launcher.ini overrides).
- Parsed `disable_games` entries take precedence and those game IDs are hidden from catalog list/grid and blocked from launcher actions.
- Parsed link keys are exposed in the top bar dropdown:
  - `lan_url`
  - `link_1` to `link_5`
  - `discord_url`
  - `ts3_server`
- Parsed `lan_title` is appended to the app title in the top bar.
- LANLauncherNG also sends non-blocking stats updates to `stats_url` (or fallback `http://launcher.lan/stats.php`).
