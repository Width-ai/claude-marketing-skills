# Google Ads Editor import files for a new campaign

Google Ads Editor is free from Google. It shows every imported item as a pending change, and nothing reaches Google Ads until the person clicks **Post**. That makes it the safe way to create a campaign without a paid connector: Google's official Google Ads MCP server can't create campaigns, ad groups, keywords, or ads, and the google-ads-apply-changes skill's Editor builder only edits existing campaigns.

## Build the files

Only after the person approves the plan, with `approved_by` and `approved_at` filled in and every `page` source confirmed:

```bash
python3 scripts/build_editor_files.py google-ads-changes/2026-11-15-search-water-heaters-build.json \
  --out google-ads-changes/2026-11-15-search-water-heaters-editor/ \
  --context .agents/google-ads-context.md --existing google-ads-data/campaigns.csv \
  --template editor-export.csv \
  --changeset google-ads-changes/2026-11-15-search-water-heaters.json
```

It re-runs every validator check and stops on any error. Without approval it refuses, unless you pass `--include-unapproved` to make a draft for review (the manifest then says not to post it).

| File | Columns | Status written |
|---|---|---|
| `campaign.csv` | Campaign, Campaign Type (`Search`), Networks (`Google Search`), Budget, Bid Strategy Type, plus Target CPA, Target ROAS, Maximum CPC bid limit, Ad Schedule, Start Date, End Date when used, plus the export-only columns below when the template proves them, then Campaign Status | Paused |
| `locations.csv` | Campaign, Location (a name, or `(10mi:37.540700:-77.436000)` for a radius), Location ID when given | |
| `ad_groups.csv` | Campaign, Ad Group, Max CPC (Manual CPC only), Ad Group Status | Paused |
| `keywords.csv` | Campaign, Ad Group, Keyword, Criterion Type (`Exact`, `Phrase`, `Broad`), Max CPC (Manual CPC only), Status | Paused |
| `negatives.csv` | Campaign, Ad Group (blank for campaign level), Keyword, Criterion Type (`Campaign Negative Phrase`, `Negative Exact`, and so on) | |
| `ads.csv` | Campaign, Ad Group, Ad type (`Responsive search ad`), Headline 1 to 15, Description 1 to 4, Path 1, Path 2, Final URL, Status | Paused |
| `sitelinks.csv` | Campaign, Link Text, Description Line 1, Description Line 2, Final URL | |
| `callouts.csv` | Campaign, Callout text | |
| `rollback/pause_campaign.csv` | Campaign, Campaign Status | Paused |
| `manifest.md` | Import order, what each import should show, by-hand steps, launch and undo steps | |

Each file holds one item type with only the columns it needs, so blank cells can't be read as "clear this value". Files are UTF-16 and tab-separated, the format Editor writes when it exports. `--utf8` writes comma-separated UTF-8 instead.

`--changeset` writes a one-entry change set (action `other`) that the google-ads-change-log skill can log, and that google-ads-apply-changes accepts as a by-hand change.

## What's confirmed, and what isn't

Checked against Google Ads Editor Help in November 2026:

- **Documented column names:** Campaign, Campaign type, Campaign status, Networks, Budget (an alias of campaign daily budget), Bid strategy type, Target CPA, Target ROAS, Maximum CPC bid limit, Max CPC, Location, Location ID, Ad schedule, Start date, End date, Ad group, Ad group status, Keyword, Criterion type (an alias of Type), Status, Headline 1 to 15, Description 1 to 4, Path 1, Path 2, Final URL, Link Text, Description Line 1, Description Line 2, Callout text. Editor matches headers regardless of capitalization or spacing; headers must be in English.
- **Documented values:** Campaign type `Search`; status `Enabled` or `Paused`; Networks `Google Search` (Google Search only), `Search Partners`, and `Search` (meaning both); bid strategy types `Manual CPC`, `Maximize clicks`, `Maximize conversions`, `Target CPA`, `Maximize conversion value`, `Target ROAS`; Target CPA as a number and Target ROAS as a percentage; dates as YYYY-MM-DD; ad schedule as `(Monday[08:00-17:30])` joined with semicolons; radius as `(10mi:latitude:longitude)`.
- **Matching Editor's own exports, not a help page:** Ad type `Responsive search ad`, and negative criterion types written as `Negative Phrase` and `Campaign Negative Phrase` (Google's page documents the `Negative` and `Campaign negative` prefixes).
- **Not documented for import, so written only from the person's export:** the location option (`Targeting method`), `Budget type`, the `EU political ads` declaration, and the AI Max settings (`AI Max`, `Text customization`, `Final URL expansion`). With `--template`, the builder looks for each column in the person's export and a value that matches the meaning (for example a Targeting method value containing "presence" but not "interest"), and copies that exact spelling. If it finds none, the setting goes on the by-hand list.

## The template export

Ask the person for one export from their Editor: **Account > Export > Export whole account** (or selected campaigns), as CSV. It serves three jobs:

1. `validate_build.py --existing editor-export.csv` checks the new name against every campaign and the keywords against live keywords.
2. `build_editor_files.py --template editor-export.csv` copies the exact header spellings their Editor version uses.
3. The same flag copies value spellings for the undocumented settings above, when their account already uses them.

## Steps for the person

The manifest carries these, with the expected result after each import. Give them in your reply too:

1. Open Google Ads Editor, select the account, and click **Get recent changes**.
2. Check that no campaign with the new name exists.
3. **Account > Import > From file...**, one file at a time, in the manifest's order: campaign, locations, ad groups, keywords, negatives, ads, sitelinks, callouts.
4. In each import preview, check the headers and the counts. After the campaign file, Editor should show 1 new campaign and no changed campaigns. If it shows a changed campaign, the name matched an existing one: revert and rename.
5. Keep the order. A keyword or ad file imported before its ad group makes Editor create the ad group with default settings.
6. Do the by-hand steps from the manifest: AI Max off (or as decided), location option Presence, the EU political ads declaration, excluded locations, any radius without coordinates, any pins, shared negative lists, and the conversion goals check.
7. Click **Check changes** and fix what Editor flags. Look at the Ad strength column for the new ads.
8. Click **Post**. Everything arrives in Google Ads paused.
9. Reply in the chat when it's posted.

Before posting, any pending change can be reverted in Editor. After posting, the campaign is paused; nothing is deleted.

## After posting: verify

With a connector, read the new campaign back (use the name; fill in the ID from the first result). If a field errors, check it with the metadata tool.

```sql
SELECT campaign.id, campaign.name, campaign.status, campaign.advertising_channel_type,
       campaign.bidding_strategy_type, campaign_budget.amount_micros,
       campaign.network_settings.target_google_search,
       campaign.network_settings.target_search_network,
       campaign.network_settings.target_content_network,
       campaign.geo_target_type_setting.positive_geo_target_type
FROM campaign
WHERE campaign.name = '<CAMPAIGN NAME>'
```

Check: status `PAUSED`, channel `SEARCH`, search network and content network `false`, positive geo target type `PRESENCE`, budget (micros divided by 1,000,000) as planned. For AI Max, look up the campaign's AI Max setting field with the metadata tool (it sits under `campaign.ai_max_setting` in recent API versions) and confirm it matches the plan.

```sql
SELECT ad_group.name, ad_group.status, ad_group_criterion.keyword.text,
       ad_group_criterion.keyword.match_type, ad_group_criterion.negative, ad_group_criterion.status
FROM ad_group_criterion
WHERE campaign.id = <ID> AND ad_group_criterion.type = 'KEYWORD'
```

Count keywords and negatives in code and compare them with the build's counts. Without a connector, ask for a fresh Editor export of the new campaign and compare the same things.

## Log it

If the google-ads-change-log skill is installed, log the change set it wrote with `--applied-via editor`. Otherwise append one row to `.agents/google-ads-change-log.csv` with the columns listed in that skill's format (action `other`, entity type `campaign`, field `new campaign (paused)`, the brief as the reason). Editor changes don't appear in the change history connectors read, so the log is the record.

## Launch is a separate approval

Posting doesn't spend money: everything is paused. When the person says to launch, they (or a write-capable route they choose) enable the ads, keywords, and ad groups, then the campaign last. Suggest checking the search terms report in the first days, and reviewing results after about two weeks. Launching is a change to the account, so it goes through the person's approval like any other.
