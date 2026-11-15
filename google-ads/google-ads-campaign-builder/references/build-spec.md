# Build spec format

One JSON file per campaign build, saved as `google-ads-changes/<YYYY-MM-DD>-<campaign-slug>-build.json`. The validator, the plan renderer, and the Editor builder all read it. Write it by hand from the brief, the keyword work, and the copy; don't invent fields the scripts don't read.

## Example (shortened)

```json
{
  "name": "2026-11-15 Search - Water Heaters - Richmond",
  "account_id": "482-913-5521",
  "account_name": "Riverbend Plumbing",
  "currency": "USD",
  "time_zone": "America/New_York",
  "created": "2026-11-15",
  "approved_by": "",
  "approved_at": "",
  "brief": "New non-brand Search campaign for water heater installs in Richmond. Goal: booked visits and calls.",
  "sources": {
    "S1": {"type": "context", "where": ".agents/google-ads-context.md, Business and offer",
           "text": "Licensed Virginia Class A contractor (DPOR license)"},
    "S4": {"type": "context", "where": ".agents/google-ads-context.md, Business and offer",
           "text": "$75 off tankless water heater installation, ends 2026-12-31. New installs only.", "expires": "2026-12-31"},
    "S5": {"type": "page", "where": "https://example.com/water-heaters",
           "text": "Same-day service when you call before noon, Monday to Friday", "confirmed": false}
  },
  "campaign": {
    "name": "Search - Water Heaters - Richmond",
    "type": "search",
    "status": "paused",
    "monthly_budget": 1200,
    "daily_budget": 39.47,
    "budget_source": "Person: $1,200 a month of the $3,000 account budget",
    "bid_strategy": "maximize_conversions",
    "bid_strategy_reason": "Tracking works; no conversion history for this service yet.",
    "conversion_goals": {"primary": ["Booking form submit", "Calls from ads"], "tracking_ready": true,
                         "conversions_30d": "MISSING", "source": "context Conversions table"},
    "networks": {"google_search": true, "search_partners": false, "display": false},
    "location_option": "presence",
    "locations": [{"name": "Richmond, Virginia, United States"},
                  {"radius": 10, "unit": "mi", "lat": 37.5407, "lng": -77.4360, "label": "the shop"}],
    "excluded_locations": [{"name": "Petersburg, Virginia, United States"}],
    "ad_schedule": [{"days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"], "start": "07:00", "end": "19:00"}],
    "schedule_reason": "Calls matter; the office answers 7 to 7 on weekdays",
    "ai_max": {"enabled": false, "text_customization": false, "final_url_expansion": false,
               "reason": "Launch on phrase and exact with chosen pages; revisit after steady conversions."},
    "eu_political_ads": "no",
    "shared_negative_lists": []
  },
  "negatives": [
    {"keyword": "jobs", "match_type": "phrase", "source": "terms_we_dont_want"}
  ],
  "ad_groups": [
    {
      "name": "Water Heater Installation",
      "theme": "People who want a water heater installed",
      "final_url": "https://example.com/water-heaters/installation",
      "status": "paused",
      "keywords": [
        {"text": "water heater installation", "match_type": "phrase", "source": "planner_export",
         "avg_monthly_searches": "1K to 10K", "volume_source": "Keyword Planner export 2026-11-15, Richmond area"},
        {"text": "water heater installer", "match_type": "phrase", "source": "seed"}
      ],
      "negatives": [{"keyword": "tankless", "match_type": "phrase", "source": "structure"}],
      "ads": [
        {
          "final_url": "https://example.com/water-heaters/installation",
          "path1": "water-heaters", "path2": "installation",
          "headlines": ["Water Heater Installation", {"text": "Licensed Class A Contractor", "source": "S1"}],
          "descriptions": [{"text": "Licensed Virginia Class A contractor installing water heaters in Richmond.", "source": "S1"},
                           "Book a visit online and pick a time that works for you."]
        }
      ]
    }
  ],
  "sitelinks": [
    {"text": "Book a Visit Online", "description1": "Pick a time that works for you",
     "description2": "Richmond, Henrico, Chesterfield", "final_url": "https://example.com/book"}
  ],
  "callouts": [{"text": "Book Online Anytime"}, {"text": "Licensed Contractor", "source": "S1"}]
}
```

## Top level

| Field | Required | Notes |
|---|---|---|
| `name` | Yes | Date and campaign name |
| `account_id`, `account_name` | Yes | From the context file or connector |
| `currency`, `time_zone` | Yes, or MISSING | From the account |
| `created` | Yes | YYYY-MM-DD |
| `approved_by`, `approved_at` | Empty until approval | The Editor builder refuses to run without `approved_by` |
| `brief` | Yes | The brief as understood, in two or three sentences. It becomes the reason in the change log. |
| `sources` | Yes when any line makes a claim | ID to source object (below) |
| `campaign` | Yes | One campaign per build |
| `negatives` | No | Campaign-level negatives |
| `ad_groups` | Yes | At least one |
| `sitelinks`, `callouts` | Recommended | Campaign-level assets |

## Sources

| Field | Notes |
|---|---|
| `type` | `context` (approved in the context file), `person` (approved by the person in this conversation), or `page` (seen on the website) |
| `where` | The file and section, the conversation date, or the page URL |
| `text` | The approved wording, copied exactly. Every number an ad line uses must appear here. |
| `confirmed` | For `page` sources: `true` only after the person confirms it |
| `expires` | YYYY-MM-DD for offers with an end date |

## Campaign

| Field | Required | Values and notes |
|---|---|---|
| `name` | Yes | Must not match an existing campaign |
| `type` | No | `search` (the only type built) |
| `status` | No | `paused` (the only value allowed) |
| `daily_budget` | Yes | In account currency |
| `monthly_budget` | No | When the person gave a monthly amount; the validator checks `daily_budget` equals it divided by 30.4 |
| `budget_source` | Yes | Where the budget came from |
| `bid_strategy` | Yes | `maximize_conversions`, `target_cpa`, `maximize_conversion_value`, `target_roas`, `maximize_clicks`, or `manual_cpc` |
| `target_cpa` / `target_roas` | For those strategies | Target ROAS as a ratio: 4 means 400% |
| `target_source` | With a target | Where the number came from |
| `max_cpc_limit` | Recommended for `maximize_clicks` | Maximum CPC bid limit |
| `expected_cpc`, `expected_cpc_source` | No | Only from account history or a keyword tool; used for clicks a day in the plan |
| `bid_strategy_reason` | Yes | One or two sentences for the plan |
| `conversion_goals` | Yes | `primary` (action names), `tracking_ready` (true only when checked), `conversions_30d` (a number from data, or "MISSING"), `has_values` (true for value-based bidding), `source` |
| `networks` | Yes | `google_search: true`, `search_partners`, `display`; `reason` required if either is true |
| `location_option` | Yes | `presence` or `presence_or_interest` (needs `location_option_reason`) |
| `locations` | Yes | Each `{"name": ..., "id": ...}` (id optional) or `{"radius": 10, "unit": "mi", "lat": ..., "lng": ..., "label": ...}` |
| `excluded_locations` | No | `{"name": ...}`; set by hand in Editor |
| `ad_schedule` | No | `{"days": [...], "start": "HH:MM", "end": "HH:MM"}`, English day names, 24-hour clock |
| `schedule_reason` | With a schedule | |
| `start_date`, `end_date` | No | YYYY-MM-DD, today or later |
| `ai_max` | Yes | `enabled`, `text_customization`, `final_url_expansion` (all true or false), `reason` |
| `eu_political_ads` | Yes | `no` or `yes`, from the person |
| `shared_negative_lists` | No | Names of existing lists to attach by hand |
| `expected_effect` | No | Goes into the change log |

Never include `languages`, `enhanced_cpc`, a campaign-level broad match setting, or Dynamic Search Ads fields. The validator rejects them.

## Ad groups

| Field | Required | Notes |
|---|---|---|
| `name` | Yes | Unique in the campaign |
| `theme` | Recommended | One line for the plan |
| `final_url` | Yes | The ad group's landing page, https |
| `status` | No | `paused` only |
| `max_cpc` | For `manual_cpc` | Default bid |
| `keywords` | Yes | Below |
| `negatives` | No | Ad group negatives, usually `structure` |
| `ads` | Yes | 2 recommended, 3 at most |

**Keywords:** `text` (no brackets or quotes), `match_type` (`exact`, `phrase`, `broad`), `source` (`seed`, `site`, `keyword_tool`, `planner_export`, `account_history`, `web`, `context`), optional `avg_monthly_searches` and `volume_source` (only for `keyword_tool` and `planner_export`, copied exactly from `keyword_list.py` output), optional `max_cpc` (Manual CPC only), `status` (`paused` only).

**Negatives** (campaign or ad group): `keyword`, `match_type`, `source` (`terms_we_dont_want`, `person`, or `structure`), optional `reason`.

**Ads:** `final_url` (defaults to the ad group's), `path1`, `path2`, `headlines` and `descriptions`. Each line is either a plain string (no claim) or `{"text": ..., "source": "S1"}`. A line may carry `"pin": 1` for legally required text; pins are set by hand. `status` is `paused` only.

## Sitelinks and callouts

**Sitelinks:** `text`, `description1`, `description2`, `final_url`, optional `source` (covers the text and both lines).

**Callouts:** `text`, optional `source`.
