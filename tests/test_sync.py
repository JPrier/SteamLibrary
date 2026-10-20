import io
import json
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse

import pytest

from steam_sync.changes import compare
from steam_sync.client import MAX_BYTES, NoRedirect, fetch_games
from steam_sync.models import SyncError, games_from_api, serialize, validate_snapshot
from steam_sync.sync import main, sync


def payload(n=3):
    return {
        "response": {
            "game_count": n,
            "games": [
                {"appid": a + 1, "name": f"Game {a}", "playtime_forever": a} for a in range(n)
            ],
        }
    }


def fake(body):
    return lambda *a, **k: body


def test_large_library():
    games = games_from_api(payload(10000))
    assert len(games) == 10000
    assert games[0]["playtime_2weeks_minutes"] is None
    assert games[-1]["appid"] == 10000


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"response": {}},
        {"response": {"game_count": 0, "games": []}},
        {"response": {"game_count": 2, "games": []}},
        [],
    ],
)
def test_invalid_response(body):
    with pytest.raises(SyncError):
        games_from_api(body)


@pytest.mark.parametrize(
    "field,value",
    [
        ("appid", True),
        ("appid", 0),
        ("playtime_forever", -1),
        ("playtime_2weeks", "4"),
        ("img_icon_url", 4),
    ],
)
def test_invalid_game(field, value):
    body = payload()
    body["response"]["games"][0][field] = value
    with pytest.raises(SyncError):
        games_from_api(body)


def test_duplicate():
    body = payload()
    body["response"]["games"][1]["appid"] = 1
    with pytest.raises(SyncError, match="duplicate"):
        games_from_api(body)


def test_missing_name_and_optional():
    body = payload(1)
    del body["response"]["games"][0]["name"]
    game = games_from_api(body)[0]
    assert game["name"] is None
    assert game["last_played_unix"] is None
    assert game["icon_hash"] is None


def test_all_metadata():
    body = payload(1)
    body["response"]["games"][0].update(
        playtime_2weeks=30, rtime_last_played=123, img_icon_url="abc"
    )
    game = games_from_api(body)[0]
    assert (game["playtime_2weeks_minutes"], game["last_played_unix"], game["icon_hash"]) == (
        30,
        123,
        "abc",
    )


def test_successful_fetch():
    def opener(url, timeout):
        params = parse_qs(urlparse(url).query)
        assert params["key"] == ["secret"]
        query = json.loads(params["input_json"][0])
        assert query["include_played_free_games"] is True
        assert query["include_free_sub"] is True
        assert timeout == 30
        return io.BytesIO(json.dumps(payload()).encode())

    assert fetch_games("secret", open_url=opener, extended=True) == payload()


@pytest.mark.parametrize("code", [401, 403, 400, 302])
def test_nonretryable_and_redaction(code):
    calls = []

    def opener(url, **kwargs):
        calls.append(url)
        raise HTTPError(url, code, "secret", {}, None)

    with pytest.raises(SyncError) as err:
        fetch_games("secret", open_url=opener)
    assert "secret" not in str(err.value)
    assert len(calls) == 1
    assert err.value.__suppress_context__


@pytest.mark.parametrize("failure", [429, 500, 503, "network", "timeout"])
def test_bounded_retries(failure):
    delays = []

    def opener(url, **kwargs):
        if failure == "network":
            raise URLError("secret")
        if failure == "timeout":
            raise TimeoutError("secret")
        raise HTTPError(url, failure, "secret", {"Retry-After": "4"}, None)

    with pytest.raises(SyncError) as err:
        fetch_games("secret", open_url=opener, sleep=delays.append)
    assert "secret" not in str(err.value)
    assert len(delays) == 3
    assert all(d <= 60 for d in delays)


def test_retry_recovers():
    results = iter([False, True])

    def opener(url, **kwargs):
        if not next(results):
            raise URLError("secret")
        return io.BytesIO(json.dumps(payload()).encode())

    assert fetch_games("secret", open_url=opener, sleep=lambda _: None) == payload()


@pytest.mark.parametrize("raw", [b"not json secret", b"\xff"])
def test_malformed_json(raw):
    with pytest.raises(SyncError, match="malformed"):
        fetch_games("secret", open_url=lambda *a, **k: io.BytesIO(raw))


def test_size_bound():
    with pytest.raises(SyncError, match="size"):
        fetch_games("secret", open_url=lambda *a, **k: io.BytesIO(b" " * (MAX_BYTES + 1)))


def test_missing_key_and_redirect():
    with pytest.raises(SyncError, match="STEAM_API_KEY"):
        fetch_games("")
    assert NoRedirect().redirect_request(None, None, 302, "", {}, "https://other") is None


def test_unchanged_is_byte_identical(tmp_path):
    assert sync("key", tmp_path, fetch=fake(payload())) == (True, 3)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    body = payload()
    body["response"]["games"].reverse()
    assert sync("key", tmp_path, fetch=fake(body)) == (False, 3)
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


def test_added_removed_updated(tmp_path):
    sync("key", tmp_path, fetch=fake(payload(100)))
    body = payload(100)
    games = body["response"]["games"]
    games.pop()
    games.append({"appid": 101, "name": "New", "playtime_forever": 0})
    games[0]["playtime_forever"] = 50
    sync("key", tmp_path, fetch=fake(body))
    changes = json.loads((tmp_path / "steam-library-changes.json").read_text())
    assert changes["added"][0]["appid"] == 101
    assert changes["removed"][0]["appid"] == 100
    assert changes["updated"][0]["fields"]["playtime_forever_minutes"]["after"] == 50


@pytest.mark.parametrize("failure", ["empty", "partial", "large", "disagree", "network"])
def test_preserves_data(tmp_path, failure):
    sync("key", tmp_path, fetch=fake(payload(100)))
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    body = payload(99)
    if failure == "empty":
        body = payload(0)
    if failure == "partial":
        body["response"]["game_count"] = 100
    if failure == "large":
        body = payload(50)
    responses = iter([body, payload(98)])

    def fetch(*a, **k):
        if failure == "network":
            raise SyncError("Network failed")
        return next(responses)

    with pytest.raises(SyncError):
        sync("key", tmp_path, fetch=fetch)
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


def test_manual_removal_override(tmp_path):
    sync("key", tmp_path, fetch=fake(payload(100)))
    assert sync("key", tmp_path, fetch=fake(payload(2)), allow_large_removal=True) == (True, 2)


def test_schema_and_stable_serialization(tmp_path):
    sync("key", tmp_path, fetch=fake(payload()))
    path = tmp_path / "steam-library.json"
    snapshot = json.loads(path.read_text())
    assert validate_snapshot(snapshot) == snapshot
    assert serialize(snapshot) == path.read_text()
    snapshot["schema_version"] = 2
    path.write_text(serialize(snapshot))
    with pytest.raises(SyncError, match="schema"):
        sync("key", tmp_path, fetch=fake(payload()))


@pytest.mark.parametrize(
    "edit",
    [
        lambda s: s.update(steam_id="wrong"),
        lambda s: s.pop("games"),
        lambda s: s.update(snapshot_updated_at="bad"),
        lambda s: s.update(snapshot_updated_at="2026-01-01T00:00:00"),
        lambda s: s["games"].reverse(),
    ],
)
def test_invalid_stored_snapshot(tmp_path, edit):
    sync("key", tmp_path, fetch=fake(payload()))
    snapshot = json.loads((tmp_path / "steam-library.json").read_text())
    edit(snapshot)
    with pytest.raises(SyncError):
        validate_snapshot(snapshot)


def test_corrupt_file(tmp_path):
    (tmp_path / "steam-library.json").write_text("invalid")
    with pytest.raises(SyncError, match="read previous"):
        sync("key", tmp_path)


def test_cli_missing_key(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("STEAM_API_KEY", raising=False)
    monkeypatch.setattr("sys.argv", ["steam-sync", "--data-dir", str(tmp_path)])
    assert main() == 1
    assert "STEAM_API_KEY" in capsys.readouterr().err


def test_cli_success(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["steam-sync", "--data-dir", str(tmp_path)])
    monkeypatch.setattr("steam_sync.sync.sync", lambda *a, **k: (True, 10))
    assert main() == 0


def test_cli_os_error(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["steam-sync"])

    def fail(*a, **k):
        raise OSError("secret")

    monkeypatch.setattr("steam_sync.sync.sync", fail)
    assert main() == 1
    assert "secret" not in capsys.readouterr().err


def test_empty_diff():
    assert compare([], []) == {"added": [], "removed": [], "updated": []}
