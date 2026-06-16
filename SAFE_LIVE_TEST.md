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

Safe search summaries now include `ranked_candidates`, a read-only shortlist scored by `candidate_scoring` keywords. The recommendation remains `manual_review_only`; the tool does not connect/message/follow candidates.

## Optional OpenRouter LLM scoring

Keyword scoring is the default and stays local. To enable LLM scoring for read-only summaries:

```powershell
$env:OPENROUTER_API_KEY="your_openrouter_key"
```

Then set in `config.json`:

```json
"llm_scoring": {
  "enabled": true,
  "provider": "openrouter",
  "model": "openai/gpt-oss-120b",
  "api_key_env": "OPENROUTER_API_KEY"
}
```

Only compact candidate evidence snippets from the read-only snapshot summary are sent to OpenRouter. No actions are taken from LLM output; recommendations remain manual-review only.
