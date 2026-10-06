import json

import pytest
from conftest import NOW

from claimcheck.cli import parse_target, run


@pytest.mark.parametrize(
    "target,expected",
    [
        ("huggingface/lerobot", ("huggingface", "lerobot", None)),
        ("huggingface/lerobot#4851", ("huggingface", "lerobot", 4851)),
        ("https://github.com/huggingface/lerobot/issues/4851", ("huggingface", "lerobot", 4851)),
        ("github.com/haosulab/ManiSkill/issues/12#issuecomment-1", ("haosulab", "ManiSkill", 12)),
        ("https://github.com/google-deepmind/mujoco_playground", ("google-deepmind", "mujoco_playground", None)),
        ("https://github.com/o/r.git", ("o", "r", None)),
    ],
)
def test_parse_target(target, expected):
    assert parse_target(target) == expected


@pytest.mark.parametrize("bad", ["lerobot", "a/b/c", "https://gitlab.com/o/r", "o/r#x"])
def test_parse_target_rejects(bad):
    with pytest.raises(ValueError):
        parse_target(bad)


def test_single_issue_text(fake, capsys):
    fake.add_scenario("lerobot_4851.json")
    code = run(["huggingface/lerobot#4851"], transport=fake.transport, now=NOW)
    out = capsys.readouterr().out
    assert code == 0
    assert "4851" in out and "CLAIMED" in out and "PR #4852 open" in out
    assert "0 of 1 issue(s) look free." in out


def test_repo_scan_json(fake, capsys):
    fake.add_repo_scan("huggingface", "lerobot", "lerobot_repo_scan.json")
    code = run(["huggingface/lerobot", "--json"], transport=fake.transport, now=NOW)
    data = json.loads(capsys.readouterr().out)
    assert code == 0
    assert [(d["number"], d["verdict"]) for d in data] == [
        (4851, "CLAIMED"),
        (4727, "CLAIMED"),
        (4700, "FREE"),
    ]
    # Scan mode lists open PRs once instead of one search call per issue.
    assert not any(r.url.path == "/search/issues" for r in fake.requests)


def test_repo_scan_markdown(fake, capsys):
    fake.add_repo_scan("huggingface", "lerobot", "lerobot_repo_scan.json")
    run(["huggingface/lerobot", "--markdown", "--label", "help wanted"], fake.transport, NOW)
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "| # | Title | Age | Verdict | Evidence |"
    assert len(out) == 3
    assert out[2].startswith("| [#4727](https://github.com/huggingface/lerobot/issues/4727) |")


def test_all_flag_sends_no_label(fake, capsys):
    fake.add_repo_scan("huggingface", "lerobot", "lerobot_repo_scan.json")
    run(["huggingface/lerobot", "--all", "--limit", "1", "--json"], fake.transport, NOW)
    issue_reqs = [r for r in fake.requests if r.url.path.endswith("/lerobot/issues")]
    assert issue_reqs and all("labels" not in r.url.params for r in issue_reqs)
    assert len(json.loads(capsys.readouterr().out)) == 1


def test_empty_scan(fake, capsys):
    code = run(["o/empty"], transport=fake.transport, now=NOW)
    assert code == 0
    assert "No matching open issues" in capsys.readouterr().out


def test_rate_limit_hint(fake, capsys):
    fake.status_override = 403
    code = run(["huggingface/lerobot#4851"], transport=fake.transport, now=NOW)
    err = capsys.readouterr().err
    assert code == 1
    assert "GITHUB_TOKEN" in err


def test_bad_target_exit_code(capsys):
    assert run(["nope"]) == 2


def test_pull_request_target_is_rejected(fake, capsys):
    fake.add_repo_scan("huggingface", "lerobot", "lerobot_repo_scan.json")
    fake.scenarios[("huggingface", "lerobot", 4852)] = {
        "issue": {"number": 4852, "pull_request": {}},
    }
    assert run(["huggingface/lerobot#4852"], transport=fake.transport, now=NOW) == 1
