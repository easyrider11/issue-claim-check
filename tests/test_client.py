import httpx
import pytest

from claimcheck.client import GitHubClient, GitHubError, RateLimitError


def test_token_sent_as_bearer(monkeypatch):
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"number": 1})

    monkeypatch.setenv("GITHUB_TOKEN", "abc123")
    with GitHubClient(transport=httpx.MockTransport(handler)) as c:
        c.get_issue("o", "r", 1)
        assert c.authenticated
    assert seen["auth"] == "Bearer abc123"


def test_no_token_no_auth_header():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={})

    with GitHubClient(transport=httpx.MockTransport(handler)) as c:
        c.get_issue("o", "r", 1)
        assert not c.authenticated
    assert seen["auth"] is None


def test_timeline_follows_link_header(fake):
    fake.add_scenario("lerobot_4851.json")
    with GitHubClient(transport=fake.transport) as c:
        events = c.timeline("huggingface", "lerobot", 4851)
    assert [e["event"] for e in events] == ["labeled", "cross-referenced"]
    assert sum(r.url.path.endswith("/timeline") for r in fake.requests) == 2


def test_list_issues_skips_prs_paginates_and_unions_labels(fake):
    fake.add_repo_scan("huggingface", "lerobot", "lerobot_repo_scan.json")
    with GitHubClient(transport=fake.transport) as c:
        issues = c.list_issues("huggingface", "lerobot", ["good first issue", "help wanted"], 50)
    assert [i["number"] for i in issues] == [4851, 4727, 4700]


def test_list_issues_respects_limit(fake):
    fake.add_repo_scan("huggingface", "lerobot", "lerobot_repo_scan.json")
    with GitHubClient(transport=fake.transport) as c:
        issues = c.list_issues("huggingface", "lerobot", ["good first issue"], 2)
    assert [i["number"] for i in issues] == [4851, 4727]


def test_search_unwraps_items(fake):
    fake.add_scenario("inspect_ai_5597.json")
    with GitHubClient(transport=fake.transport) as c:
        items = c.search_open_prs("UKGovernmentBEIS", "inspect_ai", 5597)
    assert [i["number"] for i in items] == [5688]


@pytest.mark.parametrize("status", [403, 429])
def test_rate_limit_error(status):
    transport = httpx.MockTransport(lambda r: httpx.Response(status, json={}))
    with GitHubClient(transport=transport) as c, pytest.raises(RateLimitError):
        c.get_issue("o", "r", 1)


def test_not_found_error():
    transport = httpx.MockTransport(lambda r: httpx.Response(404, json={}))
    with GitHubClient(transport=transport) as c, pytest.raises(GitHubError) as exc:
        c.get_issue("o", "r", 1)
    assert exc.value.status_code == 404
