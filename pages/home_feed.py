"""Home/Feed page — core browsing behavior with content-type awareness."""
from __future__ import annotations

import random
import time

from human_touch import HumanTouch
from detection_shields import DetectionShield


class HomeFeedPage:
    """Handles all feed/home page actions with human-like behavior."""

    def __init__(self, touch: HumanTouch, shield: DetectionShield, config: dict,
                 driver, logger) -> None:
        self._touch = touch
        self._shield = shield
        self._cfg = config
        self._driver = driver  # uiautomator2 device instance
        self._logger = logger

    def browse_feed(self, *, max_duration_seconds: float | None = None) -> dict:
        """Browse the feed with human-like scrolling, reading, liking, and profile visits.

        Returns stats: {scrolls, likes, saves, comments, profiles_opened, post_details}
        """
        stats = {"scrolls": 0, "likes": 0, "saves": 0, "comments": 0,
                 "profiles_opened": 0, "post_details": 0}

        scroll_cfg = self._cfg.get("scroll", {})
        dwell_cfg = self._cfg.get("dwell", {})
        num_swipes = random.randint(scroll_cfg.get("feed_min_swipes", 5),
                                     scroll_cfg.get("feed_max_swipes", 12))

        start_time = time.monotonic()

        for i in range(num_swipes):
            # Time check
            if max_duration_seconds and (time.monotonic() - start_time) > max_duration_seconds:
                break

            # 1. Read/dwell on current post (before scrolling)
            content_type = self._detect_content_type()
            dwell_key = f"feed_post_{content_type}_seconds"
            if dwell_key in dwell_cfg:
                dwell_range = dwell_cfg[dwell_key]
            else:
                dwell_range = dwell_cfg.get("feed_post_text_only_seconds", {"min": 0.4, "max": 1.0})
            dwell = random.uniform(dwell_range["min"], dwell_range["max"])

            # Apply behavioral variation
            dwell = self._shield.behavioral_profile.get_variation(dwell, "duration")
            time.sleep(dwell)
            self._logger.log("feed", "dwell", "ok", f"type={content_type},dwell={dwell:.2f}s")

            # 2. Decide on post interaction
            self._maybe_like_post(content_type, stats)
            self._maybe_save_post(stats)
            self._maybe_comment_post(stats)
            self._maybe_view_post_detail(stats)
            self._maybe_open_post_profile(stats)

            # 3. Scroll to next post
            self._touch.scroll_with_back_up(log_label="feed")
            stats["scrolls"] += 1

            # 4. Check stuck page
            if self._shield.record_page("feed_scroll"):
                self._logger.log("feed", "stuck_recovery", "info", "scrolling more")
                self._touch.scroll_down(3, log_label="feed_recovery")
                break

        return stats

    def _detect_content_type(self) -> str:
        """Detect post content type from UI hierarchy."""
        try:
            xml = self._driver.dump_hierarchyParser()
            xml_str = str(xml) if xml else ""

            indicators = self._cfg.get("content_types", {})

            if any(ind in xml_str for ind in indicators.get("video_indicators", [])):
                return "video"
            if any(ind in xml_str for ind in indicators.get("carousel_indicators", [])):
                return "carousel"
            if any(ind in xml_str for ind in indicators.get("document_indicators", [])):
                return "article"
            if any(ind in xml_str for ind in indicators.get("image_indicators", [])):
                return "image"

            # Check for comment indicators
            if '"comment"' in xml_str.lower() or 'comments' in xml_str.lower():
                return "with_comments"

            return "text_only"
        except Exception:
            # Fallback: random type with text_only weighted highest
            return random.choices(
                ["text_only", "image", "video", "carousel"],
                weights=[0.5, 0.25, 0.15, 0.1],
                k=1
            )[0]

    def _maybe_like_post(self, content_type: str, stats: dict) -> None:
        """Like a post with human-like gesture (double-tap or button tap)."""
        allowed, reason = self._shield.can_act("like")
        if not allowed:
            return

        prob = self._cfg.get("actions", {}).get("like_probability", 0.35)
        prob = self._shield.behavioral_profile.get_variation(prob, "probability")

        # Higher like probability for image/video content
        if content_type in ("image", "video", "carousel"):
            prob *= 1.2

        if random.random() > prob:
            return

        # Wait before liking (read time)
        read_cfg = {"min": 1.0, "max": 3.0}
        time.sleep(random.uniform(read_cfg["min"], read_cfg["max"]))

        # Decide: double-tap (images) or button tap
        if content_type in ("image", "carousel") and random.random() < 0.6:
            # Double-tap on content area (Instagram-style, but happens on LinkedIn too)
            cx = self._touch.width // 2 + random.randint(-50, 50)
            cy = self._touch.height // 2 + random.randint(-80, 80)
            self._touch.double_tap(cx, cy, log_label="feed_like_doubletap")
        else:
            # Tap like button
            self._tap_like_button()

        self._shield.record_action("like")
        stats["likes"] += 1
        self._logger.log("feed", "like", "ok", f"type={content_type}")

    def _tap_like_button(self) -> None:
        """Tap the like button on the current post."""
        # Try to find like button by resource-id, fallback to relative position
        like_btn = self._driver(resourceId="com.linkedin.android:id/button_like")
        if like_btn.exists:
            bounds = like_btn.bounds
            if bounds:
                cx = (bounds[0]["x"] + bounds[2]["x"]) // 2
                cy = (bounds[0]["y"] + bounds[2]["y"]) // 2
                self._touch.tap(cx, cy, log_label="feed_like_btn")
                return

        # Fallback: approximate position (bottom of post card)
        cx = random.randint(150, 350)
        cy = self._touch.height - self._touch.bottom_nav_h - random.randint(40, 100)
        self._touch.tap(cx, cy, log_label="feed_like_fallback")

    def _maybe_save_post(self, stats: dict) -> None:
        """Save/bookmark a post."""
        allowed, _ = self._shield.can_act("save")
        if not allowed:
            return

        prob = self._cfg.get("actions", {}).get("save_probability", 0.08)
        if random.random() > prob:
            return

        # Try to find save button
        save_btn = self._driver(resourceId="com.linkedin.android:id/action_share")
        if save_btn.exists:
            bounds = save_btn.bounds
            cx = (bounds[0]["x"] + bounds[2]["x"]) // 2
            cy = (bounds[0]["y"] + bounds[2]["y"]) // 2
            self._touch.tap(cx, cy, log_label="feed_save")
            self._shield.record_action("save")
            stats["saves"] += 1
            self._logger.log("feed", "save", "ok")

    def _maybe_comment_post(self, stats: dict) -> None:
        """Comment on a post (low probability, high engagement signal)."""
        allowed, _ = self._shield.can_act("comment")
        if not allowed:
            return

        prob = self._cfg.get("actions", {}).get("comment_probability", 0.05)
        if random.random() > prob:
            return

        # Comment flow: tap comment button → type → submit
        # For now, just log the intent — actual comment drafting needs NLP
        self._shield.record_action("comment")
        stats["comments"] += 1
        self._logger.log("feed", "comment_intent", "ok", "comment_flow_tbd")

    def _maybe_view_post_detail(self, stats: dict) -> None:
        """Expand post to see full text and comments."""
        if random.random() > 0.10:
            return

        # Tap on post text area to expand
        cx = self._touch.width // 2 + random.randint(-80, 80)
        cy = self._touch.height // 3 + random.randint(-50, 50)
        self._touch.tap(cx, cy, log_label="feed_post_detail")

        dwell_cfg = self._cfg.get("dwell", {})
        read_range = dwell_cfg.get("post_detail_read_seconds", {"min": 4, "max": 12})
        time.sleep(random.uniform(read_range["min"], read_range["max"]))

        self._touch.back(log_label="feed_post_detail_back")
        stats["post_details"] += 1
        self._logger.log("feed", "post_detail", "ok")

    def _maybe_open_post_profile(self, stats: dict) -> None:
        """Open the post author's profile from the feed."""
        allowed, _ = self._shield.can_act("profile")
        prob = self._cfg.get("actions", {}).get("profile_open_from_feed_probability", 0.18)
        if random.random() > prob:
            return

        # Tap on author name/avatar area (top-left of post card)
        cx = random.randint(30, 120)
        cy = self._touch.status_bar + random.randint(20, 80)
        self._touch.tap(cx, cy, log_label="feed_profile_open")
        time.sleep(random.uniform(0.5, 1.0))  # Page transition

        stats["profiles_opened"] += 1
        self._logger.log("feed", "profile_open", "ok")
        # Profile handling delegated to ProfilePage via the action engine
