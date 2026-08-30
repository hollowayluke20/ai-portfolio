"""Tests for the decision engine. No live API calls."""

import json

import pytest

from src.portfolio import ai
from src.portfolio.config import load_rules

# A recorded schema-valid Gemini response body (the text of parts[0].text).
RECORDED_RESPONSE = json.dumps({
    "commentary": "Portfolio is close to target weights. Adding IEF for "
                  "duration; trimming nothing this week.",
    "decisions": [
        {
            "ticker": "IEF",
            "action": "BUY",
            "target_weight": 0.063,
            "thesis": "Intermediate Treasuries diversify the all-equity book; "
                      "overlaps only loosely with existing rate-sensitive names.",
            "risks": "A renewed inflation surprise would hurt duration.",
            "reason_for_action": "Cash weight is above target and no bond "
                                 "exposure exists yet.",
            "basis": "allocation",
        },
        {
            "ticker": "MSFT",
            "action": "HOLD",
            "target_weight": 0.063,
            "thesis": "Durable enterprise franchise with AI optionality.",
            "risks": "Multiple compression if AI capex disappoints.",
            "reason_for_action": "Thesis intact; no action needed.",
            "basis": "thesis_change",
        },
    ],
    "considered": [
        {"ticker": "GLD", "verdict": "Passed — no catalyst versus bonds this week."},
        {"ticker": "QQQ", "verdict": "Passed — would push broad-US-equity cap."},
    ],
})

STATE = {
    "totals": {
        "total_value": 101166.61,
        "available_cash": 5024.11,
        "cash_weight": 0.0497,
    },
    "positions": [
        {
            "ticker": "MSFT", "weight": 0.0643, "unrealized_pl": 83.35,
            "unrealized_pl_pct": 0.013,
        },
    ],
    "pending_orders": [
        {
            "symbol": "NVDA", "side": "buy", "notional": 6300.0, "qty": None,
            "status": "accepted",
        },
    ],
}
HELD_THESES = {"MSFT": "Durable enterprise franchise with AI optionality."}
RULES = load_rules()
CANDIDATES = ["SPY", "IEF", "GLD", "MSFT"]


# --- prompt rendering --------------------------------------------------

def test_prompt_renders_with_no_placeholder_left():
    prompt = ai.render_prompt(STATE, RULES, CANDIDATES, HELD_THESES)
    assert "{" not in prompt and "}" not in prompt
    assert "portfolio manager" in prompt.lower()
    # live data made it in
    assert "101166.61" in prompt
    assert "5024.11" in prompt
    assert "IEF" in prompt
    # the held position's original thesis is shown
    assert HELD_THESES["MSFT"] in prompt
    # pending order is disclosed
    assert "NVDA" in prompt


def test_prompt_with_market_data_has_price_and_company_name():
    from src.portfolio.marketdata import TickerFeatures
    feature = TickerFeatures("IEF", 95.5, .01, .1, -.02, .15, True, 253)
    prompt = ai.render_prompt(STATE, RULES, ["IEF"], HELD_THESES,
                              {"IEF": feature}, {"IEF": {"name": "Treasury Fund", "sector": "Bond"}}, .5)
    assert "$95.50" in prompt
    assert "Treasury Fund" in prompt


def test_propose_sends_market_prompt_and_honours_pre_rendered_prompt(monkeypatch):
    from src.portfolio.marketdata import TickerFeatures
    captured = []
    response = json.dumps({"commentary": "x", "decisions": [], "considered": []})
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(ai, "_call_gemini", lambda prompt, *_: captured.append(prompt) or response)
    feature = TickerFeatures("IEF", 95.5, .01, .1, -.02, .15, True, 253)
    ai.propose(STATE, RULES, ["IEF"], HELD_THESES, {"IEF": feature},
               {"IEF": {"name": "Treasury Fund", "sector": "Bond"}}, .5)
    assert "$95.50" in captured[-1] and "Treasury Fund" in captured[-1]
    ai.propose(STATE, RULES, ["IEF"], HELD_THESES, prompt="THE EXACT PROMPT")
    assert captured[-1] == "THE EXACT PROMPT"


def test_rules_block_matches_rules_json_exactly():
    block = ai._render_rules(RULES)
    # every leaf value from rules.json appears in the rendered block
    assert "position_count.target: 15" in block
    assert "position_weight.hard_cap: 0.1" in block
    assert "cash.floor: 0.05" in block
    assert "sell_triggers.stop_loss_pct: -0.2" in block
    assert "ai.model: gemini-3.6-flash" in block
    assert "broad_us_equity_cap.limit: 0.4" in block
    assert "SPY, VOO, QQQ" in block
    # nothing restated by hand: the block is exactly the flattened file
    assert block in ai.render_prompt(STATE, RULES, CANDIDATES, HELD_THESES)
    # schema_version and comments are excluded
    assert "schema_version" not in block
    assert "_comment" not in block


# --- propose(): parsing and retry ------------------------------------

def test_schema_valid_response_parses_into_interface_shape(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(ai, "_call_gemini", lambda *a, **k: RECORDED_RESPONSE)

    out = ai.propose(STATE, RULES, CANDIDATES, HELD_THESES)

    assert set(out) == {"commentary", "review", "decisions", "considered"}
    assert isinstance(out["commentary"], str)
    first = out["decisions"][0]
    assert first["ticker"] == "IEF"
    assert first["action"] == "BUY"
    assert isinstance(first["target_weight"], float)
    assert first["target_weight"] == 0.063
    assert set(first) == {
        "ticker", "action", "target_weight", "thesis", "risks", "reason_for_action", "basis",
    }
    assert out["considered"][0] == {
        "ticker": "GLD",
        "verdict": "Passed — no catalyst versus bonds this week.",
    }


def test_malformed_response_retries_once_then_raises(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    calls = {"n": 0}

    def bad(*_a, **_k):
        calls["n"] += 1
        return "{not valid json"

    monkeypatch.setattr(ai, "_call_gemini", bad)

    with pytest.raises(ai.AIError):
        ai.propose(STATE, RULES, CANDIDATES, HELD_THESES)
    assert calls["n"] == 2  # first attempt + exactly one retry


def test_schema_invalid_response_also_retries_once(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    calls = {"n": 0}
    # valid JSON, but a decision is missing required fields and action is bad
    payload = json.dumps({
        "commentary": "x",
        "decisions": [{"ticker": "MSFT", "action": "ACCUMULATE"}],
        "considered": [],
    })

    def invalid(*_a, **_k):
        calls["n"] += 1
        return payload

    monkeypatch.setattr(ai, "_call_gemini", invalid)

    with pytest.raises(ai.AIError):
        ai.propose(STATE, RULES, CANDIDATES, HELD_THESES)
    assert calls["n"] == 2


def test_second_attempt_can_succeed(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    seq = ["garbage", RECORDED_RESPONSE]

    monkeypatch.setattr(ai, "_call_gemini", lambda *a, **k: seq.pop(0))
    out = ai.propose(STATE, RULES, CANDIDATES, HELD_THESES)
    assert out["decisions"][0]["ticker"] == "IEF"


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(ai, "_ensure_env", lambda: None)
    with pytest.raises(ai.AIError):
        ai.propose(STATE, RULES, CANDIDATES, HELD_THESES)


def test_model_name_comes_from_rules_not_hardcoded():
    assert RULES["ai"]["model"] == "gemini-3.6-flash"
    # not hardcoded anywhere in the module
    import inspect
    src = inspect.getsource(ai)
    assert "gemini-3.6-flash" not in src
    assert "gemini-2.5" not in src  # no fallback model mentioned
