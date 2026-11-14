# Claude Marketing Skills

Claude skills for the marketing work businesses do every week, starting with Google Ads. Each skill is a folder of instructions and reference files that Claude loads when a request calls for it, so you get the same process and the same quality checks every time instead of re-explaining the job in every chat.

Every skill comes with a guide that explains what it does, how it works, how to install it, how to use it, and how to fix common problems.

Built by [Width.ai](https://width.ai). Also see our [n8n workflow templates](https://github.com/Width-ai/n8n-workflows).

## Marketing areas

| Area | What's in it |
|---|---|
| [Google Ads](google-ads/) | Managing and optimizing Google Ads accounts: account context, data pulls, safe changes, change history |

More areas will be added as their first skills are ready.

## Skills

### Google Ads

- **[google-ads-account-context](google-ads/google-ads-account-context/)**: Builds the account context file the other Google Ads skills read first, covering approved offers and proof points, target and break-even CPA or ROAS, what each conversion action really measures, protected terms that negatives must never block, and what Claude may change without approval. Prefills from a connector and your website, then interviews for the rest. ([Guide](guides/google-ads/google-ads-account-context.md))
- **[google-ads-data-pull](google-ads/google-ads-data-pull/)**: Pulls Google Ads data through a connector that runs GAQL or through CSV exports, cleans it into standard tables, and computes every metric and period-over-period comparison in code, with the search terms report's hidden-traffic share and small-sample limits stated up front. ([Guide](guides/google-ads/google-ads-data-pull.md))
- **[google-ads-apply-changes](google-ads/google-ads-apply-changes/)**: Checks proposed changes against the live account (misspelled campaign names, stale values, budget moves over your limits, negatives that would block converting searches, ad text over Google's limits), shows a before and after preview, gets approval, and applies the batch through a connector or as Google Ads Editor import files with rollback files. ([Guide](guides/google-ads/google-ads-apply-changes.md))
- **[google-ads-change-log](google-ads/google-ads-change-log/)**: Logs every change with its reason, evidence, and a review date set by Google's waiting periods, lists reviews that are due, and reconciles the log against the account's change history to catch changes made by other people, scripts, and auto-applied recommendations. ([Guide](guides/google-ads/google-ads-change-log.md))

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
