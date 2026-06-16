#!/usr/bin/env python3
"""LinkedIn Human-Like Automation — main orchestrator.

Usage:
    python main.py                  # Run all planned sessions for today
    python main.py --dry-run        # Show planned schedule without running
    python main.py --once           # Run a single session now
    python main.py --device <serial> # Connect to specific device
    python main.py --config path    # Use custom config file
"""
from __future__ import annotations

import argparse
import json
import random
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ─── Core modules ────────────────────────────────────────────────────────────
from logger import ActionLogger
from human_touch import HumanTouch
from detection_shields import DetectionShield
from session_manager import SessionManager
from action_engine import ActionEngine, ActionPlan
from safety import allow_full_automation, apply_safe_live_overrides, assert_no_risk_screen, is_read_only_live_test
from read_only_summary import write_summary
from safe_search import run_safe_search
from llm_scoring import test_openrouter_scoring
from env_loader import load_dotenv


def main():
    parser = argparse.ArgumentParser(description="LinkedIn Human-Like Automation")
    parser.add_argument("--dry-run", action="store_true", help="Show schedule without running")
    parser.add_argument("--once", action="store_true", help="Run a single session now")
    parser.add_argument("--safe-live-test", action="store_true", help="Run one short read-only LinkedIn live test (no likes/connects/messages)")
    parser.add_argument("--safe-search", default="", help="Run read-only LinkedIn search scan for this query")
    parser.add_argument("--safe-open-profiles", type=int, default=0, help="With --safe-search, explicitly open up to N profiles read-only for better ranking")
    parser.add_argument("--test-llm-scoring", action="store_true", help="Test OpenRouter LLM scoring setup without opening LinkedIn")
    parser.add_argument("--device", default=None, help="ADB device serial")
    parser.add_argument("--config", default="config.json", help="Config file path")
    args = parser.parse_args()

    # ─── Load config ────────────────────────────────────────────────────────
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Config not found: {config_path}")
        sys.exit(1)

    with open(config_path) as f:
        config = json.load(f)

    load_dotenv(config_path.parent / ".env")

    # Override device serial if provided
    if args.device:
        config["device"]["serial"] = args.device

    if args.test_llm_scoring:
        try:
            result = test_openrouter_scoring(config)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return
        except Exception as exc:
            print(f"LLM scoring test failed: {exc}")
            sys.exit(1)

    if args.safe_live_test or args.safe_search:
        args.once = True
        apply_safe_live_overrides(config)

    if not args.dry_run and not args.safe_live_test and not args.safe_search and not allow_full_automation(config):
        print("Refusing to run full automation: safety.allow_full_automation is false.")
        print("Use one of the read-only commands instead:")
        print("  python main.py --safe-live-test")
        print("  python main.py --safe-search \"founder AI India\"")
        print("If you intentionally accept the account risk, set safety.allow_full_automation=true in config.json.")
        sys.exit(2)

    # Dry-run should not connect to ADB/uiautomator. It only previews schedule.
    if args.dry_run:
        logger = ActionLogger(log_dir="logs")
        session_mgr = SessionManager(config, logger, lambda: None, lambda: None)
        schedule = session_mgr.plan_day_schedule()
        print(f"\n{'='*60}")
        print(f"LinkedIn Automation — Schedule for {datetime.now().strftime('%A, %B %d')}")
        print(f"{'='*60}")
        for s in schedule:
            start_str = s["start"].strftime("%H:%M")
            end_str = s["end"].strftime("%H:%M")
            print(f"  Session #{s['index']}: {start_str} — {end_str} "
                  f"({s['duration_min']:.0f}min)")
        print(f"\nTotal: {len(schedule)} sessions planned")
        if is_read_only_live_test(config):
            print("Safe live-test overrides: enabled (read-only, no account-changing actions)")
        if args.safe_search:
            print(f"Safe search query: {args.safe_search}")
        return

    # ─── Initialize ADB connection ──────────────────────────────────────────
    try:
        import uiautomator2 as u2
    except ImportError:
        print("ERROR: Install uiautomator2: pip install uiautomator2")
        sys.exit(1)

    # Ensure atx-agent is running
    serial = config["device"].get("serial")
    if serial:
        d = u2.connect(serial)
    else:
        d = u2.connect()  # First connected device

    # Verify connection
    try:
        info = d.info
        print(f"Connected: {info.get('deviceName', 'unknown')} "
              f"({info.get('currentPackageName', 'no app')})")
    except Exception as e:
        print(f"ERROR: Cannot connect to device: {e}")
        print("Make sure ADB is running and device is connected.")
        sys.exit(1)

    def adb_shell(cmd: str) -> str:
        return d.shell(cmd)

    # ─── Initialize components ──────────────────────────────────────────────
    logger = ActionLogger(log_dir="logs")
    touch = HumanTouch(adb_shell, config, logger)
    shield = DetectionShield(config, logger, adb_shell)

    # Page handlers
    from pages.home_feed import HomeFeedPage
    from pages.notifications import NotificationsPage
    from pages.messaging import MessagingPage
    from pages.profile import ProfilePage
    from pages.network import NetworkPage

    profile_page = ProfilePage(touch, shield, config, d, logger)
    feed_page = HomeFeedPage(touch, shield, config, d, logger)
    notifications_page = NotificationsPage(touch, shield, config, d, logger)
    messaging_page = MessagingPage(touch, shield, config, d, logger)
    network_page = NetworkPage(touch, shield, config, d, logger, profile_page)

    action_engine = ActionEngine(config)

    # ─── App lifecycle helpers ──────────────────────────────────────────────
    app_package = config.get("app_package", "com.linkedin.android")

    def open_app():
        """Open LinkedIn app."""
        logger.log("app", "open", "start")
        d.app_start(app_package)
        # Wait for app to be ready
        time.sleep(random.uniform(2.0, 4.0))

        # Check for session expiry
        if config.get("recovery", {}).get("session_expiry_detection", True):
            keyword = config["recovery"].get("session_expiry_keyword", "sign in")
            if d(text=keyword).exists:
                logger.log("app", "session_expired", "warn", "login required")
                # For now, just log — auto-login flow can be added later

        # Check for update screen
        if config.get("recovery", {}).get("update_screen_detection", True):
            update_btn = d(text="Update")
            if update_btn.exists:
                logger.log("app", "update_screen", "warn", "app update needed")

        if config.get("safety", {}).get("stop_on_risk_screen", True):
            assert_no_risk_screen(d, logger, context="open_app")

        logger.log("app", "open", "ok")

    def close_app():
        """Close/background LinkedIn app (simulates phone lock/home)."""
        logger.log("app", "close", "start")
        touch.home_button()  # Press home to background the app
        gap_min = config.get("session", {}).get("weekday", {}).get("gap_min_minutes", 3)
        gap_max = config.get("session", {}).get("weekday", {}).get("gap_max_minutes", 15)
        gap = random.uniform(gap_min, gap_max)
        logger.log("app", "close", "ok", f"gap={gap:.1f}min")

        # Toggle ADB between sessions (optional stealth)
        if not is_read_only_live_test(config):
            shield.toggle_adb()

    # ─── Session runner ─────────────────────────────────────────────────────
    def run_session(duration_minutes: float) -> dict:
        """Execute a single automation session."""
        shield.reset_session()
        session_stats = {
            "total_actions": 0,
            "likes": 0, "connects": 0, "comments": 0, "saves": 0,
            "profiles_viewed": 0, "notifications_checked": 0,
            "messages_checked": 0, "network_browsed": 0,
            "duration_minutes": 0,
        }

        # Generate action plan
        plan = [ActionPlan(page="feed", action="scroll")] if is_read_only_live_test(config) else action_engine.generate_session_plan()
        logger.log("session", "plan", "ok", f"actions={len(plan)}")

        # Check accessibility services
        shield.check_accessibility_services()

        start_time = time.monotonic()
        max_seconds = duration_minutes * 60

        # Execute actions
        for action in plan:
            elapsed = time.monotonic() - start_time
            if elapsed > max_seconds:
                logger.log("session", "time_limit", "info",
                           f"elapsed={elapsed:.0f}s > max={max_seconds:.0f}s")
                break

            page = action.page
            action_name = action.action

            if config.get("safety", {}).get("stop_on_risk_screen", True):
                assert_no_risk_screen(d, logger, context=f"before_{page}_{action_name}")

            # Wait if rate-limited
            wait = shield.wait_if_needed(action_name.replace("_post", "").replace("_", ""))
            if wait > 0:
                logger.log("shield", "rate_wait", "info", f"action={action_name},wait={wait:.0f}s")

            # Execute action
            stats = execute_action(action, feed_page, notifications_page,
                                    messaging_page, network_page, profile_page)
            session_stats["total_actions"] += 1

            # Merge stats
            for key, val in stats.items():
                if isinstance(val, bool) and val:
                    session_stats[key] = session_stats.get(key, 0) + 1
                elif isinstance(val, int):
                    session_stats[key] = session_stats.get(key, 0) + val

            # Action transition pause (page switch)
            if page != action_engine.current_page():
                time.sleep(random.uniform(0.1, 0.3))

        session_stats["duration_minutes"] = (time.monotonic() - start_time) / 60.0

        # Record in behavioral profile
        shield.behavioral_profile.record_session(logger.session_id, session_stats)

        logger.log("session", "stats", "summary", json.dumps(session_stats))
        return session_stats

    def execute_action(action: ActionPlan, feed_page, notifications_page,
                       messaging_page, network_page, profile_page) -> dict:
        """Execute a single action and return its stats."""
        page = action.page
        action_name = action.action

        if page == "feed":
            if action_name == "scroll":
                feed_page._touch.nav_to_tab("home")
                return feed_page.browse_feed(
                    max_duration_seconds=random.uniform(20, 60)
                )
            elif action_name == "like_post":
                feed_page._touch.nav_to_tab("home")
                # Scroll a bit then try to like
                feed_page._touch.scroll_down(2, log_label="like_prep")
                return feed_page.browse_feed(max_duration_seconds=15)
            elif action_name == "open_profile":
                feed_page._touch.nav_to_tab("home")
                return feed_page.browse_feed(max_duration_seconds=30)
            elif action_name == "view_post_detail":
                feed_page._touch.nav_to_tab("home")
                return feed_page.browse_feed(max_duration_seconds=20)
            elif action_name in ("save_post", "comment_post"):
                feed_page._touch.nav_to_tab("home")
                return feed_page.browse_feed(max_duration_seconds=20)

        elif page == "notifications":
            return notifications_page.check_notifications()

        elif page == "messaging":
            return messaging_page.check_messages()

        elif page == "network":
            return network_page.browse_network()

        elif page == "profile":
            return profile_page.view_profile()

        elif page == "idle":
            dur = action.params.get("duration", 2.0)
            time.sleep(dur)
            logger.log("idle", "pause", "ok", f"duration={dur:.1f}s")
            return {"idle_duration": dur}

        return {}

    # ─── Session manager setup ──────────────────────────────────────────────
    session_mgr = SessionManager(config, logger, open_app, close_app)

    # ─── Run ─────────────────────────────────────────────────────────────────
    if args.once:
        # Run a single session now
        if args.safe_search:
            print(f"\nRunning SAFE SEARCH now (read-only) for: {args.safe_search}")
        elif is_read_only_live_test(config):
            print("\nRunning SAFE LIVE TEST now (read-only: no likes/connects/comments/messages)...")
        else:
            print("\nRunning single session now...")
        open_app()
        if args.safe_search:
            stats = run_safe_search(d, touch, logger, config, args.safe_search, open_profiles=max(0, args.safe_open_profiles))
        else:
            stats = run_session(random.uniform(5, 8) if is_read_only_live_test(config) else random.uniform(10, 20))
        close_app()
        print(f"\nSession complete: {json.dumps(stats, indent=2)}")
        if is_read_only_live_test(config) and not args.safe_search:
            snapshot_file = logger.log_dir / f"session_{logger.session_id}_snapshots.jsonl"
            if snapshot_file.exists():
                summary_file = write_summary(snapshot_file, scoring_profile=config.get("candidate_scoring", {}), config=config)
                print(f"Read-only summary: {summary_file}")
        summary = logger.flush()
        print(f"Log: {logger.log_file}")
        return

    # Run all planned sessions
    print(f"\nStarting LinkedIn automation for {datetime.now().strftime('%A, %B %d')}")
    print(f"Active window: {config['session']['active_window']}")

    schedule = session_mgr.plan_day_schedule()
    print(f"Planned sessions: {len(schedule)}")

    all_stats = session_mgr.run_all(run_session)

    # Final summary
    print(f"\n{'='*60}")
    print(f"Automation complete: {len(all_stats)} sessions executed")
    total_actions = sum(s.get("total_actions", 0) for s in all_stats)
    total_likes = sum(s.get("likes", 0) for s in all_stats)
    total_connects = sum(s.get("connects", 0) for s in all_stats)
    total_duration = sum(s.get("duration_minutes", 0) for s in all_stats)
    print(f"  Total actions: {total_actions}")
    print(f"  Likes: {total_likes}")
    print(f"  Connects: {total_connects}")
    print(f"  Duration: {total_duration:.1f} minutes")
    print(f"{'='*60}")

    summary = logger.flush()
    print(f"Session log: {logger.log_file}")
    print(f"Summary: {logger.log_dir / f'session_{logger.session_id}_summary.json'}")

    # Shield summary
    shield_summary = shield.summary()
    print(f"Detection shield: {json.dumps(shield_summary, indent=2)}")


if __name__ == "__main__":
    main()
