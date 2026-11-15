# Exports when there's no connector

Ask only for what the review needs, all for the same date range, and say why each file is needed. Google moves menus often. If a path below doesn't match, tell the person to type the report or setting name into the search bar at the top of Google Ads.

For every download:
- Set the date range first. Use the review window from Step 1.
- Download as CSV. Don't filter the table first: filters hide rows silently.
- Add Impr., Clicks, Cost, Conversions, and Conv. value where the page lets you choose columns.

`scripts/normalize.py` reads these downloads as they are, including the title rows and Total rows.

## The core set (always)

| File | Where | Columns to add | Used for |
|---|---|---|---|
| Campaigns | Campaigns page | Campaign type, Bid strategy type, Budget, Target CPA or Target ROAS, Status | Settings, budget, and campaign totals |
| Campaigns by network | Campaigns page, Segment > Network (with search partners) | Same metrics | Search partners share for AI Max campaigns |
| Search terms | Insights and reports > Search terms, all campaigns | Match type, Source, Campaign, Campaign type, Ad group | Brand, competitor, irrelevant, and overlap checks |
| Search keywords | Audiences, keywords, and content > Search keywords | Match type, Status, Campaign | Overlap with your exact-match keywords |
| Conversions by action | Campaigns page, Segment > Conversions > Conversion action | Conversions, All conv. | Which actions the campaigns optimize toward |

Performance Max terms should appear in the Search terms report with a Source column. If they don't, open the Performance Max campaign and use Insights > Search terms insights, and note that this view groups terms into categories and may not show cost.

## Performance Max

| File | Where | Notes |
|---|---|---|
| Channel performance | Select the Performance Max campaign, then Insights and reports > Channel performance | Channel data exists only from June 1, 2025 |
| Placements | Insights and reports > Report editor > "Performance Max campaigns placement" | Impressions only. Add the "Performance Max placement type" column. |
| Asset group assets | Select the campaign > Asset groups > open each asset group's assets table | Asset type, Status, Added by. Also note the Ad strength shown for each asset group. |
| Expanded final URL assets | Campaign > Assets > "Expanded Final URL assets" tab | Which URLs final URL expansion used, with the assets served on them |
| Search themes | Asset group > Signals | Copy the search themes per asset group into the chat if there's no download |

## AI Max for Search

| File | Where | Notes |
|---|---|---|
| Landing pages | Insights and reports > Landing pages | Keep the "Selected by" column: it shows which pages AI Max chose |
| Search terms and ad combinations | Search terms report, view drop-down > "Search terms and ad combinations" | Headline and landing page per search term. Review on its own; it overlaps the main report. |

## Settings to read, not download

Ask the person to read these, or to send screenshots, for each AI Max and Performance Max campaign:

- **AI Max (Search campaigns):** on or off; text customization on or off; final URL expansion on or off; URL exclusions; brand inclusions and exclusions.
- **Performance Max:** final URL expansion on or off (campaign settings > Asset optimization); URL exclusions; brand exclusions; negative keywords or negative keyword lists attached.
- **Brand lists:** Tools > Shared library > Brand lists, with the brands in each list.
- **Placement exclusions:** the account's excluded placements list (under Content suitability or Brand safety, depending on the layout).
- **Recent changes:** Change history for the last 30 days, plus the dates AI Max was turned on (or migrated in September 2026) and the last target, budget, and asset changes.

## What to say when asking

> I can't connect to your Google Ads account in this chat, so I'll work from downloads. For a review of your Performance Max and AI Max campaigns from Oct 18 to Nov 14, I need:
> 1. The Campaigns page as CSV, with Campaign type, Bid strategy type, Budget, and Target CPA columns added
> 2. The Search terms report for all campaigns, all rows, with the Source and Campaign type columns
> 3. Your Search keywords, with Match type
> 4. The Channel performance table for each Performance Max campaign
> 5. The "Performance Max campaigns placement" report from the Report editor
>
> Also tell me which brand names and misspellings people use for your business, and whether your Performance Max campaigns have brand exclusions set.
