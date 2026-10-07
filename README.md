# issue-claim-check

Tells you which "good first issues" in a GitHub repo are actually free, and which already have someone working on them.

An issue can look open and unassigned while a pull request for it was opened hours ago. In a scan of about 30 good-first / help-wanted issues across lerobot, inspect_ai, navigation2, mujoco_playground and ManiSkill, almost every unassigned one already had a competing open PR. `claimcheck` checks for that before you start.

## Example

Real output, captured 2026-10-07 with `GITHUB_TOKEN` set. Ages and links are as the tool printed them.

```
$ claimcheck huggingface/lerobot#4851
#     Title                                     Age  Verdict  Evidence
----  ----------------------------------------  ---  -------  --------
4851  check_version_compatibility warns "upda…  2d   CLAIMED  PR #4852 open, links via 'Fixes: #4851'

0 of 1 issue(s) look free.
```

```
$ claimcheck UKGovernmentBEIS/inspect_ai --markdown
```

| # | Title | Age | Verdict | Evidence |
|---|---|---|---|---|
| [#5712](https://github.com/UKGovernmentBEIS/inspect_ai/issues/5712) | Dataframe imports shift timezone-less t… | 1d | LIKELY-CLAIMED | @XCODESSS claimed it in a comment 1d ago |
| [#5711](https://github.com/UKGovernmentBEIS/inspect_ai/issues/5711) | Dataset loaders silently change answer … | 1d | LIKELY-CLAIMED | @XCODESSS claimed it in a comment 1d ago |
| [#5597](https://github.com/UKGovernmentBEIS/inspect_ai/issues/5597) | HF task loading reads eval.yaml with th… | 9d | CLAIMED | PR #5688 open, links via 'Fixes #5597'; PR #5629 closed, issue still open; PR #5476 merged, issue still open |

All three were open, unassigned, and labelled `good first issue`. #5711 and #5712 had no PR yet, but the
commenter had already pushed a fix to their fork the day the issues were filed.

## Install

```
pipx install git+https://github.com/easyrider11/issue-claim-check
```

Requires Python 3.10+. The only runtime dependency is `httpx`.

## Usage

```
claimcheck owner/repo                     # scan open issues labelled "good first issue" or "help wanted"
claimcheck owner/repo --label bug         # scan a different label (repeatable)
claimcheck owner/repo --all --limit 100   # scan any open issue (default limit 50)
claimcheck owner/repo#123                 # check one issue
claimcheck https://github.com/owner/repo/issues/123
claimcheck owner/repo --json              # machine-readable output
claimcheck owner/repo --markdown          # Markdown table
```

Set `GITHUB_TOKEN` to a personal access token (no scopes needed for public repos) to raise the API rate limit. Without it, GitHub allows 60 requests per hour, which is enough for a single issue or a small scan.

Exit code is 0 whenever the check ran, whatever the verdicts are; 1 on API errors, 2 on a bad argument.

## How verdicts are decided

Each issue gets the strongest verdict any check finds:

| Verdict | Meaning |
|---|---|
| ASSIGNED | The issue has an assignee. |
| CLAIMED | An open PR in the same repo references the issue in its timeline, is linked in the Development sidebar, or says `fixes/closes/resolves #N` (or the full issue URL) in its title or body. |
| LIKELY-CLAIMED | In the last 30 days a non-bot user commented something like "I'd like to work on this", "can I take this", "assign me", "I fixed this in <fork commit>", and no maintainer turned them down afterwards. A maintainer saying they are on it counts too, and is labelled as a maintainer. |
| FREE | None of the above. Closed or merged PRs, and claim comments older than 30 days, are still listed as evidence so you can judge whether they were abandoned. |

When checking one issue, open PRs are found with the search API. When scanning a repo, `claimcheck` lists the repo's open PRs once (up to 300) and matches closing keywords locally, to avoid one search request per issue.

## Limitations

- Comment matching uses a fixed phrase list (`INTENT_PHRASES` in `src/claimcheck/signals.py`). It misses claims written differently and can flag questions like "is anyone working on this?". The first run against live repos (2026-10-07: lerobot, inspect_ai, navigation2, harbor) found two misses - "I'd like to help with ..." and "I fixed this in <commit>" - which are now in the list with regression tests. Expect more.
- GitHub's search index can lag a few minutes behind new PRs. A PR that only mentions the issue number without a closing keyword is caught only through the timeline.
- Cross-references from PRs in forks or other repos are ignored.
- A scan costs about 3 requests per issue. Unauthenticated, a 50-issue scan will hit the rate limit; use `GITHUB_TOKEN`.
- `ASSIGNED` and `CLAIMED` can be stale: assignees go quiet and PRs get abandoned. Check the dates before you give up on an issue.

## Development

```
pip install -e ".[dev]"
ruff check . && ruff format --check .
pytest -q
```

Tests run offline against hand-built fixtures in `tests/fixtures/` that follow the GitHub REST response shapes.

## License

MIT
