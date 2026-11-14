# Change set format

A change set is one JSON file per batch, saved as `google-ads-changes/<YYYY-MM-DD>-<short-name>.json`. The validator, the Editor file builder, and the change log all read it.

```json
{
  "name": "2026-11-14 search term negatives",
  "account_id": "123-456-7890",
  "account_name": "Acme Plumbing",
  "created": "2026-11-14",
  "approved_by": "",
  "approved_at": "",
  "changes": [
    {
      "id": "c1",
      "action": "add_negative",
      "level": "campaign",
      "campaign": "Search - Services",
      "keyword": "jobs",
      "match_type": "broad",
      "reason": "Job seekers, not customers",
      "evidence": "14 search terms with 'jobs', 61 clicks, $142, 0 conversions, Oct 18 to Nov 14",
      "expected_effect": "Saves about $150 a month with no lost conversions"
    }
  ]
}
```

Leave `approved_by` and `approved_at` empty until the person approves the batch. Set `"approved": false` on any single entry they reject; it stays in the file as a record but isn't applied.

## Fields on every change

| Field | Required | Notes |
|---|---|---|
| `id` | Yes | Short and unique in the batch: `c1`, `c2`, ... |
| `action` | Yes | One of the actions below |
| `campaign` | Yes, except `other` | Exact campaign name as it is in the account |
| `ad_group` | For ad group level changes | Exact ad group name |
| `reason` | Yes | Why, in a sentence. The change log needs it. |
| `evidence` | Strongly recommended | The data behind it, with the date range |
| `expected_effect` | Recommended | What should happen, so the review can check |
| `over_limit_approved` | Only when needed | `true` when the person approved going past a limit for this line |
| `approved` | No | `false` to exclude an entry the person rejected |

## Actions

| Action | Extra fields | Editor file | Notes |
|---|---|---|---|
| `add_negative` | `level` (`campaign` or `ad_group`), `keyword`, `match_type` | Yes | Needs a search terms review first |
| `remove_negative` | `level`, `keyword`, `match_type` | No | Connector or by hand |
| `add_keyword` | `keyword`, `match_type`, optional `max_cpc`, `final_url`, `status` | Yes | `status` defaults to paused |
| `set_status` | `entity` (`campaign`, `ad_group`, `keyword`), `from`, `to` (`enabled` or `paused`), plus `keyword` and `match_type` for keywords | Yes | Never `removed` |
| `set_budget` | `from`, `to` (daily amount in account currency) | Yes | Check whether the budget is shared |
| `set_keyword_bid` | `keyword`, `match_type`, `from`, `to` | Yes | Manual CPC campaigns only |
| `set_target` | `target_type` (`cpa` or `roas`), `from`, `to` | No | Connector or by hand. ROAS as a ratio, 4 means 400%. |
| `add_rsa` | `headlines` (3 to 15), `descriptions` (2 to 4), `final_url`, optional `path1`, `path2`, `status` | Yes | `status` defaults to paused |
| `other` | `description` | No | Anything else, applied by hand with written steps |

Match types are `exact`, `phrase`, or `broad`. Write keywords without brackets or quotes; the match type goes in `match_type`.

## Change log columns

When the google-ads-change-log skill isn't installed, append applied changes to `.agents/google-ads-change-log.csv` with these columns, so the log skill can read them later:

`id, logged_at, status, account_id, campaign, ad_group, entity_type, entity, action, field, before, after, reason, evidence, expected_effect, approved_by, applied_via, applied_at, review_on, outcome, notes, change_set`

`status` is one of proposed, approved, applied, verified, rejected, rolled_back. `applied_via` is connector, editor, ui, or script. `review_on` comes from the validator's per-change output.
