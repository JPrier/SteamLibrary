# SteamLibrary

Hourly Steam library snapshots for [Joshua's profile](https://steamcommunity.com/profiles/76561198035296905/), using Python's standard library and GitHub Actions. No database, hosted server, or paid API is required. This repository is **public**: exported titles, playtime and last-played timestamps, including historical snapshots, will be public.

## Activate once

1. Obtain your own key at https://steamcommunity.com/dev/apikey (sign in to Steam). Never paste the key into chat or commit it.
2. In [repository Actions secrets](https://github.com/JPrier/SteamLibrary/settings/secrets/actions), create `STEAM_API_KEY`.
3. In Steam's Edit Profile → Privacy Settings, make your profile and **Game Details public**. Disable “Always keep my total playtime private” if you want playtime available. Individually private games may be excluded by Steam and cannot be recovered by this exporter.
4. Open [Sync Steam library](https://github.com/JPrier/SteamLibrary/actions/workflows/sync-steam-library.yml), click **Run workflow** on `main`, and verify both jobs are green. The first successful sync creates the JSON files; no illustrative or fabricated snapshot is committed beforehand.

The schedule runs at minute 23 each hour (UTC), approximately; GitHub can delay or drop scheduled runs. Schedules execute only from the default branch, currently `main`. Pushes run tests and synchronize on the default branch; pull requests run tests without credentials or write access. Repository rules must permit the built-in `GITHUB_TOKEN` to push the data commit. Tests must pass before every sync.

## Retrieve in future ChatGPT conversations

- [Dataset on GitHub](https://github.com/JPrier/SteamLibrary/blob/main/data/steam-library.json)
- [Raw dataset](https://raw.githubusercontent.com/JPrier/SteamLibrary/main/data/steam-library.json)
- [Latest meaningful change summary](https://github.com/JPrier/SteamLibrary/blob/main/data/steam-library-changes.json)

After activation, ask: “Fetch the current `data/steam-library.json` from `JPrier/SteamLibrary` using GitHub, then tell me which games I've never played.” AppIDs and lifetime playtime also support most-played and recently-played questions. Genres, racing/RPG classification, modding, compatibility and decompilation projects require separate live research.

Publishing does **not** inject the library into ChatGPT memory. ChatGPT needs to fetch the current file each conversation. Public URLs are the simplest retrieval route; the connected GitHub integration must have repository access. Private repositories require an authorized connector and cannot be fetched anonymously. A private-repository retrieval route has not been verified here. These URLs return 404 until a real successful sync creates the dataset.

## Schema v1

`data/steam-library.json` contains `schema_version`, `steam_id`, `profile_url`, `snapshot_updated_at` (UTC ISO-8601), `game_count`, and `games` sorted numerically by AppID. Each game has:

| Field | Type | Meaning |
| --- | --- | --- |
| `appid` | positive integer | Primary identifier |
| `name` | string or null | Steam title; null if missing, never guessed |
| `playtime_forever_minutes` | nonnegative integer | Required lifetime playtime |
| `playtime_2weeks_minutes` | integer or null | Recent playtime when supplied |
| `last_played_unix` | integer or null | Steam timestamp; zero is preserved if returned |
| `icon_hash` | string or null | Steam icon identifier |

The API returns owned games plus played free games with `include_played_free_games=true`; it does not reliably classify individual entries, so this schema does not invent a paid/free ownership distinction. Family sharing is not enumerated separately or added from another source. The dataset represents what GetOwnedGames returns, not proof of a permanent license.

The client uses the public `api.steampowered.com` GetOwnedGames v1 endpoint, key authentication, `input_json`, `steamid`, `include_appinfo=true`, and `include_played_free_games=true`. [Valve's reference](https://partner.steamgames.com/doc/webapi/IPlayerService#GetOwnedGames) documents those parameters but does not document `include_free_sub` or `language`. `--extended-parameters` optionally sends `include_free_sub=true` and `language=english`; this option is experimental, disabled in scheduled runs, and does not guarantee coverage or English names. No AppID filter or recent-games-only endpoint is used.

Unknown fields in Steam responses are ignored; schema changes require explicit migration. Metadata enrichment can join on AppID in a separate cached dataset on a slower schedule, independent of ownership sync. There are no hourly per-game store requests.

## Reliability and changes

Responses must have a nonempty games array, matching count, unique positive AppIDs and valid numeric values. Missing optional values become null. Duplicate records, inaccessible libraries, invalid JSON, mismatched counts and invalid stored snapshots fail without replacing the snapshot. HTTP calls have 30-second timeouts and four attempts with bounded exponential backoff for network failures, 429 and 5xx. Numeric Retry-After values are respected up to 60 seconds. Redirects are refused. Authentication failures fail immediately. Errors never print raw URLs, response bodies or exceptions from transport.

Every removal requires a second independently fetched, identical normalized response. Removing 25 or more games, or more than 10% of the previous snapshot, is blocked unless a manual run explicitly enables `allow_large_removal`. Check privacy and Steam availability before approving. Steam exposes no completeness proof: even two matching responses cannot guarantee that a small omission is genuine. The count, confirmation and size checks are defensive safeguards, not an ownership oracle.

Changes include additions, removals and per-field before/after values in `steam-library-changes.json`. Both files enter one Git commit. The change file describes the last meaningful update, not every hourly run. Unchanged normalized games leave **both files byte-identical**: `snapshot_updated_at` means last refresh that changed stored data. For the latest successful unchanged check, consult the Actions run timestamp/log. Formatting and API record order do not cause commits. Individual file writes are atomic; Git publishes both together. A local disk failure between replacements may require rerunning locally; CI never commits after a failed sync.

Workflow concurrency serializes runs on each branch. Pushes use the built-in token, never force push, and fail visibly if branch protection or a concurrent human commit prevents a fast-forward. Retry manually after resolving the conflict; the next run checks out the latest default branch.

## Local development

Python 3.11+:

```bash
python -m pip install -e '.[dev]'
python -m pytest --cov=steam_sync --cov-report=term-missing --cov-fail-under=90
python -m ruff check .
# Set STEAM_API_KEY in your environment through your secret manager, then:
python -m steam_sync.sync
```

Tests mock transport and need no Steam credentials. The CI coverage floor is 90%. A confirmed large expected removal can be accepted locally with `--allow-large-removal`. Do not use shell tracing or print the environment while handling credentials.

## Operations and troubleshooting

- Missing secret / 401 / 403: create or replace `STEAM_API_KEY` in repository Actions secrets, then run manually.
- Empty or inaccessible library: check profile/Game Details privacy, private games, and Steam availability. The exporter deliberately refuses an empty snapshot, even with the removal override.
- Malformed or incomplete responses / disagreement / 429 / 5xx: retry later; retain the last snapshot. Missing required playtime is rejected rather than guessed.
- Large removal blocked: investigate privacy and the expected removed games; only then approve via manual workflow input.
- Push denied: allow Actions writes and check branch rules. This workflow requests only `contents: write` for the sync job, and `contents: read` for tests.
- Missing hourly runs: check Actions is enabled, the workflow is on `main`, and recent run results. GitHub does not promise an exact hourly SLA.
- **Long-term inactivity:** [GitHub automatically disables public-repository scheduled workflows after 60 days without repository activity](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule). Review Actions monthly. If the library stays unchanged for weeks, make a useful maintenance/documentation commit before day 60; if disabled, re-enable the workflow and run it manually. Successful scheduled runs alone should not be relied on to reset inactivity. No empty keepalive commits are generated.

GitHub Actions logs provide successful-check timestamps and failures. Enable GitHub's workflow-failure notifications for this repository. No fake initial data, fabricated game count or credential-dependent test is included.
