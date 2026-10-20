from pathlib import Path

import yaml


def test_workflow_contract():
    # BaseLoader avoids YAML 1.1 interpreting the Actions key "on" as a boolean.
    doc = yaml.load(
        Path(".github/workflows/sync-steam-library.yml").read_text(), Loader=yaml.BaseLoader
    )
    assert doc["on"]["schedule"][0]["cron"] == "23 * * * *"
    assert "workflow_dispatch" in doc["on"]
    assert doc["permissions"] == {"contents": "read"}
    job = doc["jobs"]["sync"]
    assert job["permissions"] == {"contents": "write"}
    assert job["needs"] == "test"
    assert doc["concurrency"]["cancel-in-progress"] == "false"
    assert "pull_request" in job["if"]
    steps = job["steps"]
    fetch = next(s for s in steps if s.get("name") == "Fetch and validate")
    assert fetch["env"]["STEAM_API_KEY"] == "${{ secrets.STEAM_API_KEY }}"
    commit = next(s for s in steps if s.get("name") == "Commit meaningful changes")
    assert "git diff --cached --quiet" in commit["run"]
    assert "git push" in commit["run"]
    assert "--force" not in commit["run"]
