"""The decision engine — build the prompt, call Gemini, return proposals.

This module never submits an order. It returns proposals; Task E's validator
and executor decide what actually reaches the broker.

Two hard rules from TASK-D / ADR 0003:
- The model name is pinned in ``config/rules.json`` and there is **no fallback**.
  A different model is a different strategy; a silent swap is unacceptable.
- A malformed or schema-invalid response is retried **once**. If the retry also
  fails, raise ``AIError``. Never repair, guess at, or partially parse output.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import requests

from .config import load_rules

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parents[2] / "config" / "prompt.md"

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

# Network retry — same shape as alpaca.py (house style).
_MAX_RETRIES = 3
_BACKOFF_BASE = 0.5
_REQUEST_TIMEOUT = 60  # the model call is slow; give it room but never hang

_VALID_ACTIONS = {"BUY", "SELL", "TRIM", "HOLD"}
_DECISION_FIELDS = (
    "ticker", "action", "target_weight", "thesis", "risks", "reason_for_action",
)

# Structured-output schema. Verified working against this key: it returned
# target_weight as a float on the first attempt.
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "commentary": {"type": "string"},
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "action": {
                        "type": "string",
                        "enum": ["BUY", "SELL", "TRIM", "HOLD"],
                    },
                    "target_weight": {"type": "number"},
                    "thesis": {"type": "string"},
                    "risks": {"type": "string"},
                    "reason_for_action": {"type": "string"},
                },
                "required": list(_DECISION_FIELDS),
            },
        },
        "considered": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "verdict": {"type": "string"},
                },
                "required": ["ticker", "verdict"],
            },
        },
    },
    "required": ["commentary", "decisions", "considered"],
}


class AIError(RuntimeError):
    """Raised when the AI output is unusable after one retry, or the call fails."""


class _Malformed(Exception):
    """Internal: an unusable response body. Triggers the single retry."""


# --- prompt rendering ----------------------------------------------------

def _render_rules(rules: dict) -> str:
    """Flatten rules.json to text so the prompt never restates a number by hand.

    Whatever is in the file is what the AI sees, which is the same thing the
    validator enforces.
    """
    lines: list[str] = []

    def walk(prefix: str, obj: object) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if not prefix and (key == "schema_version" or key.startswith("_")):
                    continue
                walk(f"{prefix}.{key}" if prefix else key, value)
        elif isinstance(obj, list):
            lines.append(f"- {prefix}: {', '.join(str(item) for item in obj)}")
        else:
            lines.append(f"- {prefix}: {obj}")

    walk("", rules)
    return "\n".join(lines)


def _render_positions(state: dict, held_theses: dict[str, str]) -> str:
    positions = state.get("positions", [])
    if not positions:
        return "None — the portfolio is entirely in cash."
    lines = []
    for p in positions:
        thesis = held_theses.get(p["ticker"], "(no recorded thesis on file)")
        lines.append(
            f"- {p['ticker']}: weight {p.get('weight')}, "
            f"unrealised P&L {p.get('unrealized_pl')} "
            f"({p.get('unrealized_pl_pct')}). Original thesis: {thesis}"
        )
    return "\n".join(lines)


def _render_pending_orders(state: dict) -> str:
    orders = state.get("pending_orders", [])
    if not orders:
        return "None."
    lines = []
    for o in orders:
        size = (
            f"notional {o['notional']}" if o.get("notional") is not None
            else f"qty {o.get('qty')}"
        )
        lines.append(
            f"- {o.get('side', '?').upper()} {o['symbol']} {size} "
            f"(status {o.get('status')})"
        )
    return "\n".join(lines)


def render_prompt(
    state: dict, rules: dict, candidates: list[str], held_theses: dict[str, str]
) -> str:
    """Fill the config/prompt.md template. No placeholder may survive."""
    template = PROMPT_PATH.read_text(encoding="utf-8")
    totals = state.get("totals", {})
    replacements = {
        "{RULES}": _render_rules(rules),
        "{TOTAL_VALUE}": str(totals.get("total_value")),
        "{AVAILABLE_CASH}": str(totals.get("available_cash")),
        "{CASH_WEIGHT}": str(totals.get("cash_weight")),
        "{POSITIONS}": _render_positions(state, held_theses),
        "{PENDING_ORDERS}": _render_pending_orders(state),
        "{CANDIDATES}": ", ".join(candidates) if candidates else "None.",
    }
    rendered = template
    for token, value in replacements.items():
        rendered = rendered.replace(token, value)
    if "{" in rendered or "}" in rendered:
        raise AIError(f"prompt template still has an unfilled placeholder: {rendered!r}")
    return rendered


# --- Gemini call -------------------------------------------------------

def _ensure_env() -> None:
    if os.environ.get("GEMINI_API_KEY"):
        return
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _post_with_retry(url: str, body: dict, api_key: str) -> dict:
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        if attempt:
            time.sleep(_BACKOFF_BASE * (2 ** (attempt - 1)))
        try:
            resp = requests.post(
                url, json=body,
                headers={"x-goog-api-key": api_key},
                timeout=_REQUEST_TIMEOUT,
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            continue
        if 500 <= resp.status_code < 600:
            last_exc = AIError(f"Gemini {resp.status_code}: {resp.text[:200]}")
            continue
        if 400 <= resp.status_code < 500:
            # A 404 on the pinned model included — we do NOT fall back.
            raise AIError(
                f"Gemini {resp.status_code} (not retryable): {resp.text[:200]}"
            )
        resp.raise_for_status()
        return resp.json()
    raise AIError(f"Gemini unreachable after {_MAX_RETRIES} retries: {last_exc}")


def _call_gemini(prompt: str, model: str, api_key: str) -> str:
    """One full request/response. Returns the raw JSON text the model produced."""
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": RESPONSE_SCHEMA,
        },
    }
    data = _post_with_retry(GEMINI_URL.format(model=model), body, api_key)

    usage = data.get("usageMetadata", {})
    logger.info(
        "Gemini usage — prompt=%s output=%s total=%s tokens",
        usage.get("promptTokenCount"),
        usage.get("candidatesTokenCount"),
        usage.get("totalTokenCount"),
    )

    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise _Malformed(f"no text part in Gemini response: {exc}")


def _parse(text: str) -> dict:
    """Strict shape validation. Any deviation raises _Malformed — no repair."""
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _Malformed(f"response is not valid JSON: {exc}")
    if not isinstance(obj, dict):
        raise _Malformed("top-level value is not an object")
    for key in ("commentary", "decisions", "considered"):
        if key not in obj:
            raise _Malformed(f"missing top-level key: {key}")
    if not isinstance(obj["commentary"], str):
        raise _Malformed("commentary is not a string")
    if not isinstance(obj["decisions"], list):
        raise _Malformed("decisions is not a list")
    if not isinstance(obj["considered"], list):
        raise _Malformed("considered is not a list")

    decisions = []
    for entry in obj["decisions"]:
        if not isinstance(entry, dict):
            raise _Malformed("a decision entry is not an object")
        missing = [f for f in _DECISION_FIELDS if f not in entry]
        if missing:
            raise _Malformed(f"decision missing fields: {missing}")
        if entry["action"] not in _VALID_ACTIONS:
            raise _Malformed(f"invalid action: {entry['action']!r}")
        weight = entry["target_weight"]
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise _Malformed(f"target_weight is not a number: {weight!r}")
        decisions.append({
            "ticker": entry["ticker"],
            "action": entry["action"],
            "target_weight": float(weight),
            "thesis": entry["thesis"],
            "risks": entry["risks"],
            "reason_for_action": entry["reason_for_action"],
        })

    considered = []
    for entry in obj["considered"]:
        if not isinstance(entry, dict) or "ticker" not in entry or "verdict" not in entry:
            raise _Malformed("a considered entry is malformed")
        considered.append({"ticker": entry["ticker"], "verdict": entry["verdict"]})

    return {"commentary": obj["commentary"], "decisions": decisions, "considered": considered}


def propose(
    state: dict, rules: dict, candidates: list[str], held_theses: dict[str, str]
) -> dict:
    """Return {"commentary", "decisions", "considered"} or raise AIError.

    Retries exactly once on unusable output. Network failures are retried
    inside the call itself (house style) and surface as AIError.
    """
    _ensure_env()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise AIError("GEMINI_API_KEY is not set (expected in .env or the environment)")

    model = rules["ai"]["model"]
    prompt = render_prompt(state, rules, candidates, held_theses)

    last_error: Exception | None = None
    for attempt in (1, 2):
        text = _call_gemini(prompt, model, api_key)
        try:
            return _parse(text)
        except _Malformed as exc:
            last_error = exc
            logger.warning(
                "Gemini attempt %d produced unusable output: %s", attempt, exc
            )
    raise AIError(f"Gemini output unusable after one retry: {last_error}")
