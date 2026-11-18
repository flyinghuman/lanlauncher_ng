"""Startup flow regression tests for early UI/server availability."""

from __future__ import annotations

import unittest
from argparse import Namespace
from unittest.mock import Mock, patch

from src.core import main as main_module


class MainStartupTests(unittest.TestCase):
    def test_main_starts_server_thread_before_bootstrap(self) -> None:
        order: list[str] = []

        mock_config = Mock()
        mock_config.log_level = "INFO"
        mock_config.bind_host = "127.0.0.1"
        mock_config.bind_port = 18080

        mock_app = Mock()
        mock_app.run.side_effect = lambda: order.append("run")
        mock_app.bootstrap.side_effect = lambda: order.append("bootstrap")

        class ImmediateThread:
            def __init__(self, target, daemon=False):
                self._target = target

            def start(self):
                self._target()

            def join(self):
                return None

        mock_parser = Mock()
        mock_parser.parse_args.return_value = Namespace(
            config=None,
            migrate_db=False,
            rollback_db=False,
            list_db_backups=False,
            db_path=None,
            rollback_source=None,
            target_schema_version=None,
        )

        with (
            patch("src.core.main.build_parser", return_value=mock_parser),
            patch("src.core.main.load_config", return_value=mock_config),
            patch("src.core.main.configure_logging"),
            patch("src.core.main.Application", return_value=mock_app),
            patch("src.core.main.Thread", ImmediateThread),
            patch("src.core.main.signal.signal"),
            patch.dict("os.environ", {"LLNG_NO_BROWSER": "1"}, clear=False),
        ):
            code = main_module.main()

        self.assertEqual(code, 0)
        self.assertEqual(order, ["run", "bootstrap"])

    def test_main_migrate_db_mode_applies_migrations_and_exits(self) -> None:
        mock_config = Mock()
        mock_config.log_level = "INFO"
        mock_config.log_path = "data/logs/log.txt"
        mock_config.db_path = "data/lanlauncher.db"

        fake_conn = Mock()
        fake_conn.execute.return_value.fetchone.return_value = (7,)
        fake_db = Mock()
        fake_db.connection = fake_conn

        mock_parser = Mock()
        mock_parser.parse_args.return_value = Namespace(
            config=None,
            migrate_db=True,
            rollback_db=False,
            list_db_backups=False,
            db_path="tmp/test.db",
            rollback_source=None,
            target_schema_version=None,
        )

        with (
            patch("src.core.main.build_parser", return_value=mock_parser),
            patch("src.core.main.load_config", return_value=mock_config),
            patch("src.core.main.configure_logging"),
            patch("src.core.main.create_db_backup", return_value=None),
            patch("src.core.main.open_database", return_value=fake_db) as open_db,
            patch("src.core.main.Application") as app_cls,
            patch("builtins.print") as print_mock,
        ):
            code = main_module.main()

        self.assertEqual(code, 0)
        open_db.assert_called_once_with("tmp/test.db")
        app_cls.assert_not_called()
        print_mock.assert_any_call(
            "DB migration complete: tmp/test.db (schema_version=7)"
        )

    def test_main_migrate_db_mode_returns_error_on_failure(self) -> None:
        mock_config = Mock()
        mock_config.log_level = "INFO"
        mock_config.log_path = "data/logs/log.txt"
        mock_config.db_path = "data/lanlauncher.db"

        mock_parser = Mock()
        mock_parser.parse_args.return_value = Namespace(
            config=None,
            migrate_db=True,
            rollback_db=False,
            list_db_backups=False,
            db_path=None,
            rollback_source=None,
            target_schema_version=None,
        )

        with (
            patch("src.core.main.build_parser", return_value=mock_parser),
            patch("src.core.main.load_config", return_value=mock_config),
            patch("src.core.main.configure_logging"),
            patch("src.core.main.create_db_backup", return_value=None),
            patch(
                "src.core.main.open_database", side_effect=OSError("denied")
            ) as open_db,
            patch("src.core.main.Application") as app_cls,
            patch("builtins.print") as print_mock,
        ):
            code = main_module.main()

        self.assertEqual(code, 1)
        open_db.assert_called_once_with("data/lanlauncher.db")
        app_cls.assert_not_called()
        self.assertTrue(
            any(
                "DB migration failed: data/lanlauncher.db (denied)" in str(call)
                for call in print_mock.call_args_list
            )
        )

    def test_main_rollback_db_mode_uses_latest_backup_and_exits(self) -> None:
        mock_config = Mock()
        mock_config.log_level = "INFO"
        mock_config.log_path = "data/logs/log.txt"
        mock_config.db_path = "data/lanlauncher.db"

        mock_parser = Mock()
        mock_parser.parse_args.return_value = Namespace(
            config=None,
            migrate_db=False,
            rollback_db=True,
            list_db_backups=False,
            db_path=None,
            rollback_source=None,
            target_schema_version=None,
        )

        with (
            patch("src.core.main.build_parser", return_value=mock_parser),
            patch("src.core.main.load_config", return_value=mock_config),
            patch("src.core.main.configure_logging"),
            patch(
                "src.core.main.latest_db_backup",
                return_value="data/backups/lanlauncher.db.1.bak",
            ) as latest_backup,
            patch("src.core.main.restore_db_backup") as restore_backup,
            patch("src.core.main.Application") as app_cls,
            patch("builtins.print") as print_mock,
        ):
            code = main_module.main()

        self.assertEqual(code, 0)
        latest_backup.assert_called_once_with(
            "data/lanlauncher.db", target_schema_version=14
        )
        restore_backup.assert_called_once_with(
            "data/lanlauncher.db", "data/backups/lanlauncher.db.1.bak"
        )
        app_cls.assert_not_called()
        print_mock.assert_any_call(
            "DB rollback complete: data/lanlauncher.db (source=data/backups/lanlauncher.db.1.bak)"
        )

    def test_main_rollback_db_mode_fails_when_no_backup_exists(self) -> None:
        mock_config = Mock()
        mock_config.log_level = "INFO"
        mock_config.log_path = "data/logs/log.txt"
        mock_config.db_path = "data/lanlauncher.db"

        mock_parser = Mock()
        mock_parser.parse_args.return_value = Namespace(
            config=None,
            migrate_db=False,
            rollback_db=True,
            list_db_backups=False,
            db_path=None,
            rollback_source=None,
            target_schema_version=None,
        )

        with (
            patch("src.core.main.build_parser", return_value=mock_parser),
            patch("src.core.main.load_config", return_value=mock_config),
            patch("src.core.main.configure_logging"),
            patch("src.core.main.latest_db_backup", return_value=None),
            patch("src.core.main.Application") as app_cls,
            patch("builtins.print") as print_mock,
        ):
            code = main_module.main()

        self.assertEqual(code, 1)
        app_cls.assert_not_called()
        self.assertTrue(
            any(
                "DB rollback failed: no backup found for data/lanlauncher.db"
                in str(call)
                for call in print_mock.call_args_list
            )
        )

    def test_main_rollback_db_mode_uses_explicit_target_schema(self) -> None:
        mock_config = Mock()
        mock_config.log_level = "INFO"
        mock_config.log_path = "data/logs/log.txt"
        mock_config.db_path = "data/lanlauncher.db"

        mock_parser = Mock()
        mock_parser.parse_args.return_value = Namespace(
            config=None,
            migrate_db=False,
            rollback_db=True,
            list_db_backups=False,
            db_path=None,
            rollback_source=None,
            target_schema_version=4,
        )

        with (
            patch("src.core.main.build_parser", return_value=mock_parser),
            patch("src.core.main.load_config", return_value=mock_config),
            patch("src.core.main.configure_logging"),
            patch(
                "src.core.main.latest_db_backup",
                return_value="data/backups/lanlauncher.db.v4.bak",
            ) as latest_backup,
            patch("src.core.main.restore_db_backup"),
            patch("src.core.main.Application"),
            patch("builtins.print"),
        ):
            code = main_module.main()

        self.assertEqual(code, 0)
        latest_backup.assert_called_once_with(
            "data/lanlauncher.db", target_schema_version=4
        )

    def test_main_list_db_backups_mode_exits_without_starting_app(self) -> None:
        mock_config = Mock()
        mock_config.log_level = "INFO"
        mock_config.log_path = "data/logs/log.txt"
        mock_config.db_path = "data/lanlauncher.db"

        mock_parser = Mock()
        mock_parser.parse_args.return_value = Namespace(
            config=None,
            migrate_db=False,
            rollback_db=False,
            list_db_backups=True,
            db_path=None,
            rollback_source=None,
            target_schema_version=None,
        )

        with (
            patch("src.core.main.build_parser", return_value=mock_parser),
            patch("src.core.main.load_config", return_value=mock_config),
            patch("src.core.main.configure_logging"),
            patch(
                "src.core.main.list_db_backups",
                return_value=[
                    {
                        "backup_path": "data/backups/lanlauncher.db.1.bak",
                        "schema_version": 7,
                        "app_version": "0.3.2",
                        "created_at_utc": "2026-03-10T12:00:00+00:00",
                    }
                ],
            ) as list_backups,
            patch("src.core.main.Application") as app_cls,
            patch("builtins.print") as print_mock,
        ):
            code = main_module.main()

        self.assertEqual(code, 0)
        list_backups.assert_called_once_with("data/lanlauncher.db")
        app_cls.assert_not_called()
        self.assertTrue(
            any(
                "DB backups for data/lanlauncher.db:" in str(call)
                for call in print_mock.call_args_list
            )
        )


if __name__ == "__main__":
    unittest.main()
