"""Evidence signals. Each function looks at one kind of GitHub data and returns Signals.

All functions are pure (no network) so they can be unit-tested with plain dicts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

ASSIGNED = "ASSIGNED"
CLAIMED = "CLAIMED"
LIKELY_CLAIMED = "LIKELY-CLAIMED"
FREE = "FREE"

# Higher number wins.
PRECEDENCE = {FREE: 0, LIKELY_CLAIMED: 1, CLAIMED: 2, ASSIGNED: 3}

# Phrases that signal someone intends to work on an issue. Matched
# case-insensitively as substrings of a comment body (after collapsing whitespace
# and normalising curly apostrophes). Keep this list the single source of truth.
INTENT_PHRASES: tuple[str, ...] = (
    "i'd like to work on",
    "i would like to work on",
    "i want to work on",
    "i'd love to work on",
    "i would love to work on",
    "i'd like to take",
    "i would like to take",
    "i'd like to tackle",
    "i'd like to pick this up",
    "i can work on this",
    "i can take this",
    "can i work on",
    "can i take",
    "may i work on",
    "could i work on",
    "could i take",
    "i'll take",
    "i will take",
    "i'll work on",
    "i will work on",
    "i'm working on",
    "i am working on",
    "working on this",
    "i'll pick this up",
    "i'll give this a try",
    "i'll give it a try",
    "i'll give it a shot",
    "i'll open a pr",
    "i will open a pr",
    "i'll submit a pr",
    "i will submit a pr",
    "i'll send a pr",
    "assign me",
    "assign this to me",
    "assign it to me",
    "please assign",
    "is this still available",
    "is anyone working on this",
)

# Phrases a maintainer might use to turn a claimant down.
REFUSAL_PHRASES: tuple[str, ...] = (
    "already being worked on",
    "already working on",
    "someone else is working",
    "already assigned",
    "already has a pr",
    "already a pr",
    "not accepting",
    "please don't",
    "please do not",
    "won't be accepted",
    "will not be accepted",
    "not looking for",
    "we don't assign",
    "we do not assign",
)

MAINTAINER_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
COMMENT_WINDOW_DAYS = 30


@dataclass(frozen=True)
class Signal:
    verdict: str
    evidence: str
    pr: int | None = None


def _normalise(text: str | None) -> str:
    text = (text or "").replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", text).lower()


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def is_bot(user: dict | None) -> bool:
    if not user:
        return True
    login = user.get("login", "")
    return user.get("type") == "Bot" or login.endswith("[bot]")


def _repo_of(item: dict) -> str | None:
    """`owner/repo` of an issue/PR dict, from `repository` or `html_url`."""
    repo = item.get("repository")
    if isinstance(repo, dict) and repo.get("full_name"):
        return repo["full_name"].lower()
    m = re.match(r"https://github\.com/([^/]+/[^/]+)/", item.get("html_url", ""))
    return m.group(1).lower() if m else None


# -- 1. assignee -------------------------------------------------------------


def check_assignee(issue: dict) -> Signal | None:
    logins = [a["login"] for a in issue.get("assignees") or [] if a.get("login")]
    if not logins and issue.get("assignee"):
        logins = [issue["assignee"]["login"]]
    if not logins:
        return None
    return Signal(ASSIGNED, "assigned to " + ", ".join("@" + x for x in logins))


# -- closing keywords --------------------------------------------------------


def closing_keyword_pattern(owner: str, repo: str, number: int) -> re.Pattern[str]:
    """Regex for GitHub closing keywords that reference exactly this issue.

    Matches `Fixes #12`, `closes: owner/repo#12`, `Resolves https://github.com/owner/repo/issues/12`.
    Does not match `#123` when looking for `#12`.
    """
    full = re.escape(f"{owner}/{repo}")
    keyword = r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)"
    ref = (
        rf"(?:(?:{full})?#{number}"
        rf"|https?://github\.com/{full}/issues/{number})"
    )
    return re.compile(rf"\b{keyword}\b:?\s+{ref}(?![\w/])", re.IGNORECASE)


def find_closing_keyword(text: str | None, owner: str, repo: str, number: int) -> str | None:
    """Return the matched phrase (e.g. "Fixes #12") or None."""
    m = closing_keyword_pattern(owner, repo, number).search(text or "")
    return m.group(0) if m else None


def _pr_evidence(pr: dict, owner: str, repo: str, number: int, how: str) -> str:
    match = find_closing_keyword(pr.get("title"), owner, repo, number) or find_closing_keyword(
        pr.get("body"), owner, repo, number
    )
    draft = " (draft)" if pr.get("draft") else ""
    link = f"links via '{match}'" if match else how
    return f"PR #{pr['number']} open{draft}, {link}"


def _closed_pr_note(pr: dict) -> str:
    merged = (pr.get("pull_request") or {}).get("merged_at")
    return f"PR #{pr['number']} {'merged' if merged else 'closed'}, issue still open"


# -- 2. timeline -------------------------------------------------------------


def check_timeline(events: list[dict], owner: str, repo: str, number: int) -> list[Signal]:
    """Open PRs cross-referencing the issue, plus `connected` (Development sidebar) links."""
    signals: list[Signal] = []
    here = f"{owner}/{repo}".lower()
    seen: set[int] = set()
    connected = 0
    for ev in events:
        kind = ev.get("event")
        if kind == "connected":
            connected += 1
        elif kind == "disconnected":
            connected = max(0, connected - 1)
        elif kind == "cross-referenced":
            src = (ev.get("source") or {}).get("issue") or {}
            if "pull_request" not in src or src.get("number") in seen:
                continue
            if _repo_of(src) not in (None, here):
                continue  # PRs in other repos (forks, downstream) are not claims here
            seen.add(src["number"])
            if src.get("state") == "open":
                ev_text = _pr_evidence(src, owner, repo, number, "cross-referenced in timeline")
                signals.append(Signal(CLAIMED, ev_text, src["number"]))
            else:
                signals.append(Signal(FREE, _closed_pr_note(src), src["number"]))
    if connected:
        signals.append(Signal(CLAIMED, "PR linked in Development sidebar (connected event)"))
    return signals


# -- 3. open PRs with closing keywords ----------------------------------------


def check_closing_prs(prs: list[dict], owner: str, repo: str, number: int) -> list[Signal]:
    """Open PRs (search results or /pulls items) whose title/body closes this issue."""
    signals = []
    for pr in prs:
        if pr.get("state", "open") != "open":
            continue
        if not (
            find_closing_keyword(pr.get("title"), owner, repo, number)
            or find_closing_keyword(pr.get("body"), owner, repo, number)
        ):
            continue
        signals.append(Signal(CLAIMED, _pr_evidence(pr, owner, repo, number, ""), pr["number"]))
    return signals


# -- 4. intent comments ------------------------------------------------------


def has_intent(text: str | None) -> bool:
    body = _normalise(text)
    return any(p in body for p in INTENT_PHRASES)


def is_refusal(text: str | None) -> bool:
    body = _normalise(text)
    return any(p in body for p in REFUSAL_PHRASES)


def check_comments(
    comments: list[dict],
    now: datetime | None = None,
    window_days: int = COMMENT_WINDOW_DAYS,
) -> Signal | None:
    """Most recent non-bot "I'll work on this" comment in the window, unless a
    maintainer later turned it down."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)
    ordered = sorted(comments, key=lambda c: c["created_at"])
    for i in range(len(ordered) - 1, -1, -1):
        c = ordered[i]
        if is_bot(c.get("user")) or not has_intent(c.get("body")):
            continue
        created = parse_time(c["created_at"])
        if created < cutoff:
            break
        refused = any(
            later.get("author_association") in MAINTAINER_ASSOCIATIONS
            and not is_bot(later.get("user"))
            and is_refusal(later.get("body"))
            for later in ordered[i + 1 :]
        )
        if refused:
            continue
        days = (now - created).days
        when = "today" if days == 0 else f"{days}d ago"
        return Signal(LIKELY_CLAIMED, f"@{c['user']['login']} asked to work on it {when}")
    return None
