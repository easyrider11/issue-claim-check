"""Combine signals into a verdict and run all checks for an issue."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from . import signals as s
from .client import GitHubClient


@dataclass
class Report:
    number: int
    title: str
    url: str
    created_at: str
    verdict: str
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def decide(found: list[s.Signal]) -> tuple[str, list[str]]:
    """Pick the strongest verdict (ASSIGNED > CLAIMED > LIKELY-CLAIMED > FREE).

    Evidence is ordered strongest first; a PR reported by several signals
    is listed once.
    """
    verdict = s.FREE
    for sig in found:
        if s.PRECEDENCE[sig.verdict] > s.PRECEDENCE[verdict]:
            verdict = sig.verdict
    evidence: list[str] = []
    seen_prs: set[int] = set()
    for sig in sorted(found, key=lambda x: -s.PRECEDENCE[x.verdict]):
        if sig.pr is not None:
            if sig.pr in seen_prs:
                continue
            seen_prs.add(sig.pr)
        if sig.evidence not in evidence:
            evidence.append(sig.evidence)
    return verdict, evidence


def check_issue(
    client: GitHubClient,
    owner: str,
    repo: str,
    issue: dict,
    now: datetime | None = None,
    open_prs: list[dict] | None = None,
) -> Report:
    """Run every signal for one issue.

    `open_prs`: pre-fetched open PRs for the repo (used in scan mode to avoid one
    search call per issue). When None, the search API is used.
    """
    now = now or datetime.now(timezone.utc)
    number = issue["number"]
    found: list[s.Signal] = []

    assignee = s.check_assignee(issue)
    if assignee:
        found.append(assignee)

    found += s.check_timeline(client.timeline(owner, repo, number), owner, repo, number)

    prs = open_prs if open_prs is not None else client.search_open_prs(owner, repo, number)
    found += s.check_closing_prs(prs, owner, repo, number)

    if issue.get("comments", 1):
        comment = s.check_comments(client.comments(owner, repo, number), now=now)
        if comment:
            found.append(comment)

    verdict, evidence = decide(found)
    return Report(
        number=number,
        title=issue.get("title", ""),
        url=issue.get("html_url", ""),
        created_at=issue.get("created_at", ""),
        verdict=verdict,
        evidence=evidence,
    )
