"""Strict normalization shared by network responses and stored schema v1."""

import json
from datetime import datetime

STEAM_ID = "76561198035296905"
PROFILE_URL = f"https://steamcommunity.com/profiles/{STEAM_ID}/"


class SyncError(Exception):
    """Safe, fixed diagnostic suitable for logging without credentials."""


def integer(value, nullable=False):
    if value is None and nullable:
        return None
    if type(value) is not int or value < 0:
        raise SyncError("Invalid numeric game field; previous snapshot preserved.")
    return value


def games_from_api(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("response"), dict):
        raise SyncError("Malformed Steam response; previous snapshot preserved.")
    response = payload["response"]
    games = response.get("games")
    count = integer(response.get("game_count"))
    if not isinstance(games, list) or not games or count != len(games):
        raise SyncError("Empty, inaccessible or incomplete library. Check Game Details privacy.")
    normalized = []
    seen = set()
    for game in games:
        if not isinstance(game, dict):
            raise SyncError("Invalid game record.")
        appid = integer(game.get("appid"))
        if not appid or appid in seen:
            raise SyncError("Invalid or duplicate AppID; previous snapshot preserved.")
        seen.add(appid)
        name = game.get("name")
        icon = game.get("img_icon_url")
        if name is not None and (not isinstance(name, str) or not name.strip()):
            name = None
        if icon is not None and not isinstance(icon, str):
            raise SyncError("Invalid icon metadata.")
        normalized.append(
            {
                "appid": appid,
                "name": name,
                "playtime_forever_minutes": integer(game.get("playtime_forever")),
                "playtime_2weeks_minutes": integer(game.get("playtime_2weeks"), True),
                "last_played_unix": integer(game.get("rtime_last_played"), True),
                "icon_hash": icon or None,
            }
        )
    return sorted(normalized, key=lambda game: game["appid"])


def validate_snapshot(snapshot):
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != 1:
        raise SyncError("Unsupported snapshot schema; explicit migration required.")
    if snapshot.get("steam_id") != STEAM_ID or snapshot.get("profile_url") != PROFILE_URL:
        raise SyncError("Snapshot profile mismatch.")
    try:
        timestamp = datetime.fromisoformat(snapshot["snapshot_updated_at"].replace("Z", "+00:00"))
        if timestamp.utcoffset() is None or timestamp.utcoffset().total_seconds() != 0:
            raise ValueError
        games = snapshot["games"]
        translated = [
            {
                "appid": g["appid"],
                "name": g["name"],
                "playtime_forever": g["playtime_forever_minutes"],
                "playtime_2weeks": g["playtime_2weeks_minutes"],
                "rtime_last_played": g["last_played_unix"],
                "img_icon_url": g["icon_hash"],
            }
            for g in games
        ]
        normalized = games_from_api(
            {
                "response": {
                    "game_count": snapshot["game_count"],
                    "games": translated,
                }
            }
        )
        if normalized != games:
            raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError):
        raise SyncError("Invalid stored snapshot; repair or restore it before syncing.") from None
    return snapshot


def serialize(value):
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
