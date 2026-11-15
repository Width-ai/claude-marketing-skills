Adapted from the Google Search playbook in [coreyhaines31/marketingskills](https://github.com/coreyhaines31/marketingskills) (MIT, Copyright (c) 2025 Corey Haines), the keyword and campaign creation references in [thalesholleben/skill-google-ads](https://github.com/thalesholleben/skill-google-ads) (MIT, Copyright (c) 2026 google-ads-manager contributors), the campaign builder in [Insightful-Pipe/google-ads-skills](https://github.com/Insightful-Pipe/google-ads-skills) (MIT, Copyright (c) 2026 InsightfulPipe), and the negative keyword rules in [AgriciDaniel/claude-ads](https://github.com/AgriciDaniel/claude-ads) (MIT, Copyright (c) 2026 Daniel Agrici).

# Structure, keywords, match types, and negatives

Facts here were checked against Google Ads Help in November 2026. Rules marked "practice" come from practitioners, not Google.

## 1. Campaigns: when to split

One build makes one Search campaign. Make a separate campaign when any of these differ, because each needs its own budget or bidding:

- **Brand vs. non-brand.** Brand searches are cheaper and convert better. In one campaign with shared money, brand takes the budget and hides how non-brand performs (practice).
- **Services with different economics.** A service with a much higher value or a different target CPA gets its own campaign and budget (practice).
- **Different locations or hours** that need their own budget.
- **Competitor terms**, if the competitor policy allows them: their costs and conversion rates differ from everything else (practice).

When volume is low, consolidate instead. A campaign that can't reach roughly 15 to 30 conversions a month gives Smart Bidding little to learn from, and every extra split thins the data further (practice). If the brief needs several campaigns, say so in the plan and build them one at a time, each with its own build file.

**Name** the campaign with the account's naming convention from the Campaign map. Without one, use `Search - <Service> - <Area>`. The name must not match an existing campaign: an Editor import with a matching name changes that campaign instead of creating a new one. The validator errors on a match with an enabled or paused campaign and warns on a removed one.

## 2. Ad groups: themes

- **One theme and one intent per ad group.** The test: can one ad answer every keyword in the group? If not, split it (practice). Google's Quality Score guidance also says to group closely related keywords by theme.
- **5 to 15 keywords is typical** (practice). The validator warns above 20. Don't build single-keyword ad groups in a new campaign; they split data that's already thin.
- **One landing page per ad group,** the most specific page for that theme. If two keywords need different pages or different promises, they belong in different ad groups.
- **Name ad groups for the theme,** such as "Water Heater Installation", not "AG1".
- **Separate by intent,** not just by words: someone hiring a provider, someone comparing options, and someone researching how to do it themselves want different ads. Research and do-it-yourself searches usually aren't worth buying for a service business (practice).

## 3. Keyword research without a paid tool

Use these sources, in this order. Record each keyword's source in the build spec.

| Source | `source` value | Search volumes? |
|---|---|---|
| Keywords and search terms that converted in this account for the same service (connector or exports) | `account_history` | No. Impressions aren't search volume. |
| A keyword ideas tool on a connected Google Ads tool, if one exists | `keyword_tool` | Yes, as the tool reports them |
| Keyword Planner in the Google Ads interface: **Tools > Planning > Keyword Planner > Discover new keywords**, with the seeds and the landing page, set to the campaign's locations, then **Download keyword ideas** | `planner_export` | Yes, as exported |
| The person's own terms | `seed` | No |
| The landing pages and site navigation | `site` | No |
| Web research: how competitors and directories name the service, common questions | `web` | No |

Notes on the sources:

- **Google's official Google Ads MCP server has no keyword ideas tool,** and Keyword Planner's API (`KeywordPlanIdeaService`) is blocked at the entry Explorer access level. A third-party connector may have one. Don't add a paid tool to get volumes; the Keyword Planner export is free in any Google Ads account.
- **Volumes come only from a tool or an export, copied as reported.** Keyword Planner often shows ranges ("1K to 10K") for accounts with little spend; keep the range. A blank volume means "below what Google reports", not zero. Everything else is MISSING. Never estimate a volume from impressions, from another keyword, or from memory.
- **Keyword Planner bids are top-of-page bid ranges,** not average CPCs. Don't present them as what a click will cost.
- **Planner CPCs are in the currency of the account** the person exported from.

Run every candidate list through the cleaner:

```bash
python3 scripts/keyword_list.py planner-export.csv seeds.txt --out google-ads-data/keyword-candidates.csv \
  --exclude "jobs,careers,diy,water heater rental" --competitors "Bluewater Plumbing" \
  --require "water heater,tankless" --themes "Tankless=tankless;Installation=install,installation;Replacement=replace,replacement,new"
```

It merges and deduplicates, lower-cases, strips match-type punctuation, copies reported volumes exactly, and flags keywords that are too long, use symbols Google rejects, use the retired "+" modifier, contain an unwanted term or a competitor name, lack a service word, or repeat another keyword's words in a different order. `--themes` assigns a draft theme by word; treat it as a starting point for the ad groups, not the answer.

**Leave out** candidates that:
- don't contain a word for the service (`no_service_word`)
- name a place outside the target area
- name another business, unless the competitor policy allows competitor keywords
- name something the business doesn't sell, or match Terms we don't want
- only ask what something means or how to do it yourself, unless the person wants that traffic
- repeat another keyword in a different order (Google treats them as duplicates)

Pass the cleaner's output to `validate_build.py --keyword-data`, which checks every volume in the build against it.

## 4. Match types

Google's definitions (Google Ads Help, keyword matching options):

- **Exact** matches searches with the same meaning or intent as the keyword.
- **Phrase** matches searches that include the keyword's meaning.
- **Broad** matches related searches, even without the keyword's words, using signals such as the landing page and the other keywords in the ad group. It's Google's default, and Google calls Smart Bidding critical when using it.
- **An exact keyword identical to the search wins** over phrase, broad, AI Max, and Performance Max for that search.

**At launch, in this skill:**

1. Add every chosen keyword as **phrase**.
2. Also add the core keywords as **exact**: the ones that converted in account history, the ones with the most reported volume, and the main term of each ad group. Exact keywords on core terms keep those searches in this campaign.
3. **No broad match at launch,** unless the account already has steady conversion volume for this kind of traffic, the campaign uses conversion-based Smart Bidding, and the person accepts it. Practitioners usually wait for roughly 30 conversions a month in the campaign, Smart Bidding, and a tight negative list (practice). The validator warns on any broad keyword.
4. Don't put the same keyword with the same match type in two ad groups. The validator errors on it.

Retired, never used: the broad match modifier ("+keyword"), and the campaign-level broad match setting (can't be created since August 3, 2026; broad now comes from broad keywords or AI Max's search term matching).

Write keywords in the spec without brackets or quotes; the match type goes in `match_type`.

## 5. The starting negatives

A new campaign has no search terms report yet, so its negatives come only from:

| `source` | Where it comes from |
|---|---|
| `terms_we_dont_want` | The context file's Terms we don't want |
| `person` | What the person adds in the interview |
| `structure` | Routing: keeping one ad group's searches out of another (for example "tankless" as a negative in the standard installation group), or keeping searches that belong to another campaign out of this one |

The context template calls Terms we don't want candidates for negatives after a search terms review. A new campaign has no report yet, so the plan lists each starting negative with its source for the person to approve.

Never add a generic starter list on your own. A loose one-word negative can block buyers: "free" blocks "free estimate", and "contractor" meant for job seekers blocks "general contractor near me". You may ask about common categories (jobs and careers, do-it-yourself, training and courses, used or rental), but add a term only when the person confirms it.

How negatives work (Google Ads Help, negative keywords):

- They don't match close variants, plurals, or misspellings. "job" doesn't block "jobs"; add both if both matter.
- **Broad negative** blocks searches containing all its words, in any order. **Phrase** blocks the words in that order. **Exact** blocks only that exact search.
- Accents count, and "&" and "and" are different.

In this skill:

- Write each negative as **phrase** by default. Use exact for one specific search, and broad only for a combination of words that's always wrong.
- Put routing negatives at the ad group level, and everything else at the campaign level.
- The validator errors when a negative would block a planned keyword, and warns when it touches a protected term. Brand terms are usually protected, so a brand negative in a non-brand campaign needs the person's explicit say-so, and the warning stays in the plan.
- If the account uses shared negative lists, list them in `shared_negative_lists`. They're attached by hand after import.

After launch, negatives come from the search terms report. That's ongoing management, not part of this build; the google-ads-search-terms-to-negatives skill handles it if it's installed.
