from datetime import datetime, timezone

import pytest

from claimcheck import signals as s

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def _comment(login, body, created, assoc="NONE", typ="User"):
    return {
        "user": {"login": login, "type": typ},
        "body": body,
        "created_at": created,
        "author_association": assoc,
    }


def _xref(number, state="open", body="", repo="huggingface/lerobot", merged_at=None, title="x"):
    return {
        "event": "cross-referenced",
        "source": {
            "type": "issue",
            "issue": {
                "number": number,
                "state": state,
                "title": title,
                "body": body,
                "html_url": f"https://github.com/{repo}/pull/{number}",
                "pull_request": {"merged_at": merged_at},
                "repository": {"full_name": repo},
            },
        },
    }


# -- assignee ----------------------------------------------------------------


def test_assignee_present():
    sig = s.check_assignee({"assignees": [{"login": "a"}, {"login": "b"}]})
    assert sig == s.Signal(s.ASSIGNED, "assigned to @a, @b")


def test_assignee_legacy_field():
    assert s.check_assignee({"assignees": [], "assignee": {"login": "a"}}).verdict == s.ASSIGNED


def test_no_assignee():
    assert s.check_assignee({"assignees": [], "assignee": None}) is None


# -- closing keywords --------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Fixes #4851",
        "fixes #4851.",
        "This PR closes #4851 and more",
        "RESOLVED #4851",
        "Fix: #4851",
        "close huggingface/lerobot#4851",
        "Resolves https://github.com/huggingface/lerobot/issues/4851",
        "fixed\n#4851",
    ],
)
def test_closing_keyword_matches(text):
    assert s.find_closing_keyword(text, "huggingface", "lerobot", 4851)


@pytest.mark.parametrize(
    "text",
    [
        "Related to #4851",
        "Fixes #48510",
        "Fixes #485",
        "fixes 4851",
        "prefixes #4851",
        "Fixes other/repo#4851",
        "Fixes https://github.com/other/repo/issues/4851",
        "Fixes https://github.com/huggingface/lerobot/issues/48510",
        "",
        None,
    ],
)
def test_closing_keyword_rejects(text):
    assert s.find_closing_keyword(text, "huggingface", "lerobot", 4851) is None


def test_closing_keyword_returns_phrase():
    assert s.find_closing_keyword("blah. Fixes #12\n", "o", "r", 12) == "Fixes #12"


# -- timeline ----------------------------------------------------------------


def test_timeline_open_pr_with_keyword():
    sigs = s.check_timeline([_xref(4852, body="Fixes #4851")], "huggingface", "lerobot", 4851)
    assert sigs == [s.Signal(s.CLAIMED, "PR #4852 open, links via 'Fixes #4851'", 4852)]


def test_timeline_open_pr_without_keyword():
    sigs = s.check_timeline([_xref(9, body="see issue")], "huggingface", "lerobot", 1)
    assert sigs[0].evidence == "PR #9 open, cross-referenced in timeline"


def test_timeline_ignores_issue_cross_refs_and_other_repos():
    plain_issue = {"event": "cross-referenced", "source": {"issue": {"number": 5, "state": "open"}}}
    other_repo = _xref(3, repo="fork/lerobot")
    assert s.check_timeline([plain_issue, other_repo], "huggingface", "lerobot", 1) == []


def test_timeline_closed_and_merged_prs_are_notes():
    sigs = s.check_timeline(
        [_xref(10, state="closed"), _xref(11, state="closed", merged_at="2026-01-01T00:00:00Z")],
        "huggingface",
        "lerobot",
        1,
    )
    assert [x.verdict for x in sigs] == [s.FREE, s.FREE]
    assert sigs[0].evidence == "PR #10 closed, issue still open"
    assert sigs[1].evidence == "PR #11 merged, issue still open"


def test_timeline_connected_event():
    sigs = s.check_timeline([{"event": "connected"}], "o", "r", 1)
    assert sigs[0].verdict == s.CLAIMED


def test_timeline_connected_then_disconnected():
    assert s.check_timeline([{"event": "connected"}, {"event": "disconnected"}], "o", "r", 1) == []


def test_timeline_dedupes_same_pr():
    assert len(s.check_timeline([_xref(9), _xref(9)], "huggingface", "lerobot", 1)) == 1


# -- search / open PR list ---------------------------------------------------


def test_closing_prs_strict_filter():
    prs = [
        {"number": 1, "state": "open", "title": "x", "body": "Fixes #4851"},
        {"number": 2, "state": "open", "title": "Bump 4851", "body": "#48510"},
        {"number": 3, "state": "closed", "title": "x", "body": "Fixes #4851"},
        {"number": 4, "state": "open", "title": "Closes #4851", "body": None, "draft": True},
    ]
    sigs = s.check_closing_prs(prs, "huggingface", "lerobot", 4851)
    assert [x.pr for x in sigs] == [1, 4]
    assert sigs[1].evidence == "PR #4 open (draft), links via 'Closes #4851'"


# -- comments ----------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "I'd like to work on this!",
        "Hi, I’d like to work on this",
        "Can I take this?",
        "I'll take it",
        "Currently WORKING ON THIS",
        "please assign me",
        "I'll open a PR shortly",
        "I would like to   work on\nthis issue",
        "I'd like to help with a bounded first step",  # lerobot#4784, missed before
        "I would like to contribute a fix",
        "I'm happy to open a PR for this",
        "I fixed this in [b4b6eed74](https://github.com/x/inspect_ai/commit/b4b6eed74).",
        "I have a fix ready locally",
    ],
)
def test_has_intent(text):
    assert s.has_intent(text)


@pytest.mark.parametrize(
    "text",
    ["Thanks for the report", "Is this a bug?", "Happy to review a PR", "", None],
)
def test_no_intent(text):
    assert not s.has_intent(text)


def test_recent_intent_comment():
    sig = s.check_comments(
        [_comment("dev", "I'd like to work on this", "2026-10-01T12:00:00Z")], NOW
    )
    assert sig == s.Signal(s.LIKELY_CLAIMED, "@dev claimed it in a comment 4d ago")


def test_scoped_proposal_counts_as_claim():
    # Real comment shape from huggingface/lerobot#4784 (2026-09-30): a scoped
    # first-step proposal, "no PR yet". Reported FREE before this phrase existed.
    body = (
        "I'd like to help with a bounded first step: a non-blocking name-count lint "
        "for 1D numeric features ... I haven't started an implementation or PR yet."
    )
    sig = s.check_comments([_comment("contrib", body, "2026-09-30T12:00:00Z")], NOW)
    assert sig.verdict == s.LIKELY_CLAIMED


def test_fixed_in_fork_counts_as_claim():
    # Real comment shape from UKGovernmentBEIS/inspect_ai#5711 (2026-10-06):
    # a fork commit, no PR opened yet. Reported FREE before.
    c = _comment(
        "forker",
        "I fixed this in [b4b6eed74](https://github.com/forker/inspect_ai/"
        "commit/b4b6eed74). `read_choices()` now ...",
        "2026-10-04T00:00:00Z",
    )
    assert s.check_comments([c], NOW).verdict == s.LIKELY_CLAIMED


def test_maintainer_claim_is_worded_as_maintainer():
    # ros-navigation/navigation2#5952: the maintainer took the work himself.
    c = _comment(
        "lead",
        "I'm pretty deep down it, working on this in the background",
        "2026-09-10T00:00:00Z",
        assoc="MEMBER",
    )
    sig = s.check_comments([c], NOW)
    assert sig == s.Signal(s.LIKELY_CLAIMED, "maintainer @lead claimed it in a comment 25d ago")


def test_old_intent_comment_is_evidence_but_not_a_claim():
    # ros-navigation/navigation2#6349: "i'd love to work on this" 53 days earlier.
    # Still FREE, but shown, so the reader can check whether it was abandoned.
    sig = s.check_comments([_comment("dev", "can I take this", "2026-08-01T00:00:00Z")], NOW)
    assert sig == s.Signal(s.FREE, "@dev claimed it in a comment 65d ago (older than 30 days)")


def test_bot_intent_comment_ignored():
    c = _comment("helper[bot]", "I'll take it", "2026-10-04T00:00:00Z", typ="Bot")
    assert s.check_comments([c], NOW) is None


def test_maintainer_refusal_cancels_claim():
    comments = [
        _comment("dev", "Can I take this?", "2026-10-01T00:00:00Z"),
        _comment(
            "lead", "Sorry, this is already being worked on.", "2026-10-02T00:00:00Z", "MEMBER"
        ),
    ]
    assert s.check_comments(comments, NOW) is None


def test_refusal_by_non_maintainer_does_not_cancel():
    comments = [
        _comment("dev", "Can I take this?", "2026-10-01T00:00:00Z"),
        _comment("rando", "please don't", "2026-10-02T00:00:00Z", "NONE"),
    ]
    assert s.check_comments(comments, NOW).verdict == s.LIKELY_CLAIMED


def test_later_claim_after_refusal_counts():
    comments = [
        _comment("a", "Can I take this?", "2026-09-20T00:00:00Z"),
        _comment("lead", "Already assigned elsewhere", "2026-09-21T00:00:00Z", "OWNER"),
        _comment("b", "I'll take it then", "2026-10-05T08:00:00Z"),
    ]
    assert s.check_comments(comments, NOW).evidence == "@b claimed it in a comment today"
