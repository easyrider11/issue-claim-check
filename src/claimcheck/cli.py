"""Command line entry point: `claimcheck owner/repo` or `claimcheck owner/repo#123`."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from datetime import datetime, timezone

import httpx

from . import __version__, render
from .client import GitHubClient, GitHubError, RateLimitError
from .verdict import check_issue

DEFAULT_LABELS = ["good first issue", "help wanted"]

_URL_RE = re.compile(
    r"^(?:https?://)?github\.com/(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)"
    r"(?:/(?:issues|pull)/(?P<num>\d+))?/?(?:[?#].*)?$"
)
_SHORT_RE = re.compile(r"^(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(?:#(?P<num>\d+))?$")


def parse_target(target: str) -> tuple[str, str, int | None]:
    """Parse `owner/repo`, `owner/repo#123` or a GitHub issue URL."""
    target = target.strip()
    m = _URL_RE.match(target) or _SHORT_RE.match(target)
    if not m:
        raise ValueError(f"not a repo or issue reference: {target!r}")
    repo = m.group("repo")
    if repo.endswith(".git"):
        repo = repo[:-4]
    num = m.group("num")
    return m.group("owner"), repo, int(num) if num else None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="claimcheck",
        description="Check whether GitHub issues already have someone working on them.",
    )
    p.add_argument("target", help="owner/repo, owner/repo#123, or an issue URL")
    p.add_argument(
        "--label",
        action="append",
        dest="labels",
        metavar="LABEL",
        help='issue label to scan (repeatable; default: "good first issue", "help wanted")',
    )
    p.add_argument("--all", action="store_true", help="scan all open issues, ignoring labels")
    p.add_argument("--limit", type=int, default=50, help="max issues to scan (default 50)")
    fmt = p.add_mutually_exclusive_group()
    fmt.add_argument("--json", action="store_true", help="print JSON")
    fmt.add_argument("--markdown", action="store_true", help="print a Markdown table")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def run(
    argv: Sequence[str] | None = None,
    transport: httpx.BaseTransport | None = None,
    now: datetime | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    try:
        owner, repo, number = parse_target(args.target)
    except ValueError as e:
        print(f"claimcheck: {e}", file=sys.stderr)
        return 2
    now = now or datetime.now(timezone.utc)

    client = GitHubClient(transport=transport)
    try:
        if number is not None:
            issue = client.get_issue(owner, repo, number)
            if "pull_request" in issue:
                print(f"claimcheck: #{number} is a pull request, not an issue", file=sys.stderr)
                return 1
            reports = [check_issue(client, owner, repo, issue, now=now)]
        else:
            labels = None if args.all else (args.labels or DEFAULT_LABELS)
            issues = client.list_issues(owner, repo, labels=labels, limit=args.limit)
            open_prs = client.list_open_prs(owner, repo) if issues else []
            reports = [
                check_issue(client, owner, repo, issue, now=now, open_prs=open_prs)
                for issue in issues
            ]
    except RateLimitError as e:
        print(f"claimcheck: {e}", file=sys.stderr)
        if not client.authenticated:
            print(
                "hint: unauthenticated requests are limited to 60/hour; "
                "set GITHUB_TOKEN to raise the limit.",
                file=sys.stderr,
            )
        return 1
    except GitHubError as e:
        print(f"claimcheck: {e}", file=sys.stderr)
        return 1
    finally:
        client.close()

    if args.json:
        print(render.render_json(reports))
    elif not reports:
        print(f"No matching open issues in {owner}/{repo}.")
    elif args.markdown:
        print(render.render_markdown(reports, now))
    else:
        print(render.render_text(reports, now))
        print()
        print(render.summary(reports))
    return 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
