# Acting on the verdicts

`scripts/triage.py` writes the steps for each verdict into `triage.md`. This file explains them, covers what the script can't, and holds the auto-apply and optimization score notes. Nothing here is done by an agent: the person applies, dismisses, and sets up experiments, or approves a change set that google-ads-apply-changes applies.

## Accept

**Through a change set.** Accepted items that match an action google-ads-apply-changes supports go into `google-ads-changes/<date>-recommendations.json`, in that skill's change set format:

| Recommendation | Action | Notes |
|---|---|---|
| Raise budget, move unused budget | `set_budget` | Capped at the context's max budget change. Shared budgets change every campaign on them; the reason says so. |
| Loosen or set a target (campaign already has one) | `set_target` | `target_type` is `cpa` or `roas`, ROAS as a ratio. Capped at the max target change. |
| Add keywords | `add_keyword` | Created paused. Broad suggestions become phrase. |
| Remove redundant or non-serving keywords | `set_status` to `paused` | Pause, never delete. |
| Remove a conflicting negative that blocks a protected term | `remove_negative` | Only when the negative was found in the negatives pull. |

Each entry carries the recommendation's reason, the evidence with its window, the expected effect, and `source_recommendation` (the recommendation's ID). `approved_by` stays empty: google-ads-apply-changes validates the batch against the live account, shows a preview, and applies only what the person approves.

Tell the person not to use Google's Apply button for these. Apply takes Google's full suggested amount, past the limits, and leaves no reason in the change log. When a change is made outside the card, the card can stay up until Google recalculates; it isn't a sign the change failed.

**Without google-ads-apply-changes,** or for accepted items with no matching action (assets, ads, measurement, rotation, repairs), give the numbered interface steps from `triage.md`. Add:

- **Ads and assets:** write the text from the context file's approved offers, proof points, and brand voice, never Google's suggested wording, and have the person confirm every claim and URL. A copy skill can write it. New responsive search ads go in as `add_rsa` entries (created paused) once written.
- **Measurement:** the person or their site owner makes tracking changes. Never change conversion actions, goals, or tracking through a connector here.
- **Log it.** If google-ads-change-log is installed, log every applied change with its reason and review date. Otherwise append rows to `.agents/google-ads-change-log.csv` with the columns google-ads-apply-changes documents.

## Reject

The person dismisses rejected cards themselves:

1. Campaigns, Recommendations.
2. Find the card. The table view shows many at once and lets you select several.
3. Dismiss (or the three-dot menu, then Dismiss), and pick the closest reason.

Dismissed recommendations can come back when Google thinks they're relevant again. Dismissing also raises the optimization score, which is one more sign the score isn't a performance measure. Never dismiss through a connector or the API, even when a tool offers it.

## Test

Every test verdict comes with an experiment plan: the type, the change in the trial arm, a 50% split, the duration, the success metric, a guardrail, and the expected conversions per arm.

| Experiment | Use it for | Where |
|---|---|---|
| Custom experiment | Bid strategy and target changes, broad match, audience changes on Search, Display, and Video campaigns | Campaigns, Experiments, plus button, Custom |
| AI Max experiment | Turning on AI Max on a Search campaign | Campaigns, Experiments, plus button, Campaign features and settings, AI Max for Search campaigns |
| Performance Max experiments | Uplift (adding Performance Max), upgrade (Shopping or DSA into Performance Max), and optimization experiments such as Final URL expansion | Campaigns, Experiments, plus button |
| Network test | Search partners, Display expansion, video partners | No split: turn it on for one campaign and compare networks with Segment, Network |

Google notes for setup:

- Custom experiments support Search, Display, Video, and Hotel campaigns, not App or Shopping. Only eligible campaigns appear in the picker.
- Google's AI Max experiment flow excludes campaigns with text customization already on, Display network targeting, portfolio bid strategies, shared budgets, bidding exploration, or another active experiment. `triage.py` switches to a custom experiment when the budget is shared.
- Only one experiment runs at a time on a campaign. Schedule experiments to start in the future so ads finish review.
- Leave "Apply experiment changes if the trial wins" (the AI Max version says "if results are favorable") unchecked. The person decides after reading the result.
- Don't change the original campaign while the test runs.

**Reading the result.** Pull both arms for the measuring window, leaving out the settle days and the last days still affected by conversion delay. Compute CPA or ROAS and conversions for each arm in code (the copied `scripts/metrics.py compare` does this from two CSVs). Then:

- **Keep the change** when the trial arm gets more conversions or value and meets the target, and never crossed the guardrail.
- **End it early** when the trial arm's CPA or ROAS crosses break-even with enough conversions to trust it.
- **Call it directional** when per-arm volume was low, as the plan warned. Don't call a winner from a gap smaller than the plan's "clear" gap.

## Hold

A hold means one question decides it. Leave the card open (don't apply or dismiss) and ask the person the question in the reason, or pull the missing data and re-run. If the person answers with a decision, record it as an override row (`rec_id`, `verdict`, `reason`, `decided_by` with their name) and re-run, so the table stays generated by code.

## Auto-apply

Auto-apply lets Google apply recommendations of chosen types without asking. It skips the review this skill exists for.

- **Check it two ways.** The API's `recommendation_subscription` list shows the types it can see. Change history with `client_type` `GOOGLE_ADS_RECOMMENDATIONS_SUBSCRIPTION` shows what auto-apply actually changed in the last 30 days. Some interface types never appear in the API list, so always ask the person to open Recommendations, Auto-apply settings, and look.
- **Advice.** Turn off every type that can change spend, bids, keywords, targeting, ads, or tracking. "Use optimized ad rotation" can stay on. Practitioners widely advise switching auto-apply off; Claire Jarrett (April 2026) reports an account that fell from 15 leads a day to 2 after auto-applied changes.
- **To turn a type off:** Recommendations, Auto-apply settings, Manage tab, uncheck it, Save. The History tab shows what auto-apply changed, and Change history shows each change. An agent never changes auto-apply settings.
- **What it already changed.** For each auto-applied change in the window, judge the result since that date with the same rules (a keyword that spent without converting, a network that missed target). Changes older than 30 days are only in the interface's Change history.

## Optimization score

Say this plainly every time:

> Optimization score measures how much of Google's own advice the account has adopted, not how well it performs. Google calculates it from its open recommendations; applying or dismissing them changes it. Google says Quality Score doesn't use it.

Claire Jarrett (April 2026) reports a 95% score on a money-losing account and 40% on a profitable one. Report the score, never grade the account with it, and never accept a recommendation to raise it.
