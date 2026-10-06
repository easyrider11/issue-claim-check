"""Output formatting: plain text table, Markdown table, JSON."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from .signals import parse_time
from .verdict import Report

HEADERS = ("#", "Title", "Age", "Verdict", "Evidence")
TITLE_WIDTH = 40


def age(created_at: str, now: datetime | None = None) -> str:
    if not created_at:
        return "?"
    now = now or datetime.now(timezone.utc)
    days = max(0, (now - parse_time(created_at)).days)
    if days < 1:
        return "today"
    if days < 60:
        return f"{days}d"
    if days < 730:
        return f"{days // 30}mo"
    return f"{days // 365}y"


def truncate(text: str, width: int = TITLE_WIDTH) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


def _rows(reports: list[Report], now: datetime | None) -> list[tuple[str, ...]]:
    return [
        (
            str(r.number),
            truncate(r.title),
            age(r.created_at, now),
            r.verdict,
            "; ".join(r.evidence) or "-",
        )
        for r in reports
    ]


def render_text(reports: list[Report], now: datetime | None = None) -> str:
    rows = _rows(reports, now)
    widths = [max(len(h), *(len(row[i]) for row in rows)) for i, h in enumerate(HEADERS)]
    widths[-1] = len(HEADERS[-1])  # last column is not padded

    def line(cells: tuple[str, ...]) -> str:
        return "  ".join(c.ljust(w) for c, w in zip(cells, widths, strict=True)).rstrip()

    out = [line(HEADERS), line(tuple("-" * w for w in widths))]
    out += [line(row) for row in rows]
    return "\n".join(out)


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|")


def render_markdown(reports: list[Report], now: datetime | None = None) -> str:
    out = ["| " + " | ".join(HEADERS) + " |", "|" + "---|" * len(HEADERS)]
    for r, row in zip(reports, _rows(reports, now), strict=True):
        cells = list(row)
        cells[0] = f"[#{r.number}]({r.url})" if r.url else f"#{r.number}"
        out.append("| " + " | ".join(_md_escape(c) for c in cells) + " |")
    return "\n".join(out)


def render_json(reports: list[Report]) -> str:
    return json.dumps([r.to_dict() for r in reports], indent=2, ensure_ascii=False)


def summary(reports: list[Report]) -> str:
    free = sum(r.verdict == "FREE" for r in reports)
    return f"{free} of {len(reports)} issue(s) look free."
