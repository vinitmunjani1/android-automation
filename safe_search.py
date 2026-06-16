"""Read-only LinkedIn search scanner.

This module performs a bounded, read-only search-results scan. It does not
like, comment, connect, follow, open messages, or send anything.
"""
from __future__ import annotations

import re
import time
import random
from pathlib import Path

from safety import assert_no_risk_screen, save_read_only_snapshot
from read_only_summary import write_summary


def _adb_input_text(value: str) -> str:
    """Escape text for Android `input text` enough for simple search queries."""
    value = value.strip()
    value = value.replace("%", "%25")
    value = value.replace(" ", "%s")
    # Keep search query conservative for shell input fallback.
    value = re.sub(r"[^A-Za-z0-9_%s+.#@-]", "", value)
    return value


def _adb_input_char(value: str) -> str:
    """Escape one character for Android `input text`."""
    if value == " ":
        return "%s"
    if value == "%":
        return "%25"
    if re.match(r"[A-Za-z0-9_.#@+-]", value):
        return value
    return ""


def _wait(config: dict, key: str, default: tuple[float, float], logger=None) -> float:
    """Randomized UI pacing wait. This is for reliability/readability, not evasion."""
    waits = config.get("safe_search", {}).get("waits", {})
    value = waits.get(key, {"min": default[0], "max": default[1]})
    lo = float(value.get("min", default[0]))
    hi = float(value.get("max", default[1]))
    if hi < lo:
        hi = lo
    duration = random.uniform(lo, hi)
    time.sleep(duration)
    if logger:
        logger.log("safe_search", "wait", "ok", f"{key}={duration:.2f}s")
    return duration


def _type_query_slowly(touch, logger, query: str, config: dict) -> int:
    """Type query gradually so the UI visibly receives input.

    This is a reliability/readability feature, not a detection bypass.
    """
    typing_cfg = config.get("safe_search", {}).get("typing", {})
    min_delay = float(typing_cfg.get("char_delay_min_seconds", 0.08))
    max_delay = float(typing_cfg.get("char_delay_max_seconds", 0.18))
    typed = 0
    for char in query:
        escaped = _adb_input_char(char)
        if not escaped:
            continue
        touch._shell(f"input text {escaped}")
        typed += 1
        time.sleep(random.uniform(min_delay, max_delay))
    logger.log("safe_search", "type_query_slowly", "ok", f"chars={typed}")
    return typed


def _tap_selector(obj, logger, config: dict, label: str) -> bool:
    try:
        if obj.exists:
            obj.click()
            logger.log("safe_search", label, "ok", "selector_click")
            _wait(config, "after_selector_tap_seconds", (0.6, 1.2), logger)
            return True
    except Exception as exc:
        logger.log("safe_search", label, "warn", f"selector_click_failed={exc}")
    return False


def _open_search(driver, touch, logger) -> None:
    """Open LinkedIn search input from the home screen."""
    candidates = [
        driver(resourceId="com.linkedin.android:id/search_open_bar_box"),
        driver(resourceId="com.linkedin.android:id/search_bar"),
        driver(resourceId="com.linkedin.android:id/search_bar_text"),
        driver(descriptionContains="Search"),
        driver(textContains="Search"),
    ]
    for candidate in candidates:
        if _tap_selector(candidate, logger, touch._cfg, "open_search"):
            return

    # Coordinate fallback: top search bar area from captured LinkedIn home UI.
    touch.tap(int(touch.width * 0.42), touch.status_bar + 70, log_label="safe_search_open_fallback")
    logger.log("safe_search", "open_search", "ok", "coordinate_fallback")
    _wait(touch._cfg, "after_open_search_seconds", (0.8, 1.4), logger)


def _enter_query(driver, touch, logger, config: dict, query: str) -> None:
    """Enter search query and submit."""
    try:
        edit = driver(className="android.widget.EditText")
        if edit.exists:
            edit.click()
            _wait(config, "after_focus_input_seconds", (0.25, 0.7), logger)
    except Exception as exc:
        logger.log("safe_search", "focus_query", "warn", f"edit_focus_failed={exc}")

    typed = _type_query_slowly(touch, logger, query, config=config)
    if typed == 0:
        safe_query = _adb_input_text(query)
        touch._shell(f"input text {safe_query}")
        logger.log("safe_search", "enter_query", "ok", "adb_input_text_fallback")

    _wait(config, "before_submit_seconds", (0.4, 0.9), logger)
    try:
        driver.press("enter")
    except Exception:
        touch._shell("input keyevent 66")  # KEYCODE_ENTER
    logger.log("safe_search", "submit_query", "ok", query)
    _wait(config, "after_submit_seconds", (2.0, 3.8), logger)


def _try_people_filter(driver, logger, config: dict) -> None:
    """Tap People filter if visible. Safe/read-only."""
    for selector in (driver(text="People"), driver(textContains="People")):
        try:
            if selector.exists:
                selector.click()
                logger.log("safe_search", "people_filter", "ok", "selector_click")
                _wait(config, "after_people_filter_seconds", (1.2, 2.4), logger)
                return
        except Exception as exc:
            logger.log("safe_search", "people_filter", "warn", f"failed={exc}")
    logger.log("safe_search", "people_filter", "skip", "not_visible")


def run_safe_search(driver, touch, logger, config: dict, query: str) -> dict:
    """Run a read-only search scan and write snapshots + summary."""
    query = query.strip()
    if not query:
        raise ValueError("safe search query cannot be empty")

    stats = {"query": query, "snapshots": 0, "scrolls": 0, "summary_file": ""}
    logger.log("safe_search", "start", "ok", query)

    touch.nav_to_tab("home", log_label="safe_search_home")
    assert_no_risk_screen(driver, logger, context="safe_search_home")

    _open_search(driver, touch, logger)
    assert_no_risk_screen(driver, logger, context="safe_search_open")

    _enter_query(driver, touch, logger, config, query)
    assert_no_risk_screen(driver, logger, context="safe_search_results")

    _try_people_filter(driver, logger, config)
    assert_no_risk_screen(driver, logger, context="safe_search_people_filter")

    save_read_only_snapshot(driver, logger, context="search_results_start")
    stats["snapshots"] += 1

    search_cfg = config.get("safe_search", {})
    scrolls = int(search_cfg.get("result_scrolls", 8))
    snapshot_every = max(1, int(search_cfg.get("snapshot_every_scrolls", 2)))

    for idx in range(1, scrolls + 1):
        touch.scroll_down(count=1, log_label="safe_search_results")
        stats["scrolls"] += 1
        _wait(config, "after_result_scroll_seconds", (0.8, 1.8), logger)
        assert_no_risk_screen(driver, logger, context=f"safe_search_scroll_{idx}")
        if idx == 1 or idx % snapshot_every == 0:
            save_read_only_snapshot(driver, logger, context=f"search_results_scroll_{idx}")
            stats["snapshots"] += 1

    snapshot_file = logger.log_dir / f"session_{logger.session_id}_snapshots.jsonl"
    if Path(snapshot_file).exists():
        summary_file = write_summary(snapshot_file, scoring_profile=config.get("candidate_scoring", {}))
        stats["summary_file"] = str(summary_file)
        logger.log("safe_search", "summary", "ok", str(summary_file))

    logger.log("safe_search", "complete", "ok", f"query={query},scrolls={stats['scrolls']},snapshots={stats['snapshots']}")
    return stats
