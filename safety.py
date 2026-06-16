"""Account-risk safety helpers.

This module intentionally does not hide emulator, ADB, uiautomator, or platform
telemetry signals. It only prevents accidental account-changing actions and stops
runs when LinkedIn shows checkpoint/verification/risk screens.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Iterable

ACCOUNT_CHANGING_ACTIONS = {
    "like",
    "comment",
    "save",
    "connect",
    "follow",
    "pending_accept",
    "message_open",
    "notification_tap",
    "post_detail_open",
    "profile_open",
}

RISK_SCREEN_KEYWORDS = (
    "verify your identity",
    "verification required",
    "security check",
    "unusual activity",
    "suspicious",
    "checkpoint",
    "captcha",
    "confirm it's you",
    "confirm it’s you",
    "sign in",
    "session expired",
    "temporarily restricted",
    "restricted your account",
)


def safety_config(config: dict) -> dict:
    return config.setdefault("safety", {})


def is_read_only_live_test(config: dict) -> bool:
    return bool(safety_config(config).get("read_only_live_test", False))


def require_manual_approval(config: dict) -> bool:
    return bool(safety_config(config).get("require_manual_approval", True))


def allow_full_automation(config: dict) -> bool:
    return bool(safety_config(config).get("allow_full_automation", False))


def is_action_allowed(config: dict, action: str) -> bool:
    safety = safety_config(config)
    allow_key = f"allow_{action}"

    if is_read_only_live_test(config) and action in ACCOUNT_CHANGING_ACTIONS:
        return False

    if action in ACCOUNT_CHANGING_ACTIONS:
        return bool(safety.get(allow_key, False))

    return True


def block_action(logger, area: str, action: str, reason: str = "safety_gate") -> None:
    try:
        logger.log(area, f"{action}_blocked", "safety", reason)
    except Exception:
        pass


def dump_visible_text(driver) -> str:
    try:
        xml = driver.dump_hierarchy()
    except Exception:
        try:
            xml = driver.dump_hierarchyParser()
        except Exception:
            return ""
    return str(xml or "")


def compact_visible_text(raw: str, *, max_chars: int = 4000) -> str:
    """Make a UI hierarchy dump reviewable without changing device state."""
    raw = raw or ""
    attr_values = []
    for attr in ("text", "content-desc", "resource-id"):
        attr_values.extend(re.findall(rf'{attr}="([^"]+)"', raw))
    text = " ".join(attr_values) if attr_values else re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def save_read_only_snapshot(driver, logger, *, context: str) -> None:
    """Persist a read-only visible-screen snapshot next to the session log."""
    raw = dump_visible_text(driver)
    compact = compact_visible_text(raw)
    snapshot_file = logger.log_dir / f"session_{logger.session_id}_snapshots.jsonl"
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "context": context,
        "chars": len(compact),
        "text": compact,
    }
    with open(snapshot_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    try:
        logger.log("safety", "read_only_snapshot", "ok", f"context={context},chars={len(compact)}")
    except Exception:
        pass


def find_risk_keywords(text: str, keywords: Iterable[str] = RISK_SCREEN_KEYWORDS) -> list[str]:
    lowered = text.lower()
    return [keyword for keyword in keywords if keyword in lowered]


def assert_no_risk_screen(driver, logger, *, context: str = "screen") -> None:
    text = dump_visible_text(driver)
    hits = find_risk_keywords(text)
    if not hits:
        return
    detail = f"context={context},keywords={','.join(hits)}"
    try:
        logger.log("safety", "risk_screen_detected", "stop", detail)
    except Exception:
        pass
    raise RuntimeError(f"Stopped: LinkedIn risk/checkpoint screen detected ({', '.join(hits)})")


def apply_safe_live_overrides(config: dict) -> None:
    """Force a short read-only session profile for first live tests."""
    safety = safety_config(config)
    safety.update({
        "read_only_live_test": True,
        "require_manual_approval": True,
        "allow_like": False,
        "allow_comment": False,
        "allow_save": False,
        "allow_connect": False,
        "allow_follow": False,
        "allow_pending_accept": False,
        "allow_message_open": False,
        "allow_notification_tap": False,
        "allow_post_detail_open": False,
        "allow_profile_open": False,
        "stop_on_risk_screen": True,
    })

    actions = config.setdefault("actions", {})
    actions.update({
        "like_probability": 0.0,
        "comment_probability": 0.0,
        "save_probability": 0.0,
        "connect_probability": 0.0,
        "profile_open_from_feed_probability": 0.0,
        "profile_open_from_network_probability": 0.0,
        "notification_tap_probability": 0.0,
        "message_tap_probability": 0.0,
        "max_likes_per_session": 0,
        "max_connects_per_session": 0,
        "max_comments_per_session": 0,
        "max_saves_per_session": 0,
        "min_per_session": 1,
        "max_per_session": 1,
    })

    scroll = config.setdefault("scroll", {})
    scroll.update({
        "feed_min_swipes": 10,
        "feed_max_swipes": 20,
    })
