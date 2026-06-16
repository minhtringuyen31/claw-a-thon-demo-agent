"""Notification tool — strategist hand-off.

Production: Slack / email with an approve link. Dev: stdout.
"""
from __future__ import annotations


def notify_strategist(summary: str) -> None:
    print("\n" + "=" * 60)
    print("NOTIFY STRATEGIST — pattern ready for review:")
    print(summary)
    print("=" * 60 + "\n")
