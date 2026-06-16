"""Read-only LinkedIn search scanner.

This module performs a bounded, read-only search-results scan. It does not
like, comment, connect, follow, open messages, or send anything.
"""
from __future__ import annotations

import re
import time
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


def _tap_selector(obj, logger, label: str) -> bool:
    try:
        if obj.exists:
            obj.click()
            logger.log("safe_search", label, "ok", "selector_click")
            time.sleep(0.8)
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
        if _tap_selector(candidate, logger, "open_search"):
            return

    # Coordinate fallback: top search bar area from captured LinkedIn home UI.
    touch.tap(int(touch.width * 0.42), touch.status_bar + 70, log_label="safe_search_open_fallback")
    logger.log("safe_search", "open_search", "ok", "coordinate_fallback")
    time.sleep(1.0)


def _enter_query(driver, touch, logger, query: str) -> None:
    """Enter search query and submit."""
    entered = False
    try:
        edit = driver(className="android.widget.EditText")
        if edit.exists:
            edit.set_text(query)
            entered = True
            logger.log("safe_search", "enter_query", "ok", "edit_text_set_text")
    except Exception as exc:
        logger.log("safe_search", "enter_query", "warn", f"set_text_failed={exc}")

    if not entered:
        safe_query = _adb_input_text(query)
        touch._shell(f"input text {safe_query}")
        logger.log("safe_search", "enter_query", "ok", "adb_input_text")

    time.sleep(0.5)
    try:
        driver.press("enter")
    except Exception:
        touch._shell("input keyevent 66")  # KEYCODE_ENTER
    logger.log("safe_search", "submit_query", "ok", query)
    time.sleep(2.5)


def _try_people_filter(driver, logger) -> None:
    """Tap People filter if visible. Safe/read-only."""
    for selector in (driver(text="People"), driver(textContains="People")):
        try:
            if selector.exists:
                selector.click()
                logger.log("safe_search", "people_filter", "ok", "selector_click")
                time.sleep(1.5)
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

    _enter_query(driver, touch, logger, query)
    assert_no_risk_screen(driver, logger, context="safe_search_results")

    _try_people_filter(driver, logger)
    assert_no_risk_screen(driver, logger, context="safe_search_people_filter")

    save_read_only_snapshot(driver, logger, context="search_results_start")
    stats["snapshots"] += 1

    search_cfg = config.get("safe_search", {})
    scrolls = int(search_cfg.get("result_scrolls", 8))
    snapshot_every = max(1, int(search_cfg.get("snapshot_every_scrolls", 2)))

    for idx in range(1, scrolls + 1):
        touch.scroll_down(count=1, log_label="safe_search_results")
        stats["scrolls"] += 1
        time.sleep(1.0)
        assert_no_risk_screen(driver, logger, context=f"safe_search_scroll_{idx}")
        if idx == 1 or idx % snapshot_every == 0:
            save_read_only_snapshot(driver, logger, context=f"search_results_scroll_{idx}")
            stats["snapshots"] += 1

    snapshot_file = logger.log_dir / f"session_{logger.session_id}_snapshots.jsonl"
    if Path(snapshot_file).exists():
        summary_file = write_summary(snapshot_file)
        stats["summary_file"] = str(summary_file)
        logger.log("safe_search", "summary", "ok", str(summary_file))

    logger.log("safe_search", "complete", "ok", f"query={query},scrolls={stats['scrolls']},snapshots={stats['snapshots']}")
    return stats
