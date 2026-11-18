"""CLI entrypoint for lanlauncher-core."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
from threading import Event, Thread

from src.core.config.loader import load_config
from src.core.db.migrations import SCHEMA_VERSION
from src.core.db.rollback import (
    create_db_backup,
    latest_db_backup,
    list_db_backups,
    restore_db_backup,
)
from src.core.db.store import open_database
from src.core.service.app import Application
from src.core.service.logging_setup import configure_logging
from src.core.version import APP_VERSION


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LANLauncherNG core service")
    parser.add_argument("--config", default=None, help="Path to config JSON file")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--migrate-db",
        action="store_true",
        help="Apply pending SQLite migrations and exit without starting the service.",
    )
    mode_group.add_argument(
        "--rollback-db",
        action="store_true",
        help="Restore SQLite DB from latest backup and exit without starting the service.",
    )
    mode_group.add_argument(
        "--list-db-backups",
        action="store_true",
        help="List discovered DB backup snapshots and exit.",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Optional DB path override for --migrate-db/--rollback-db (default: config db_path).",
    )
    parser.add_argument(
        "--rollback-source",
        default=None,
        help="Optional backup file path for --rollback-db (default: latest backup).",
    )
    parser.add_argument(
        "--target-schema-version",
        default=None,
        type=int,
        help="Optional schema version target for automatic backup selection in --rollback-db.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = load_config(args.config)
    configure_logging(config.log_level, log_path=config.log_path)

    if bool(getattr(args, "migrate_db", False)):
        target_db_path = str(getattr(args, "db_path", "") or config.db_path).strip()
        try:
            backup_path = create_db_backup(target_db_path, app_version=APP_VERSION)
            db = open_database(target_db_path)
            row = db.connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone()
            db.connection.close()
            version = int(row[0]) if row else 0
            logging.getLogger(__name__).info(
                "db_migration_complete path=%s version=%s", target_db_path, version
            )
            if backup_path is not None:
                logging.getLogger(__name__).info(
                    "db_migration_backup_created path=%s backup=%s",
                    target_db_path,
                    backup_path,
                )
            print(f"DB migration complete: {target_db_path} (schema_version={version})")
            if backup_path is not None:
                print(f"DB backup created: {backup_path}")
            return 0
        except OSError as exc:
            logging.getLogger(__name__).error(
                "db_migration_failed path=%s error=%s", target_db_path, exc
            )
            print(f"DB migration failed: {target_db_path} ({exc})", file=sys.stderr)
            return 1

    if bool(getattr(args, "list_db_backups", False)):
        target_db_path = str(getattr(args, "db_path", "") or config.db_path).strip()
        backups = list_db_backups(target_db_path)
        if not backups:
            print(f"No DB backups found for {target_db_path}")
            return 0
        print(f"DB backups for {target_db_path}:")
        for item in backups:
            print(
                "- "
                f"path={item.get('backup_path', '')} "
                f"schema_version={item.get('schema_version', 0)} "
                f"app_version={item.get('app_version', '')} "
                f"created_at_utc={item.get('created_at_utc', '')}"
            )
        return 0

    if bool(getattr(args, "rollback_db", False)):
        target_db_path = str(getattr(args, "db_path", "") or config.db_path).strip()
        source = str(getattr(args, "rollback_source", "") or "").strip()
        target_schema_version_raw = getattr(args, "target_schema_version", None)
        target_schema_version = (
            int(target_schema_version_raw)
            if target_schema_version_raw is not None
            else SCHEMA_VERSION
        )
        source_path = source or ""
        if not source_path:
            latest = latest_db_backup(
                target_db_path, target_schema_version=target_schema_version
            )
            if latest is None:
                print(
                    "DB rollback failed: no backup found for "
                    f"{target_db_path} (target_schema_version={target_schema_version})",
                    file=sys.stderr,
                )
                return 1
            source_path = str(latest)
        try:
            restore_db_backup(target_db_path, source_path)
            logging.getLogger(__name__).info(
                "db_rollback_complete path=%s source=%s", target_db_path, source_path
            )
            print(f"DB rollback complete: {target_db_path} (source={source_path})")
            return 0
        except OSError as exc:
            logging.getLogger(__name__).error(
                "db_rollback_failed path=%s source=%s error=%s",
                target_db_path,
                source_path,
                exc,
            )
            print(
                f"DB rollback failed: {target_db_path} (source={source_path}) ({exc})",
                file=sys.stderr,
            )
            return 1

    app = Application(config)
    shutdown_started = Event()

    def _request_shutdown(reason: str) -> None:
        if shutdown_started.is_set():
            return
        shutdown_started.set()
        logging.getLogger(__name__).info("shutdown_requested reason=%s", reason)
        # Avoid stopping the HTTP server directly from signal-handler context.
        Thread(target=app.stop, daemon=True).start()

    def _signal_handler(_sig: int, _frame: object) -> None:
        _request_shutdown("signal")

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    import os

    try:
        # Start serving immediately so static frontend assets are reachable while
        # backend bootstrap (catalog import/scan/sync prep) is still warming up.
        run_thread = Thread(target=app.run, daemon=True)
        run_thread.start()

        if os.environ.get("LLNG_NO_BROWSER", "0") != "1":
            from src.core.platform.browser import launch_ui_async

            host = (
                config.bind_host
                if config.bind_host not in ("0.0.0.0", "::")
                else "127.0.0.1"
            )
            url = f"http://{host}:{config.bind_port}/"
            launch_ui_async(
                url,
                delay=0.15,
                on_closed=lambda: _request_shutdown("ui_window_closed"),
            )

        app.bootstrap()
        run_thread.join()
    except OSError as exc:
        logging.getLogger(__name__).error("startup_failed: %s", exc)
        app.stop()
        return 1
    except Exception:
        app.stop()
        raise
    except KeyboardInterrupt:
        app.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
