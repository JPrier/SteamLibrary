"""Changes between consecutive validated snapshots, keyed by AppID."""


def compare(old, new):
    before = {g["appid"]: g for g in old}
    after = {g["appid"]: g for g in new}
    return {
        "added": [after[a] for a in sorted(after.keys() - before.keys())],
        "removed": [before[a] for a in sorted(before.keys() - after.keys())],
        "updated": [
            {
                "appid": a,
                "fields": {
                    field: {"before": before[a][field], "after": after[a][field]}
                    for field in sorted(after[a])
                    if before[a][field] != after[a][field]
                },
            }
            for a in sorted(before.keys() & after.keys())
            if before[a] != after[a]
        ],
    }
