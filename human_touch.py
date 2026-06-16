"""Human touch simulation layer — simulates real human finger interactions via ADB.

Key anti-detection features:
- Tap: touch-down → micro-drift → dwell → lift (not instant)
- Swipe: Bezier curve with variable velocity (ease-in → cruise → ease-out)
- Scroll: burst micro-swipes with content-aware pauses and occasional scroll-back
- Accidental touches with correction behavior
- Thumb-zone awareness (different touch patterns for different screen regions)
- Back gesture (edge swipe) vs bottom-nav tap mixing
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass


@dataclass
class TouchPoint:
    x: int
    y: int
    duration_ms: int = 0


class HumanTouch:
    """Simulates human finger interactions on an Android device via ADB input commands."""

    def __init__(self, adb_shell: callable, config: dict, logger) -> None:
        """
        Args:
            adb_shell: callable(cmd_str) -> subprocess result (like d.shell from uiautomator2)
            config: full config dict
            logger: ActionLogger instance
        """
        self._shell = adb_shell
        self._cfg = config
        self._touch_cfg = config.get("touch", {})
        self._device_cfg = config.get("device", {})
        self._logger = logger

        # Device dimensions
        self.width = self._device_cfg.get("screen_width", 1080)
        self.height = self._device_cfg.get("screen_height", 2340)
        self.status_bar = self._device_cfg.get("status_bar_height", 100)
        self.bottom_nav_h = self._device_cfg.get("bottom_nav_height", 124)

        # Thumb zone boundaries
        self.thumb_y_min = self._device_cfg.get("thumb_zone_safe_y_min", 400)
        self.thumb_y_max = self._device_cfg.get("thumb_zone_safe_y_max", 1800)
        self.two_hand_above = self._device_cfg.get("two_hand_zone_above", 350)
        self.two_hand_below = self._device_cfg.get("two_hand_zone_below", 1850)

    # ─── Helpers ───────────────────────────────────────────────────────────

    def _r(self, lo: float, hi: float) -> float:
        """Gaussian-like random between lo and hi (using sum of 3 uniforms for bell curve)."""
        raw = random.random() + random.random() + random.random()
        # raw in [1,3], normalize to [0,1]
        normalized = (raw - 1.5) / 1.5  # [-1, 1]
        # Clamp and scale
        normalized = max(-1.0, min(1.0, normalized))
        center = (lo + hi) / 2
        half_range = (hi - lo) / 2
        return center + normalized * half_range

    def _cfg_range(self, key: str) -> tuple[float, float]:
        defaults = {
            "tap_drift_px": {"min": 1, "max": 4},
            "tap_dwell_ms": {"min": 30, "max": 90},
            "accidental_correction_delay_ms": {"min": 200, "max": 600},
            "swipe_duration_ms": {"min": 200, "max": 600},
            "scroll_micro_swipe_ms": {"min": 250, "max": 480},
            "burst_segment_ms": {"min": 40, "max": 180},
            "bottom_nav_offset_px": {"min": -8, "max": 8},
        }
        obj = self._touch_cfg.get(key) or self._cfg.get("scroll", {}).get(key) or defaults.get(key)
        if not isinstance(obj, dict) or "min" not in obj or "max" not in obj:
            raise KeyError(f"Missing range config for {key}; expected {{'min': ..., 'max': ...}}")
        return float(obj["min"]), float(obj["max"])

    def _cfg_int_range(self, key: str) -> tuple[int, int]:
        lo, hi = self._cfg_range(key)
        return int(round(lo)), int(round(hi))

    def _clamp(self, x: int, y: int) -> tuple[int, int]:
        return (max(0, min(x, self.width - 1)), max(0, min(y, self.height - 1)))

    def _is_thumb_zone(self, y: int) -> bool:
        return self.thumb_y_min <= y <= self.thumb_y_max

    def _is_two_hand_zone(self, y: int) -> bool:
        return y < self.two_hand_above or y > self.two_hand_below

    # ─── Tap ───────────────────────────────────────────────────────────────

    def tap(self, x: int, y: int, *, drift: bool = True, log_label: str = "") -> TouchPoint:
        """Simulate a human tap: touch-down → micro-drift → dwell → lift.

        Uses ADB input touchscreen commands for realistic finger movement.
        """
        x, y = self._clamp(x, y)

        # Add drift
        if drift:
            _, drift_max = self._cfg_int_range("tap_drift_px")
            dx = random.randint(-drift_max, drift_max)
            dy = random.randint(-drift_max, drift_max)
            drift_x = x + dx
            drift_y = y + dy
        else:
            drift_x, drift_y = x, y
            dx = dy = 0

        drift_x, drift_y = self._clamp(drift_x, drift_y)
        dwell_ms = int(self._r(*self._cfg_range("tap_dwell_ms")))

        # Build touchscreen sequence: down → move(drift) → up
        # Format: input touchscreen down x y [ms] → move x y → up
        self._shell(
            f"input touchscreen down {x} {y} && "
            f"sleep 0.{dwell_ms:03d} && "
            f"input touchscreen move {drift_x} {drift_y} && "
            f"input touchscreen up"
        )

        time.sleep(dwell_ms / 1000.0 + 0.02)  # Small buffer

        tp = TouchPoint(x=drift_x, y=drift_y, duration_ms=dwell_ms)
        if log_label:
            self._logger.log("touch_tap", log_label, "ok",
                             f"x={drift_x},y={drift_y},dwell={dwell_ms}ms,drift=({dx},{dy})")
        return tp

    def double_tap(self, x: int, y: int, log_label: str = "") -> list[TouchPoint]:
        """Double-tap (occasionally happens with excitement/uncertainty)."""
        t1 = self.tap(x, y, log_label=f"{log_label}_1")
        gap = random.uniform(0.12, 0.28)
        time.sleep(gap)
        t2 = self.tap(x + random.randint(-5, 5), y + random.randint(-5, 5),
                       log_label=f"{log_label}_2")
        return [t1, t2]

    def accidental_touch(self, x: int, y: int, nearby_element_bounds: tuple[int, int, int, int] | None = None,
                         log_label: str = "") -> bool:
        """Simulate accidental touch + correction (go back or re-tap correct element).

        Returns True if correction happened.
        """
        if random.random() > self._touch_cfg.get("accidental_touch_probability", 0.04):
            return False

        # Accidental: tap slightly offset
        off_x = x + random.randint(-15, 15)
        off_y = y + random.randint(-15, 15)
        self.tap(off_x, off_y, log_label=f"{log_label}_accident")

        # Correction delay
        corr_ms = int(self._r(*self._cfg_range("accidental_correction_delay_ms")))
        time.sleep(corr_ms / 1000.0)

        # Correction: either back or re-tap the intended target
        if random.random() < 0.5:
            self.back()
        else:
            self.tap(x, y, log_label=f"{log_label}_correct")

        self._logger.log("touch_accidental", log_label, "corrected", f"offset=({off_x-x},{off_y-y})")
        return True

    # ─── Swipe ─────────────────────────────────────────────────────────────

    def swipe(self, x1: int, y1: int, x2: int, y2: int,
              *, duration_ms: int | None = None, log_label: str = "") -> None:
        """Simulate a human swipe with Bezier curve and variable velocity.

        Breaks the swipe into segments: ease-in → cruise → ease-out,
        with intermediate move events for realistic finger tracking.
        """
        x1, y1 = self._clamp(x1, y1)
        x2, y2 = self._clamp(x2, y2)

        if duration_ms is None:
            duration_ms = int(self._r(*self._cfg_range("swipe_duration_ms")))

        # Add slight randomness to endpoints
        x2 += random.randint(-5, 5)
        y2 += random.randint(-5, 5)
        x2, y2 = self._clamp(x2, y2)

        # Number of intermediate points depends on distance and duration
        distance = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
        num_points = max(3, min(12, int(distance / 80)))

        # Generate points along Bezier curve (quadratic with random control point)
        # Control point is slightly off the straight line
        cx = (x1 + x2) / 2 + random.uniform(-distance * 0.08, distance * 0.08)
        cy = (y1 + y2) / 2 + random.uniform(-distance * 0.08, distance * 0.08)

        points = []
        for i in range(num_points + 1):
            t = i / num_points
            # Bezier interpolation
            bx = (1 - t) ** 2 * x1 + 2 * (1 - t) * t * cx + t ** 2 * x2
            by = (1 - t) ** 2 * y1 + 2 * (1 - t) * t * cy + t ** 2 * y2
            # Variable velocity: ease-in-out timing
            ease_t = t * t * (3 - 2 * t)  # smoothstep
            seg_ms = int(duration_ms * ease_t / (num_points)) if i < num_points else 0
            points.append((int(bx), int(by), seg_ms))

        # Build ADB command sequence
        parts = [f"input touchscreen down {x1} {y1}"]
        for px, py, ms in points[1:]:
            if ms > 0:
                parts.append(f"sleep 0.{ms:03d}")
            parts.append(f"input touchscreen move {px} {py}")
        parts.append("input touchscreen up")

        cmd = " && ".join(parts)
        self._shell(cmd)
        time.sleep(duration_ms / 1000.0 + 0.02)

        if log_label:
            self._logger.log("touch_swipe", log_label, "ok",
                             f"({x1},{y1})->({x2},{y2}),dur={duration_ms}ms,pts={num_points}")

    # ─── Scroll ────────────────────────────────────────────────────────────

    def scroll_down(self, count: int | None = None, *, region: tuple[int, int, int, int] | None = None,
                    log_label: "str" = "") -> list[str]:
        """Scroll down (swipe up) with burst mode and occasional mid-scroll reversal.

        Returns list of action labels for each scroll segment.
        """
        scroll_cfg = self._cfg.get("scroll", {})
        if count is None:
            count = random.randint(scroll_cfg.get("feed_min_swipes", 5),
                                   scroll_cfg.get("feed_max_swipes", 12))

        if region is None:
            # Default scroll region: center-bottom of screen
            rw = self.width // 3
            rh = self.height // 3
            region = (self.width // 2 - rw // 2,
                      self.height // 2,
                      self.width // 2 + rw // 2,
                      self.height - self.bottom_nav_h - 50)

        rx1, ry1, rx2, ry2 = region
        actions: list[str] = []
        for i in range(count):
            # Random start position within scroll region
            sx = random.randint(rx1, rx2)
            sy_start = random.randint(ry1, ry2)
            sy_end = sy_start - random.randint(120, 280)

            # Burst mode: faster, shorter swipes
            if random.random() < scroll_cfg.get("burst_scroll_probability", 0.30):
                dur = int(self._r(*self._cfg_range("burst_segment_ms")))
                sy_end = sy_start - random.randint(60, 150)
            else:
                dur = int(self._r(*self._cfg_range("scroll_micro_swipe_ms")))

            # Mid-scroll reversal (scroll back up briefly)
            if i > 0 and random.random() < scroll_cfg.get("mid_scroll_reverse_probability", 0.15):
                self.swipe(sx, sy_end, sx, sy_start, duration_ms=dur)
                actions.append("reverse")
                time.sleep(random.uniform(0.3, 0.8))

            self.swipe(sx, sy_start, sx, sy_end, duration_ms=dur,
                       log_label=f"{log_label}_scroll_{i}")
            actions.append("down")

            # Pause between scrolls (content-aware dwell)
            pause = random.uniform(0.15, 0.6)
            time.sleep(pause)

        return actions

    def scroll_up(self, count: int = 2, *, region: tuple[int, int, int, int] | None = None,
                  log_label: str = "") -> None:
        """Scroll up (swipe down) — for re-reading content above."""
        scroll_cfg = self._cfg.get("scroll", {})
        if region is None:
            rw = self.width // 3
            region = (self.width // 2 - rw // 2,
                      self.height // 2 - 100,
                      self.width // 2 + rw // 2,
                      self.height // 2 + 200)

        rx1, ry1, rx2, ry2 = region
        for i in range(count):
            sx = random.randint(rx1, rx2)
            sy_start = random.randint(ry1, ry2)
            sy_end = sy_start + random.randint(120, 280)
            dur = int(self._r(*self._cfg_range("scroll_micro_swipe_ms")))
            self.swipe(sx, sy_start, sx, sy_end, duration_ms=dur,
                       log_label=f"{log_label}_up_{i}")
            time.sleep(random.uniform(0.2, 0.5))

    def scroll_with_back_up(self, count: int | None = None, *, log_label: str = "") -> list[str]:
        """Scroll down with occasional scroll-back-up (human re-reading behavior)."""
        actions = self.scroll_down(count, log_label=log_label)

        # 12% chance to scroll back up a bit
        if random.random() < self._touch_cfg.get("scroll_back_up_probability", 0.12):
            back_count = random.randint(1, 3)
            time.sleep(random.uniform(0.8, 2.0))
            self.scroll_up(back_count, log_label=f"{log_label}_backup")
            actions.append(f"back_up_{back_count}")

        return actions

    # ─── Navigation ────────────────────────────────────────────────────────

    def back(self, *, use_gesture: bool | None = None, log_label: str = "") -> str:
        """Go back — randomly uses edge swipe gesture or system back button.

        Returns method used: "gesture" or "button".
        """
        if use_gesture is None:
            use_gesture = random.random() < self._touch_cfg.get("back_gesture_probability", 0.45)

        if use_gesture:
            # Edge swipe from left side
            edge_max = self._touch_cfg.get("edge_swipe_from_x_max", 80)
            sx = random.randint(0, edge_max)
            sy = random.randint(self.status_bar + 100, self.height - self.bottom_nav_h - 100)
            ex = random.randint(self.width // 3, self.width // 2)
            ey = sy + random.randint(-30, 30)
            dur = random.randint(200, 400)
            self.swipe(sx, sy, ex, ey, duration_ms=dur, log_label=f"{log_label}_back_gesture")
            method = "gesture"
        else:
            self._shell("input keyevent 4")  # KEYCODE_BACK
            time.sleep(random.uniform(0.1, 0.3))
            method = "button"

        if log_label:
            self._logger.log("nav_back", log_label, "ok", f"method={method}")
        return method

    def nav_to_tab(self, tab_key: str, *, log_label: str = "") -> None:
        """Navigate to a bottom-nav tab with thumb-zone offset."""
        tabs = self._cfg.get("navigation_tabs") or {
            "home": {"nav_index": 0, "label": "Home"},
            "messaging": {"nav_index": 1, "label": "Messaging"},
            "networking": {"nav_index": 2, "label": "My Network"},
            "jobs": {"nav_index": 3, "label": "Jobs"},
            "notifications": {"nav_index": 4, "label": "Notifications"},
        }
        tab = tabs.get(tab_key, {})
        if not tab:
            self._logger.log("nav_tab", tab_key, "blocked", "unknown_tab")
            return

        # Calculate approximate position on bottom nav
        nav_h = self.bottom_nav_h
        num_tabs = max(1, len(tabs))
        tab_index = tab.get("nav_index", 0)
        tab_width = self.width / num_tabs
        tap_x = int((tab_index + 0.5) * tab_width)
        tap_y = self.height - int(nav_h / 2)

        # Add thumb-zone offset
        offset_min, offset_max = self._cfg_range("bottom_nav_offset_px")
        tap_x += random.randint(int(offset_min), int(offset_max))
        tap_y += random.randint(int(offset_min), int(offset_max))

        self.tap(tap_x, tap_y, log_label=f"nav_{tab_key}")
        time.sleep(random.uniform(0.2, 0.5))  # Page transition

        if log_label:
            self._logger.log("nav_tab", tab_key, "ok", f"tab={tab.get('label','')},x={tap_x},y={tap_y}")

    def home_button(self) -> None:
        """Press Android home button (for app background/close)."""
        self._shell("input keyevent 3")  # KEYCODE_HOME
        time.sleep(random.uniform(0.3, 0.6))

    def recent_apps(self) -> None:
        """Press recent apps button."""
        self._shell("input keyevent 187")  # KEYCODE_APP_SWITCH
        time.sleep(random.uniform(0.3, 0.6))

    # ─── Special Gestures ──────────────────────────────────────────────────

    def long_press(self, x: int, y: int, *, duration_ms: int | None = None,
                   log_label: str = "") -> None:
        """Long press at position."""
        if duration_ms is None:
            duration_ms = random.randint(600, 1200)
        x, y = self._clamp(x, y)
        self._shell(
            f"input touchscreen down {x} {y} && "
            f"sleep 0.{duration_ms:03d} && "
            f"input touchscreen up"
        )
        time.sleep(duration_ms / 1000.0 + 0.05)
        if log_label:
            self._logger.log("touch_long_press", log_label, "ok", f"x={x},y={y},dur={duration_ms}ms")

    def two_finger_scroll(self, x: int, y: int, direction: str = "down",
                           distance: int = 200, log_label: str = "") -> None:
        """Two-finger scroll (zoom-style) for content like carousels."""
        gap = 80  # pixels between fingers
        x1, x2 = x - gap // 2, x + gap // 2
        y_start = y
        y_end = y + distance if direction == "down" else y - distance
        dur = random.randint(300, 500)

        self._shell(
            f"input touchscreen down {x1} {y_start} && "
            f"input touchscreen down {x2} {y_start} && "
            f"sleep 0.{dur:03d} && "
            f"input touchscreen move {x1} {y_end} && "
            f"input touchscreen move {x2} {y_end} && "
            f"input touchscreen up"
        )
        time.sleep(dur / 1000.0 + 0.05)
        if log_label:
            self._logger.log("touch_two_finger", log_label, "ok",
                             f"dir={direction},dist={distance}")
