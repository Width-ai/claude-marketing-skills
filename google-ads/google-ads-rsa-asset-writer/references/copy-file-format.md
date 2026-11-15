Source tags adapted from rsa-ad-copy-writer in [Insightful-Pipe/google-ads-skills](https://github.com/Insightful-Pipe/google-ads-skills) (MIT, Copyright (c) 2026 InsightfulPipe).

# Copy file format

The copy file holds one batch of ad copy: the RSAs for one or more ad groups in one campaign, plus any sitelinks, callouts, and structured snippets. `scripts/check_ad_copy.py` checks it and `scripts/build_upload_files.py` turns it into a change set and Google Ads Editor files.

Save it as `google-ads-copy/<YYYY-MM-DD>-<short-name>.json`. In a chat with no project folder, keep it in the working directory and hand it to the person at the end with the other files.

## Example

```json
{
  "name": "2026-11-15 water heater RSA and assets",
  "account_id": "482-913-5570",
  "account_name": "Brightwater Plumbing",
  "created": "2026-11-15",
  "campaign": "Search - Water Heaters",
  "reason": "Ad group has one RSA rated Average with 8 headlines",
  "evidence": "Ad group spent $2,140 with 31 conversions, Oct 16 to Nov 14",
  "ad_groups": [
    {
      "ad_group": "Water Heater Repair",
      "final_url": "https://brightwaterplumbing.com/water-heaters",
      "landing_page_file": "landing-water-heaters.txt",
      "keywords": [
        {"text": "water heater repair", "conversions": 18, "clicks": 240},
        "water heater replacement"
      ],
      "rsas": [
        {
          "id": "rsa-a",
          "path1": "water-heaters",
          "path2": "austin",
          "headlines": [
            {"text": "Water Heater Repair Austin", "role": "keyword", "source": "keyword"},
            {"text": "Rated 4.9 Stars on Google", "role": "proof", "source": "context"},
            {"text": "Book Your Repair Today", "role": "cta", "source": "new"}
          ],
          "descriptions": [
            {"text": "Free in-home estimates on water heater replacement. Upfront pricing before work starts.", "role": "offer", "source": "context"}
          ]
        }
      ],
      "sitelinks": []
    }
  ],
  "sitelinks": [
    {"link_text": "Read Our Reviews", "description1": "4.9 stars on Google", "description2": "From 850+ local reviews", "final_url": "https://brightwaterplumbing.com/reviews"}
  ],
  "callouts": [{"text": "Serving Austin Since 1998"}],
  "snippets": [{"header": "Service catalog", "values": ["Water heater repair", "Tankless installs", "Drain cleaning"]}]
}
```

## Top-level fields

| Field | Required | Notes |
|---|---|---|
| `name` | Yes | Shown in reports and used as the change set name |
| `account_id`, `account_name` | Recommended | Copied into the change set |
| `created` | Recommended | `YYYY-MM-DD` |
| `campaign` | Yes | Exact campaign name as it is in the account |
| `reason`, `evidence`, `expected_effect` | Recommended | Copied into each `add_rsa` entry for the change log. An RSA can override them with its own. |
| `ad_groups` | Yes, unless the batch is assets only | List of ad groups, below |
| `sitelinks`, `callouts`, `snippets` | No | Campaign-level assets by default. Add `"level": "account"` to an item for account level. |

## Ad group fields

| Field | Required | Notes |
|---|---|---|
| `ad_group` | Yes | Exact ad group name |
| `final_url` | Yes | The landing page. An RSA can set its own `final_url`. |
| `keywords` | Recommended | Strings, or objects with `text`, `conversions`, `clicks`. The checker uses the top three (by conversions, then clicks) for the keyword coverage check. `--keywords keywords.csv` adds more from a normalized keyword file. |
| `landing_page_file` | Recommended | A text file with the landing page's words, relative to the copy file. The checker warns when an offer in the ad isn't on the page. |
| `rsas` | Yes | One to three RSAs |
| `sitelinks`, `callouts`, `snippets` | No | Ad-group-level assets |

## RSA fields

| Field | Required | Notes |
|---|---|---|
| `id` | Yes | Short and unique in the file, such as `rsa-a` |
| `headlines` | Yes | 3 to 15 items |
| `descriptions` | Yes | 2 to 4 items |
| `path1`, `path2` | No | Up to 15 characters each. `path2` needs `path1`. |
| `final_url` | No | Overrides the ad group's |

Each headline or description is an object (a plain string also works):

| Field | Notes |
|---|---|
| `text` | The words. Keyword insertion (`{KeyWord:Default text}`) and customizers (`{CUSTOMIZER.Name:Default text}`) are allowed; the checker counts them by their default text, as Google does. |
| `role` | `keyword`, `benefit`, `proof`, `offer`, `cta`, `brand`, `qualifier`, `objection`, `feature`, or `disclaimer`. Shown in the copy table. |
| `source` | Where the words came from, below |
| `pin` | `1`, `2`, or `3` for headlines; `1` or `2` for descriptions. Leave it out unless a line must always show in one place. |

## Source tags

Tag every line with where it came from, so the person can see why each line is there:

| Tag | Meaning |
|---|---|
| `keyword` | Built from a keyword in the ad group |
| `search_term` | Built from a search term people used |
| `kept` | An existing line that serves and converts, carried over on purpose. The checker doesn't warn that it's already running. |
| `context` | Uses an approved item from the context file's "Business and offer" section |
| `claims_file` | Uses an item from the approved-claims file |
| `landing_page` | Plain service or product words from the landing page. Never a number, price, rating, guarantee, or result. |
| `new` | New wording with no claim in it, such as a call to action |

## Asset fields

| Asset | Fields |
|---|---|
| Sitelink | `link_text` (25), `description1` and `description2` (35 each, both or neither), `final_url`, optional `level` at top level |
| Callout | `text` (25), optional `level` at top level |
| Structured snippet | `header` (one of Google's 13 headers), `values` (3 to 10, 25 each), optional `level` at top level |

Top-level assets take `level` `campaign` (the default) or `account`. Assets inside an ad group are ad group level.

## Approved-claims file

Use it for claims the person approves in the chat that aren't in the context file yet, or when there's no context file. Save it as `google-ads-copy/approved-claims.txt` and pass it to both scripts with `--claims`. One claim per line, with an optional kind in front (`offer:`, `price:`, `proof:`, `disclaimer:`; `proof` if none) and where the approval came from:

```text
# Approved in chat by Dana Ruiz on 2026-11-15
offer: Free second opinion on any water heater repair quote (approved by Dana Ruiz in chat, 2026-11-15)
proof: Angi Super Service Award 2025 (confirmed by Dana Ruiz in chat, 2026-11-15)
price: Water heater flush $129, through 2026-12-31
```

Write offer end dates as `ends YYYY-MM-DD`, `through YYYY-MM-DD`, or `until Dec 31, 2026`. The checker reads them: it rejects claims that rely on an ended offer, and it checks deadlines in the copy ("ends Friday", "this week only") against them. Never put a claim in this file that the person didn't approve, and suggest adding approved claims to the context file with the google-ads-account-context skill so they're there next time.
