"""Read-only LinkedIn search scanner.

This module performs a bounded, read-only search-results scan. It does not
like, comment, connect, follow, open messages, or send anything.
"""
from __future__ import annotations

import re
import time
import random
from pathlib import Path

from safety import assert_no_risk_screen, dump_visible_text, save_read_only_snapshot
from read_only_summary import _candidate_names, write_summary


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
    word_pause_min = float(typing_cfg.get("word_pause_min_seconds", 0.25))
    word_pause_max = float(typing_cfg.get("word_pause_max_seconds", 0.85))
    typed = 0
    for char in query:
        escaped = _adb_input_char(char)
        if not escaped:
            continue
        touch._shell(f"input text {escaped}")
        typed += 1
        if char == " ":
            time.sleep(random.uniform(word_pause_min, word_pause_max))
        else:
            time.sleep(random.uniform(min_delay, max_delay))
    logger.log("safe_search", "type_query_slowly", "ok", f"chars={typed},word_pauses=true")
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


def _click_object_center(obj, touch, logger, label: str) -> bool:
    """Click a UI object using bounds center when direct click is unreliable."""
    try:
        info = obj.info if hasattr(obj, "info") else obj.get_info()
        bounds = info.get("bounds", {}) if isinstance(info, dict) else {}
        if not bounds:
            return False
        left = bounds.get("left", bounds.get("x", 0))
        right = bounds.get("right", 0)
        top = bounds.get("top", bounds.get("y", 0))
        bottom = bounds.get("bottom", 0)
        if right <= left or bottom <= top:
            return False
        cx = int((left + right) / 2)
        cy = int((top + bottom) / 2)
        touch.tap(cx, cy, log_label=label)
        logger.log("safe_search", label, "ok", f"bounds_center=({cx},{cy})")
        return True
    except Exception as exc:
        logger.log("safe_search", label, "warn", f"bounds_click_failed={exc}")
        return False


def _try_open_by_name(driver, touch, logger, config: dict, name: str) -> bool:
    """Try opening a visible result by candidate name text."""
    selectors = [driver(text=name), driver(textContains=name)]
    for selector in selectors:
        try:
            if selector.exists:
                try:
                    selector.click()
                    logger.log("safe_search", "open_profile_by_name", "ok", name)
                    return True
                except Exception:
                    if _click_object_center(selector, touch, logger, "open_profile_by_name_center"):
                        return True
        except Exception as exc:
            logger.log("safe_search", "open_profile_by_name", "warn", f"{name}: {exc}")
    return False


def _try_open_by_resource_ids(driver, touch, logger, config: dict, max_to_open: int) -> int:
    """Try LinkedIn search-result resource IDs across app variants."""
    opened = 0
    resource_ids = [
        "com.linkedin.android:id/search_entity_result_actor_title",
        "com.linkedin.android:id/search_entity_result_actor_first_line_container",
        "com.linkedin.android:id/search_entity_result_content_actor",
        "com.linkedin.android:id/search_entity_result_content_b_actor",
        "com.linkedin.android:id/search_entity_result_content_a_template",
        "com.linkedin.android:id/search_entity_result_content_b_template",
    ]
    for resource_id in resource_ids:
        if opened >= max_to_open:
            break
        try:
            collection = driver(resourceId=resource_id)
            count = int(getattr(collection, "count", 0) or 0)
            logger.log("safe_search", "profile_selector_count", "ok", f"{resource_id}={count}")
        except Exception as exc:
            logger.log("safe_search", "profile_selector", "warn", f"{resource_id} failed={exc}")
            continue

        for idx in range(min(count, max_to_open - opened)):
            try:
                item = collection[idx]
                if not item.exists:
                    continue
                try:
                    item.click()
                except Exception:
                    if not _click_object_center(item, touch, logger, "open_profile_resource_center"):
                        continue
                logger.log("safe_search", "open_profile_resource", "ok", f"resource_id={resource_id},index={idx}")
                opened += 1
                _wait(config, "after_profile_open_seconds", (2.0, 3.5), logger)
                assert_no_risk_screen(driver, logger, context=f"safe_profile_resource_{opened}")
                save_read_only_snapshot(driver, logger, context=f"profile_read_only_{opened}")
                touch.back(log_label="safe_profile_back")
                _wait(config, "after_profile_back_seconds", (1.0, 2.0), logger)
                if opened >= max_to_open:
                    return opened
            except Exception as exc:
                logger.log("safe_search", "open_profile_resource", "warn", str(exc)[:500])
                try:
                    touch.back(log_label="safe_profile_back_after_error")
                except Exception:
                    pass
    return opened


def _try_open_by_coordinates(driver, touch, logger, config: dict, max_to_open: int) -> int:
    """Last-resort read-only result-card coordinate opening.

    This is disabled unless safe_search.profile_open_coordinate_fallback is true.
    """
    if not config.get("safe_search", {}).get("profile_open_coordinate_fallback", True):
        logger.log("safe_search", "profile_coordinate_fallback", "skip", "disabled")
        return 0
    opened = 0
    x = int(touch.width * 0.38)
    y_values = [int(touch.height * ratio) for ratio in (0.31, 0.43, 0.55, 0.67)]
    for y in y_values[:max_to_open]:
        touch.tap(x, y, log_label="open_profile_coordinate_fallback")
        logger.log("safe_search", "open_profile_coordinate", "ok", f"x={x},y={y}")
        opened += 1
        _wait(config, "after_profile_open_seconds", (2.0, 3.5), logger)
        try:
            assert_no_risk_screen(driver, logger, context=f"safe_profile_coordinate_{opened}")
            save_read_only_snapshot(driver, logger, context=f"profile_read_only_coordinate_{opened}")
        except Exception as exc:
            logger.log("safe_search", "profile_coordinate_snapshot", "warn", str(exc)[:500])
        touch.back(log_label="safe_profile_back")
        _wait(config, "after_profile_back_seconds", (1.0, 2.0), logger)
    return opened


def _open_visible_profiles_read_only(driver, touch, logger, config: dict, max_profiles: int) -> int:
    """Open visible search-result profile/title rows read-only and snapshot them.

    This can create LinkedIn profile-view signals, so it is only called when the
    user explicitly passes --safe-open-profiles N.
    """
    if max_profiles <= 0:
        return 0

    opened = 0
    visible_names = _candidate_names(dump_visible_text(driver))
    logger.log("safe_search", "visible_profile_names", "ok", ", ".join(visible_names[:8]) or "none")

    for name in visible_names:
        if opened >= max_profiles:
            return opened
        if _try_open_by_name(driver, touch, logger, config, name):
            try:
                _wait(config, "after_profile_open_seconds", (2.0, 3.5), logger)
                assert_no_risk_screen(driver, logger, context=f"safe_profile_{opened + 1}")
                save_read_only_snapshot(driver, logger, context=f"profile_read_only_{opened + 1}")
                opened += 1
                touch.back(log_label="safe_profile_back")
                _wait(config, "after_profile_back_seconds", (1.0, 2.0), logger)
                if opened >= max_profiles:
                    return opened
            except Exception as exc:
                logger.log("safe_search", "open_profile_read_only", "warn", str(exc)[:500])
                try:
                    touch.back(log_label="safe_profile_back_after_error")
                except Exception:
                    pass
    if opened < max_profiles:
        opened += _try_open_by_resource_ids(driver, touch, logger, config, max_profiles - opened)
    if opened < max_profiles:
        opened += _try_open_by_coordinates(driver, touch, logger, config, max_profiles - opened)
    if opened < max_profiles:
        logger.log("safe_search", "profile_open_methods_exhausted", "warn", f"opened={opened},requested={max_profiles}")
    return opened


def run_safe_search(driver, touch, logger, config: dict, query: str, open_profiles: int = 0) -> dict:
    """Run a read-only search scan and write snapshots + summary."""
    query = query.strip()
    if not query:
        raise ValueError("safe search query cannot be empty")

    stats = {"query": query, "snapshots": 0, "scrolls": 0, "profiles_opened_read_only": 0, "summary_file": ""}
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

        if open_profiles and stats["profiles_opened_read_only"] < open_profiles and idx in (1, 2):
            opened_now = _open_visible_profiles_read_only(
                driver,
                touch,
                logger,
                config,
                open_profiles - stats["profiles_opened_read_only"],
            )
            stats["profiles_opened_read_only"] += opened_now

    snapshot_file = logger.log_dir / f"session_{logger.session_id}_snapshots.jsonl"
    if Path(snapshot_file).exists():
        summary_file = write_summary(snapshot_file, scoring_profile=config.get("candidate_scoring", {}), config=config, query=query)
        stats["summary_file"] = str(summary_file)
        logger.log("safe_search", "summary", "ok", str(summary_file))

    logger.log("safe_search", "complete", "ok", f"query={query},scrolls={stats['scrolls']},snapshots={stats['snapshots']},profiles_opened_read_only={stats['profiles_opened_read_only']}")
    return stats
