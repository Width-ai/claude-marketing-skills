// Read the sponsored (paid) search ads on a Google results page, without clicking anything.
// Run it in the results tab with the browser's JavaScript tool. Clicking an ad costs the
// advertiser money, so this script only reads the page. It finds ads by Google's text-ad
// marker (data-text-ad), not by class names, which change often.
//
// The browser tool returns about 1,000 characters, so the output is plain text in parts.
// Run it with PART = "headlines" first, then "descriptions" and "extras" if you need them.
// If a part ends with "run again with START = n", set START and run it again. The tool also
// blocks some text with "&" in it, so "&" comes back as "and".
const PART = "headlines";
const START = 0;

const norm = (s) =>
  (s || "")
    .replace(/\s*&\s*/g, " and ")
    .replace(/=/g, " ")
    .replace(/\s+/g, " ")
    .trim();
const pageText = document.body ? document.body.innerText : "";

const blocked =
  /unusual traffic|not a robot|recaptcha/i.test(pageText.slice(0, 4000)) ||
  !!document.querySelector("form#captcha-form, #recaptcha");
const consent = /before you continue to google/i.test(pageText.slice(0, 4000));
const searchTerm = norm(document.title.replace(/ - Google Search$/, ""));

// Headlines are 30 characters at most, so a longer piece is two headlines joined.
function splitHeadlines(heading) {
  const out = [];
  for (const part of heading.split(/\s[|\u00b7]\s/)) {
    if (part.length > 30) out.push(...part.split(/\s[-\u2013\u2014]\s/));
    else out.push(part);
  }
  return out.map(norm).filter(Boolean);
}

function domainOf(lines) {
  const line = lines.find((l) => /^(https?:\/\/)?(www\.)?[a-z0-9-]+(\.[a-z0-9-]+)+(\s|\u203a|\/|$)/i.test(l));
  if (!line) return "";
  return line.replace(/^https?:\/\//i, "").replace(/^www\./i, "").split(/[\s\u203a/]/)[0].toLowerCase();
}

function readAd(box, position) {
  const headingEl = [...box.querySelectorAll('[role="heading"]')].find((h) => !/ad center/i.test(h.textContent));
  const heading = norm(headingEl ? headingEl.textContent : "");
  const lines = (box.innerText || "").split("\n").map(norm).filter(Boolean);
  const at = lines.indexOf(heading);
  const domain = domainOf(lines);
  const advertiser = at >= 0 && lines[at + 1] && !lines[at + 1].includes("://") ? lines[at + 1] : domain;
  const rest = lines.filter(
    (l, i) =>
      i !== at && l !== advertiser && !/^sponsored$/i.test(l) && !/^https?:\/\//i.test(l) && !/ad center/i.test(l)
  );
  const description = rest.filter((l) => l.length >= 40).sort((a, b) => b.length - a.length)[0] || "";
  const extras = rest.filter((l) => l !== description && !/^(\u00b7|\u203a|\.\.\.)$/.test(l));
  return {
    position,
    advertiser,
    domain,
    heading,
    headlines: splitHeadlines(heading),
    description,
    other_lines: extras.slice(0, 8),
  };
}

// Text ads carry data-text-ad. They can sit above the results, among them, or below them.
// Local Services ads (the boxes with a photo, rating, and "Book online") aren't text ads
// and aren't read here.
const ads = [];
if (!blocked && !consent) {
  for (const box of document.querySelectorAll("[data-text-ad]")) {
    if (box.parentElement && box.parentElement.closest("[data-text-ad]")) continue;
    const position = box.closest("#tads") ? "top" : box.closest("#tadsb, #bottomads") ? "bottom" : "among results";
    const ad = readAd(box, position);
    if (ad.heading) ads.push(ad);
  }
}

const header =
  `query: ${searchTerm} | text ads: ${ads.length} | captcha: ${blocked ? "yes, stop" : "no"} | ` +
  `consent page: ${consent ? "yes" : "no"}`;
const rows = ads.map((a, i) => {
  if (PART === "descriptions") return `${i + 1} | ${a.advertiser} | ${a.description}`;
  if (PART === "extras") return `${i + 1} | ${a.advertiser} | ${a.other_lines.join(" / ")}`;
  return `${i + 1} | ${a.position} | ${a.advertiser} | ${a.domain} | ${a.headlines.join(" | ")}`;
});
const out = [header];
let used = header.length;
let next = null;
for (let i = START; i < rows.length; i++) {
  if (used + rows[i].length > 900 && i > START) {
    next = i;
    break;
  }
  out.push(rows[i].slice(0, 900));
  used += rows[i].length + 1;
}
if (next !== null) out.push(`more: run again with START = ${next}`);
out.join("\n");
