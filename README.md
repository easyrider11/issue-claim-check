# issue-claim-check

Tells you which "good first issues" in a GitHub repo are actually free, and which already have someone working on them.

An issue can look open and unassigned while a pull request for it was opened hours ago. In a scan of about 30 good-first / help-wanted issues across lerobot, inspect_ai, navigation2, mujoco_playground and ManiSkill, almost every unassigned one already had a competing open PR. `claimcheck` checks for that before you start.

## Example

Example from a scan on 2026-10-05. Titles are paraphrased and the Age column is left out; the evidence column is shortened to the PR numbers that were found.

| Repo | # | Title | Verdict | Evidence |
|---|---|---|---|---|
| huggingface/lerobot | 4851 | version check | CLAIMED | PR #4852 open (opened the same day as the issue) |
| huggingface/lerobot | 4727 | — | CLAIMED | PR #4728 open; PR #4729 open |
| UKGovernmentBEIS/inspect_ai | 5597 | HF eval.yaml encoding | CLAIMED | PR #5688 open (opened the same day as the issue) |

Plain-text output for one issue has this shape (illustrative: the age and the link wording below are placeholders, not captured output):

```
$ claimcheck huggingface/lerobot#4851
#     Title                                 Age  Verdict  Evidence
----  ------------------------------------  ---  -------  --------
4851  ...                                   ?d   CLAIMED  PR #4852 open, links via '<how it links>'

0 of 1 issue(s) look free.
```

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
| LIKELY-CLAIMED | In the last 30 days a non-bot user commented something like "I'd like to work on this", "can I take this", "assign me", and no maintainer turned them down afterwards. |
| FREE | None of the above. Closed or merged PRs are still listed as evidence. |

When checking one issue, open PRs are found with the search API. When scanning a repo, `claimcheck` lists the repo's open PRs once (up to 300) and matches closing keywords locally, to avoid one search request per issue.

## Limitations

- Comment matching uses a fixed phrase list (`INTENT_PHRASES` in `src/claimcheck/signals.py`). It misses claims written differently and can flag questions like "is anyone working on this?".
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
