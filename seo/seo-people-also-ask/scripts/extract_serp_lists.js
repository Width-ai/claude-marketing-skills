// Extract "People also ask" and "People also search for" from a Google results page.
// Run it in the results tab with the browser's JavaScript tool. Set EXPAND_ROUNDS first:
// 0 reads only the questions already showing; each extra round clicks up to 4 unopened
// questions so Google loads more. Finds sections by their visible headings, not by
// Google's class names, which change often.
const EXPAND_ROUNDS = 2;

const norm = (s) => (s || "").replace(/\s+/g, " ").trim();
const uniq = (list) => [...new Set(list.filter(Boolean))];
const pageText = document.body ? document.body.innerText : "";

const blocked =
  /unusual traffic|not a robot|recaptcha/i.test(pageText.slice(0, 4000)) ||
  !!document.querySelector("form#captcha-form, #recaptcha");
const consent = /before you continue to google/i.test(pageText.slice(0, 4000));

const searchTerm = norm(document.title.replace(/ - Google Search$/, ""));
const questions = () =>
  uniq([...document.querySelectorAll("[data-q]")].map((el) => norm(el.getAttribute("data-q")))).filter(
    (q) => q.toLowerCase() !== searchTerm.toLowerCase()
  );

let expanded = 0;
if (!blocked && !consent) {
  const opened = new Set();
  for (let round = 0; round < EXPAND_ROUNDS; round++) {
    const fresh = [...document.querySelectorAll("[data-q]")].filter(
      (el) => !opened.has(el.getAttribute("data-q"))
    );
    if (!fresh.length) break;
    for (const el of fresh.slice(0, 4)) {
      opened.add(el.getAttribute("data-q"));
      (el.querySelector('[role="button"], [aria-expanded]') || el).click();
      expanded++;
      await new Promise((resolve) => setTimeout(resolve, 900));
    }
  }
}

function linksUnder(headingPattern) {
  const heading = [...document.querySelectorAll('[role="heading"], h2, h3')].find((el) =>
    headingPattern.test(norm(el.textContent))
  );
  if (!heading) return null;
  let box = heading;
  for (let i = 0; i < 8 && box; i++) {
    box = box.parentElement;
    if (!box) break;
    const links = [...box.querySelectorAll('a[href*="/search?"]')];
    if (links.length >= 3) {
      return uniq(links.map((a) => norm(a.innerText || a.textContent)).filter((t) => t.length < 120));
    }
  }
  return [];
}

const peopleAlsoSearchFor = linksUnder(/^people also search for$/i);
const relatedSearches = peopleAlsoSearchFor && peopleAlsoSearchFor.length ? null : linksUnder(/^related searches$/i);

JSON.stringify(
  {
    query: searchTerm,
    blocked_by_captcha: blocked,
    consent_page: consent,
    questions_clicked: expanded,
    people_also_ask: questions(),
    people_also_search_for: peopleAlsoSearchFor,
    related_searches: relatedSearches,
  },
  null,
  1
);
