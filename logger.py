"""Action logger — structured JSON logging for audit and tuning."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path


class ActionLogger:
    def __init__(self, log_dir: str = "logs", session_id: str | None = None) -> None:
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self._actions: list[dict] = []
        self._session_start = datetime.now(timezone.utc)

    @property
    def log_file(self) -> Path:
        return self.log_dir / f"session_{self.session_id}.jsonl"

    def log(self, action: str, target: str = "", status: str = "ok", detail: str = "") -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "target": target,
            "status": status,
            "detail": detail,
        }
        if detail:
            entry["detail"] = detail
        self._actions.append(entry)
        # Write immediately for live monitoring
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def summary(self) -> dict:
        return {
            "session_id": self.session_id,
            "start": self._session_start.isoformat(),
            "end": datetime.now(timezone.utc).isoformat(),
            "total_actions": len(self._actions),
            "by_action": self._count_by("action"),
            "by_status": self._count_by("status"),
        }

    def _count_by(self, key: str) -> dict:
        counts: dict[str, int] = {}
        for a in self._actions:
            v = a.get(key, "unknown")
            counts[v] = counts.get(v, 0) + 1
        return counts

    def flush(self) -> dict:
        summary = self.summary()
        summary_file = self.log_dir / f"session_{self.session_id}_summary.json"
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        return summary
