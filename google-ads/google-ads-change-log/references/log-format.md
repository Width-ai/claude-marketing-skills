# Change log format

The log is a CSV at `.agents/google-ads-change-log.csv`, one per account (`.agents/google-ads-change-log-<customer-id>.csv` when you manage several). It opens in any spreadsheet app. Edit it with `changelog.py` so ids and review dates stay consistent.

## Columns

| Column | What goes in it |
|---|---|
| `id` | Sequential number, set by the script |
| `logged_at` | When the entry was written |
| `status` | proposed, approved, applied, verified, rejected, or rolled_back |
| `account_id` | Google Ads customer ID |
| `campaign`, `ad_group` | Exact names as in the account |
| `entity_type` | campaign, ad_group, keyword, campaign_negative, ad_group_negative, ad, or other |
| `entity` | The item, for example `jobs (broad)` or the campaign name |
| `action` | Same names as the change set: add_negative, remove_negative, add_keyword, set_status, set_budget, set_keyword_bid, set_target, add_rsa, other. The log also accepts set_bid_strategy, add_assets, and enable_ai_max for changes made by hand. |
| `field` | What changed: status, daily budget, max_cpc, target cpa, negative keyword |
| `before`, `after` | Values before and after |
| `reason` | Why, in the person's or the analysis's words. "reason not recorded" when unknown. |
| `evidence` | The data behind it, with the date range |
| `expected_effect` | What should happen |
| `approved_by` | Who approved it |
| `applied_via` | connector, editor, ui, or script |
| `applied_at` | When it went live |
| `review_on` | When to judge it, from `references/review-windows.md` |
| `outcome` | One line with numbers and windows, written at review |
| `notes` | Anything else, including overlapping changes |
| `change_set` | The change set file it came from |

## Statuses

- **proposed:** written down, not yet approved.
- **approved:** approved, not yet live.
- **applied:** live; gets a review date.
- **verified:** reviewed, with an outcome written.
- **rejected:** the person said no. Keep it; rejected ideas are worth remembering.
- **rolled_back:** undone, with the reason in `notes`.

## Change history client types

`reconcile` groups the account's unlogged changes by the tool that made them (`change_event.client_type`):

| client_type | Shown as |
|---|---|
| GOOGLE_ADS_WEB_CLIENT | Google Ads UI |
| GOOGLE_ADS_API | API tool or connector |
| GOOGLE_ADS_SCRIPTS | Google Ads Script |
| GOOGLE_ADS_AUTOMATED_RULE | Automated rule |
| GOOGLE_ADS_BULK_UPLOAD | Bulk upload |
| GOOGLE_ADS_RECOMMENDATIONS | Recommendation applied (often auto-apply) |
| INTERNAL_TOOL | Google internal tool |

Matching is by date (within a day) and by the kind of item changed, plus the campaign name when the history row has one. It's a best-effort match, so treat a "no match" as a question to check, not proof that something went wrong. Google Ads Editor changes never appear in the API's change history, which is why entries applied via `editor` are left out of matching.
