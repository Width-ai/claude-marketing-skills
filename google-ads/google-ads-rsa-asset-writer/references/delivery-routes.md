# Getting the copy into the account

This skill never writes to the account itself. After the person approves the copy, it goes in by one of the routes below, and every new ad starts paused.

## Pick the route

| What | Best route | Other routes |
|---|---|---|
| New RSAs | The google-ads-apply-changes skill, if installed: a change set with one `add_rsa` entry per ad | This skill's Editor file `ads.csv`; or by hand in Google Ads |
| Sitelinks, callouts, snippets | This skill's Editor files: they create and link the assets in one import, and nothing goes live until the person posts | Google's official Google Ads MCP server can create the assets (with a dry run and a confirm step), but the person then links them by hand; or by hand in Google Ads |
| Pins | By hand on the paused ad, before it's enabled | Neither `add_rsa` nor this skill's Editor files carry pins |

## Build the files

```bash
python3 scripts/build_upload_files.py google-ads-copy/2026-11-15-water-heaters.json \
  --context .agents/google-ads-context.md \
  --change-set google-ads-changes/2026-11-15-rsa-water-heaters.json
```

The builder runs the checker first and refuses to build while any error remains. Pass the same `--context` and `--claims` you passed to the checker.

## Route 1: through google-ads-apply-changes

The change set holds:

- one `add_rsa` entry per RSA, with headlines, descriptions, final URL, paths, `"status": "paused"`, and the reason and evidence from the copy file
- one `other` entry per RSA that has pins, with the exact pins to set by hand
- one `other` entry per set of sitelinks, callouts, or snippets, naming the Editor file that holds them

Hand it to apply-changes: it takes a fresh snapshot, runs its own validator, shows the preview, gets approval, applies the RSAs, and logs everything. Its `other` entries are applied by hand, so build the Editor files too (Route 2) and give the person both: the change set for the ads, and `sitelinks.csv`, `callouts.csv`, and `structured_snippets.csv` for the assets.

Keyword insertion and customizers: apply-changes' validator counts the token text literally, so `{KeyWord:Tankless Water Heaters}` reads as 32 characters even though Google counts the 22-character default. If its validator rejects a token line that `check_ad_copy.py` passed, send that ad through Route 2 and tell the person why.

## Route 2: Google Ads Editor files (works without apply-changes)

After the person approves the copy in the chat:

```bash
python3 scripts/build_upload_files.py google-ads-copy/2026-11-15-water-heaters.json \
  --context .agents/google-ads-context.md \
  --editor-dir google-ads-changes/2026-11-15-rsa-water-heaters-editor/ \
  --approved-by "Dana Ruiz"
```

Use `--draft` instead of `--approved-by` for a preview; the manifest then says not to post it.

| File | Columns |
|---|---|
| `ads.csv` | Campaign, Ad Group, Ad type, Headline 1 to 15, Description 1 to 4, Path 1, Path 2, Final URL, Status (Paused). The same layout apply-changes uses. |
| `sitelinks.csv` | Campaign, Ad Group (only for ad-group-level rows), Link text, Description line 1, Description line 2, Final URL |
| `callouts.csv` | Campaign, Ad Group (when needed), Callout text |
| `structured_snippets.csv` | Campaign, Ad Group (when needed), Header, Snippet Values (separated by semicolons) |
| `manifest.md` | Import order, the pins to set by hand, what to check before posting, the import steps, and how to undo |

Account-level assets get `<Account-level>` in the Campaign column, as Google's Editor help describes. The column names come from Google's Editor help (Add sitelinks, and the CSV column list). Files are UTF-16 and tab-separated; if Editor won't read them, rebuild with `--utf8`. If the import preview doesn't recognize a column, ask the person to export a small sample from their Editor and rebuild with `--template that-export.csv` to copy its header spellings.

Two things the person should know before posting, both in the manifest:

- **Assets have no paused state in these files.** Sitelinks, callouts, and snippets show with the campaign's live ads as soon as they're posted. To hold them back, import them later.
- **The snippet value separator isn't documented.** Google's Editor help names the Snippet Values column but not how to separate values. The builder uses semicolons, as Editor does for other multi-value cells. The person checks the import preview shows each value separately, or adds the snippet by hand.

Give the person the files and these steps (also in the manifest):

1. Open Google Ads Editor, select the account, and click **Get recent changes**.
2. Go to **Account > Import > From file...** and pick the first file in the manifest's order.
3. In the preview, check every column header is recognized. Fix any from the drop-down.
4. Finish the import. Rows become pending changes; nothing is live yet.
5. Repeat for each file.
6. Review the pending changes. A new campaign or ad group you didn't expect means a name didn't match: revert it.
7. Click **Check changes**, fix anything Editor flags, then **Post**.
8. Reply in the chat when it's posted, so the changes can be checked and logged.

## Route 3: assets through Google's official MCP server

Use this when the person wants the sitelinks, callouts, or snippets created through the connector rather than Editor. The official server (googleads/google-ads-mcp) has a create-asset tool for SITELINK, CALLOUT, and STRUCTURED_SNIPPET assets. It can't create ads, and it can't link assets to campaigns or ad groups. Tool names have changed between releases, so find the tool by its description.

1. Confirm the customer ID matches the copy file's account.
2. For each asset, call the create-asset tool with its default dry run (`validate_only` true). For a sitelink, pass the link text, both description lines, and the final URL in `final_urls`. For a callout, the callout text. For a snippet, the header and the values.
3. Show the person the change items the dry run returns, and get approval for the whole set.
4. Repeat each call with the same parameters, `validate_only` false, and the checksum the dry run returned. Never change a parameter between the two calls; the server rejects a mismatch.
5. Read the new assets back with a GAQL query on `asset` (filter by `asset.type` and the text).
6. Give the person the linking steps. The assets don't show anywhere until they're linked, which makes this the route to use when they want assets held back. In Google Ads: open the campaign (or ad group), go to **Ads & assets > Assets**, click **+**, choose the asset type, pick the level, and select the new assets from the existing ones instead of creating new ones. Google moves menu items now and then; the search bar at the top of Google Ads finds the Assets page.

If a write fails or times out, read the asset back before retrying. Never create the same asset twice on a guess.

## Route 4: by hand

When neither Editor nor a connector is available, give numbered steps for the Google Ads interface, using the exact text from the copy table:

- **New RSA:** open the ad group, go to **Ads**, click **+**, choose **Responsive search ad**, enter the final URL, paths, headlines, and descriptions, set any pins with the pin icon next to each line, and save it paused.
- **Sitelinks, callouts, snippets:** open the campaign (or ad group), go to **Assets**, click **+**, choose the type and level, and enter each one.

Wait for the person to confirm it's done.

## After it's live

- **Verify.** Pull the new ads and assets again (connector or a fresh export) and compare them with the copy file, line for line.
- **Log.** Record the batch in the change log. If the google-ads-change-log skill is installed, use it with the change set. Otherwise append rows to `.agents/google-ads-change-log.csv` with these columns: `id, logged_at, status, account_id, campaign, ad_group, entity_type, entity, action, field, before, after, reason, evidence, expected_effect, approved_by, applied_via, applied_at, review_on, outcome, notes, change_set`. Use `add_rsa` for ads and `add_assets` for sitelinks, callouts, and snippets; `applied_via` is connector, editor, or ui. Set `review_on` 14 days after the ad goes live, longer for low-volume ad groups.
- **Remind.** New ads are paused. Tell the person to enable each one after looking at it, pausing an old ad first if the ad group already has 3 enabled. Offers with end dates need the ad paused or edited by then.

## Never

- Write ads or assets to the account without the person's approval of the exact copy.
- Create ads enabled, unless the person asks for that when they approve.
- Delete or remove ads or assets. Pause instead, and leave removal to the person.
