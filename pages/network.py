"""My Network page — suggestions scrolling with profile visits and pending request checks."""
from __future__ import annotations

import random
import time

from human_touch import HumanTouch
from detection_shields import DetectionShield
from safety import assert_no_risk_screen, block_action, is_action_allowed, is_read_only_live_test


class NetworkPage:
    """Handles My Network page actions."""

    def __init__(self, touch: HumanTouch, shield: DetectionShield, config: dict,
                 driver, logger, profile_page) -> None:
        self._touch = touch
        self._shield = shield
        self._cfg = config
        self._driver = driver
        self._logger = logger
        self._profile_page = profile_page  # ProfilePage instance for reuse

    def browse_network(self) -> dict:
        """Browse the My Network page like a human.

        Returns: {scrolled, profiles_viewed, pending_checked}
        """
        stats = {"scrolled": 0, "profiles_viewed": 0, "pending_checked": False}
        if self._cfg.get("safety", {}).get("stop_on_risk_screen", True):
            assert_no_risk_screen(self._driver, self._logger, context="network")

        scroll_cfg = self._cfg.get("scroll", {})
        dwell_cfg = self._cfg.get("dwell", {})
        actions_cfg = self._cfg.get("actions", {})

        # Navigate to network tab
        self._touch.nav_to_tab("networking", log_label="net_nav")

        # Check pending invitations first (occasionally)
        if not is_read_only_live_test(self._cfg) and random.random() < 0.30:
            self._check_pending_invitations(stats)

        # Scan network suggestions
        scan_range = dwell_cfg.get("network_scan_seconds", {"min": 1.0, "max": 2.5})
        time.sleep(random.uniform(scan_range["min"], scan_range["max"]))

        # Scroll through suggestions
        num_swipes = random.randint(scroll_cfg.get("network_min_swipes", 3),
                                     scroll_cfg.get("network_max_swipes", 6))

        for i in range(num_swipes):
            self._touch.scroll_with_back_up(log_label="net_scroll")
            stats["scrolled"] += 1

            # Dwell on each suggestion card
            dwell = random.uniform(0.5, 1.5)
            time.sleep(dwell)

            # Maybe open a profile
            if not is_read_only_live_test(self._cfg) and random.random() < actions_cfg.get("profile_open_from_network_probability", 0.25):
                self._open_suggested_profile(stats)

        self._logger.log("network", "browse", "ok",
                         f"scrolls={stats['scrolled']},profiles={stats['profiles_viewed']}")
        return stats

    def _check_pending_invitations(self, stats: dict) -> None:
        """Check pending connection requests (incoming + sent)."""
        if not is_action_allowed(self._cfg, "pending_accept"):
            block_action(self._logger, "network", "pending_check")
            return
        # Look for pending indicator
        pending_badge = self._driver(resourceId="com.linkedin.android:id/tab_notifications")
        pending_text = self._driver(text="Pending")

        if pending_text.exists:
            bounds = pending_text.bounds
            if bounds:
                cx = (bounds[0]["x"] + bounds[2]["x"]) // 2
                cy = (bounds[0]["y"] + bounds[2]["y"]) // 2
                self._touch.tap(cx, cy, log_label="net_pending")

                # Scan pending list
                time.sleep(random.uniform(1.0, 2.5))

                # Maybe accept a pending request
                if random.random() < 0.50:
                    self._maybe_accept_pending()

                self._touch.back(log_label="net_pending_back")
                stats["pending_checked"] = True

                self._logger.log("network", "pending_checked", "ok")
        else:
            self._logger.log("network", "no_pending", "ok")

    def _maybe_accept_pending(self) -> None:
        """Accept a pending connection request."""
        if not is_action_allowed(self._cfg, "pending_accept"):
            block_action(self._logger, "network", "pending_accept")
            return
        confirm_btn = self._driver(text="Confirm")
        if not confirm_btn.exists:
            confirm_btn = self._driver(text="Accept")

        if confirm_btn.exists:
            # Find first pending request's confirm button
            pending_items = self._driver(className="android.widget.LinearLayout")
            if pending_items.count > 1:
                index = random.randint(1, min(pending_items.count - 1, 4))
                try:
                    info = pending_items[index].get_info()
                    bounds = info.get("bounds", {})
                    if bounds:
                        cx = (bounds["left"] + bounds["right"]) // 2
                        cy = (bounds["top"] + bounds["bottom"]) // 2
                        # Tap to expand
                        self._touch.tap(cx, cy, log_label="net_pending_expand")
                        time.sleep(random.uniform(0.5, 1.0))

                        # Tap confirm
                        if confirm_btn.exists:
                            cb = confirm_btn.bounds
                            if cb:
                                self._touch.tap(
                                    (cb[0]["x"] + cb[2]["x"]) // 2,
                                    (cb[0]["y"] + cb[2]["y"]) // 2,
                                    log_label="net_pending_confirm"
                                )
                except (IndexError, TypeError):
                    pass

    def _open_suggested_profile(self, stats: dict) -> None:
        """Open a suggested profile from network suggestions."""
        if not is_action_allowed(self._cfg, "profile_open"):
            block_action(self._logger, "network", "profile_open")
            return
        # Tap on a suggested profile card (name/avatar area)
        cx = random.randint(30, 150)
        cy = random.randint(
            self._touch.status_bar + 200,
            self._touch.height - self._touch.bottom_nav_h - 100
        )
        self._touch.tap(cx, cy, log_label="net_profile_open")
        time.sleep(random.uniform(0.5, 1.0))

        # Use the profile page handler for viewing
        profile_stats = self._profile_page.view_profile()
        stats["profiles_viewed"] += 1
        if profile_stats.get("connected"):
            self._logger.log("network", "profile_connected", "ok",
                             f"score={profile_stats.get('score', 0)}")
