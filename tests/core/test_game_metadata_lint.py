"""Tests for game metadata action linting used before packaging content."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.scripts.lint_game_metadata import find_metadata_files, lint_file


class GameMetadataLintTests(unittest.TestCase):
    def test_windows_and_linux_package_builders_run_metadata_linter(self) -> None:
        repo = Path(__file__).parents[2]
        for relative in (
            "tools/scripts/package-windows.ps1",
            "packaging/linux/package-linux.sh",
        ):
            with self.subTest(script=relative):
                source = (repo / relative).read_text(encoding="utf-8")
                self.assertIn("lint_game_metadata.py", source)
                self.assertIn("library", source)
                self.assertIn("ng_provider", source)

    def test_cli_fails_for_invalid_actions_before_packaging(self) -> None:
        script = Path(__file__).parents[2] / "tools" / "scripts" / "lint_game_metadata.py"
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp) / "demo"
            game.mkdir()
            (game / "metadata.json").write_text(
                json.dumps({"installer_tasks": [{"name": "unknown-action"}]}),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(script), str(game)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("unsupported action 'unknown-action'", result.stderr)

    def test_supported_actions_accept_packages_from_app_or_args(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp) / "demo"
            game.mkdir()
            metadata_path = game / "metadata.json"
            metadata_path.write_text(
                json.dumps(
                    {
                        "game_id": "demo",
                        "installer_tasks": [
                            {"name": "winetricks", "app": "vcrun2019"},
                            {"action": "protontricks", "args": "corefonts"},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(lint_file(metadata_path), [])

    def test_unsupported_actions_and_tasks_without_packages_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp) / "demo"
            game.mkdir()
            metadata_path = game / "metadata.json"
            metadata_path.write_text(
                json.dumps(
                    {
                        "installer_tasks": [
                            {"name": "custom-shell", "args": "setup"},
                            {"name": "winetricks", "args": "-q"},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            diagnostics = lint_file(metadata_path)

            self.assertEqual(len(diagnostics), 2)
            self.assertIn("unsupported action 'custom-shell'", diagnostics[0])
            self.assertIn("needs a package in app or args", diagnostics[1])

    def test_malformed_task_shape_and_quote_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp) / "demo"
            game.mkdir()
            metadata_path = game / "metadata.json"
            metadata_path.write_text(
                json.dumps(
                    {
                        "installer": [
                            "not-an-object",
                            {"name": "winetricks", "args": "'unterminated"},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            diagnostics = lint_file(metadata_path)

            self.assertIn("installer task 1 must be an object", diagnostics[0])
            self.assertIn("args must be a string or an array", diagnostics[1])

    def test_discovers_metadata_at_game_root_and_ouisync_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp)
            portable = library / "portable" / "metadata.json"
            ouisync = library / "synced" / ".ouisync" / "metadata.json"
            portable.parent.mkdir()
            ouisync.parent.mkdir(parents=True)
            portable.write_text("{}", encoding="utf-8")
            ouisync.write_text("{}", encoding="utf-8")
            nested_local = library / "synced" / ".ouisync" / "local"
            nested_local.mkdir()
            (nested_local / "metadata.json").write_text("{}", encoding="utf-8")

            files = find_metadata_files([library])

            self.assertEqual(files, [portable, ouisync])
            self.assertEqual(lint_file(ouisync), [])

    def test_invalid_game_id_location_and_malformed_json_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp) / "folder-id"
            game.mkdir()
            metadata_path = game / "metadata.json"
            metadata_path.write_text(
                json.dumps({"game_id": "different-id"}), encoding="utf-8"
            )
            self.assertIn("does not match containing folder", lint_file(metadata_path)[0])

            metadata_path.write_text("{broken", encoding="utf-8")
            self.assertIn("cannot read metadata JSON", lint_file(metadata_path)[0])

