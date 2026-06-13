# LinkedIn Human-Like Automation

> Automates the LinkedIn Android app with human-mimicking behavior designed to evade LinkedIn's detection algorithms.

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

## Key Anti-Detection Features

| Signal | Evasion |
|--------|---------|
| Uniform timing | Gaussian jitter on every delay; 15% daily behavioral variation |
| Perfect touches | Micro-drift (1-4px), dwell (30-90ms), Bezier swipe curves |
| Predictable sequences | Markov-chain transitions; no two sessions follow same path |
| Session length | 3-5 burst sessions/day, 8-22 min each, 2-15 min gaps |
| Scroll patterns | Burst scrolling, mid-scroll reversal, scroll-back-up re-reading |
| Accidental touches | 4% mis-tap rate with correction behavior |
| Rate limits | Per-minute caps on likes (2), connects (1), total actions (8) |
| Content awareness | Different dwell times for text/image/video/carousel posts |
| Thumb-zone modeling | Different touch patterns for thumb-reachable vs two-hand zones |
| Back navigation | 45% edge-swipe gesture, 55% back button (mixed randomly) |
| Accessibility check | Detects enabled accessibility services (common bot vector) |

## Quick Start

```bash
cd linkedin-human-automation

# Install dependencies
pip install uiautomator2

# Connect Android device via USB + enable ADB
adb devices

# Preview today's schedule
python main.py --dry-run

# Run a single session now (10-20 min)
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
- **`anti_detection`**: Rate limits, stuck page detection, behavioral variation
- **`recovery`**: Session expiry, network errors, crash recovery
- **`profile_defaults`**: Your profile data for scoring comparison

## Prerequisites

1. Android device (physical preferred over emulator)
2. ADB installed and device connected
3. `uiautomator2` Python package
4. atx-agent running on device (`python -m uiautomator2 init`)
5. LinkedIn app installed and logged in
6. Accessibility services **disabled** (LinkedIn checks for third-party services)

## Detection Vectors Addressed

1. **Timing regularity** → Gaussian jitter + daily variation
2. **Touch patterns** → Drift, dwell, Bezier curves, accidental touches
3. **Action predictability** → Markov-chain transitions
4. **Session duration** → Burst model with random gaps
5. **Scroll velocity** → Variable speed with burst/reverse
6. **Navigation** → Mixed back-gesture + bottom-nav
7. **Activity hours** → Configurable window, bell-curve preference
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
