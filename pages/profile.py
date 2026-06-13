"""Profile page — viewing profiles with scoring-aware connect behavior."""
from __future__ import annotations

import random
import time

from human_touch import HumanTouch
from detection_shields import DetectionShield


class ProfilePage:
    """Handles profile viewing actions with human-like scrolling and scoring."""

    def __init__(self, touch: HumanTouch, shield: DetectionShield, config: dict,
                 driver, logger) -> None:
        self._touch = touch
        self._shield = shield
        self._cfg = config
        self._driver = driver
        self._logger = logger

    def view_profile(self, *, profile_name: str = "") -> dict:
        """View a profile with human-like behavior: scroll, read, possibly connect.

        Returns: {scrolled, connected, score, viewed_activity}
        """
        stats = {"scrolled": 0, "connected": False, "score": 0, "viewed_activity": False}
        dwell_cfg = self._cfg.get("dwell", {})
        scroll_cfg = self._cfg.get("scroll", {})

        # 1. Initial read of header (name, headline, company)
        header_dwell = random.uniform(1.5, 3.5)
        time.sleep(header_dwell)
        self._logger.log("profile", "read_header", "ok", f"name={profile_name},dwell={header_dwell:.1f}s")

        # 2. Score the profile (for connect decision)
        score = self._score_profile()
        stats["score"] = score

        # 3. Scroll through profile sections
        num_swipes = random.randint(scroll_cfg.get("profile_min_swipes", 2),
                                     scroll_cfg.get("profile_max_swipes", 5))

        for i in range(num_swipes):
            # Variable scroll speed: slower on About/Experience sections
            swipe_dur = random.randint(300, 550)
            region_y = 300 + i * 250  # Approximate section positions

            sx = random.randint(300, 700)
            sy_start = min(region_y + 100, self._touch.height - 200)
            sy_end = sy_start - random.randint(150, 300)

            self._touch.swipe(sx, sy_start, sx, sy_end, duration_ms=swipe_dur,
                              log_label=f"profile_scroll_{i}")
            stats["scrolled"] += 1

            # Dwell after each scroll (reading section)
            section_dwell = random.uniform(0.8, 2.0)
            time.sleep(section_dwell)

        # 4. Total dwell check
        min_dwell = dwell_cfg.get("profile_seconds", {"min": 5, "max": 15})["min"]
        max_dwell = dwell_cfg.get("profile_seconds", {"min": 5, "max": 15})["max"]
        elapsed = time.monotonic()  # Track if we need more viewing time

        # 5. Maybe view activity section
        if random.random() < 0.20 and score > 50:
            self._view_activity()
            stats["viewed_activity"] = True

        # 6. Connect decision (score-gated)
        if self._should_connect(score):
            self._tap_connect()
            stats["connected"] = True

        # 7. Go back
        self._touch.back(log_label="profile_back")
        self._logger.log("profile", "view_complete", "ok",
                         f"name={profile_name},score={score},connected={stats['connected']}")
        return stats

    def _score_profile(self) -> int:
        """Score a profile for connect relevance (0-100).

        Uses scoring factors from config. For feed-encountered profiles,
        this uses visible UI data. For network suggestions, LinkedIn's
        own "X mutual connections" text is parsed.
        """
        score_factors = self._cfg.get("scoring", {}).get("score_factors", {})
        score = 30  # Base score

        try:
            xml = self._driver.dump_hierarchyParser()
            xml_str = str(xml) if xml else ""

            # Factor 1: Mutual connections (highest weight)
            mutual = self._parse_mutual_connections(xml_str)
            if mutual > 0:
                score += int(score_factors.get("mutual_connections_weight", 0.30) * 100 * min(mutual / 5, 1.0))

            # Factor 2: Same industry
            my_industry = self._cfg.get("profile_defaults", {}).get("my_industry", "")
            if my_industry and my_industry.lower() in xml_str.lower():
                score += int(score_factors.get("same_industry_weight", 0.20) * 100)

            # Factor 3: Similar role
            my_roles = self._cfg.get("profile_defaults", {}).get("my_roles", [])
            for role in my_roles:
                if role.lower() in xml_str.lower():
                    score += int(score_factors.get("similar_role_weight", 0.20) * 100)
                    break

            # Factor 4: Profile completeness (detect presence of key sections)
            sections_found = 0
            for section in ["About", "Experience", "Activity", "Publications"]:
                if section in xml_str:
                    sections_found += 1
            completeness = sections_found / 4.0
            score += int(score_factors.get("profile_completeness_weight", 0.15) * 100 * completeness)

            # Factor 5: Activity recency (if "Active X" text found)
            if "active" in xml_str.lower():
                score += int(score_factors.get("activity_recency_weight", 0.15) * 100 * 0.7)

        except Exception:
            # Fallback: random score with normal distribution around 50
            score = int(random.gauss(50, 15))

        return max(0, min(100, score))

    def _parse_mutual_connections(self, xml_str: str) -> int:
        """Parse mutual connections count from profile XML."""
        import re
        # Look for patterns like "X mutual connections" or "X mutual"
        match = re.search(r'(\d+)\s*mutual', xml_str, re.IGNORECASE)
        if match:
            return int(match.group(1))
        return 0

    def _should_connect(self, score: int) -> bool:
        """Decide whether to send a connect request based on score."""
        min_score = self._cfg.get("scoring", {}).get("auto_connect_min_score", 70)
        prob = self._cfg.get("actions", {}).get("connect_probability", 0.50)

        # No connect if score is below minimum
        if score < min_score:
            return False

        # Higher score = higher probability
        adjusted_prob = prob * (score / 100.0)
        return random.random() < adjusted_prob

    def _tap_connect(self) -> None:
        """Tap the connect/follow button on a profile."""
        allowed, reason = self._shield.can_act("connect")
        if not allowed:
            self._logger.log("profile", "connect_skipped", "rate_limited", reason)
            return

        # Try to find connect button by text
        connect_btn = self._driver(text="Connect")
        if not connect_btn.exists:
            connect_btn = self._driver(text="Follow")
        if not connect_btn.exists:
            connect_btn = self._driver(resourceId="com.linkedin.android:id/button_connect")

        if connect_btn.exists:
            bounds = connect_btn.bounds
            if bounds:
                cx = (bounds[0]["x"] + bounds[2]["x"]) // 2
                cy = (bounds[0]["y"] + bounds[2]["y"]) // 2
                self._touch.tap(cx, cy, log_label="profile_connect")
                self._shield.record_action("connect")

                # Check if a dialog appeared (connect with options)
                time.sleep(random.uniform(0.3, 0.6))
                self._handle_connect_dialog()

                self._logger.log("profile", "connect_sent", "ok")
                return

        # Fallback: tap in expected button area (bottom area of profile)
        cx = random.randint(200, 500)
        cy = self._touch.height - self._touch.bottom_nav_h - random.randint(30, 80)
        self._touch.tap(cx, cy, log_label="profile_connect_fallback")
        self._shield.record_action("connect")

    def _handle_connect_dialog(self) -> None:
        """Handle the 'Connect' vs 'Follow' vs 'Add to network' dialog."""
        # Check for "Connect" button in dialog
        connect_confirm = self._driver(text="Connect")
        if connect_confirm.exists:
            # Check if "Add a note" option is available
            add_note = self._driver(text="Add a note")
            if add_note.exists and random.random() < 0.20:
                # 20% chance to add a note
                self._touch.tap(
                    add_note.bounds[0]["x"] + 50,
                    add_note.bounds[2]["y"] - 20,
                    log_label="connect_add_note"
                )
                time.sleep(random.uniform(1.0, 2.0))
                # Tap connect without note for now (note drafting TBD)

            bounds = connect_confirm.bounds
            cx = (bounds[0]["x"] + bounds[2]["x"]) // 2
            cy = (bounds[0]["y"] + bounds[2]["y"]) // 2
            self._touch.tap(cx, cy, log_label="connect_confirm")
        else:
            # Direct connect (no dialog) — just confirm
            time.sleep(random.uniform(0.2, 0.5))

    def _view_activity(self) -> None:
        """View the profile's activity/recent posts."""
        activity_tab = self._driver(text="Activity")
        if not activity_tab.exists:
            activity_tab = self._driver(text="Posts")

        if activity_tab.exists:
            bounds = activity_tab.bounds
            cx = (bounds[0]["x"] + bounds[2]["x"]) // 2
            cy = (bounds[0]["y"] + bounds[2]["y"]) // 2
            self._touch.tap(cx, cy, log_label="profile_activity")
            time.sleep(random.uniform(2.0, 4.0))
            # Scroll activity briefly
            self._touch.scroll_down(2, log_label="profile_activity_scroll")
        else:
            # Scroll to activity section in profile
            self._touch.scroll_down(3, log_label="profile_to_activity")
            time.sleep(random.uniform(1.5, 3.0))
