# Safe Live Test Mode

This repo controls the real LinkedIn Android app through ADB/uiautomator2. That still carries account risk, even on a physical phone with USB debugging enabled.

Safe live-test mode is designed to reduce account risk, not to hide automation signals.

## What it does

```bash
python main.py --safe-live-test
```

Equivalent behavior:

- opens LinkedIn
- navigates to Home/feed
- reads/dwells briefly
- scrolls lightly
- logs the run
- stops on checkpoint / verification / unusual-activity screens

## What it blocks

- likes
- comments
- saves
- connect/follow
- pending request accept
- opening messages
- tapping notifications
- opening post details
- opening profiles

## Notes

- `--dry-run` now only prints schedule/config preview and does not connect to the phone.
- Safe mode does not hide emulator, ADB, uiautomator, USB debugging, Play Integrity, or LinkedIn telemetry signals.
- First live test should use a physical phone, already logged in, with no scheduled/full-auto run enabled.

## Safe search mode

```bash
python main.py --safe-search "founder AI India"
```

Safe search mode:

- opens LinkedIn
- opens search
- enters the query
- tries the People filter if visible
- scrolls results read-only
- saves snapshots and a read-only summary
- does not like, comment, connect, follow, message, or accept requests

Outputs:

```text
logs/session_<id>.jsonl
logs/session_<id>_snapshots.jsonl
logs/session_<id>_read_only_summary.json
```

Safe search uses configurable randomized UI pacing waits under `safe_search.waits` and gradual typing under `safe_search.typing`. These are for reliability/readability, not detection bypass.
