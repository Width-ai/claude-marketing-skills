Adapted from the campaign setup and bidding references in [thalesholleben/skill-google-ads](https://github.com/thalesholleben/skill-google-ads) (MIT, Copyright (c) 2026 google-ads-manager contributors) and the bidding by conversion volume rules in the Google Search playbook in [coreyhaines31/marketingskills](https://github.com/coreyhaines31/marketingskills) (MIT, Copyright (c) 2025 Corey Haines).

# Campaign settings: defaults and reasons

Every setting in the plan shows its value and the reason. Platform facts below were checked in November 2026 against Google Ads Help, the Google Ads Developer Blog, and Google Ads Editor Help. They change; when something here looks out of date, check the account with the connector's metadata tool or Google Ads Help, and say in the plan what you couldn't confirm.

## Defaults at a glance

| Setting | Default in this skill | Change it when |
|---|---|---|
| Campaign type | Search | Never in this skill (see "Not covered") |
| Status | Paused, with every ad group, keyword, and ad | Never at build time; launching is a separate approval |
| Networks | Google Search only: search partners off, Display off | The person wants a deliberate test, with a reason recorded |
| Locations | The real service area from the context file or brief | Always set; Editor's default would target everywhere |
| Location option | Presence | The business wants people planning to visit or move (travel, relocation), with a reason recorded |
| Excluded locations | From the context file | Set by hand in Editor |
| Languages | Not set | Never: removed from Search |
| Ad schedule | All hours | Calls matter and nobody answers outside business hours |
| Budget | From the brief, as a daily amount | |
| Bid strategy | By tracking and conversion volume (table below) | |
| Conversion goals | The primary actions that measure real leads or sales | |
| AI Max | Off at launch | The person chooses it, knowing the trade-offs below |
| EU political ads | The person's answer | |

## Networks

Search campaigns can also show on Google's search partner sites and, through Display expansion, on the Display Network. Both stay optional settings in Google Ads. This skill turns both off:

- **Search partners:** traffic quality varies by site and Search campaigns can't control it site by site. Test it on its own later, comparing conversion rates (practice).
- **Display Network:** it spends Search budget on display placements, which convert very differently. Display left on in Search campaigns tops one auditor's 2026 list of the mistakes she finds most often (practice).

In Editor, the Networks value `Google Search` means Google Search only. `Search` means Google Search plus search partners.

## Locations and the location option

- List the real markets: cities, counties, regions, or a radius around an address. Never leave locations empty.
- Use the names as Google Ads shows them ("Richmond, Virginia, United States"). Add a Location ID only from Google's geo target list or the connector, never from memory.
- A radius needs the latitude and longitude of the center, from the person, their Google Business Profile, or a map they share. Without coordinates, it becomes a by-hand step.
- **Location option: Presence.** Google's options are "Presence or interest" (Google's default and recommendation: people in, regularly in, or showing interest in the locations) and "Presence" (people in or regularly in the locations). For a business that serves an area, people elsewhere who are only interested in it rarely become customers, so this skill uses Presence (practice). Exclusions use Presence by default.

## Languages

Not set. Google removed campaign-level language targeting from Search and AI Max for Search campaigns in late September 2026 (Google Ads Developer Blog, August 13, 2026). Search ads now match on the language of the ads and landing pages, along with the user's language settings. The API rejects language criteria on Search campaigns. Write the ads in the language customers search in; for a bilingual audience, use separate ad groups or campaigns with copy in each language.

## Ad schedule

All hours by default. Add a schedule only when calls matter and nobody answers outside business hours, or the business asks. Times use the account's time zone and a 24-hour clock, in 15-minute steps. Editor's format, which the builder writes: `(Monday[08:00-17:30]);(Tuesday[08:00-17:30])`.

## Budget

- The build stores a **daily** budget. If the person gives a monthly amount, store it in `monthly_budget`; the validator checks that the daily budget equals the monthly amount divided by 30.4.
- Google spends up to 30.4 times the average daily budget in a month, and up to twice the daily budget on a single day (Google Ads Help, average daily budget). `render_plan.py` shows both.
- If the context has a target CPA, the plan shows how many conversions a day the budget could buy at that CPA. The validator warns when the daily budget is below the target CPA.
- Clicks a day appear only when there's an expected CPC from account history (cost divided by clicks for similar campaigns) or a keyword tool. Keyword Planner's top-of-page bids are not an average CPC. Otherwise, MISSING.
- Since August 17, 2026, budget-limited Target CPA and Target ROAS campaigns spend toward their target instead of beating it (Google Ads Help). One more reason to start without a target and set it from real results.

## Bid strategy

First check whether conversion tracking works: the primary actions exist, they measure real leads or sales (the context file's Conversions table), and they recorded conversions recently (the connector query in `references/brief-interview.md`). Then pick by primary conversions in the last 30 days for this kind of traffic in the account, counted in code. For a new service or a new account, that's usually 0 or MISSING.

| Situation | Strategy | Basis |
|---|---|---|
| Tracking not working or not confirmed | Fix tracking first. If the person must launch anyway: Maximize clicks with a Maximum CPC bid limit, or Manual CPC | Smart Bidding needs conversion tracking (Google). Practice for the fallback. |
| Tracking works, fewer than 30 conversions in 30 days (most new campaigns) | Maximize conversions, no target | Google says Target CPA can start without history but recommends judging it over 30 days with at least 30 conversions; starting without a target is common practice. Manual CPC if the person wants keyword-level control. |
| 30 or more steady conversions in 30 days for the same traffic (for example, rebuilding an existing campaign) | Target CPA, set at the last 30 days' average CPA adjusted for conversion delay, calculated in code | Google Ads Help, Target CPA |
| Real conversion values, 15 or more conversions in 30 days | Maximize conversion value, or Target ROAS from recent actual ROAS | Google Ads Help, Target ROAS (15 conversions in 30 days for Search) |
| Brand campaign that only needs visibility | Maximize conversions or Manual CPC here; Target impression share is set by hand after import if wanted | |

Rules:
- The context file's target CPA is the business goal and the break-even check. It isn't the launch bid target.
- Any target needs `target_source`: where the number came from.
- Since June 2026, Google calls "Maximize conversions with a target CPA" **Target CPA** and "Maximize conversion value with a target ROAS" **Target ROAS**. Same behavior; Editor and the API may still show older labels.
- Enhanced CPC ended in March 2025. Never propose it.
- Editor bid strategy values the builder writes: `Manual CPC`, `Maximize clicks`, `Maximize conversions`, `Target CPA`, `Maximize conversion value`, `Target ROAS` (Google Ads Editor Help). Target CPA is a plain number; Target ROAS is a percentage (`400%`).

## Conversion goals

- Name the primary conversion actions the campaign should bid for, from the context file, and say whether tracking was checked.
- New campaigns use the account's default conversion goals. If this campaign needs different ones, that's set in Google Ads after posting; it's on the by-hand list.
- Don't build a Smart Bidding campaign on an action nobody has checked. A page view or a click on a booking button isn't a lead.

## AI Max

**What it is.** A set of features inside a Search campaign, not a campaign type: search term matching (per ad group; matches searches beyond the keywords), text customization (campaign level; writes ad text from the site and ads), and final URL expansion (campaign level; sends people to the page Google picks; needs text customization; pins are ignored when it's on). Controls include brand inclusions and exclusions, URL inclusions and exclusions, and negatives.

**The default you're working against.** Google Ads Help says new Search campaigns have AI Max turned on by default, and Google Ads Editor 2.14 (reported November 12, 2026) turns on AI Max, text customization, and final URL expansion by default for new Search campaigns. Creating the old campaign-level broad match setting and automatically created assets has been blocked since August 3, 2026. Google auto-upgraded campaigns using them into AI Max from September 2026, and its Dynamic Search Ads auto-upgrade into AI Max begins in February 2027.

**This skill's default: off at launch.** Reasons to give the person:
- It works with conversion-based Smart Bidding and needs a budget that isn't limited; Google says it won't be effective in budget-limited campaigns.
- Final URL expansion can send traffic to pages you didn't choose, and ignores pins.
- Practitioner tests in 2026 measured weaker results than exact and phrase match (a four-month test reported an AI Max CPA of $100.37 against $52.69 for exact match; a study of 250+ retail campaigns reported roughly 35% lower ROAS). These are third-party findings reported by PPC Land, not Google's.
- A new campaign with a fresh keyword list is easier to read without it. It can be tested later as a deliberate change, waiting about 2 weeks before judging it (Google's guidance).

If the person wants it on, record `enabled: true` with the features they want, plan URL exclusions for pages that shouldn't get ad traffic, and plan weekly search term reviews. Either way, the campaign's AI Max state is a by-hand check in Editor before posting, because Google doesn't document the Editor import columns for it. If the google-ads-ai-max-pmax-review skill is installed, it can review AI Max after launch.

## EU political ads

Google requires every new campaign to declare whether it contains EU political advertising. Ask the person; never assume. Campaigns that declare yes don't serve in the EU. The declaration is a by-hand step in Editor unless the person's Editor export shows the column and value spelling.

## Pre-launch checks outside the build

List these in the plan for the person:
- **Auto-applied recommendations** (account level): practitioners turn them off, because they can add broad keywords, change targeting, and rewrite ads.
- **Conversion tracking** fires on a real test conversion.
- **Landing pages** load, match the ads, and show the claims the ads make.
- **Billing** is set up and the account has no spending limit about to run out.

## Not covered by this version

- Performance Max, Shopping, Demand Gen, Display, Video, and App campaigns.
- Changes to existing campaigns (use the google-ads-apply-changes skill).
- Structured snippets, call, image, price, promotion, and lead form assets.
- Shared budgets, portfolio bid strategies, campaign total budgets, experiments, and audience targeting.
- Never built because they're retired or blocked: Enhanced CPC, broad match modifier, expanded text ads, call-only ads, Smart campaigns, Dynamic Search Ads, and the campaign-level broad match setting.
