"""Persist the LAN owner's explicitly published game IDs outside the synced tree."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

_GAME_ID = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]{0,127}$")


class InvalidLanShares(ValueError):
    """The local LAN share selection is malformed."""


class LanShareStore:
    """Store the owner's share selection in app data, never in a game repository."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def read(self) -> list[str]:
        try:
            value = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise InvalidLanShares("lan_shares_invalid") from exc
        if (
            not isinstance(value, dict)
            or type(value.get("schema_version")) is not int
            or value.get("schema_version") != 1
            or not isinstance(value.get("game_ids"), list)
        ):
            raise InvalidLanShares("lan_shares_invalid")
        result: list[str] = []
        seen: set[str] = set()
        for game_id in value["game_ids"]:
            if not isinstance(game_id, str) or not _GAME_ID.fullmatch(game_id):
                raise InvalidLanShares("lan_shares_invalid")
            normalized = game_id.casefold()
            if normalized not in seen:
                seen.add(normalized)
                result.append(game_id)
        return result

    def write(self, game_ids: list[str]) -> list[str]:
        if not isinstance(game_ids, list):
            raise InvalidLanShares("lan_shares_invalid")
        selected: list[str] = []
        seen: set[str] = set()
        for game_id in game_ids:
            if not isinstance(game_id, str) or not _GAME_ID.fullmatch(game_id):
                raise InvalidLanShares("lan_shares_invalid")
            normalized = game_id.casefold()
            if normalized not in seen:
                seen.add(normalized)
                selected.append(game_id)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"schema_version": 1, "game_ids": selected},
            ensure_ascii=True,
            indent=2,
        ) + "\n"
        temp_name = ""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._path.parent,
                prefix=".lan-shares-",
                delete=False,
            ) as stream:
                temp_name = stream.name
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, self._path)
        finally:
            if temp_name:
                Path(temp_name).unlink(missing_ok=True)
        return selected

    def set_shared(self, game_id: str, shared: bool) -> list[str]:
        current = self.read()
        existing = next(
            (value for value in current if value.casefold() == game_id.casefold()),
            None,
        )
        if shared and existing is None:
            current.append(game_id)
        elif not shared and existing is not None:
            current = [value for value in current if value.casefold() != game_id.casefold()]
        return self.write(current)
