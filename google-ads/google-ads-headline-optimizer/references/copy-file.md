
# The copy file

The copy file holds the ad's new headline set: every live headline you're keeping, copied exactly, plus the new ones. `scripts/check_ad_copy.py` checks it, `scripts/plan_swap.py` compares it with the live ad, and `scripts/build_upload_files.py` turns it into a new paused ad when that's the route. It uses the same format as the google-ads-rsa-asset-writer skill.

Save it as `google-ads-copy/<YYYY-MM-DD>-headlines-<ad group>.json`. In a chat with no project folder, keep it in the working directory and hand it to the person at the end with the other files.

## Example

```json
{
  "name": "2026-11-16 headline test, Water Heater Repair",
  "account_id": "482-913-5570",
  "account_name": "Brightwater Plumbing",
  "created": "2026-11-16",
  "campaign": "Search - Water Heaters",
  "reason": "Three headlines lag the rest of the ad or rarely show",
  "evidence": "Oct 17 to Nov 15: 'Call Now For Fast Service' 0 impressions; 'Quality Service You Can Trust' CTR 3.5% vs 5.2% for the other headlines",
  "expected_effect": "Higher CTR on the variation, with conversions per impression no lower",
  "ad_groups": [
    {
      "ad_group": "Water Heater Repair",
      "final_url": "https://brightwaterplumbing.com/water-heaters",
      "keywords": [{"text": "water heater repair austin", "conversions": 20, "clicks": 210}],
      "rsas": [
        {
          "id": "rsa-a",
          "path1": "water-heaters",
          "path2": "austin",
          "headlines": [
            {"text": "Water Heater Repair Austin", "role": "keyword", "source": "kept", "pin": 1},
            {"text": "Same-Day Water Heater Service", "role": "benefit", "source": "kept"},
            {"text": "Rated 4.9 Stars on Google", "role": "proof", "source": "kept"},
            {"text": "Emergency Water Heater Repair", "role": "keyword", "source": "search_term"},
            {"text": "Get Your Hot Water Back", "role": "benefit", "source": "new"}
          ],
          "descriptions": [
            {"text": "Upfront pricing before any work starts. Licensed, insured, and local to Austin.", "source": "kept"},
            {"text": "Free in-home estimates on water heater replacement. Book online in minutes.", "source": "kept"}
          ]
        }
      ]
    }
  ]
}
```

## Rules for this skill

- **One ad group, one RSA:** the ad being optimized. `plan_swap.py` refuses anything else.
- **Kept lines are copied exactly** from the live ad, character for character, with `"source": "kept"`. Google treats a change in capitals or spacing as a new line with no history, and `plan_swap.py` fails it.
- **Keep the live pins** on kept lines unless the person asked to change them. `pin` is `1`, `2`, or `3` for headlines.
- **Descriptions, paths, and the final URL stay as they are live.** Copy them in so the checker and the builder have the whole ad. This skill changes headlines only.
- **Live lines you're removing are left out.** `plan_swap.py` lists them.

## Fields

| Field | Required | Notes |
|---|---|---|
| `name` | Yes | Shown in reports and used as the change set name |
| `account_id`, `account_name`, `created` | Recommended | Copied into the change set |
| `campaign` | Yes | Exact campaign name |
| `reason`, `evidence`, `expected_effect` | Recommended | Copied into the change set for the change log. Put the analyzer's numbers in `evidence`, with the dates. |
| `ad_groups[].ad_group`, `final_url` | Yes | Exact ad group name and the live final URL |
| `ad_groups[].keywords` | Recommended | Top converting keywords, as strings or `{"text", "conversions", "clicks"}`. The checker uses the top three for its keyword coverage check. |
| `ad_groups[].landing_page_file` | No | A text file with the landing page's words. The checker warns when an offer in the ad isn't on the page. |
| `rsas[].id` | Yes | Short, such as `rsa-a` |
| `rsas[].headlines` | Yes | 3 to 15 items |
| `rsas[].descriptions` | Yes | The live descriptions, 2 to 4 |
| `rsas[].path1`, `path2` | No | The live display paths |

Each headline is an object with `text`, `role` (`keyword`, `benefit`, `proof`, `offer`, `cta`, `brand`, `qualifier`, `objection`, `feature`, or `disclaimer`), `source`, and an optional `pin`.

## Source tags

| Tag | Meaning |
|---|---|
| `kept` | A live line carried over exactly |
| `keyword` | Built from a keyword in the ad group |
| `search_term` | Built from a search term people used |
| `context` | Uses an approved item from the context file's "Business and offer" section |
| `claims_file` | Uses an item from the approved-claims file |
| `landing_page` | Plain service or product words from the landing page. Never a number, price, rating, guarantee, or result. |
| `competitor_gap` | An angle competitors use that the ad lacked, written in the business's own words, with any claim approved |
| `new` | New wording with no claim in it, such as a call to action |

## Approved-claims file

For claims the person approves in the chat that aren't in the context file yet, or when there's no context file. Save it as `google-ads-copy/approved-claims.txt` and pass it to the checker and the builder with `--claims`. One claim per line, with an optional kind in front (`offer:`, `price:`, `proof:`, `disclaimer:`; `proof` if none) and where the approval came from:

```text
# Approved in chat by Dana Ruiz on 2026-11-16
proof: 1-year labor warranty on every repair (approved by Dana Ruiz in chat, 2026-11-16)
offer: $50 off water heater repair, through 2026-12-31
```

Write offer end dates as `ends YYYY-MM-DD`, `through YYYY-MM-DD`, or `until Dec 31, 2026`; the checker rejects claims that rely on an ended offer. Never put a claim here that the person didn't approve. Suggest adding approved claims to the context file with the google-ads-account-context skill, so they're there next time.
