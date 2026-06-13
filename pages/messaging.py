"""Messaging page — inbox scrolling with occasional conversation reading."""
from __future__ import annotations

import random
import time

from human_touch import HumanTouch
from detection_shields import DetectionShield


class MessagingPage:
    """Handles messaging/inbox page actions."""

    def __init__(self, touch: HumanTouch, shield: DetectionShield, config: dict,
                 driver, logger) -> None:
        self._touch = touch
        self._shield = shield
        self._cfg = config
        self._driver = driver
        self._logger = logger

    def check_messages(self) -> dict:
        """Check messaging inbox like a human.

        Returns: {has_conversations, scrolled, opened_conversation, read_duration}
        """
        stats = {"has_conversations": False, "scrolled": 0, "opened_conversation": False,
                 "read_duration": 0.0}

        dwell_cfg = self._cfg.get("dwell", {})
        actions_cfg = self._cfg.get("actions", {})

        # Navigate to messaging tab
        self._touch.nav_to_tab("messaging", log_label="msg_nav")

        # Check if there are conversations
        has_conversations = self._has_conversations()
        stats["has_conversations"] = has_conversations

        if has_conversations:
            # Scroll through conversations
            scroll_count = random.randint(2, 5)
            self._touch.scroll_down(scroll_count, log_label="msg_inbox_scroll")
            stats["scrolled"] = scroll_count

            # Maybe open a conversation
            if random.random() < actions_cfg.get("message_tap_probability", 0.40):
                self._open_random_conversation(stats)
        else:
            # No conversations — quick glance and leave
            glance_time = random.uniform(1.0, 2.0)
            time.sleep(glance_time)
            self._logger.log("messaging", "empty_inbox", "ok", f"glance={glance_time:.1f}s")

            # Navigate to a random page instead
            if random.random() < 0.5:
                self._touch.nav_to_tab("home", log_label="msg_empty_to_home")
            else:
                self._touch.nav_to_tab("networking", log_label="msg_empty_to_network")

        self._logger.log("messaging", "check", "ok",
                         f"has_conv={has_conversations},opened={stats['opened_conversation']}")
        return stats

    def _has_conversations(self) -> bool:
        """Check if there are conversations in the inbox."""
        try:
            # Check for empty state
            empty_view = self._driver(resourceId="com.linkedin.android:id/conversation_list_empty_state_view")
            if empty_view.exists and empty_view.get_info().get("text", ""):
                return False

            # Check for conversation list
            conv_list = self._driver(resourceId="com.linkedin.android:id/conversation_list")
            if conv_list.exists:
                return True

            # Fallback: look for text views (conversation entries)
            text_views = self._driver(className="android.widget.TextView")
            if text_views.count > 3:
                return True

            return False
        except Exception:
            return True  # Default to assuming conversations exist

    def _open_random_conversation(self, stats: dict) -> None:
        """Open and read a random conversation."""
        # Tap a random conversation in the list
        conv_items = self._driver(className="android.widget.RelativeLayout")
        if conv_items.count < 2:
            return

        # Pick a random one (not always the first)
        index = random.randint(0, min(conv_items.count - 1, 5))

        # Find bounds of the selected conversation
        try:
            info = conv_items[index].get_info()
            bounds = info.get("bounds", {})
            if bounds:
                cx = (bounds["left"] + bounds["right"]) // 2
                cy = (bounds["top"] + bounds["bottom"]) // 2
            else:
                # Fallback position
                cx = random.randint(300, 700)
                cy = random.randint(250 + index * 80, 300 + index * 80)
        except (IndexError, TypeError):
            cx = random.randint(300, 700)
            cy = random.randint(250 + index * 80, 300 + index * 80)

        self._touch.tap(cx, cy, log_label="msg_conv_open")
        stats["opened_conversation"] = True

        # Read the conversation
        read_range = self._cfg.get("dwell", {}).get("message_read_seconds", {"min": 3, "max": 8})
        read_time = random.uniform(read_range["min"], read_range["max"])
        read_time = self._shield.behavioral_profile.get_variation(read_time, "duration")
        time.sleep(read_time)
        stats["read_duration"] = read_time

        # Scroll through messages
        scroll_count = random.randint(1, 4)
        self._touch.scroll_down(scroll_count, log_label="msg_conv_scroll")

        # Maybe scroll back up to re-read
        if random.random() < 0.20:
            self._touch.scroll_up(2, log_label="msg_conv_backup")

        # Go back
        self._touch.back(log_label="msg_conv_back")

        self._logger.log("messaging", "conversation", "ok",
                         f"index={index},read={read_time:.1f}s,scrolls={scroll_count}")
