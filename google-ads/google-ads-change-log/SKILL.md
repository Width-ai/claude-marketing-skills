---
name: google-ads-change-log
description: >
  Keeps a lasting log of Google Ads changes with the reason, the evidence,
  the expected effect, who approved it, and when to review the result, then
  checks it against the account's own change history to catch changes made
  by other people, scripts, automated rules, and recommendations Google
  applied automatically. Use when someone asks what changed in the account,
  why performance moved, which changes are due for review, or wants to
  record a change made outside Claude.
metadata:
  version: "1.0.0"
---

# Google Ads Change Log

Google Ads keeps detailed change history for only 30 days. It records what changed but never why, and the history available to connectors leaves out Google Ads Editor changes. This skill keeps the record the account doesn't: every change, the reason for it, what was expected, and when to check whether it worked.

The log is a CSV at `.agents/google-ads-change-log.csv` (use `.agents/google-ads-change-log-<customer-id>.csv` when managing several accounts). Column definitions are in `references/log-format.md`. In a chat with no project folder, send the file to the person to download and ask them to attach it next time.

All commands use `scripts/changelog.py`. Script paths are relative to this skill's folder, and the script uses only the Python standard library.

## Jobs and commands

| Job | Command |
|---|---|
| Start a log | `changelog.py init` |
| Record a batch from a change set | `changelog.py add --from google-ads-changes/2026-11-14-negatives.json --status applied --applied-via editor --approved-by "Name" --conversion-lag 7` |
| Record one change by hand | `changelog.py add --action set_budget --campaign "Brand" --before 50 --after 60 --reason "..." --status applied --applied-via ui` |
| Update an entry | `changelog.py update 12 --status verified --outcome "..."` |
| See reviews that are due | `changelog.py due` |
| Find changes nobody logged | `changelog.py reconcile --history google-ads-data/2026-11-14/change_history.csv` |
| Summarize a period | `changelog.py summary --since 2026-10-01 --until 2026-10-31` |

## Recording a change

Every entry needs:
- the account, the campaign, and the ad group if relevant
- what changed: action, field, before, and after
- the reason, and the evidence with its date range
- the expected effect
- who approved it, and how it was applied (connector, Editor, UI, or script)
- the status

`add` sets the review date from the change type, using the waiting periods in `references/review-windows.md`. For bidding changes, pass the account's conversion delay with `--conversion-lag`. Use `--review-on` when the person wants a different date.

Never write a reason you weren't given. If nobody knows why a change was made, the script writes "reason not recorded". Ask the person, and update the entry when they answer.

When the person describes changes they made themselves ("I raised the brand budget last Tuesday"), log them with `--applied-via ui` and the real date in `--applied-at`.

## Reviewing changes that are due

Run `due`. For each entry it lists:

1. **Pull before and after windows.** Pull the same metrics for equal periods before and after the change, using the google-ads-data-pull skill or exports. Leave out the waiting period itself and recent days still affected by conversion delay.
2. **Compute the comparison in code.** Use the data pull skill's `metrics.py compare` if it's installed; otherwise write the comparison as a short script. Never compare by eye.
3. **Write the outcome** in one line, with numbers and both windows. For example: "CPA $82 to $71, Oct 1 to 14 vs. Oct 22 to Nov 4, excluding a 7-day conversion delay; conversions flat."
4. **Name overlapping changes.** If other changes landed on the same campaign in either window, say so: the result can't be credited to one change.
5. **Set the status.** Use `verified`. If the person decides to undo the change, use `rolled_back` and record the reason in notes.

## Reconciling with the account's change history

Pull change history (it goes back at most 30 days) with the google-ads-data-pull skill or the person's export. Normalize it, then run `reconcile`. It reports two things:

- **Changes in the account's history with no log entry**, grouped by the tool that made them: the Google Ads UI, API tools, scripts, automated rules, bulk uploads, or recommendations Google applied.
- **Logged changes with no match in the history.** Changes applied through Editor are skipped, because Editor changes never show up in that history. Anything else unmatched needs a check that it really went live.

Show the unlogged changes to the person and ask for the reasons, then log the ones they explain. Flag changes made by recommendations on their own line, because they usually mean auto-apply is on. Matching works on dates and the kind of item changed, so treat it as best effort, not proof.

## Answering "what changed?" and "why did performance move?"

1. **Gather the changes.** Run `summary` for the period, and pull change history for the same days if it's within 30 days.
2. **Line up changes with movements.** Match changes to the dates the metrics moved. A metric that moved within days of a change probably moved because of it. Say "likely", not "because".
3. **Name what the record can't see:**
   - conversions are dated by click
   - change history only covers 30 days
   - Google's own changes (algorithm updates, policy changes, forced migrations such as AI Max) appear nowhere in the account

   When nothing in the log explains a move, list these as possible causes instead of inventing one.

## Quality checks

Before finishing, confirm:

- Every applied change from the batch has an entry with a reason and a review date.
- Every outcome cites numbers, both windows, and any overlapping changes.
- Reconcile results were shown to the person, not filed away quietly.
- Nothing in the log was invented. Unknown reasons say so.

## Reference files

| File | Read it when |
|---|---|
| `references/log-format.md` | Creating entries, reading the CSV, or interpreting reconcile output |
| `references/review-windows.md` | Setting or explaining review dates |
| `scripts/changelog.py` | Every log operation |
