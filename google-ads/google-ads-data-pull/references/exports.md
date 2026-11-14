# Asking for exports

Use this when no Google Ads connector is available. Ask only for the datasets the question needs, all for the same date range, and say why each is needed. Google moves menu items now and then; if a path below doesn't match, tell the person to type the report name into the search bar at the top of Google Ads.

For every download:
- Set the date range first (top right of most pages). For a comparison, download the same report twice: once for this period, once for the period before it.
- Download as CSV (the download icon above the table).
- Don't filter the table before downloading unless asked. Filters hide rows silently.
- Include these columns where the page lets you pick: Impr., Clicks, Cost, Conversions, Conv. value. Ratio columns (CTR, Avg. CPC, Cost / conv.) are fine to leave in; the normalizer drops them and recomputes.

## Google Ads web interface

| Dataset | Where | Columns to add | Notes |
|---|---|---|---|
| Campaigns | Campaigns page | Campaign type, Bid strategy type, Budget, Search impr. share, Search lost IS (budget), Search lost IS (rank) | Add a "Segment by day" if you need a daily trend |
| Ad groups | Ad groups page | Status | |
| Keywords | Search keywords page (under Audiences, keywords, and content in most layouts) | Match type, Quality Score, Max. CPC | Positives only |
| Negative keywords | Negative search keywords page, same section | Level, Match type | Include negative keyword lists from the Shared library if the account uses them |
| Search terms | Search terms page (under Insights and reports in most layouts) | Match type, Added/Excluded, Campaign, Ad group, Keyword | Download all rows, not just the first page |
| Ads | Ads page | Ad strength, Status, Final URL | |
| Conversions by action | Campaigns page, segmented by Conversions > Conversion action | Conversions, Conv. value | Cost won't show per action; that's expected |
| Conversion actions | Goals > Summary (or Conversions) | Action optimization (primary or secondary), Count, Click-through window | |
| Change history | Change history (under Tools or the account menu) | User, Tool, Changes | The Tool column shows which tool made each change |

## Google Ads Editor

Editor exports are good for structure: campaigns, ad groups, keywords with match types, negatives at every level, and ads with their text. They don't carry performance data unless statistics were downloaded.

1. Open Editor and download the account (or Get recent changes if it's already downloaded).
2. Select the campaigns needed in the tree, or the whole account.
3. Use Account > Export > Export selected campaigns (or Export whole account) as CSV.

Editor saves UTF-16, tab-separated files. `normalize.py` reads them as they are; don't convert them.

## What to say when asking

Keep it short and concrete. For example:

> I can't connect to your Google Ads account in this chat, so I'll work from exports. For this question I need two downloads, both for Oct 18 to Nov 14:
> 1. The Search terms report, all rows, as CSV
> 2. The Campaigns page with Impr., Clicks, Cost, and Conversions, as CSV
>
> The second one lets me check how much of your traffic the search terms report actually shows.
