# Our Claude Marketing Skills | Get real value out of your claude subscription

Claude skills for the marketing work businesses do every week.

Each skill is a folder of instructions and reference files that Claude loads when a request calls for it, so you get the same process and the same quality checks every time instead of re-explaining the job in every chat.

Every skill comes with a guide that explains what it does, how it works, how to install it, how to use it, and how to fix common problems.

Built by [Width.ai](https://width.ai). Also see our [n8n workflow templates](https://github.com/Width-ai/n8n-workflows).

## Marketing areas

| Area | What's in it |
|---|---|
| [Google Ads](google-ads/) | Building, managing, and optimizing Google Ads accounts: campaign builds, ad copy, search terms, AI Max and Performance Max, recommendations, safe changes, change history |
| [SEO](seo/) | Search engine optimization research and content planning: People also ask questions and related searches |

More areas will be added as their first skills are ready.

## Skills

### Google Ads

- **[google-ads-account-context](google-ads/google-ads-account-context/)**: Builds the account context file the other Google Ads skills read first, covering approved offers and proof points, target and break-even CPA or ROAS, what each conversion action really measures, protected terms that negatives must never block, and what Claude may change without approval. Prefills from a connector and your website, then interviews for the rest. ([Guide](guides/google-ads/google-ads-account-context.md))
- **[google-ads-data-pull](google-ads/google-ads-data-pull/)**: Pulls Google Ads data through a connector that runs GAQL or through CSV exports, cleans it into standard tables, and computes every metric and period-over-period comparison in code, with the search terms report's hidden-traffic share and small-sample limits stated up front. ([Guide](guides/google-ads/google-ads-data-pull.md))
- **[google-ads-campaign-builder](google-ads/google-ads-campaign-builder/)**: Turns a brief into a complete new Search campaign (themed ad groups, keywords, starting negatives, ads, sitelinks, callouts, and settings) from your context file, landing pages, and keyword research. It checks every claim, limit, and setting in code, and returns a build plan to approve plus Google Ads Editor import files that create the campaign paused, with no paid connector needed. ([Guide](guides/google-ads/google-ads-campaign-builder.md))
- **[google-ads-rsa-asset-writer](google-ads/google-ads-rsa-asset-writer/)**: Writes responsive search ad headlines and descriptions, sitelinks, callouts, and structured snippets from the approved offers and proof in your context file, the landing page, and your keywords. A script checks Google's character limits, editorial rules, and every claim in the copy, so nothing like "20% off" gets in unless you approved it. New ads go in paused. ([Guide](guides/google-ads/google-ads-rsa-asset-writer.md))
- **[google-ads-search-terms-to-negatives](google-ads/google-ads-search-terms-to-negatives/)**: Reviews your search terms report (Search, AI Max, and Performance Max) with break-even statistics and word-pattern analysis, calling a search wasted only when its clicks prove it. Every proposed negative is checked against live keywords, converting searches, and protected terms, and you get a review table plus a batch of negatives and paused keywords ready to apply. ([Guide](guides/google-ads/google-ads-search-terms-to-negatives.md))
- **[google-ads-ai-max-pmax-review](google-ads/google-ads-ai-max-pmax-review/)**: Reviews AI Max and Performance Max campaigns from the advertiser's side: where spend went by channel, how much search traffic is brand, competitor, irrelevant, or a repeat of your exact keywords, whether brand exclusions are set, which landing pages Google picked and how they convert, and which placements are apps or junk sites. It respects Google's waiting periods and returns findings with evidence, a change set, and step-by-step fixes. ([Guide](guides/google-ads/google-ads-ai-max-pmax-review.md))
- **[google-ads-recommendations-triage](google-ads/google-ads-recommendations-triage/)**: Sorts every open Google Ads recommendation into accept, reject, or test, judged against the campaign's own numbers and your target and break-even CPA or ROAS, and flags the ones that mainly raise spend. You get a reason for each that names the numbers, a change set for accepted items, experiment plans for tests, and a check of whether auto-apply is on. ([Guide](guides/google-ads/google-ads-recommendations-triage.md))
- **[google-ads-apply-changes](google-ads/google-ads-apply-changes/)**: Checks proposed changes against the live account (misspelled campaign names, stale values, budget moves over your limits, negatives that would block converting searches, ad text over Google's limits), shows a before and after preview, gets approval, and applies the batch through a connector or as Google Ads Editor import files with rollback files. ([Guide](guides/google-ads/google-ads-apply-changes.md))
- **[google-ads-change-log](google-ads/google-ads-change-log/)**: Logs every change with its reason, evidence, and a review date set by Google's waiting periods, lists reviews that are due, and reconciles the log against the account's change history to catch changes made by other people, scripts, and auto-applied recommendations. ([Guide](guides/google-ads/google-ads-change-log.md))

### SEO

- **[seo-people-also-ask](seo/seo-people-also-ask/)**: Searches Google for a term in your own Chrome through Claude in Chrome and returns the "People also ask" questions and "People also search for" terms, in Google's order and wording. It opens a few questions first so Google loads more, and stops for you if Google shows a CAPTCHA. ([Guide](guides/seo/seo-people-also-ask.md))

## How the repo is organized

```
claude-marketing-skills/
├── <area>/                     one folder per marketing area
│   ├── README.md               what the area covers, and its skills
│   └── <skill-name>/           one folder per skill, ready to install as-is
│       ├── SKILL.md            the instructions Claude follows
│       └── references/         detail Claude reads only when a step needs it
├── guides/
│   └── <area>/
│       └── <skill-name>.md     the guide for that skill
├── templates/                  starting points for new skills and guides
└── scripts/validate.py         checks names, metadata, guides, and the indexes
```

Skill folders hold only what Claude needs, so you can install one exactly as it is. Guides live in `guides/` for people to read.

## Installing a skill

### Claude (web and desktop apps)

1. Download this repo (**Code → Download ZIP**) and unzip it.
2. Zip the skill's folder on its own, for example `seo/<skill-name>`. On a Mac, right-click the folder and choose **Compress**. The zip must contain the folder, and the folder name must match the skill name.
3. In Claude, go to **Customize → Skills**, click **+**, then **Create skill → Upload a skill**, and upload the zip.
4. Make sure code execution is on: **Settings → Capabilities** on Free, Pro, and Max plans, or **Organization settings → Skills** on Team and Enterprise plans.

Skills you upload are private to your account until you share them. Skills turned on in your Claude settings also load in Claude Code when you sign in with the same account.

### Claude Code

Copy the skill folder into `~/.claude/skills/` to use it in every project, or into `.claude/skills/` inside a project to share it with everyone who works on that project:

```bash
git clone https://github.com/Width-ai/claude-marketing-skills.git
cp -R claude-marketing-skills/<area>/<skill-name> ~/.claude/skills/
```

### Skills CLI (Claude Code, Codex, Cursor, and other agents)

```bash
# See every skill in the repo
npx skills add Width-ai/claude-marketing-skills --list

# Install one skill for all your projects
npx skills add Width-ai/claude-marketing-skills --skill <skill-name> --global
```

Leave off `--global` to install into the current project only.

### Claude API

Upload the skill folder through the Skills API (`/v1/skills`), then pass its `skill_id` in the `container` parameter along with the code execution tool. See Anthropic's [Agent Skills docs](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview).

## About Width.ai

Width.ai builds custom AI agents and automation for marketing, sales, and ecommerce teams, and is a member of the Claude Partner Network. Need a skill built around your own process? [Talk to us](https://width.ai).

## FAQ

### How to add marketing skills to Claude

Each skill in this repo is a folder you install on its own:

- **Claude (web and desktop apps):** zip the skill's folder, then go to **Customize → Skills**, click **+**, choose **Create skill → Upload a skill**, and upload the zip. Code execution needs to be on in **Settings → Capabilities**.
- **Claude Code:** copy the folder into `~/.claude/skills/` to use it in every project, or into `.claude/skills/` in one project.
- **Any agent that supports skills:** run `npx skills add Width-ai/claude-marketing-skills --skill <skill-name> --global`.

Once a skill is installed, Claude uses it automatically when a request matches what it does. You can also ask for it by name. See [Installing a skill](#installing-a-skill) for every option, including the Claude API.

### How can you use Claude for marketing?

Claude handles the research, writing, and analysis behind most marketing work: drafting ad copy and content, analyzing campaign data, reviewing competitors, and turning raw exports into clear answers. Three things make it reliable for real work:

- **Skills** give Claude a tested process for one job, including the rules, checks, and scripts that do the math, so results stay consistent instead of depending on how you phrase each request.
- **Connectors** let Claude read your own data, such as your Google Ads account, instead of working from numbers pasted into the chat.
- **Approval before changes:** the skills here only prepare changes. You review a preview and approve it before anything in your accounts changes.

With the Google Ads skills in this repo, for example, Claude can record your targets and approved offers once, build a new Search campaign from a brief, write ad copy that only uses claims you've approved, turn the search terms report into negative keywords backed by real numbers, review AI Max and Performance Max spend, and sort Google's recommendations into accept, reject, or test. Every change waits for your approval of a checked preview, and a log records what changed and why.
