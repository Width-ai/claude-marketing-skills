---
name: seo-people-also-ask
description: >
  Searches Google for a term in the person's own Chrome browser through Claude
  in Chrome and returns the "People also ask" questions and the "People also
  search for" terms from the results page. Use when someone asks for People
  also ask questions, related questions, People also search for terms, or
  related searches for a keyword, or wants question ideas for content, FAQs,
  or SEO research.
metadata:
  version: "1.0.0"
---

# SEO People Also Ask

Search Google for one term in the person's Chrome and return two lists from the results page: the "People also ask" questions and the "People also search for" terms. Report only what Google showed. Never add, reword, or invent entries.

## Inputs

- **Search term** (required). Use it exactly as given.
- **Language** (optional): adds `hl=` to the search, for example `hl=en`. Default `en`.
- **Country** (optional): adds `gl=` to the search, for example `gl=us`. Without it, Google uses the browser's location.
- **How many questions** (optional): "just what shows" means 0 expand rounds, the default is 2 rounds (usually 10 to 25 questions), and "as many as possible" means 5 rounds.

## Steps

1. **Open a tab.** Use the Claude in Chrome tools. Call `tabs_context_mcp` first, then open a new tab with `tabs_create_mcp`. Don't reuse the person's own tabs. If the Claude in Chrome tools aren't available, say so. If the session has another browser with a JavaScript tool, the same steps work there.
2. **Search.** Navigate to `https://www.google.com/search?q=<term, URL-encoded>&hl=<language>`, plus `&gl=<country>` if one was given.
3. **Extract.** Run `scripts/extract_serp_lists.js` with the browser's JavaScript tool (`javascript_tool`): paste the whole file, with `EXPAND_ROUNDS` set from the inputs. The script:
   - finds the sections by their visible headings, not by Google's class names, which change often
   - clicks up to 4 unopened questions per round, so Google loads more
   - returns JSON with `people_also_ask`, `people_also_search_for`, and `related_searches` (used only when Google labels the block that way instead)
4. **Handle blocks.**
   - **CAPTCHA:** if `blocked_by_captcha` is true, stop. Ask the person to solve it in the Chrome tab, then run the script again. Never try to get around it.
   - **Consent page:** if `consent_page` is true, ask the person to choose an option on Google's consent screen, then run the script again.
5. **Check empty results.** If a list comes back empty or null, read the page with `get_page_text` and look for that heading. If it isn't there, Google didn't show that section for this search. Say so, and don't fill the gap.
6. **Close the tab** you opened.

Run one term at a time. For several terms, repeat the steps for each, and wait a few seconds between searches so Google doesn't flag the browser.

## Output

Reply in the chat:

```
Search: <term> (Google, <language>[, <country>], <date>)

People also ask (<count>)
1. ...

People also search for (<count>)
1. ...
```

- Keep Google's order and wording.
- If the block was labeled "Related searches", use that heading instead.
- End with one line saying results reflect the person's location and Google account, so they can differ for other people.
- If the person asks for a file, also give a CSV with the columns `search_term`, `list`, `position`, `text`.

## Reference files

| File | Read it when |
|---|---|
| `scripts/extract_serp_lists.js` | Every search (Step 3) |
