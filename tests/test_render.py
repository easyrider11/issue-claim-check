import json
from datetime import datetime, timezone

import pytest

from claimcheck import render
from claimcheck.verdict import Report

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def _report(**kw):
    base = dict(
        number=4851,
        title="Version check fails for dev installs",
        url="https://github.com/huggingface/lerobot/issues/4851",
        created_at="2026-10-02T09:14:00Z",
        verdict="CLAIMED",
        evidence=["PR #4852 open, links via 'Fixes #4851'"],
    )
    base.update(kw)
    return Report(**base)


@pytest.mark.parametrize(
    "created,expected",
    [
        ("2026-10-05T01:00:00Z", "today"),
        ("2026-10-02T09:14:00Z", "3d"),
        ("2026-06-01T00:00:00Z", "4mo"),
        ("2023-01-01T00:00:00Z", "3y"),
        ("", "?"),
    ],
)
def test_age(created, expected):
    assert render.age(created, NOW) == expected


def test_truncate():
    assert render.truncate("a" * 50, 10) == "a" * 9 + "…"
    assert render.truncate("short") == "short"


def test_text_table_alignment():
    out = render.render_text([_report(), _report(number=7, verdict="FREE", evidence=[])], NOW)
    lines = out.splitlines()
    assert lines[0].startswith("#     Title")
    assert lines[2].split()[0] == "4851"
    assert lines[3].split()[-2:] == ["FREE", "-"]
    # Verdict column starts at the same offset on every row.
    assert lines[2].index("CLAIMED") == lines[3].index("FREE") == lines[0].index("Verdict")


def test_markdown_escapes_pipes():
    out = render.render_markdown([_report(title="a | b")], NOW)
    assert "a \\| b" in out


def test_json_round_trip():
    data = json.loads(render.render_json([_report()]))
    assert data[0]["verdict"] == "CLAIMED"
    assert data[0]["evidence"] == ["PR #4852 open, links via 'Fixes #4851'"]
