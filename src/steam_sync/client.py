"""Bounded HTTPS transport. Never propagate URLs, response bodies or network exceptions."""

import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, build_opener

from .models import STEAM_ID, SyncError

ENDPOINT = "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/"
MAX_BYTES = 20_000_000


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Do not forward credentials to another host.


def fetch_games(key, *, extended=False, open_url=None, sleep=time.sleep):
    if not key or not key.strip():
        raise SyncError("Set the STEAM_API_KEY Actions secret before running sync.")
    parameters = {"steamid": STEAM_ID, "include_appinfo": True, "include_played_free_games": True}
    if extended:
        parameters.update(include_free_sub=True, language="english")
    url = ENDPOINT + "?" + urlencode({"key": key, "input_json": json.dumps(parameters)})
    open_url = open_url or build_opener(NoRedirect).open
    for attempt in range(4):
        delay = 2**attempt
        try:
            with open_url(url, timeout=30) as response:
                raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise SyncError("Steam response exceeds size limit.")
            return json.loads(raw)
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise SyncError("Steam rejected credentials. Check STEAM_API_KEY.") from None
            if exc.code != 429 and not 500 <= exc.code <= 599:
                raise SyncError("Steam returned a non-retryable HTTP error.") from None
            retry_after = exc.headers.get("Retry-After", "") if exc.headers else ""
            if retry_after.isdigit():
                delay = min(60, max(delay, int(retry_after)))
        except (URLError, TimeoutError, OSError):
            pass
        except (ValueError, UnicodeError):
            raise SyncError("Steam returned malformed JSON; previous snapshot preserved.") from None
        if attempt < 3:
            sleep(delay)
    raise SyncError("Steam unavailable after four attempts; retry later. Snapshot preserved.")
