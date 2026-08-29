#!/usr/bin/env python3
"""Send the weekly portfolio report; dry-run is the safe default."""

from __future__ import annotations

import argparse
import json
import os
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.portfolio.report import build_report  # noqa: E402


REPO = Path(__file__).resolve().parents[1]


def _read(path, default=None):
    try:
        with path.open(encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        return default


def main(send: bool) -> int:
    state = _read(REPO / "data" / "state.json")
    history = _read(REPO / "data" / "history.json")
    if state is None or history is None:
        raise RuntimeError("state.json and history.json must exist before sending a report")
    subject, body = build_report(state, history, _read(REPO / "data" / "decisions" / "latest.json"))
    if not send:
        print(f"Subject: {subject}\n\n{body}")
        return 0
    address, password = os.environ.get("GMAIL_ADDRESS"), os.environ.get("GMAIL_APP_PASSWORD")
    if not address or not password:
        raise RuntimeError("GMAIL_ADDRESS and GMAIL_APP_PASSWORD must be set to send the report")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = address
    message["To"] = address
    message.set_content(body)
    with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
        smtp.starttls()
        smtp.login(address, password)
        smtp.send_message(message)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--send", action="store_true")
    arguments = parser.parse_args()
    try:
        sys.exit(main(send=arguments.send))
    except Exception as exc:  # noqa: BLE001
        print(f"send_report FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
