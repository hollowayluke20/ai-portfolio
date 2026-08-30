import importlib.util
from pathlib import Path
import sys


SPEC = importlib.util.spec_from_file_location("audit_fundamentals", Path(__file__).parents[1] / "scripts" / "audit_fundamentals.py")
audit_fundamentals = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = audit_fundamentals
SPEC.loader.exec_module(audit_fundamentals)


def _flow(value, start="2025-01-01", end="2025-03-31"):
    return {"start": start, "end": end, "filed": "2025-05-01", "val": value}


def _document():
    quarters = [_flow(10, "2024-01-01", "2024-03-31"), _flow(10, "2024-04-01", "2024-06-30"), _flow(10, "2024-07-01", "2024-09-30"), _flow(10, "2024-10-01", "2024-12-31")]
    measures = {name: {"points": quarters if spec["kind"] == "flow" else [{"end": "2024-12-31", "filed": "2025-05-01", "val": 100}]} for name, spec in audit_fundamentals.MEASURES.items()}
    return {"generated_at": "2025-06-01T00:00:00Z", "tickers": {"GOOD": {"cik": "1", "measures": measures}, "ETF": {"cik": None, "measures": {}}}}


def test_audit_flags_low_coverage_and_accounting_identities():
    document = _document()
    document["tickers"]["GOOD"]["measures"]["GrossProfit"]["points"] = [_flow(11)] * 4
    document["tickers"]["GOOD"]["measures"]["AssetsCurrent"]["points"] = [{"end": "2024-12-31", "filed": "2025-05-01", "val": 101}]
    document["tickers"]["GOOD"]["measures"]["Revenues"]["points"] = []
    result = audit_fundamentals.audit_document(document)
    assert result.failed
    assert result.coverage["Revenues"] == 0
    assert any("current assets" in violation for violation in result.identity_violations)


def test_audit_reports_sanity_ranges_and_crosscheck_pe():
    document = _document()
    document["tickers"]["GOOD"]["measures"]["NetIncomeLoss"]["points"] = [
        _flow(20, "2024-01-01", "2024-03-31"), _flow(20, "2024-04-01", "2024-06-30"),
        _flow(20, "2024-07-01", "2024-09-30"), _flow(20, "2024-10-01", "2024-12-31"),
    ]
    result = audit_fundamentals.audit_document(document, prices={"GOOD": 10000})
    assert result.margin_outliers == ["GOOD: profit margin 200.0%"]
    assert result.pe_outliers == ["GOOD: P/E 250.00"]
    rows = audit_fundamentals.crosscheck_rows({"tickers": {"AAPL": document["tickers"]["GOOD"]}}, {"AAPL": 400}, "2025-06-01")
    assert rows[0] == ("AAPL", 40.0, 40.0, 10.0)


def test_parse_prices_rejects_ambiguous_input():
    assert audit_fundamentals._parse_prices(["aapl=100"]) == {"AAPL": 100.0}
    try:
        audit_fundamentals._parse_prices(["AAPL"])
    except ValueError:
        pass
    else:
        raise AssertionError("invalid price must be rejected")
