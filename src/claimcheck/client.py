"""Minimal GitHub REST client. Transport is injectable so tests run offline."""

from __future__ import annotations

import os
from typing import Any

import httpx

API_URL = "https://api.github.com"
PER_PAGE = 100


class GitHubError(Exception):
    """Any non-success response from the GitHub API."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class RateLimitError(GitHubError):
    """403/429 responses, which are usually rate limits."""


class GitHubClient:
    def __init__(
        self,
        token: str | None = None,
        transport: httpx.BaseTransport | None = None,
        base_url: str = API_URL,
        timeout: float = 20.0,
    ):
        if token is None:
            token = os.environ.get("GITHUB_TOKEN") or None
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "issue-claim-check",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.authenticated = bool(token)
        self._http = httpx.Client(
            base_url=base_url, headers=headers, transport=transport, timeout=timeout
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- low level -------------------------------------------------------

    def _request(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        try:
            resp = self._http.get(url, params=params)
        except httpx.HTTPError as e:
            raise GitHubError(f"network error: {e}") from e
        if resp.status_code in (403, 429):
            raise RateLimitError(
                f"GitHub returned {resp.status_code} for {resp.request.url.path}",
                resp.status_code,
            )
        if resp.status_code >= 400:
            raise GitHubError(
                f"GitHub returned {resp.status_code} for {resp.request.url.path}",
                resp.status_code,
            )
        return resp

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._request(path, params).json()

    def paginate(
        self, path: str, params: dict[str, Any] | None = None, max_items: int | None = None
    ) -> list[Any]:
        """Follow `Link: rel="next"` headers and collect list items."""
        params = {"per_page": PER_PAGE, **(params or {})}
        items: list[Any] = []
        url: str | None = path
        while url:
            resp = self._request(url, params)
            data = resp.json()
            if isinstance(data, dict) and "items" in data:
                data = data["items"]
            items.extend(data)
            if max_items is not None and len(items) >= max_items:
                return items[:max_items]
            nxt = resp.links.get("next")
            url = nxt["url"] if nxt else None
            params = None  # the next URL already carries the query string
        return items

    # -- endpoints -------------------------------------------------------

    def get_issue(self, owner: str, repo: str, number: int) -> dict:
        return self.get_json(f"/repos/{owner}/{repo}/issues/{number}")

    def list_issues(
        self,
        owner: str,
        repo: str,
        labels: list[str] | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Open issues (pull requests removed). Labels are OR-ed: one query per label."""
        path = f"/repos/{owner}/{repo}/issues"
        queries = [{"labels": lab} for lab in labels] if labels else [{}]
        seen: dict[int, dict] = {}
        for q in queries:
            params = {"state": "open", "sort": "created", "direction": "desc", **q}
            # Ask for a little extra because PRs are filtered out afterwards.
            for item in self.paginate(path, params, max_items=limit * 2):
                if "pull_request" in item:
                    continue
                seen.setdefault(item["number"], item)
        issues = sorted(seen.values(), key=lambda i: i["number"], reverse=True)
        return issues[:limit]

    def timeline(self, owner: str, repo: str, number: int) -> list[dict]:
        return self.paginate(f"/repos/{owner}/{repo}/issues/{number}/timeline")

    def comments(self, owner: str, repo: str, number: int) -> list[dict]:
        return self.paginate(f"/repos/{owner}/{repo}/issues/{number}/comments")

    def search_open_prs(self, owner: str, repo: str, number: int) -> list[dict]:
        q = f"repo:{owner}/{repo} is:pr is:open {number}"
        return self.paginate("/search/issues", {"q": q}, max_items=100)

    def list_open_prs(self, owner: str, repo: str, limit: int = 300) -> list[dict]:
        return self.paginate(f"/repos/{owner}/{repo}/pulls", {"state": "open"}, max_items=limit)
