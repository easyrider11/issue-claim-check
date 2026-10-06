"""Offline fake of the GitHub REST API built on httpx.MockTransport."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeGitHub:
    """Routes requests to fixture data. Records every request for assertions."""

    def __init__(self) -> None:
        self.scenarios: dict[tuple[str, str, int], dict] = {}
        self.issue_lists: dict[tuple[str, str], dict[str, list[list[dict]]]] = {}
        self.pulls: dict[tuple[str, str], list[dict]] = {}
        self.requests: list[httpx.Request] = []
        self.status_override: int | None = None

    def add_scenario(self, name: str) -> dict:
        sc = load(f"scenarios/{name}")
        key = (sc["owner"].lower(), sc["repo"].lower(), sc["issue"]["number"])
        self.scenarios[key] = sc
        return sc

    def add_repo_scan(self, owner: str, repo: str, name: str) -> None:
        data = load(name)
        resolved = {
            label: [[self._resolve(i) for i in page] for page in pages]
            for label, pages in data["issues_by_label"].items()
        }
        self.issue_lists[(owner.lower(), repo.lower())] = resolved
        self.pulls[(owner.lower(), repo.lower())] = data["open_pulls"]

    def _resolve(self, item: dict) -> dict:
        if "$ref" in item:
            sc = self.add_scenario(Path(item["$ref"]).name)
            return sc["issue"]
        return item

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    # -- routing ---------------------------------------------------------

    def _paged(self, request: httpx.Request, pages: list[list[dict]]) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        body = pages[page - 1] if page <= len(pages) else []
        headers = {}
        if page < len(pages):
            nxt = request.url.copy_merge_params({"page": str(page + 1)})
            headers["Link"] = f'<{nxt}>; rel="next"'
        return httpx.Response(200, json=body, headers=headers)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status_override:
            return httpx.Response(self.status_override, json={"message": "API rate limit exceeded"})
        path = request.url.path

        if path == "/search/issues":
            q = request.url.params["q"]
            m = re.match(r"repo:([^/]+)/(\S+) is:pr is:open (\d+)$", q)
            assert m, f"unexpected search query {q!r}"
            sc = self.scenarios.get((m[1].lower(), m[2].lower(), int(m[3])))
            items = sc["search_items"] if sc else []
            body = {"total_count": len(items), "incomplete_results": False, "items": items}
            return httpx.Response(200, json=body)

        m = re.match(r"^/repos/([^/]+)/([^/]+)/(issues|pulls)(?:/(\d+)(?:/(\w+))?)?$", path)
        if not m:
            return httpx.Response(404, json={"message": "Not Found"})
        owner, repo, kind, num, sub = m[1].lower(), m[2].lower(), m[3], m[4], m[5]

        if kind == "pulls" and num is None:
            return self._paged(request, [self.pulls.get((owner, repo), [])])
        if kind == "issues" and num is None:
            lists = self.issue_lists.get((owner, repo), {})
            label = request.url.params.get("labels")
            if label is None:
                pages = [[i for pgs in lists.values() for pg in pgs for i in pg]]
            else:
                pages = lists.get(label, [[]])
            return self._paged(request, pages)

        sc = self.scenarios.get((owner, repo, int(num)))
        if sc is None:
            return httpx.Response(404, json={"message": "Not Found"})
        if sub is None:
            return httpx.Response(200, json=sc["issue"])
        if sub == "timeline":
            return self._paged(request, sc["timeline_pages"])
        if sub == "comments":
            return self._paged(request, [sc["comments"]])
        return httpx.Response(404, json={"message": "Not Found"})


@pytest.fixture
def fake() -> FakeGitHub:
    return FakeGitHub()


@pytest.fixture(autouse=True)
def _no_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
