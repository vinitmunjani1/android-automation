"""Optional OpenRouter LLM scoring for read-only candidate summaries.

This is disabled by default. It sends only compact candidate evidence snippets to
OpenRouter when explicitly enabled and OPENROUTER_API_KEY is present.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-120b"


SYSTEM_PROMPT = """You score LinkedIn search candidates for manual review.
Return strict JSON only. Do not suggest automation, evasion, or sending messages.
Score fit from 0-100 based on the provided name/evidence/query/ICP.
Use conservative reasoning: if evidence is weak, score lower.
"""


def llm_scoring_enabled(config: dict) -> bool:
    llm_cfg = config.get("llm_scoring", {})
    return bool(llm_cfg.get("enabled", False))


def llm_scoring_diagnostics(config: dict) -> dict:
    llm_cfg = config.get("llm_scoring", {})
    env_name = llm_cfg.get("api_key_env", "OPENROUTER_API_KEY")
    return {
        "enabled": bool(llm_cfg.get("enabled", False)),
        "provider": llm_cfg.get("provider", "openrouter"),
        "model": llm_cfg.get("model", DEFAULT_MODEL),
        "api_key_env": env_name,
        "api_key_present": bool(os.environ.get(env_name, "").strip()),
        "max_candidates": int(llm_cfg.get("max_candidates", 15)),
    }


def _openrouter_key(config: dict) -> str:
    env_name = config.get("llm_scoring", {}).get("api_key_env", "OPENROUTER_API_KEY")
    return os.environ.get(env_name, "").strip()


def _candidate_payload(candidate: dict) -> dict:
    return {
        "name": candidate.get("name", ""),
        "keyword_score": candidate.get("score", 0),
        "mentions": candidate.get("mentions", 0),
        "matched_positive_keywords": candidate.get("matched_positive_keywords", []),
        "matched_negative_keywords": candidate.get("matched_negative_keywords", []),
        "evidence": str(candidate.get("evidence", ""))[:900],
    }


def _build_prompt(candidates: list[dict], config: dict, query: str = "") -> str:
    llm_cfg = config.get("llm_scoring", {})
    icp = llm_cfg.get("icp", "Founder/operator/decision-maker relevant to the search query")
    max_candidates = int(llm_cfg.get("max_candidates", 15))
    payload = {
        "query": query,
        "icp": icp,
        "instructions": {
            "score_range": "0-100",
            "recommendation_values": ["high_manual_review", "medium_manual_review", "low_priority", "skip"],
            "do_not": ["do not recommend automated connection", "do not draft/send messages"],
        },
        "candidates": [_candidate_payload(c) for c in candidates[:max_candidates]],
    }
    return json.dumps(payload, ensure_ascii=False)


def _parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.replace("json\n", "", 1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise


def score_candidates_with_openrouter(candidates: list[dict], config: dict, query: str = "") -> list[dict]:
    """Return candidates enriched with llm_score fields.

    Raises RuntimeError on missing key or API errors; caller should fallback to
    keyword scoring unless strict LLM mode is desired.
    """
    if not candidates:
        return []
    key = _openrouter_key(config)
    if not key:
        raise RuntimeError("OpenRouter API key missing; set OPENROUTER_API_KEY or llm_scoring.api_key_env")

    llm_cfg = config.get("llm_scoring", {})
    model = llm_cfg.get("model", DEFAULT_MODEL)
    timeout = float(llm_cfg.get("timeout_seconds", 45))
    temperature = float(llm_cfg.get("temperature", 0.1))

    user_prompt = _build_prompt(candidates, config, query=query)
    body = {
        "model": model,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    }

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": llm_cfg.get("site_url", "https://github.com/vinitmunjani1/android-automation"),
        "X-Title": llm_cfg.get("app_title", "android-automation-safe-search"),
    }
    req = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"OpenRouter HTTP {exc.code}: {details}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenRouter request failed: {exc}") from exc

    payload = json.loads(raw)
    content = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
    parsed = _parse_json_object(content)
    scored = parsed.get("candidates", [])
    by_name = {str(item.get("name", "")).lower(): item for item in scored if item.get("name")}

    enriched = []
    for candidate in candidates:
        item = dict(candidate)
        llm_item = by_name.get(str(candidate.get("name", "")).lower())
        if llm_item:
            item["llm_score"] = int(llm_item.get("score", candidate.get("score", 0)))
            item["llm_recommendation"] = llm_item.get("recommendation", "manual_review_only")
            item["llm_reason"] = str(llm_item.get("reason", ""))[:500]
        else:
            item["llm_score"] = None
            item["llm_recommendation"] = "not_scored"
            item["llm_reason"] = "Candidate not returned by LLM"
        enriched.append(item)

    return sorted(enriched, key=lambda item: (item.get("llm_score") is not None, item.get("llm_score") or 0, item.get("score", 0)), reverse=True)


def test_openrouter_scoring(config: dict) -> dict:
    """Small no-LinkedIn diagnostic call for OpenRouter setup."""
    test_candidates = [{
        "name": "Test Founder",
        "score": 50,
        "mentions": 1,
        "matched_positive_keywords": ["founder", "ai"],
        "matched_negative_keywords": [],
        "evidence": "Founder and CEO building AI workflow automation for B2B teams.",
    }]
    scored = score_candidates_with_openrouter(test_candidates, config, query="AI workflow founder")
    return {
        "diagnostics": llm_scoring_diagnostics(config),
        "result": scored[0] if scored else None,
    }
