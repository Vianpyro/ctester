"use strict";
// What Lighthouse cannot see. It measures four screens, signed out: a student's bar wrapped once
// signed in, and the account menu it opened fell off the screen. This drives Chrome over some
// forty screens, signed in and out, in both languages, and checks what must hold on every one.
//
//   LAYOUT_BASE_URL  the page and the demo content (default http://localhost:8000, as for lhci)
//   CHROME_PATH      the browser: the runner's google-chrome in CI, Playwright's own locally
//   LAYOUT_OUT       where each failure's screenshot goes (default layout-audit)
//   LAYOUT_ONLY      run only the contexts whose name contains this, to iterate on one screen
//
// playwright-core is installed globally next to lhci and found through NODE_PATH.
const { chromium } = require("playwright-core");
const fs = require("node:fs");
const path = require("node:path");
const fixtures = require("./fixtures.json");

const BASE = (process.env.LAYOUT_BASE_URL || "http://localhost:8000").replace(/\/+$/, "");
const OUT = process.env.LAYOUT_OUT || "layout-audit";
const ONLY = process.env.LAYOUT_ONLY || "";
const WORKERS = 4;

// Width, height, touch. A touch context is a mobile one: coarse pointer, no hover, and the
// viewport meta honoured.
const SCREENS = [
  // Phones in portrait then landscape, then a foldable closed and open.
  [280, 653, 1], [320, 568, 1], [360, 740, 1], [375, 667, 1], [390, 844, 1], [412, 915, 1],
  [430, 932, 1], [568, 320, 1], [667, 375, 1], [844, 390, 1], [932, 430, 1], [673, 841, 1],
  [884, 1104, 1],
  // Tablets.
  [744, 1133, 1], [768, 1024, 1], [810, 1080, 1], [820, 1180, 1], [1024, 768, 1], [1024, 1366, 1],
  [1180, 820, 1], [1366, 1024, 1],
  // Windows and zoom levels: 320x256 is 1280x1024 at 400 % (WCAG 1.4.10), 1536x864 is a 1920
  // screen at 125 %.
  [320, 256, 0], [640, 360, 0], [1024, 640, 0], [1100, 700, 0], [1280, 720, 0], [1280, 800, 0],
  [1366, 768, 0], [1440, 900, 0], [1536, 864, 0], [1600, 900, 0], [1680, 1050, 0], [1920, 1080, 0],
  [2048, 1152, 0], [2560, 1080, 0], [2560, 1440, 0], [3440, 1440, 0], [3840, 2160, 0],
  [5120, 1440, 0],
];
// A student's own text size, set in the browser rather than zoomed: rem grows, the viewport not.
const FONTS = [[1366, 768, 0, 20], [1366, 768, 0, 24], [390, 844, 1, 20], [390, 844, 1, 24]];

const STATES = {
  "out-fr": { lang: "fr", signedIn: false },
  "in-fr": { lang: "fr", signedIn: true },
  "in-en": { lang: "en", signedIn: true },
};

function contexts() {
  const all = [];
  for (const [w, h, touch] of SCREENS) {
    for (const state of Object.keys(STATES)) all.push({ w, h, touch, font: 0, state });
  }
  for (const [w, h, touch, font] of FONTS) all.push({ w, h, touch, font, state: "in-fr" });
  for (const c of all) {
    c.name = `${c.w}x${c.h}${c.touch ? "-touch" : ""}${c.font ? "-font" + c.font : ""}-${c.state}`;
  }
  return all.filter((c) => c.name.includes(ONLY));
}

const json = (route, body) =>
  route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

async function open(browser, c) {
  const { lang, signedIn } = STATES[c.state];
  const context = await browser.newContext({
    viewport: { width: c.w, height: c.h },
    isMobile: !!c.touch,
    hasTouch: !!c.touch,
    locale: lang,
    // Nothing is in flight when a box is measured.
    reducedMotion: "reduce",
    // A worker's fetches would slip past the routes below.
    serviceWorkers: "block",
  });
  await context.addInitScript(
    ({ lang, signedIn }) => {
      localStorage.setItem("ctester.lang", lang);
      if (!signedIn) return;
      localStorage.setItem("ctester.token", "layout-audit");
      localStorage.setItem("ctester.expiry", String(Math.floor(Date.now() / 1000) + 86400));
    },
    { lang, signedIn },
  );
  const origin = new URL(BASE).origin;
  await context.route("**/*", (route) => {
    const request = route.request();
    const url = new URL(request.url());
    // The issuer and anything else stay offline: the page must not need them to lay out.
    if (url.origin !== origin) return route.abort();
    const name = url.pathname.slice(1);
    if (name in fixtures.public) return json(route, fixtures.public[name]);
    if (!request.headers().authorization) return route.continue();
    const reading = request.method() === "GET";
    if (name === "preferences") return json(route, reading ? { theme: "dark", lang } : { ok: true });
    if (name in fixtures.signedIn) return json(route, fixtures.signedIn[name]);
    return json(route, reading ? {} : { ok: true });
  });
  const page = await context.newPage();
  if (c.font) {
    const cdp = await context.newCDPSession(page);
    await cdp.send("Page.setFontSizes", { fontSizes: { standard: c.font } });
  }
  await page.goto(BASE + "/?k=dev&tp=tp1-ex1");
  await page.waitForSelector("#now h2", { state: "attached", timeout: 20_000 });
  if (signedIn) await page.waitForFunction((l) => document.documentElement.lang === l, lang);
  await settle(page);
  return { context, page };
}

async function settle(page) {
  await page.waitForLoadState("networkidle", { timeout: 5_000 }).catch(() => {});
  await page.evaluate(() => document.fonts.ready);
  await page.evaluate(() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))));
}

// The geometry, read in one pass inside the page. Each problem is [check, detail].
function survey({ touch, scope }) {
  const W = innerWidth;
  const H = innerHeight;
  const problems = [];
  const shown = (el) => {
    const style = getComputedStyle(el);
    const box = el.getBoundingClientRect();
    return style.visibility !== "hidden" && box.width > 0 && box.height > 0;
  };
  const name = (el) =>
    el.id ? "#" + el.id : el.tagName.toLowerCase() + (el.classList[0] ? "." + el.classList[0] : "");
  const rect = (b) => `[${Math.round(b.left)},${Math.round(b.top)} ${Math.round(b.width)}x${Math.round(b.height)}]`;
  const inside = (b) => b.left >= -1 && b.top >= -1 && b.right <= W + 1 && b.bottom <= H + 1;

  if (scope === "page" || scope === "bar") {
    const wide = document.documentElement.scrollWidth;
    if (wide > W + 1) problems.push(["page", `scrolls sideways (${wide}px in ${W}px)`]);

    // The bar's rows: its in-flow boxes, looking through display: contents, by vertical centre.
    const flow = [];
    const walk = (parent) => {
      for (const el of parent.children) {
        const style = getComputedStyle(el);
        if (style.display === "contents") walk(el);
        else if (style.display !== "none" && !["absolute", "fixed"].includes(style.position) && shown(el)) flow.push(el);
      }
    };
    walk(document.getElementById("top"));
    const centres = flow.map((el) => {
      const b = el.getBoundingClientRect();
      return b.top + b.height / 2;
    }).sort((a, b) => a - b);
    let rows = centres.length ? 1 : 0;
    for (let i = 1; i < centres.length; i++) if (centres[i] - centres[i - 1] > 16) rows++;
    // As base.css lays the bar out: two rows on a phone held upright or a screen this narrow.
    const allowed = matchMedia("(max-width: 700px) and (orientation: portrait), (max-width: 30rem)").matches ? 2 : 1;
    if (rows > allowed) problems.push(["bar-rows", `${rows} rows (${allowed} allowed)`]);

    const min = touch ? 44 : 24;
    const controls = document.querySelectorAll(
      "#top :is(button, summary, select, a[href]), #panes button, #actions :is(button, label.btn)",
    );
    for (const el of controls) {
      // A link in a sentence is exempt from target size (WCAG 2.5.8); a closed menu has no box.
      if (el.closest(".credit, .menupanel, [role=dialog], dialog") || !shown(el)) continue;
      const b = el.getBoundingClientRect();
      if (el.closest("#top") && !inside(b)) problems.push(["bar-control", `${name(el)} off screen ${rect(b)}`]);
      if (b.width < min - 0.5 || b.height < min - 0.5) {
        problems.push(["target", `${name(el)} ${Math.round(b.width)}x${Math.round(b.height)} < ${min}`]);
      }
    }
  }

  if (scope === "bench") {
    const go = document.getElementById("go");
    // A window too short for the bench scrolls (WCAG 1.4.10): Test only has to be reachable.
    go?.scrollIntoView({ block: "nearest" });
    if (!go || !shown(go) || !inside(go.getBoundingClientRect())) {
      problems.push(["bench", "Test is not on screen " + (go ? rect(go.getBoundingClientRect()) : "")]);
    }
    const editor = document.querySelector("#editor .edwrap");
    const tall = editor ? editor.getBoundingClientRect().height : 0;
    const rem = parseFloat(getComputedStyle(document.documentElement).fontSize);
    if (tall < 6 * rem) problems.push(["bench", `the editor is ${Math.round(tall)}px tall`]);
    const panes = document.getElementById("panes");
    const work = document.getElementById("work");
    if (panes && W <= 700) {
      if (!shown(panes)) problems.push(["panes", "the switcher is not shown"]);
      if (work.scrollWidth < 2.9 * work.clientWidth) problems.push(["panes", "#work is not three panes wide"]);
    }
  }
  return problems;
}

// A panel just opened: whole on screen, and whatever does not fit scrolls.
function boxed({ selector, keep }) {
  const el = document.querySelector(selector);
  const problems = [];
  if (!el) return [["opened", `${selector} is missing`]];
  const b = el.getBoundingClientRect();
  const style = getComputedStyle(el);
  if (style.display === "none" || b.width === 0) return [["opened", `${selector} did not open`]];
  const r = `[${Math.round(b.left)},${Math.round(b.top)} ${Math.round(b.width)}x${Math.round(b.height)}]`;
  if (b.left < -1 || b.top < -1 || b.right > innerWidth + 1 || b.bottom > innerHeight + 1) {
    problems.push(["panel", `${selector} off screen ${r}`]);
  }
  const cut = (node) => node.scrollHeight > node.clientHeight + 1 && !/auto|scroll/.test(getComputedStyle(node).overflowY);
  if (cut(el) && ![...el.querySelectorAll("*")].some((n) => /auto|scroll/.test(getComputedStyle(n).overflowY))) {
    problems.push(["panel", `${selector} is cut off and does not scroll`]);
  }
  if (keep) {
    const button = [...el.querySelectorAll("button")].find((n) => keep.test(n.textContent || ""));
    const k = button && button.getBoundingClientRect();
    if (!k || k.top < -1 || k.bottom > innerHeight + 1 || k.width === 0) {
      problems.push(["panel", `${selector}: "${keep.source}" is not on screen without scrolling`]);
    }
  }
  return problems;
}

async function visible(page, selector) {
  return await page.locator(selector).first().isVisible().catch(() => false);
}

// Clicks a bar control, through the folded menu when the bar has folded it away.
async function press(page, selector) {
  if (!(await visible(page, selector)) && (await visible(page, "#burger"))) {
    await page.click("#burger");
  }
  if (!(await visible(page, selector))) return false;
  await page.click(selector);
  return true;
}

async function audit(browser, c) {
  const found = [];
  let page;
  let context;
  const note = async (step, problems) => {
    if (!problems.length) return;
    for (const [check, detail] of problems) found.push({ context: c.name, step, check, detail });
    fs.mkdirSync(OUT, { recursive: true });
    await page.screenshot({ path: path.join(OUT, `${c.name}-${step}.png`) }).catch(() => {});
  };
  const close = async () => {
    await page.keyboard.press("Escape");
    await settle(page);
  };
  const panel = async (step, selector, keep) => {
    await settle(page);
    await note(step, await page.evaluate(boxed, { selector, keep }));
  };
  try {
    ({ context, page } = await open(browser, c));
    const { signedIn } = STATES[c.state];
    await note("load", await page.evaluate(survey, { touch: c.touch, scope: "bar" }));

    if (await visible(page, "#tocode")) await page.click("#tocode");
    await settle(page);
    await note("bench", await page.evaluate(survey, { touch: c.touch, scope: "bench" }));

    await page.click("#excurrent");
    await panel("catalog", "#exlist");
    await close();

    if (await visible(page, "#burger")) {
      await page.click("#burger");
      await panel("menu", "#tools");
      await close();
    }
    if (await press(page, "#shortcutsbutton")) {
      await page.waitForSelector("#shortcuts:not([hidden])", { timeout: 10_000 }).catch(() => {});
      await panel("shortcuts", "#shortcuts");
      await close();
    }
    if (!signedIn && (await visible(page, "#login"))) {
      await page.click("#login");
      await panel("consent", "#consent");
      await close();
    }
    if (signedIn) {
      await page.click("#plate");
      await panel("account", "#accountmenu .menupanel");
      await page.click("#identity");
      await page.waitForSelector("#identitypanel:not([hidden])", { timeout: 10_000 }).catch(() => {});
      await panel("identity", "#identitypanel", /^\s*(Enregistrer|Save)\s*$/);
      await close();
      // The plate now carries the long name the profile gave it.
      await note("named", await page.evaluate(survey, { touch: c.touch, scope: "bar" }));
      if (await press(page, "#scratch")) {
        await page.waitForSelector("#viewscratch:not([hidden])", { timeout: 10_000 }).catch(() => {});
        await settle(page);
        await note("view", await page.evaluate(survey, { touch: c.touch, scope: "bar" }));
      }
    }
  } catch (error) {
    found.push({ context: c.name, step: "run", check: "error", detail: String(error.message || error).split("\n")[0] });
    if (page) await page.screenshot({ path: path.join(OUT, `${c.name}-error.png`) }).catch(() => {});
  } finally {
    if (context) await context.close();
  }
  return found;
}

(async () => {
  fs.rmSync(OUT, { recursive: true, force: true });
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || undefined });
  const queue = contexts();
  const total = queue.length;
  const found = [];
  await Promise.all(
    Array.from({ length: WORKERS }, async () => {
      for (let c = queue.shift(); c; c = queue.shift()) found.push(...(await audit(browser, c)));
    }),
  );
  await browser.close();
  found.sort((a, b) => a.context.localeCompare(b.context, "en", { numeric: true }));
  for (const f of found) console.log(`${f.context}  ${f.step}  ${f.check}  ${f.detail}`);
  const failed = new Set(found.map((f) => f.context)).size;
  console.log(`\n${total} contexts, ${failed} with problems, ${found.length} problems.`);
  process.exit(found.length ? 1 : 0);
})();
