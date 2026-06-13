"""Session manager — schedules and manages open/close cycles of the LinkedIn app.

Implements the burst model:
- 3-5 sessions per weekday, 1-3 per weekend
- Each session: 8-25 min of activity
- Gaps between sessions: 2-15 min (app backgrounded)
- All within a configurable active window (e.g., 09:00-21:00)
"""
from __future__ import annotations

import random
import time
from datetime import datetime, timedelta, timezone
from typing import Callable


def _parse_hhmm(value: str, base: datetime) -> datetime:
    hour, minute = map(int, value.split(":"))
    return base.replace(hour=hour, minute=minute, second=0, microsecond=0)


class SessionManager:
    """Manages LinkedIn app session scheduling and lifecycle."""

    def __init__(self, config: dict, logger, open_app: Callable, close_app: Callable) -> None:
        """
        Args:
            config: Full config dict
            logger: ActionLogger instance
            open_app: Callable that opens the LinkedIn app
            close_app: Callable that closes/backgrounds the LinkedIn app
        """
        self._cfg = config.get("session", {})
        self._logger = logger
        self._open_app = open_app
        self._close_app = close_app

        self._active_window = self._cfg.get("active_window", {"start": "09:00", "end": "21:00"})
        self._weekday_cfg = self._cfg.get("weekday", {})
        self._weekend_cfg = self._cfg.get("weekend", {})

        self._sessions_today: list[dict] = []
        self._current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._is_running = False

    def plan_day_schedule(self) -> list[dict]:
        """Plan all sessions for today. Returns list of {start, end, duration_min}.

        Should be called once at day start or when first invoked.
        """
        now = datetime.now(timezone.utc)

        # Detect new day
        today = now.strftime("%Y-%m-%d")
        if today != self._current_date:
            self._current_date = today
            self._sessions_today = []

        if self._sessions_today:
            return self._sessions_today

        # Determine weekday vs weekend
        is_weekend = now.weekday() >= 5  # 5=Sat, 6=Sun
        cfg = self._weekend_cfg if is_weekend else self._weekday_cfg

        # Parse active window
        start_dt = _parse_hhmm(self._active_window["start"], now)
        end_dt = _parse_hhmm(self._active_window["end"], now)
        if end_dt <= start_dt:
            end_dt += timedelta(days=1)

        # If current time is past the window, schedule for next day
        if now > end_dt:
            start_dt += timedelta(days=1)
            end_dt += timedelta(days=1)

        # Clamp start to now if we're within the window
        effective_start = max(now, start_dt)

        if effective_start > end_dt:
            self._logger.log("schedule", "no_window", "info",
                             f"current_time={now.isoformat()},window={self._active_window}")
            return []

        # Number of sessions today
        min_sessions = cfg.get("min_sessions_per_day", 3)
        max_sessions = cfg.get("max_sessions_per_day", 5)
        num_sessions = random.randint(min_sessions, max_sessions)

        # Available time in minutes
        available_minutes = (end_dt - effective_start).total_seconds() / 60

        # Session and gap parameters
        sess_min = cfg.get("session_min_minutes", 8)
        sess_max = cfg.get("session_max_minutes", 22)
        gap_min = cfg.get("gap_min_minutes", 3)
        gap_max = cfg.get("gap_max_minutes", 15)

        # Check if we have enough time
        min_total = num_sessions * sess_min + (num_sessions - 1) * gap_min
        if min_total > available_minutes:
            # Reduce number of sessions
            num_sessions = max(1, int(available_minutes / (sess_min + gap_min)))
            min_total = num_sessions * sess_min + (num_sessions - 1) * gap_min

        if num_sessions < 1:
            return []

        # Allocate time to sessions and gaps
        remaining = available_minutes - min_total
        # Distribute extra time proportionally
        extra_per_session = remaining / num_sessions if num_sessions > 0 else 0
        extra_per_gap = remaining / max(1, num_sessions - 1) if num_sessions > 1 else 0

        sessions = []
        current_time = effective_start

        for i in range(num_sessions):
            duration = sess_min + random.uniform(0, extra_per_session + (sess_max - sess_min))
            duration = min(duration, sess_max)

            session_start = current_time
            session_end = session_start + timedelta(minutes=duration)

            # Don't exceed window
            if session_end > end_dt:
                session_end = end_dt
                duration = (session_end - session_start).total_seconds() / 60

            sessions.append({
                "index": i,
                "start": session_start,
                "end": session_end,
                "duration_min": duration,
            })

            # Gap to next session
            if i < num_sessions - 1:
                gap = gap_min + random.uniform(0, extra_per_gap + (gap_max - gap_min))
                gap = min(gap, gap_max)
                current_time = session_end + timedelta(minutes=gap)
            else:
                current_time = session_end

        self._sessions_today = sessions
        self._logger.log("schedule", "day_planned", "ok",
                         f"num_sessions={num_sessions},is_weekend={is_weekend},window={self._active_window}")
        return sessions

    def next_session(self) -> dict | None:
        """Get the next session to run. Returns None if all done or no sessions planned."""
        self.plan_day_schedule()

        now = datetime.now(timezone.utc)

        for session in self._sessions_today:
            if session["start"] > now - timedelta(seconds=1):
                # Not yet started (with 1s tolerance)
                return session

        # Check if we should create an ad-hoc session (human sometimes opens app unplanned)
        if random.random() < 0.15 and len(self._sessions_today) < 6:
            ad_hoc = self._create_ad_hoc_session(now)
            if ad_hoc:
                self._sessions_today.append(ad_hoc)
                self._sessions_today.sort(key=lambda s: s["start"])
                return ad_hoc

        return None

    def _create_ad_hoc_session(self, now: datetime) -> dict | None:
        """Create an unplanned session (occasional extra app open)."""
        is_weekend = now.weekday() >= 5
        cfg = self._weekend_cfg if is_weekend else self._weekday_cfg

        start_dt = _parse_hhmm(self._active_window["start"], now)
        end_dt = _parse_hhmm(self._active_window["end"], now)
        if end_dt <= start_dt:
            end_dt += timedelta(days=1)

        if start_dt <= now <= end_dt:
            duration = random.uniform(cfg.get("session_min_minutes", 5),
                                      cfg.get("session_max_minutes", 15))
            session_end = now + timedelta(minutes=duration)
            if session_end > end_dt:
                session_end = end_dt
                duration = (session_end - now).total_seconds() / 60

            return {
                "index": len(self._sessions_today),
                "start": now,
                "end": session_end,
                "duration_min": duration,
            }
        return None

    def run_session(self, session: dict, session_runner: Callable) -> dict:
        """Execute a single session: open app, run actions, close app.

        Args:
            session: Session plan dict from plan_day_schedule()
            session_runner: Callable(session_duration_minutes) -> session_stats dict

        Returns session stats dict.
        """
        now = datetime.now(timezone.utc)
        session_start = session["start"]

        # Wait until session start time
        wait_seconds = (session_start - now).total_seconds()
        if wait_seconds > 0:
            self._logger.log("session", f"#{session['index']}", "waiting",
                             f"wait={wait_seconds:.0f}s, starts={session_start.isoformat()}")
            # Sleep in chunks for responsiveness
            while wait_seconds > 0:
                sleep_time = min(wait_seconds, 60)
                time.sleep(sleep_time)
                wait_seconds = (session_start - datetime.now(timezone.utc)).total_seconds()

        self._logger.log("session", f"#{session['index']}", "starting",
                         f"duration={session['duration_min']:.1f}min")
        self._is_running = True

        # Open app
        self._open_app()

        try:
            # Run session actions
            stats = session_runner(session["duration_min"])

            # Log session completion
            self._logger.log("session", f"#{session['index']}", "completed",
                             f"stats={stats}")
            return stats
        except Exception as e:
            self._logger.log("session", f"#{session['index']}", "error", str(e))
            raise
        finally:
            # Close app (background it — don't kill)
            self._close_app()
            self._is_running = False

    def run_all(self, session_runner: Callable) -> list[dict]:
        """Run all planned sessions for today.

        Args:
            session_runner: Callable(session_duration_minutes) -> session_stats dict

        Returns list of session stats.
        """
        all_stats = []
        while True:
            session = self.next_session()
            if session is None:
                break

            stats = self.run_session(session, session_runner)
            all_stats.append(stats)

            # Gap between sessions: app is backgrounded, wait for next session start
            self._logger.log("scheduler", "gap", "info",
                             f"waiting for next session")

        return all_stats

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def sessions_completed(self) -> int:
        return len([s for s in self._sessions_today if s.get("completed", False)])
