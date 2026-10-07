import pytest
from conftest import NOW

from claimcheck import signals as s
from claimcheck.client import GitHubClient
from claimcheck.verdict import check_issue, decide


def test_decide_empty_is_free():
    assert decide([]) == (s.FREE, [])


@pytest.mark.parametrize(
    "verdicts,expected",
    [
        ([s.FREE, s.LIKELY_CLAIMED], s.LIKELY_CLAIMED),
        ([s.LIKELY_CLAIMED, s.CLAIMED], s.CLAIMED),
        ([s.CLAIMED, s.ASSIGNED, s.LIKELY_CLAIMED], s.ASSIGNED),
        ([s.FREE], s.FREE),
    ],
)
def test_decide_precedence(verdicts, expected):
    found = [s.Signal(v, f"e{i}") for i, v in enumerate(verdicts)]
    assert decide(found)[0] == expected


def test_decide_orders_evidence_and_dedupes_prs():
    found = [
        s.Signal(s.FREE, "PR #1 closed, issue still open", 1),
        s.Signal(s.CLAIMED, "PR #2 open, cross-referenced in timeline", 2),
        s.Signal(s.CLAIMED, "PR #2 open, links via 'Fixes #9'", 2),
    ]
    verdict, evidence = decide(found)
    assert verdict == s.CLAIMED
    assert evidence == [
        "PR #2 open, cross-referenced in timeline",
        "PR #1 closed, issue still open",
    ]


@pytest.mark.parametrize(
    "scenario,verdict,evidence",
    [
        ("lerobot_4851.json", "CLAIMED", ["PR #4852 open, links via 'Fixes #4851'"]),
        (
            "lerobot_4727.json",
            "CLAIMED",
            [
                "PR #4728 open, links via 'Closes #4727'",
                "PR #4729 open (draft), cross-referenced in timeline",
            ],
        ),
        (
            "inspect_ai_5597.json",
            "CLAIMED",
            [
                "PR #5688 open, links via "
                "'resolves https://github.com/UKGovernmentBEIS/inspect_ai/issues/5597'"
            ],
        ),
        ("lerobot_4700_closed_pr.json", "FREE", ["PR #4701 closed, issue still open"]),
        ("navigation2_assigned.json", "ASSIGNED", ["assigned to @helper-i"]),
        ("maniskill_intent.json", "LIKELY-CLAIMED", ["@newcomer-l claimed it in a comment 5d ago"]),
        (
            "mujoco_playground_free.json",
            "FREE",
            ["@drive-by-o claimed it in a comment 117d ago (older than 30 days)"],
        ),
    ],
)
def test_scenarios(fake, scenario, verdict, evidence):
    sc = fake.add_scenario(scenario)
    with GitHubClient(transport=fake.transport) as client:
        report = check_issue(client, sc["owner"], sc["repo"], sc["issue"], now=NOW)
    assert report.verdict == verdict
    assert report.evidence == evidence
    assert report.number == sc["issue"]["number"]


def test_skips_comments_call_when_issue_has_none(fake):
    sc = fake.add_scenario("lerobot_4851.json")
    with GitHubClient(transport=fake.transport) as client:
        check_issue(client, sc["owner"], sc["repo"], sc["issue"], now=NOW)
    assert not any(r.url.path.endswith("/comments") for r in fake.requests)


def test_uses_prefetched_prs_instead_of_search(fake):
    sc = fake.add_scenario("inspect_ai_5597.json")
    with GitHubClient(transport=fake.transport) as client:
        report = check_issue(client, sc["owner"], sc["repo"], sc["issue"], now=NOW, open_prs=[])
    assert report.verdict == "FREE"
    assert not any(r.url.path == "/search/issues" for r in fake.requests)
