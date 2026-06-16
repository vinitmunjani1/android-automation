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
