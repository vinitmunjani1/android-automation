"""Anti-detection shields — guards against LinkedIn's automation detection signals.

Detection vectors addressed:
1. Rate limiting (per-minute action caps)
2. Accessibility service detection
3. Behavioral profile consistency (daily variation)
4. Touch pattern regularity
5. Session fingerprint rotation
6. ADB connection visibility
7. Action sequence predictability
"""
from __future__ import annotations

import hashlib
import json
import random
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


class RateLimiter:
    """Per-minute rate limiting for specific action types."""

    def __init__(self, config: dict) -> None:
        actions_cfg = config.get("actions", {})
        self._limits: dict[str, int] = {
            "like": actions_cfg.get("max_likes_per_minute", 2),
            "connect": actions_cfg.get("max_connects_per_minute", 1),
            "comment": 2,
            "save": 2,
            "total": config.get("anti_detection", {}).get("max_actions_per_minute", 8),
        }
        self._windows: dict[str, list[float]] = defaultdict(list)
        self._now = time.monotonic

    def can_act(self, action_type: str, session_counts: dict[str, int] | None = None) -> tuple[bool, str]:
        """Check if action is allowed by both per-minute and per-session limits.

        Returns (allowed, reason).
        """
        now = self._now()

        # Clean old entries (older than 60s)
        for key in self._windows:
            self._windows[key] = [t for t in self._windows[key] if now - t < 60.0]

        # Check per-minute limit
        per_min_key = action_type if action_type in self._limits else "total"
        count = len(self._windows[per_min_key])
        limit = self._limits.get(per_min_key, 999)
        if count >= limit:
            cooldown = min((t - now + 60) for t in self._windows[per_min_key]) if self._windows[per_min_key] else 0
            return False, f"per_minute_limit({per_min_key}:{count}/{limit},cooldown:{cooldown:.0f}s)"

        # Check per-session limit
        if session_counts:
            session_key = action_type
            session_max_key = f"max_{action_type}s_per_session"
            if session_max_key in session_counts:
                session_limit = session_counts[session_max_key]
                session_count = session_counts.get(session_key, 0)
                if session_count >= session_limit:
                    return False, f"per_session_limit({session_key}:{session_count}/{session_limit})"

        return True, "ok"

    def record(self, action_type: str) -> None:
        """Record an action occurrence."""
        now = self._now()
        per_min_key = action_type if action_type in self._limits else "total"
        self._windows[per_min_key].append(now)
        self._windows["total"].append(now)

    def wait_if_needed(self, action_type: str, session_counts: dict[str, int] | None = None) -> float:
        """Wait until the action is allowed. Returns wait time in seconds (0 if no wait)."""
        waited = 0.0
        max_wait = 120.0  # 2 minute max
        while waited < max_wait:
            allowed, reason = self.can_act(action_type, session_counts)
            if allowed:
                return waited
            # Estimate wait time
            now = self._now()
            oldest = min(self._windows.get(action_type, [now + 60]))
            wait_time = max(0.1, 61.0 - (now - oldest))
            time.sleep(min(wait_time, 5.0))  # Sleep in chunks
            waited += min(wait_time, 5.0)
        return waited


class BehavioralProfile:
    """Tracks and varies daily behavior to prevent pattern detection."""

    def __init__(self, config: dict, data_dir: str = "logs") -> None:
        self._cfg = config
        self._variation_pct = config.get("anti_detection", {}).get("behavioral_daily_variation_pct", 0.15)
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._profile_file = self._data_dir / "behavioral_profile.json"
        self._history: dict[str, dict] = self._load()

    def _load(self) -> dict:
        if self._profile_file.exists():
            with open(self._profile_file) as f:
                return json.load(f)
        return {}

    def _save(self) -> None:
        with open(self._profile_file, "w") as f:
            json.dump(self._history, f, indent=2)

    def get_variation(self, base_value: float, value_type: str = "probability") -> float:
        """Apply daily variation to a base value."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        # Consistent variation per day (same seed for same day)
        day_hash = int(hashlib.md5(today.encode()).hexdigest()[:8], 16)
        rng = random.Random(day_hash)
        variation = rng.uniform(-self._variation_pct, self._variation_pct)

        if value_type == "probability":
            return max(0.0, min(1.0, base_value * (1 + variation)))
        elif value_type == "duration":
            return max(base_value * 0.5, base_value * (1 + variation))
        elif value_type == "count":
            return max(1, int(base_value * (1 + variation)))
        return base_value * (1 + variation)

    def record_session(self, session_id: str, stats: dict) -> None:
        """Record session stats for behavioral tracking."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today not in self._history:
            self._history[today] = {"sessions": [], "total_actions": 0, "total_likes": 0,
                                     "total_connects": 0, "total_comments": 0, "total_saves": 0}

        self._history[today]["sessions"].append({
            "id": session_id,
            "actions": stats.get("total_actions", 0),
            "likes": stats.get("likes", 0),
            "connects": stats.get("connects", 0),
            "comments": stats.get("comments", 0),
            "saves": self.stats.get("saves", 0) if hasattr(self, 'stats') else 0,
            "duration_minutes": stats.get("duration_minutes", 0),
        })
        self._history[today]["total_actions"] += stats.get("total_actions", 0)
        self._history[today]["total_likes"] += stats.get("likes", 0)
        self._history[today]["total_connects"] += stats.get("connects", 0)
        self._history[today]["total_comments"] += stats.get("comments", 0)
        self._save()

    def get_today_stats(self) -> dict:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._history.get(today, {"sessions": [], "total_actions": 0, "total_likes": 0,
                                          "total_connects": 0, "total_comments": 0})

    def get_recent_average(self, key: str, days: int = 3) -> float:
        """Get recent average for a metric across the last N days."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        total = 0
        count = 0
        for date_str, data in self._history.items():
            if date_str <= today and count < days:
                total += data.get(f"total_{key}", 0)
                count += 1
        return total / count if count > 0 else 0


class DetectionShield:
    """Combined anti-detection controller."""

    def __init__(self, config: dict, logger, adb_shell: callable | None = None) -> None:
        self._cfg = config
        self._logger = logger
        self._adb_shell = adb_shell

        self.rate_limiter = RateLimiter(config)
        self.behavioral_profile = BehavioralProfile(config)

        # Session counters
        self._session_counts: dict[str, int] = {
            "like": 0, "connect": 0, "comment": 0, "save": 0,
            "max_likes_per_session": config.get("actions", {}).get("max_likes_per_session", 3),
            "max_connects_per_session": config.get("actions", {}).get("max_connects_per_session", 5),
            "max_comments_per_session": config.get("actions", {}).get("max_comments_per_session", 2),
            "max_saves_per_session": config.get("actions", {}).get("max_saves_per_session", 2),
        }

        # Stuck page detection
        self._page_signatures: list[str] = []
        self._stuck_threshold = config.get("anti_detection", {}).get("stuck_page_threshold", 3)

        # Fingerprint
        self._session_fingerprint = self._generate_fingerprint()

    def _generate_fingerprint(self) -> str:
        """Generate a unique but human-like session fingerprint."""
        if self._cfg.get("anti_detection", {}).get("session_fingerprint_rotation", True):
            data = f"{time.monotonic()}{random.random()}{datetime.now().strftime('%Y%m%d')}"
            return hashlib.sha256(data.encode()).hexdigest()[:16]
        return "fixed_fp"

    @property
    def fingerprint(self) -> str:
        return self._session_fingerprint

    def can_act(self, action_type: str) -> tuple[bool, str]:
        """Check if an action should be performed (rate + session limits)."""
        return self.rate_limiter.can_act(action_type, self._session_counts)

    def record_action(self, action_type: str) -> None:
        """Record an action for rate limiting and session counting."""
        self.rate_limiter.record(action_type)
        if action_type in self._session_counts:
            self._session_counts[action_type] += 1

    def wait_if_needed(self, action_type: str) -> float:
        """Wait until the action is allowed. Returns wait time."""
        return self.rate_limiter.wait_if_needed(action_type, self._session_counts)

    def record_page(self, signature: str) -> bool:
        """Record current page signature. Returns True if stuck detected."""
        self._page_signatures.append(signature)
        # Keep only last N signatures
        if len(self._page_signatures) > self._stuck_threshold + 2:
            self._page_signatures.pop(0)

        if len(self._page_signatures) >= self._stuck_threshold:
            recent = self._page_signatures[-self._stuck_threshold:]
            if len(set(recent)) == 1:
                self._logger.log("shield_stuck", signature, "detected",
                                 f"same_page_x{self._stuck_threshold}")
                return True
        return False

    def reset_session(self) -> dict:
        """Reset counters for a new session. Returns previous counts."""
        counts = {k: v for k, v in self._session_counts.items()
                  if k.startswith("max_") is False}
        for key in counts:
            self._session_counts[key] = 0
        self._page_signatures.clear()
        if self._cfg.get("anti_detection", {}).get("session_fingerprint_rotation", True):
            self._session_fingerprint = self._generate_fingerprint()
        return counts

    def check_accessibility_services(self) -> bool:
        """Check if accessibility services are enabled (LinkedIn detection vector)."""
        if not self._adb_shell:
            return True
        try:
            result = self._adb_shell(
                "settings get secure enabled_accessibility_services"
            )
            enabled = result.strip() if result else ""
            has_service = enabled and enabled != ""
            if has_service and self._cfg.get("anti_detection", {}).get("disable_accessibility_services", True):
                self._logger.log("shield_accessibility", "warning", "detected",
                                 f"enabled_services={enabled}")
                return False  # Risk detected
            return True
        except Exception:
            return True

    def toggle_adb(self) -> None:
        """Toggle ADB USB debugging between sessions (optional stealth)."""
        if not self._adb_shell or not self._cfg.get("anti_detection", {}).get("toggle_adb_between_sessions", False):
            return
        try:
            # This is a placeholder — actual toggle requires USB connection changes
            self._logger.log("shield_adb", "toggle", "ok", "adb_toggle_attempted")
        except Exception:
            pass

    def get_session_counts(self) -> dict:
        return {k: v for k, v in self._session_counts.items() if not k.startswith("max_")}

    def summary(self) -> dict:
        return {
            "fingerprint": self.fingerprint,
            "session_counts": self.get_session_counts(),
            "page_signatures_len": len(self._page_signatures),
            "behavioral_profile": self.behavioral_profile.get_today_stats(),
        }
