"""Validate everything before writing; unchanged libraries produce no file changes."""

import argparse
import json
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from .changes import compare
from .client import fetch_games
from .models import PROFILE_URL, STEAM_ID, SyncError, games_from_api, serialize, validate_snapshot


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False
        ) as handle:
            temp = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temp.replace(path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def sync(
    key, directory=Path("data"), *, fetch=fetch_games, allow_large_removal=False, extended=False
):
    directory = Path(directory)
    path = directory / "steam-library.json"
    old = None
    if path.exists():
        try:
            old = validate_snapshot(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            raise SyncError("Cannot read previous snapshot; restore it before syncing.") from None
    games = games_from_api(fetch(key, extended=extended))
    changes = compare(old["games"] if old else [], games)
    removed = changes["removed"]
    if removed:
        if old and (len(removed) >= 25 or len(removed) / old["game_count"] > 0.1):
            if not allow_large_removal:
                raise SyncError(
                    "Large removal blocked. Check privacy; approve manually only if expected."
                )
        # Every removal requires two agreeing network reads, even small removals.
        confirmed = games_from_api(fetch(key, extended=extended))
        if games != confirmed:
            raise SyncError("Steam responses disagree; no removals or changes saved. Retry later.")
    if old and old["games"] == games:
        return False, len(games)
    now = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    snapshot = {
        "schema_version": 1,
        "steam_id": STEAM_ID,
        "profile_url": PROFILE_URL,
        "snapshot_updated_at": now,
        "game_count": len(games),
        "games": games,
    }
    validate_snapshot(snapshot)
    summary = {
        "schema_version": 1,
        "previous_snapshot_updated_at": old["snapshot_updated_at"] if old else None,
        "snapshot_updated_at": now,
        **changes,
    }
    # Git commits both files together; each local file replacement is atomic.
    atomic_write(directory / "steam-library-changes.json", serialize(summary))
    atomic_write(path, serialize(snapshot))
    return True, len(games)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--allow-large-removal", action="store_true")
    parser.add_argument("--extended-parameters", action="store_true")
    args = parser.parse_args()
    try:
        changed, count = sync(
            os.environ.get("STEAM_API_KEY", ""),
            args.data_dir,
            allow_large_removal=args.allow_large_removal,
            extended=args.extended_parameters,
        )
        print(f"Validated {count} games; " + ("snapshot updated." if changed else "unchanged."))
    except (SyncError, OSError):
        # Only fixed internal diagnostics may be printed; OS errors can contain sensitive paths.
        error = sys.exception()
        message = str(error) if isinstance(error, SyncError) else "Snapshot write failed."
        print(message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
