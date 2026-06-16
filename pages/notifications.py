"""Notifications page — quick scan with occasional deep interaction."""
from __future__ import annotations

import random
import time

from human_touch import HumanTouch
from detection_shields import DetectionShield
from safety import assert_no_risk_screen, block_action, is_action_allowed, is_read_only_live_test


class NotificationsPage:
    """Handles notifications page actions."""

    def __init__(self, touch: HumanTouch, shield: DetectionShield, config: dict,
                 driver, logger) -> None:
        self._touch = touch
        self._shield = shield
        self._cfg = config
        self._driver = driver
        self._logger = logger

    def check_notifications(self) -> dict:
        """Quick scan notifications like a human glancing at them.

        Returns: {scanned, tapped, notification_type}
        """
        stats = {"scanned": True, "tapped": False, "notification_type": ""}
        if self._cfg.get("safety", {}).get("stop_on_risk_screen", True):
            assert_no_risk_screen(self._driver, self._logger, context="notifications")

        dwell_cfg = self._cfg.get("dwell", {})
        actions_cfg = self._cfg.get("actions", {})

        # Navigate to notifications tab
        self._touch.nav_to_tab("notifications", log_label="notif_nav")

        # Scan notifications
        scan_range = dwell_cfg.get("notification_scan_seconds", {"min": 0.6, "max": 1.4})
        scan_time = random.uniform(scan_range["min"], scan_range["max"])
        scan_time = self._shield.behavioral_profile.get_variation(scan_time, "duration")
        time.sleep(scan_time)

        # Brief scroll to see more
        self._touch.scroll_down(2, log_label="notif_scan_scroll")

        # Maybe tap a notification
        if not is_read_only_live_test(self._cfg) and random.random() < actions_cfg.get("notification_tap_probability", 0.30):
            self._tap_random_notification(stats)

        self._logger.log("notifications", "check", "ok",
                         f"scan={scan_time:.2f}s,tapped={stats['tapped']}")
        return stats

    def _tap_random_notification(self, stats: dict) -> None:
        """Tap a random notification to view the related content."""
        if not is_action_allowed(self._cfg, "notification_tap"):
            block_action(self._logger, "notifications", "notification_tap")
            return
        try:
            # Get list of notification items
            notifications = self._driver(resourceId="com.linkedin.android:id/content_notification_list")
            if not notifications.exists:
                # Fallback: find by class
                notif_items = self._driver(className="android.widget.LinearLayout").child(
                    className="android.widget.RelativeLayout"
                )

            # Tap a random notification (not the first one — humans don't always tap first)
            tap_y = random.randint(
                self._touch.status_bar + 150,
                self._touch.height - self._touch.bottom_nav_h - 50
            )
            tap_x = random.randint(200, 800)

            self._touch.tap(tap_x, tap_y, log_label="notif_tap")

            # Dwell on the opened content
            dwell = random.uniform(3.0, 7.0)
            time.sleep(dwell)

            # Maybe scroll the opened content
            if random.random() < 0.40:
                self._touch.scroll_down(2, log_label="notif_content_scroll")

            stats["tapped"] = True
            stats["notification_type"] = self._classify_notification()
            self._logger.log("notifications", "tap", "ok",
                             f"type={stats['notification_type']},dwell={dwell:.1f}s")

        except Exception as e:
            self._logger.log("notifications", "tap_error", "warn", str(e))

    def _classify_notification(self) -> str:
        """Classify the type of notification viewed."""
        try:
            xml = self._driver.dump_hierarchyParser()
            xml_str = str(xml) if xml else ""

            if "like" in xml_str.lower():
                return "like"
            if "comment" in xml_str.lower():
                return "comment"
            if "connection" in xml_str.lower() or "connect" in xml_str.lower():
                return "connection"
            if "view" in xml_str.lower() and "profile" in xml_str.lower():
                return "profile_view"
            if "reacted" in xml_str.lower():
                return "reaction"
            return "other"
        except Exception:
            return "unknown"
