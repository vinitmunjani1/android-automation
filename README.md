# LinkedIn Android Automation

> Controls the LinkedIn Android app through ADB/uiautomator2. This carries account risk. The safest supported live path is read-only `--safe-live-test`; this project does not hide emulator, ADB, uiautomator, USB debugging, Play Integrity, or LinkedIn telemetry signals.

## Architecture

```
linkedin-human-automation/
├── main.py                    # Orchestrator entry point
├── config.json                # All behavior parameters (tuning hub)
├── logger.py                  # Structured JSON action logging
├── human_touch.py             # Touch/swipe simulation (anti-detection core)
├── detection_shields.py       # Rate limiting + behavioral profile + anti-detection
├── session_manager.py         # Burst session scheduling (weekday/weekend)
├── action_engine.py           # Markov-chain action sequence generator
├── pages/
│   ├── home_feed.py           # Feed browsing with content-type awareness
│   ├── profile.py             # Profile viewing with scoring + connect logic
│   ├── notifications.py       # Notifications scanning
│   ├── messaging.py           # Messaging inbox with conversation reading
│   └── network.py             # My Network browsing + pending requests
└── logs/                      # Session logs (JSONL + summaries)
```

## Account-Risk Safety Features

| Risk | Safety behavior |
|------|-----------------|
| First live run | `--safe-live-test` is read-only |
| Accidental engagement | likes/comments/saves/connects/messages are config-gated |
| Old full-auto defaults | account-changing actions default to blocked in `safety` config |
| Checkpoint / verification | run stops on suspicious-login, checkpoint, captcha, sign-in, or restriction text |
| Dry-run surprise | `--dry-run` no longer connects to ADB/uiautomator |
| Auditability | actions and blocked actions are logged |

This does **not** bypass platform detection. It only reduces account-changing behavior risk.

## Quick Start

```bash
cd linkedin-human-automation

# Install dependencies
pip install uiautomator2

# Connect Android device via USB + enable ADB
adb devices

# Preview today's schedule without connecting to the phone
python main.py --dry-run

# First real-device test: read-only, no likes/connects/comments/messages
python main.py --safe-live-test

# Run a single session now (account-changing actions remain safety-gated by config)
python main.py --once

# Run all planned sessions for today
python main.py

# Use specific device
python main.py --device emulator-5554
```

## Configuration

All behavior is tuned via `config.json`. Key sections:

- **`session`**: Active window, session counts, durations, gaps (weekday vs weekend)
- **`actions`**: Probabilities for like/save/comment/connect, per-session and per-minute limits
- **`touch`**: Tap drift, dwell, swipe curves, accidental touches, back gesture ratio
- **`dwell`**: Reading time ranges per content type (text/image/video/carousel/article)
- **`scroll`**: Swipe counts, burst probability, reverse probability
- **`scoring`**: Profile scoring factors for connect decision (mutual connections, industry, role)
- **`safety`**: Read-only live test, action gates, checkpoint/risk-screen stop rules
- **`anti_detection`**: Legacy timing/rate-limit/stuck-page settings; not a detection bypass
- **`recovery`**: Session expiry, network errors, crash recovery
- **`profile_defaults`**: Your profile data for scoring comparison

## Prerequisites

1. Android device (physical preferred over emulator)
2. ADB installed and device connected
3. `uiautomator2` Python package
4. atx-agent running on device (`python -m uiautomator2 init`)
5. LinkedIn app installed and logged in
6. Accessibility services **disabled** (LinkedIn checks for third-party services)

## Detection / Platform Signals

This project does not hide or bypass emulator, ADB, uiautomator, USB debugging, Play Integrity/SafetyNet, device reputation, network reputation, or LinkedIn telemetry signals.

Use a physical phone and start with `--safe-live-test`. Keep account-changing actions manual-approved or disabled unless you explicitly accept the risk.
8. **Interaction ratios** → Configurable probabilities with rate limits
9. **Content awareness** → Different behavior per content type
10. **Device fingerprint** → Accessibility service check, ADB toggle option

## Planned Enhancements

- [ ] Comment drafting with LLM
- [ ] Post publishing automation
- [ ] Search page actions
- [ ] Jobs page browsing
- [ ] Auto-login on session expiry
- [ ] Screenshot logging for debugging
- [ ] Behavioral profile learning from history
