"""Markov-chain action engine — generates human-like action sequences.

Uses transition probability matrix between page states to create
unpredictable but realistic navigation patterns.  No two sessions
follow the same path.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field


PAGES = ("feed", "notifications", "messaging", "network", "profile", "idle")

# Transition matrix: from row → column probabilities
# Row order: feed, notifications, messaging, network, profile, idle
TRANSITION_MATRIX = [
    #          feed   notify  msg    network profile idle
    [0.39,     0.13,  0.11,   0.11,  0.20,   0.06],   # from feed
    [0.44,     0.06,  0.11,   0.11,  0.13,   0.15],   # from notifications
    [0.40,     0.09,  0.06,   0.13,  0.11,   0.21],   # from messaging
    [0.34,     0.09,  0.08,   0.06,  0.27,   0.16],   # from network
    [0.33,     0.11,  0.09,   0.17,  0.06,   0.24],   # from profile
    [0.50,     0.11,  0.11,   0.11,  0.11,   0.06],   # from idle
]

PAGE_INDEX = {p: i for i, p in enumerate(PAGES)}


@dataclass
class ActionPlan:
    """A planned action to execute."""
    page: str               # Target page
    action: str             # Specific action (e.g., "scroll", "like", "open_profile")
    params: dict = field(default_factory=dict)  # Action-specific parameters
    priority: float = 1.0   # Higher = more likely when choosing among options


class ActionEngine:
    """Generates human-like action sequences using a Markov chain with constraints."""

    def __init__(self, config: dict) -> None:
        self._cfg = config
        actions_cfg = config.get("actions", {})
        self._min_actions = actions_cfg.get("min_per_session", 8)
        self._max_actions = actions_cfg.get("max_per_session", 18)
        self._max_consecutive = actions_cfg.get("max_consecutive_same_page", 2)
        self._current_page = "feed"  # Default starting page
        self._page_streak = 0
        self._action_sequence: list[ActionPlan] = []

    def generate_session_plan(self, start_page: str = "feed") -> list[ActionPlan]:
        """Generate a complete session action plan."""
        self._current_page = start_page
        self._page_streak = 0
        self._action_sequence = []

        n_actions = random.randint(self._min_actions, self._max_actions)

        # First action varies (always, for anti-detection)
        if self._cfg.get("anti_detection", {}).get("vary_first_action_probability", 1.0) > 0:
            first_action = self._pick_action("feed")
            if first_action:
                self._action_sequence.append(first_action)
                n_actions -= 1

        for _ in range(n_actions):
            # Decide: stay or transition?
            next_page = self._next_page()

            # Generate action for the target page
            action = self._pick_action(next_page)
            if action is None:
                # Fallback to idle if no meaningful action available
                action = ActionPlan(page="idle", action="pause",
                                    params={"duration": random.uniform(1.0, 3.0)})

            self._action_sequence.append(action)

        return self._action_sequence

    def _next_page(self) -> str:
        """Determine next page using Markov chain + streak constraint."""
        current_idx = PAGE_INDEX[self._current_page]
        probs = TRANSITION_MATRIX[current_idx]

        # Penalize staying on same page if streak limit reached
        if self._page_streak >= self._max_consecutive:
            probs[current_idx] = 0.0

        # Renormalize
        total = sum(probs)
        if total > 0:
            probs = [p / total for p in probs]

        # Weighted random selection
        next_idx = random.choices(range(len(PAGES)), weights=probs, k=1)[0]
        next_page = PAGES[next_idx]

        if next_page == self._current_page:
            self._page_streak += 1
        else:
            self._page_streak = 1
            self._current_page = next_page

        return next_page

    def _pick_action(self, page: str) -> ActionPlan | None:
        """Pick a specific action for the given page, respecting rate limits."""
        action_pool = self._page_action_pool(page)
        if not action_pool:
            return None

        # Weighted selection based on probabilities
        weights = [a.priority for a in action_pool]
        total = sum(weights)
        if total <= 0:
            return None

        weights = [w / total for w in weights]
        chosen = random.choices(action_pool, weights=weights, k=1)[0]
        return chosen

    def _page_action_pool(self, page: str) -> list[ActionPlan]:
        """Build the pool of possible actions for each page."""
        a_cfg = self._cfg.get("actions", {})

        if page == "feed":
            return self._feed_actions(a_cfg)
        elif page == "notifications":
            return self._notification_actions(a_cfg)
        elif page == "messaging":
            return self._messaging_actions(a_cfg)
        elif page == "network":
            return self._network_actions(a_cfg)
        elif page == "profile":
            return self._profile_actions(a_cfg)
        elif page == "idle":
            return [ActionPlan(page="idle", action="pause",
                               params={"duration": random.uniform(1.0, 4.0)},
                               priority=1.0)]
        return []

    def _feed_actions(self, a_cfg: dict) -> list[ActionPlan]:
        actions = [
            ActionPlan("feed", "scroll",
                       params={"count": random.randint(3, 8)},
                       priority=0.40),
        ]
        # Like (only if under limits)
        if a_cfg.get("max_likes_per_session", 99) > 0:
            actions.append(
                ActionPlan("feed", "like_post",
                           params={},
                           priority=a_cfg.get("like_probability", 0.35))
            )
        # Save
        if a_cfg.get("max_saves_per_session", 99) > 0:
            actions.append(
                ActionPlan("feed", "save_post",
                           params={},
                           priority=a_cfg.get("save_probability", 0.08))
            )
        # Comment
        if a_cfg.get("max_comments_per_session", 99) > 0:
            actions.append(
                ActionPlan("feed", "comment_post",
                           params={},
                           priority=a_cfg.get("comment_probability", 0.05))
            )
        # Open profile from feed
        actions.append(
            ActionPlan("feed", "open_profile",
                       params={},
                       priority=a_cfg.get("profile_open_from_feed_probability", 0.18))
        )
        # Expand post detail
        actions.append(
            ActionPlan("feed", "view_post_detail",
                       params={},
                       priority=0.10)
        )
        return actions

    def _notification_actions(self, a_cfg: dict) -> list[ActionPlan]:
        return [
            ActionPlan("notifications", "scan",
                       params={},
                       priority=0.60),
            ActionPlan("notifications", "tap_notification",
                       params={},
                       priority=a_cfg.get("notification_tap_probability", 0.30)),
        ]

    def _messaging_actions(self, a_cfg: dict) -> list[ActionPlan]:
        return [
            ActionPlan("messaging", "scroll_inbox",
                       params={"count": random.randint(2, 5)},
                       priority=0.50),
            ActionPlan("messaging", "open_conversation",
                       params={},
                       priority=a_cfg.get("message_tap_probability", 0.40)),
        ]

    def _network_actions(self, a_cfg: dict) -> list[ActionPlan]:
        return [
            ActionPlan("network", "scroll",
                       params={"count": random.randint(2, 5)},
                       priority=0.45),
            ActionPlan("network", "open_profile",
                       params={},
                       priority=a_cfg.get("profile_open_from_network_probability", 0.25)),
            ActionPlan("network", "check_pending",
                       params={},
                       priority=0.15),
        ]

    def _profile_actions(self, a_cfg: dict) -> list[ActionPlan]:
        return [
            ActionPlan("profile", "scroll",
                       params={"count": random.randint(2, 5)},
                       priority=0.45),
            ActionPlan("profile", "connect",
                       params={},
                       priority=a_cfg.get("connect_probability", 0.50)),
            ActionPlan("profile", "view_activity",
                       params={},
                       priority=0.15),
        ]

    def current_page(self) -> str:
        return self._current_page

    @property
    def plan(self) -> list[ActionPlan]:
        return self._action_sequence
