"""Read-only snapshot summarizer for safe live-test runs."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

NOISE_WORDS = {
    "Home", "My Network", "Post", "Notifications", "Jobs", "Search", "Comment",
    "Repost", "Send", "Follow", "Suggested", "Promoted", "View", "Show", "Hide",
    "Menu", "Battery", "Discord", "Android", "System", "Gmail", "Airtel",
}


def _clean(value: str) -> str:
    value = re.sub(r"&amp;", "&", value)
    value = re.sub(r"&#10;", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" -•|.,")
    return value


def _candidate_names(text: str) -> list[str]:
    patterns = [
        r"View ([A-Z][A-Za-z .,'-]{2,80}) profile",
        r"Invite ([A-Z][A-Za-z .,'-]{2,80}) to connect",
        r"Suggested ([A-Z][A-Za-z .,'-]{2,80}) [•]",
    ]
    names: list[str] = []
    for pattern in patterns:
        for match in re.findall(pattern, text):
            name = _clean(match)
            if name and name not in NOISE_WORDS and len(name.split()) <= 6:
                names.append(name)
    return names


def _hashtags(text: str) -> list[str]:
    return [tag for tag in re.findall(r"#[A-Za-z][A-Za-z0-9_]{2,40}", text) if len(tag) <= 45]


def _post_snippets(text: str) -> list[str]:
    snippets = []
    for marker in ("Visibility: Global", "Promoted", "Sponsored Content"):
        parts = text.split(marker)
        for part in parts[1:]:
            snippet = _clean(part[:280])
            if snippet and len(snippet) > 40:
                snippets.append(snippet)
    return snippets[:10]


def summarize_snapshots(snapshot_path: str | Path) -> dict:
    path = Path(snapshot_path)
    names: list[str] = []
    hashtags: list[str] = []
    snippets: list[str] = []
    contexts: list[str] = []
    count = 0

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            count += 1
            contexts.append(record.get("context", ""))
            text = record.get("text", "")
            names.extend(_candidate_names(text))
            hashtags.extend(_hashtags(text))
            snippets.extend(_post_snippets(text))

    name_counts = Counter(names)
    hashtag_counts = Counter(hashtags)
    unique_snippets = []
    seen = set()
    for snippet in snippets:
        key = snippet.lower()[:120]
        if key not in seen:
            seen.add(key)
            unique_snippets.append(snippet)

    return {
        "snapshot_file": str(path),
        "snapshots": count,
        "contexts": contexts,
        "candidate_names": [{"name": name, "mentions": mentions} for name, mentions in name_counts.most_common(25)],
        "top_hashtags": [{"hashtag": tag, "mentions": mentions} for tag, mentions in hashtag_counts.most_common(25)],
        "post_snippets": unique_snippets[:10],
    }


def write_summary(snapshot_path: str | Path) -> Path:
    path = Path(snapshot_path)
    summary = summarize_snapshots(path)
    out = path.with_name(path.stem.replace("_snapshots", "_read_only_summary") + ".json")
    with out.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    return out
