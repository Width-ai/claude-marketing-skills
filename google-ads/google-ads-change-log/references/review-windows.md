# Review windows

How long to wait after a change before judging it. `changelog.py add` sets `review_on` from this table. Bidding changes also add the account's conversion delay (`--conversion-lag`), because the last days before a review undercount conversions.

| Action | Wait (days) | Basis |
|---|---|---|
| `set_target`, `set_bid_strategy`, `set_keyword_bid` | 14 plus conversion delay | Google's Smart Bidding guidance: judge performance over at least two weeks, with the window ending one conversion delay in the past |
| `enable_ai_max` | 14 | Google's AI Max guidance: give it about two weeks before making certain changes |
| `add_assets` (Performance Max) | 21 | Google's Performance Max guidance: two to three weeks before replacing weak assets |
| `set_budget` | 7 | Default in this skill. A budget change shows up in spend within days. |
| `add_negative`, `remove_negative` | 14 | Default in this skill. Long enough to see whether volume or conversions dropped. |
| `add_keyword` | 14 | Default in this skill |
| `add_rsa` | 14 | Default in this skill. Low-volume ad groups may need longer to gather impressions. |
| `set_status` (pause or enable) | 7 | Default in this skill |
| `other` | 14 | Default in this skill |

Override any date with `--review-on YYYY-MM-DD` when the person wants a different one, or when volume is so low that the default window won't hold enough data. As a rough check, a window needs enough clicks to rule out the break-even conversion rate (see the data pull skill's `metrics.py zero-conv`).

## Other pacing rules worth knowing

- Demand Gen: Google advises changing bids by no more than 15% at a time, waiting about a week between changes, and allowing two weeks or 50 conversions before major changes.
- Budget-limited target CPA and target ROAS campaigns have spent toward their target, rather than beating it, since August 17, 2026. Comparisons that cross that date need care.
- Two changes to the same campaign inside one window can't be judged separately. Note the overlap in the outcome.
