const TOKEN = document.body.dataset.token;
const $ = (id) => document.getElementById(id);

let openId = null;
let settings = {};
let firstLoad = true;
let view = "feed";
let dataSection = "feed";
let lastAlertId = null;
let lastSoundPing = null;
let lastWatchPing = null;

const api = async (path, options = {}) => {
  const res = await fetch(path, {
    ...options,
    headers: { "X-PH-Token": TOKEN, "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
};

const money = (n) =>
  n === null || n === undefined ? "—" : `$${Number(n).toFixed(2)}`;

const SOURCE_LABEL = {
  hiddenclearances: "Hidden Clearances",
  camelcamelcamel: "Camel drops",
  slickdeals: "Slickdeals",
  slickdeals_popular: "Slickdeals popular",
  techbargains: "TechBargains",
  woot: "Woot feed",
  walmart: "Walmart feed",
};

/* Default discount at which a card gets the aurora; overridden from settings. */
let GLOW_DISCOUNT = 50;

/* mode drives the light/dark variable block in the stylesheet; bg/raised are
   the two surfaces each theme paints on top of it. */
const BG_THEMES = {
  charcoal: { label: "Charcoal", mode: "dark",  bg: "#202430", raised: "#2a2f3d" },
  slate:    { label: "Slate",    mode: "dark",  bg: "#1b2130", raised: "#262d40" },
  midnight: { label: "Midnight", mode: "dark",  bg: "#141824", raised: "#1e2333" },
  ink:      { label: "Ink",      mode: "dark",  bg: "#0d1117", raised: "#161b22" },
  graphite: { label: "Graphite", mode: "dark",  bg: "#26262b", raised: "#323238" },
  cocoa:    { label: "Cocoa",    mode: "dark",  bg: "#241f1d", raised: "#302926" },
  daylight: { label: "Daylight", mode: "light", bg: "#eef1f6", raised: "#ffffff" },
  paper:    { label: "Paper",    mode: "light", bg: "#f6f3ee", raised: "#fffdfa" },
  mist:     { label: "Mist",     mode: "light", bg: "#e8eef2", raised: "#f9fcfd" },
};

function applyTheme(name) {
  const t = BG_THEMES[name] || BG_THEMES.charcoal;
  const root = document.documentElement;
  root.style.setProperty("--bg", t.bg);
  root.style.setProperty("--bg-raised", t.raised);
  root.dataset.mode = t.mode;
  // The page washes are tuned for a dark ground and turn to mud on a light
  // one, so they are dialled back rather than removed.
  root.style.setProperty("--wash-a", t.mode === "light" ? ".10" : ".10");
  root.style.setProperty("--wash-b", t.mode === "light" ? ".09" : ".09");
  document.querySelectorAll(".swatch").forEach((s) =>
    s.classList.toggle("on", s.dataset.theme === name)
  );
}

/* ---------- screen edge glow ----------
   Deliberately not tied to the background poll: that runs every couple of
   minutes and a full-screen glow on every cycle would be wallpaper. It fires
   on the three moments that actually mean something - a price-error alert, a
   sound-only discount hit, and a refresh the user asked for. */
let screenGlow = null;
let glowTimer = null;

function initScreenGlow() {
  if (screenGlow || !window.SiriGlow) return;
  try {
    // Above the alert card (60), below the detail modal (80), so opening a
    // deal is never washed out by it.
    screenGlow = new SiriGlow({ zIndex: 75, lambda: 54, hairline: 0.7 });
  } catch (err) {
    screenGlow = null;   // never let an effect break the app
  }
}

function glowPulse(amplitude, holdMs) {
  if (!screenGlow || !settings.screen_glow) return;
  clearTimeout(glowTimer);
  screenGlow.amplitude = amplitude;
  screenGlow.state = "listening";
  glowTimer = setTimeout(() => {
    screenGlow.state = "exit";
    glowTimer = setTimeout(() => {
      if (screenGlow.state === "exit") screenGlow.state = "idle";
    }, 400);
  }, holdMs);
}

function glowStop() {
  clearTimeout(glowTimer);
  if (screenGlow) screenGlow.state = "idle";
}

const TIER_LABEL = { error: "LIKELY PRICE ERROR", strong: "STRONG DEAL", normal: "DEAL" };
const TIER_COLOR = { error: "#ff4d5e", strong: "#f5a524", normal: "#3b4a5c" };

/* Only ever follow http(s) links from the feed. */
function safeUrl(raw) {
  if (!raw) return null;
  try {
    const u = new URL(raw, "https://www.hiddenclearances.com");
    return u.protocol === "https:" || u.protocol === "http:" ? u.href : null;
  } catch {
    return null;
  }
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function stat(label, value, mod) {
  const box = el("div", "stat");
  box.append(el("div", "k", label));
  box.append(el("div", `v${mod ? " " + mod : ""}`, value));
  return box;
}

function buildCard(deal) {
  const card = el("article", "card");
  card.dataset.id = deal.id;
  // Anything at or above this discount gets the aurora backlight.
  if (settings.card_glow !== false && (deal.discount_pct || 0) >= GLOW_DISCOUNT) {
    card.classList.add("glow");
  }

  // thumbnail
  const thumb = el("div", "thumb");
  const fallback = buildThumbFallback(deal);
  thumb.append(fallback);

  const img = safeUrl(deal.image);
  if (!img) {
    thumb.classList.add("noimg");
  } else {
    const image = new Image();
    image.src = img;
    image.alt = deal.title || "";
    image.loading = "lazy";
    // The fallback stays hidden while loading, so a card never pops from a
    // placeholder letter to the photo. It appears only on a real failure.
    const drop = () => {
      image.remove();
      thumb.classList.remove("hasimg");
      thumb.classList.add("noimg");
    };
    // Some retailers block hotlinking; show the fallback, not a broken icon.
    image.onerror = drop;
    // Amazon's by-ASIN path answers with a 43-byte 1px placeholder for most
    // non-book ASINs. It "loads" fine, so size is the only way to spot it.
    image.onload = () => {
      if (image.naturalWidth < 32 || image.naturalHeight < 32) drop();
      else thumb.classList.add("hasimg");
    };
    thumb.append(image);
  }
  const badge = el("span", `badge ${deal.tier || "normal"}`, `${Math.round(deal.score)} · ${TIER_LABEL[deal.tier] || "DEAL"}`);
  thumb.append(badge);
  if (deal.is_new) thumb.append(el("span", "newflag", "NEW"));
  card.append(thumb);

  // body
  const body = el("div", "body");
  const line = el("div", "retailerline");
  line.append(el("span", "retailer", deal.retailer || "Unknown"));
  line.append(el("span", "srctag", SOURCE_LABEL[deal.source] || deal.source || "feed"));
  body.append(line);
  body.append(el("h2", "title", deal.title || "Untitled"));

  const prices = el("div", "prices");
  prices.append(el("span", "now", money(deal.price)));
  if (deal.list_price) prices.append(el("span", "was", money(deal.list_price)));
  if (deal.discount_pct) prices.append(el("span", "off", `${Math.round(deal.discount_pct)}% off`));
  body.append(prices);

  const meta = el("div", "meta");
  meta.append(el("span", null, deal.age_text || ""));
  meta.append(el("span", null, deal.savings ? `save ${money(deal.savings)}` : ""));
  body.append(meta);

  // Straight to the product, without opening the details first. Sits at the
  // bottom of every card so the row of buttons lines up across the grid.
  const target = safeUrl(deal.direct_url) || safeUrl(deal.out_url) || safeUrl(deal.url);
  if (target) {
    const quick = el("a", "quicklink", `Open on ${hostLabel(target)} →`);
    quick.href = target;
    quick.target = "_blank";
    quick.rel = "noopener noreferrer";
    // Stop the click bubbling into the card's open-details handler.
    quick.addEventListener("click", (event) => event.stopPropagation());
    body.append(quick);
  }

  card.append(body);

  card.addEventListener("click", (event) => {
    if (event.target.closest("a")) return;
    openModal(deal.id);
  });
  return card;
}

/* Details open in a floating panel. Previously they expanded inline, which
   pushed the whole grid around and forced a full re-render on every click. */
function openModal(id) {
  const deal = (window.__deals || []).find((d) => d.id === id);
  if (!deal) return;
  openId = id;

  const bodyEl = $("modalbody");
  bodyEl.replaceChildren();

  const img = safeUrl(deal.image);
  if (img) {
    const hero = el("div", "modalhero");
    const image = new Image();
    image.src = img;
    image.alt = deal.title || "";
    image.onerror = () => hero.remove();
    image.onload = () => {
      if (image.naturalWidth < 32) hero.remove();
    };
    hero.append(image);
    bodyEl.append(hero);
  }

  const main = el("div", "modalmain");
  const line = el("div", "retailerline");
  line.append(el("span", "retailer", deal.retailer || "Unknown"));
  line.append(el("span", "srctag", SOURCE_LABEL[deal.source] || deal.source || "feed"));
  main.append(line);
  const heading = el("h2", "title", deal.title || "Untitled");
  heading.id = "modaltitle";
  main.append(heading);
  main.append(buildDetail(deal));
  bodyEl.append(main);

  $("modal").classList.remove("hidden");
  document.body.classList.add("modal-open");
  $("modalclose").focus();
}

function closeModal() {
  const modal = $("modal");
  if (modal.classList.contains("hidden")) return;
  openId = null;
  document.body.classList.remove("modal-open");
  modal.classList.add("closing");
  setTimeout(() => {
    modal.classList.add("hidden");
    modal.classList.remove("closing");
    $("modalbody").replaceChildren();
  }, 220);
}

$("modalclose").addEventListener("click", closeModal);
$("modal").addEventListener("click", (event) => {
  if (event.target === $("modal")) closeModal();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeModal();
});

function buildDetail(deal) {
  const wrap = el("div", "detail");

  const grid = el("div", "detailgrid");
  grid.append(stat("Price now", money(deal.price), "good"));
  grid.append(stat("Real / list price", money(deal.list_price)));
  grid.append(stat("You save", money(deal.savings)));
  grid.append(stat("Discount", deal.discount_pct ? `${Math.round(deal.discount_pct)}%` : "—"));
  grid.append(stat("Error score", `${Math.round(deal.score)}/100`, deal.tier === "error" ? "hot" : ""));
  if (deal.prev_price) grid.append(stat("Was tracked at", money(deal.prev_price)));
  wrap.append(grid);

  const bar = el("div", "scorebar");
  const fill = el("i");
  fill.style.width = `${Math.max(3, Math.min(100, deal.score))}%`;
  fill.style.background = TIER_COLOR[deal.tier] || "#3b4a5c";
  bar.append(fill);
  wrap.append(bar);

  if (deal.reasons?.length) {
    const list = el("ul", "why");
    deal.reasons.forEach((r) => list.append(el("li", null, r)));
    wrap.append(list);
  }

  if (deal.description) wrap.append(el("div", "desc", deal.description));

  if (deal.asin) wrap.append(buildAmazonPanel(deal));

  const actions = el("div", "actions");
  // Prefer the fully resolved retailer URL so one click lands on the product
  // page instead of bouncing through the deals site again.
  const direct = safeUrl(deal.direct_url);
  const target = direct || safeUrl(deal.out_url) || safeUrl(deal.url);
  if (target) {
    const label = direct
      ? `Open on ${hostLabel(direct)} →`
      : deal.out_url
      ? `Open on ${deal.retailer || "retailer"} →`
      : "Open deal page →";
    const link = el("a", "open", label);
    link.href = target;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    actions.append(link);
  }
  const page = safeUrl(deal.url);
  if (page && target !== page) {
    const alt = el("a", "btn linkbtn", "Deal details");
    alt.href = page;
    alt.target = "_blank";
    alt.rel = "noopener noreferrer";
    actions.append(alt);
  }

  // Escape hatch for anything the category rules miss.
  const hide = el("button", "hidecard", "Hide this deal");
  hide.addEventListener("click", async (event) => {
    event.stopPropagation();
    hide.disabled = true;
    await api("/api/hide", {
      method: "POST",
      body: JSON.stringify({ id: deal.id }),
    }).catch(() => {});
    cardCache.delete(deal.id);
    closeModal();
    load();
  });
  actions.append(hide);

  wrap.append(actions);
  return wrap;
}

/* Sits behind the image. When no usable artwork exists the card shows this
   instead of an empty white rectangle, so it reads as designed, not broken. */
function buildThumbFallback(deal) {
  const box = el("div", "thumbfallback");
  const word = (deal.title || "?").replace(/^[^A-Za-z0-9]+/, "");
  box.append(el("span", "fbinitial", (word[0] || "?").toUpperCase()));
  box.append(el("span", "fbname", deal.retailer || "Deal"));
  return box;
}

function hostLabel(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "retailer";
  }
}

function buildAmazonPanel(deal) {
  const panel = el("div", "amzpanel");

  const head = el("div", "amzhead");
  head.append(el("span", "asin", `ASIN ${deal.asin}`));
  if (deal.amz_verdict) {
    head.append(el("span", `vd ${deal.amz_verdict}`, deal.amz_note || deal.amz_verdict));
  }
  panel.append(head);

  // Price history is loaded straight from CamelCamelCamel by the browser, so
  // nothing is scraped. They do apply hotlink protection, and when it kicks in
  // the chart and its caption are both removed together - an orphaned caption
  // describing a missing chart is worse than no chart at all.
  const chartBlock = el("div", "chartblock");
  const chart = el("div", "chartwrap");
  const img = new Image();
  img.src =
    `https://charts.camelcamelcamel.com/us/${encodeURIComponent(deal.asin)}` +
    `/amazon-new-used.png?force=1&zero=0&w=725&h=440&desired=false&legend=1&ilt=1&tp=all&fo=0`;
  img.alt = `Amazon price history for ${deal.asin}`;
  img.loading = "lazy";
  img.onerror = () => {
    chartBlock.replaceChildren(
      el("p", "chartcap",
         "CamelCamelCamel is not serving the inline chart right now — " +
         "use Price history page below for the full graph.")
    );
  };
  chart.append(img);
  chartBlock.append(chart);
  chartBlock.append(
    el("p", "chartcap", "Amazon price history (CamelCamelCamel) — green is Amazon's own price.")
  );
  panel.append(chartBlock);

  const row = el("div", "actions");
  const check = el("button", "btn", "Check live price");
  check.addEventListener("click", async (event) => {
    event.stopPropagation();
    check.disabled = true;
    check.textContent = "Checking…";
    try {
      const res = await api("/api/amazon/check", {
        method: "POST",
        body: JSON.stringify({ id: deal.id }),
      });
      check.textContent = "Check live price";
      const existing = head.querySelector(".vd");
      const badge = el("span", `vd ${res.verdict || "unknown"}`, res.note || "No result");
      existing ? existing.replaceWith(badge) : head.append(badge);
    } catch {
      check.textContent = "Check failed";
    } finally {
      check.disabled = false;
    }
  });
  row.append(check);

  const camel = el("a", "btn linkbtn", "Price history page");
  camel.href = `https://camelcamelcamel.com/product/${encodeURIComponent(deal.asin)}`;
  camel.target = "_blank";
  camel.rel = "noopener noreferrer";
  row.append(camel);
  panel.append(row);

  return panel;
}

/* Cards fade up as they scroll into view. Anything already on screen at render
   time is revealed straight away, so the first paint never looks empty. */
const revealed = new Set();
let revealTimer = null;

/* Safety net. A decorative animation must never decide whether content is
   visible: if the observer has not fired shortly after a render - hidden tab,
   zero-size viewport, no IntersectionObserver - reveal everything outright. */
function scheduleRevealFallback() {
  clearTimeout(revealTimer);
  revealTimer = setTimeout(() => {
    document.querySelectorAll(".card.reveal:not(.in-view)").forEach((card) => {
      card.style.transitionDelay = "0ms";
      card.classList.add("in-view");
      if (card.dataset.id) revealed.add(card.dataset.id);
    });
  }, 1400);
}

const revealer =
  "IntersectionObserver" in window
    ? new IntersectionObserver(
        (entries, obs) =>
          entries.forEach((entry) => {
            if (!entry.isIntersecting) return;
            entry.target.classList.add("in-view");
            if (entry.target.dataset.id) revealed.add(entry.target.dataset.id);
            obs.unobserve(entry.target);
          }),
        { rootMargin: "0px 0px -8% 0px", threshold: 0.05 }
      )
    : null;

/* Everything the card paints except the age, which ticks on every poll and is
   patched in place instead of forcing a rebuild. */
function cardSignature(d) {
  return [
    d.title, d.price, d.list_price, d.discount_pct, d.savings,
    d.score, d.tier, d.is_new, d.image, d.retailer, d.source,
  ].join("");
}

const cardCache = new Map();

/* The age string changes every poll. Patching it avoids rebuilding the card
   (and its image) just to move "2 min ago" to "5 min ago". */
function patchAge(card, deal) {
  const meta = card.querySelector(".meta span");
  if (meta && meta.textContent !== (deal.age_text || "")) {
    meta.textContent = deal.age_text || "";
  }
  const flag = card.querySelector(".newflag");
  if (!deal.is_new && flag) flag.remove();
}

function render(deals) {
  window.__deals = deals;
  const grid = $("grid");
  const animate = revealer && !document.hidden;
  const frag = document.createDocumentFragment();
  const seen = new Set();

  deals.forEach((d, index) => {
    seen.add(d.id);
    const sig = cardSignature(d);
    let entry = cardCache.get(d.id);

    if (!entry || entry.sig !== sig) {
      // Rebuilding replaces the <img>, so only do it when something visible
      // actually changed. Recreating every card each poll was what made the
      // thumbnails flash black.
      const card = buildCard(d);
      entry = { card, sig };
      cardCache.set(d.id, entry);
      if (animate && !revealed.has(d.id)) {
        card.classList.add("reveal");
        card.style.transitionDelay = index < 12 ? `${Math.min(index, 11) * 45}ms` : "0ms";
        revealer.observe(card);
      }
    } else {
      patchAge(entry.card, d);
    }
    frag.append(entry.card);   // moves the existing node, keeping its image
  });

  cardCache.forEach((_, id) => {
    if (!seen.has(id)) cardCache.delete(id);
  });
  grid.replaceChildren(frag);
  scheduleRevealFallback();

  $("empty").classList.toggle("hidden", deals.length > 0);
  if (!deals.length) $("empty").textContent = "No deals match these filters yet.";

  const errors = deals.filter((d) => d.tier === "error").length;
  const fresh = deals.filter((d) => d.is_new).length;
  const counts = $("counts");
  counts.replaceChildren();
  counts.append(el("span", null, `${deals.length} deals · `));
  const b = el("b", null, `${errors} likely price errors`);
  counts.append(b);
  if (fresh) counts.append(el("span", null, ` · ${fresh} new`));
}

function applyStatus(status) {
  const pulse = $("pulse");
  pulse.className = "pulse" + (status.last_error ? " bad" : status.running ? " busy" : "");

  // A manual refresh leaves the glow in "thinking"; retire it once the cycle
  // finishes, unless an alert has since taken it over.
  if (screenGlow && screenGlow.state === "thinking" && !status.running) {
    screenGlow.state = "exit";
    glowTimer = setTimeout(() => {
      if (screenGlow.state === "exit") screenGlow.state = "idle";
    }, 400);
  }

  const secs = status.seconds_to_next;
  $("nextrun").textContent =
    status.running ? "checking…" : secs === null || secs === undefined ? "—" : `next in ${fmt(secs)}`;

  if (status.last_error) {
    $("laststate").textContent = status.last_error;
  } else if (status.last_ok) {
    const ago = Math.round(Date.now() / 1000 - status.last_ok);
    $("laststate").textContent = `updated ${fmt(ago)} ago · ${status.cycles} checks`;
  }

  const pa = status.paapi || {};
  const note = $("amazonnote");
  note.replaceChildren();
  note.classList.toggle("bad", !!status.amazon_error);
  note.classList.toggle("good", !status.amazon_error && !!pa.configured);
  if (status.amazon_error) {
    note.append(el("strong", null, "Creators API error: "));
    note.append(el("span", null, status.amazon_error));
  } else if (pa.configured) {
    note.append(el("strong", null, "Creators API active "));
    note.append(el("span", null,
      `(${pa.partner_tag} · ${pa.marketplace}). Prices come straight from Amazon's ` +
      `official API — no scraping, no CAPTCHAs, 10 items per request.`));
  } else {
    note.append(el("span", null,
      "Links go straight to the product, and each deal shows its real Amazon price " +
      "history — the chart is the reliable signal here, since it shows whether a " +
      "price has ever been this low. Live checks are best-effort scraping and are " +
      "often blocked; Amazon's own API needs an Associates account with sales " +
      "history, so it is out of reach for most personal setups."));
  }

  // A keyword hit takes the card for itself; otherwise the score alert has it.
  if (!watchAlert(status)) renderAlert(status.top_new);
  soundOnlyPing(status);
}

/* Discount-threshold hits are audible only. The poller just increments a
   counter, so a change means "new qualifying deals arrived" - nothing is shown
   and nothing needs dismissing. */
function soundOnlyPing(status) {
  const ping = status.sound_ping || 0;
  if (lastSoundPing === null) {
    lastSoundPing = ping;          // first load: adopt, never chime
    return;
  }
  if (ping !== lastSoundPing) {
    lastSoundPing = ping;
    if (settings.sound_alerts) chime();
    // These raise no card on purpose, so keep the glow brief and dim - it is
    // a cue to glance at the feed, not something to dismiss.
    glowPulse(0.4, 2200);
  }
}

/* The alert used to be an unlabelled bar that only marked things read, which is
   why clicking it appeared to do nothing. It now opens the deal, and dismissing
   is a separate control so the two actions cannot be confused. */
function renderAlert(top, keyword) {
  const alert = $("alert");
  if (!top) {
    alert.classList.add("hidden");
    lastAlertId = null;
    return;
  }

  // A watch hit has already made its own sound and glow; do not repeat them.
  if (!keyword && top.id !== lastAlertId) {
    lastAlertId = top.id;
    if (settings.sound_alerts) chime();
    notifyDesktop(top);
    // Brightness tracks how strong the find is.
    glowPulse(0.55 + 0.45 * Math.min(1, (top.score || 0) / 100), 5000);
  }
  if (keyword) lastAlertId = top.id;

  alert.classList.remove("hidden");
  alert.replaceChildren();

  if (top.image) {
    const img = new Image();
    img.className = "alertthumb";
    img.src = top.image;
    img.alt = "";
    img.onerror = () => img.remove();
    alert.append(img);
  }

  const body = el("div", "alertbody");
  const kicker = keyword
    ? `Watching “${keyword}”`
    : `Possible price error · ${Math.round(top.score)}/100`;
  const kickerEl = el("span", "alertkicker", kicker);
  if (keyword) kickerEl.classList.add("watch");
  body.append(kickerEl);
  body.append(el("span", "alerttitle", top.title));
  const bits = [];
  if (top.retailer) bits.push(top.retailer);
  if (typeof top.price === "number") bits.push(money(top.price));
  if (top.discount_pct) bits.push(`${Math.round(top.discount_pct)}% off`);
  bits.push("Click to open →");
  body.append(el("div", "alertmeta", bits.join(" · ")));
  alert.append(body);

  const close = el("button", "alertclose", "×");
  close.title = "Dismiss";
  close.addEventListener("click", (event) => {
    event.stopPropagation();
    dismissAlert();
  });
  alert.append(close);

  alert.onclick = () => {
    const url = safeUrl(top.url);
    if (url) window.open(url, "_blank", "noopener,noreferrer");
    dismissAlert();
  };
}

async function dismissAlert() {
  $("alert").classList.add("hidden");
  const ids = (window.__deals || []).filter((d) => d.is_new).map((d) => d.id);
  await api("/api/seen", { method: "POST", body: JSON.stringify({ ids }) }).catch(() => {});
  load();
}

/* Keyword watch. A word the user typed is the strongest signal in the app, so
   it gets its own sound and its own card naming the match. */
function watchAlert(status) {
  const ping = status.watch_ping || 0;
  if (lastWatchPing === null) {
    lastWatchPing = ping;              // first sample: adopt, never fire
    return false;
  }
  if (ping === lastWatchPing) return false;
  lastWatchPing = ping;

  const hit = status.watch_hit;
  if (!hit) return false;
  if (settings.sound_alerts) chime("watch");
  notifyDesktop({ ...hit, title: `“${hit.keyword}” — ${hit.title}` });
  renderAlert(hit, hit.keyword);
  glowPulse(1, 6000);
  return true;
}

/* Two WebAudio motifs, distinct enough to tell apart without looking:
   a rising two-note chime for a price error, and a brighter three-note
   arpeggio for a keyword you asked to watch. */
const CHIMES = {
  default: [{ f: 880.0, t: 0 }, { f: 1318.51, t: 0.13 }],
  watch: [
    { f: 1046.5, t: 0 },      // C6
    { f: 1318.5, t: 0.10 },   // E6
    { f: 1568.0, t: 0.20 },   // G6
    { f: 2093.0, t: 0.32 },   // C7, the tell
  ],
};

let audioCtx = null;
function chime(kind) {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    audioCtx = audioCtx || new Ctx();
    if (audioCtx.state === "suspended") audioCtx.resume();
    const now = audioCtx.currentTime;
    (CHIMES[kind] || CHIMES.default).forEach(({ f, t }) => {
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.type = "sine";
      osc.frequency.value = f;
      // Quick attack, long soft tail so it reads as a chime, not a buzz.
      gain.gain.setValueAtTime(0.0001, now + t);
      gain.gain.exponentialRampToValueAtTime(0.16, now + t + 0.015);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + t + 0.55);
      osc.connect(gain).connect(audioCtx.destination);
      osc.start(now + t);
      osc.stop(now + t + 0.6);
    });
  } catch {}
}

// Browsers only allow audio after a gesture, so prime the context on first click.
["click", "keydown"].forEach((evt) =>
  window.addEventListener(evt, function prime() {
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      audioCtx = audioCtx || (Ctx ? new Ctx() : null);
      if (audioCtx && audioCtx.state === "suspended") audioCtx.resume();
    } catch {}
    window.removeEventListener(evt, prime);
  }, { once: true })
);

function notifyDesktop(top) {
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  try {
    const note = new Notification("Possible price error", {
      body: `${top.title}\n${top.retailer || ""} ${
        typeof top.price === "number" ? money(top.price) : ""
      }`.trim(),
      icon: top.image || undefined,
      tag: top.id,
    });
    note.onclick = () => {
      const url = safeUrl(top.url);
      if (url) window.open(url, "_blank", "noopener,noreferrer");
      note.close();
    };
  } catch {}
}

const fmt = (s) => (s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`);

function applySettings(cfg) {
  settings = cfg;
  if (firstLoad) {
    $("mindiscount").value = String(cfg.min_discount || 0);
    $("sort").value = cfg.sort || "score";
    $("sound").checked = !!cfg.sound_alerts;
    $("livecheck").checked = !!cfg.amazon_live_check;
    $("interval").value = String(cfg.poll_interval);
    $("keywords").value = cfg.exclude_keywords || "";
    $("sounddiscount").value = String(cfg.sound_discount || 0);
    $("screenglow").checked = cfg.screen_glow !== false;
    $("cardglow").value = String(cfg.card_glow_discount ?? 50);
    $("o-cardglow").textContent = `${cfg.card_glow_discount ?? 50}%`;
    $("cardglowon").checked = cfg.card_glow !== false;
    $("watchwords").value = cfg.watch_keywords || "";
    $("dealttl").value = String(cfg.deal_ttl_hours ?? 3);
    $("alertscore").value = String(cfg.alert_score ?? 75);
    $("o-alertscore").textContent = String(cfg.alert_score ?? 75);
    GLOW_DISCOUNT = cfg.card_glow_discount ?? 50;
    buildSettings(cfg);
    applyTheme(cfg.bg_theme || "charcoal");
    firstLoad = false;
  }
  // Created lazily so the WebGL context only exists when it is wanted.
  if (cfg.screen_glow !== false) initScreenGlow();
}

function renderCategories(list, excluded) {
  const box = $("categories");
  if (!list || box.dataset.built === "1") return;
  box.dataset.built = "1";
  box.replaceChildren();
  list.forEach((cat) => {
    const on = (excluded || []).includes(cat.key);
    const pill = el("label", "catpill" + (on ? " on" : ""));
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = on;
    input.value = cat.key;
    input.addEventListener("change", () => {
      pill.classList.toggle("on", input.checked);
      saveSettings();
      load();
    });
    pill.append(input, el("span", "tick", "✓"), el("span", null, cat.label));
    box.append(pill);
  });
}

function selectedCategories() {
  return [...document.querySelectorAll("#categories input:checked")].map((i) => i.value);
}

/* ---------- settings tab ---------- */

const SOURCE_KEYS = [
  ["source_hiddenclearances", "Hidden Clearances"],
  ["source_camelcamelcamel", "Camel top drops"],
  ["source_slickdeals", "Slickdeals"],
  ["source_slickdeals_popular", "Slickdeals popular"],
  ["source_woot", "Woot"],
  ["source_walmart", "Walmart"],
  ["source_techbargains", "TechBargains"],
];

let settingsBuilt = false;

function buildSettings(cfg) {
  if (settingsBuilt) return;
  settingsBuilt = true;

  const swatches = $("themes");
  Object.keys(BG_THEMES).forEach((key) => {
    const t = BG_THEMES[key];
    const b = document.createElement("button");
    b.className = "swatch";
    b.dataset.theme = key;
    b.title = t.label;
    b.setAttribute("aria-label", t.label);
    b.style.background = `linear-gradient(140deg, ${t.raised}, ${t.bg})`;
    b.addEventListener("click", () => {
      applyTheme(key);
      saveSettings();
    });
    swatches.append(b);
  });

  const list = $("sourcelist");
  SOURCE_KEYS.forEach(([key, label]) => {
    const on = cfg[key] !== false;
    const pill = el("label", "catpill" + (on ? " on" : ""));
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = on;
    input.dataset.key = key;
    input.addEventListener("change", () => {
      pill.classList.toggle("on", input.checked);
      saveSettings();
    });
    pill.append(input, el("span", "tick", "✓"), el("span", null, label));
    list.append(pill);
  });

  bindRange("cardglow", (v) => `${v}%`, (v) => {
    GLOW_DISCOUNT = v;
    cardCache.clear();               // glow state is baked into each card
    render(window.__deals || []);
  });
  bindRange("alertscore", (v) => String(v), () => {});

  $("cardglowon").addEventListener("change", () => {
    saveSettings();
    cardCache.clear();
    render(window.__deals || []);
  });
}

function bindRange(id, fmtFn, apply) {
  const input = $(id);
  const out = $("o-" + id);
  input.addEventListener("input", () => {
    out.textContent = fmtFn(Number(input.value));
    apply(Number(input.value));
  });
  input.addEventListener("change", saveSettings);
}

function selectedSources() {
  const out = {};
  document.querySelectorAll("#sourcelist input").forEach((i) => {
    out[i.dataset.key] = i.checked;
  });
  return out;
}

async function load() {
  const params = new URLSearchParams({
    section: dataSection,
    min: $("mindiscount").value,
    sort: $("sort").value,
  });
  try {
    const data = await api(`/api/deals?${params}`);
    renderCategories(data.categories, data.settings.excluded_categories);
    applySettings(data.settings);
    applyStatus(data.status);
    render(data.deals);
    applyTabCounts(data.counts);
  } catch (err) {
    $("laststate").textContent = "lost contact with the local service";
    $("pulse").className = "pulse bad";
  }
}

/* Every tab count arrives with the listing, so no extra request and no chance
   of a tab showing a number the list disagrees with. */
function applyTabCounts(counts) {
  if (!counts) return;
  Object.keys(counts).forEach((name) => {
    const el = document.getElementById("count-" + name);
    if (el) el.textContent = counts[name];
  });
}

function setView(next) {
  view = next;
  // Settings is a panel, not a deal section, so the data query keeps whichever
  // section was last open and returns to it when the tab is left.
  const isSettings = next === "settings";
  if (!isSettings) dataSection = next;

  document.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("active", t.dataset.view === next)
  );
  $("settingsview").classList.toggle("hidden", !isSettings);
  $("grid").classList.toggle("hidden", isSettings);
  document.querySelector(".controls").classList.toggle("hidden", isSettings);
  $("amazonnote").classList.toggle("hidden", next !== "amazon");
  document.querySelectorAll(".amazonopt").forEach((n) =>
    n.classList.toggle("hidden", next !== "amazon")
  );
  openId = null;
  load();
}

document.querySelectorAll(".tab").forEach((t) =>
  t.addEventListener("click", () => setView(t.dataset.view))
);

async function tick() {
  try {
    applyStatus(await api("/api/status"));
  } catch {}
}

function saveSettings() {
  const payload = {
    min_discount: Number($("mindiscount").value),
    sort: $("sort").value,
    sound_alerts: $("sound").checked,
    amazon_live_check: $("livecheck").checked,
    poll_interval: Number($("interval").value),
    sound_discount: Number($("sounddiscount").value),
    screen_glow: $("screenglow").checked,
    excluded_categories: selectedCategories(),
    exclude_keywords: $("keywords").value,
    watch_keywords: $("watchwords").value,
    deal_ttl_hours: Number($("dealttl").value),
    bg_theme: document.querySelector(".swatch.on")?.dataset.theme || "charcoal",
    card_glow: $("cardglowon").checked,
    card_glow_discount: Number($("cardglow").value),
    alert_score: Number($("alertscore").value),
    ...selectedSources(),
  };
  api("/api/settings", { method: "POST", body: JSON.stringify(payload) }).catch(() => {});
}

// Watch words only affect future alerts, so a debounced save is enough.
let watchTimer = null;
$("watchwords").addEventListener("input", () => {
  clearTimeout(watchTimer);
  watchTimer = setTimeout(saveSettings, 450);
});

let kwTimer = null;
$("keywords").addEventListener("input", () => {
  clearTimeout(kwTimer);
  // Debounced so a filter is not run on every keystroke.
  kwTimer = setTimeout(() => {
    saveSettings();
    load();
  }, 450);
});

["mindiscount", "sort"].forEach((id) =>
  $(id).addEventListener("change", () => {
    saveSettings();
    load();
  })
);
["sound", "interval", "livecheck", "sounddiscount"].forEach((id) =>
  $(id).addEventListener("change", saveSettings)
);

$("dealttl").addEventListener("change", () => {
  saveSettings();
  load();          // retention changes what is listed straight away
});

$("screenglow").addEventListener("change", () => {
  saveSettings();
  settings.screen_glow = $("screenglow").checked;
  if (settings.screen_glow) {
    initScreenGlow();
    glowPulse(0.7, 1600);        // confirm the toggle did something
  } else {
    glowStop();
  }
});

$("refresh").addEventListener("click", async () => {
  const btn = $("refresh");
  btn.disabled = true;
  // A refresh the user asked for is worth showing; background polls are not.
  if (screenGlow && settings.screen_glow) {
    clearTimeout(glowTimer);
    screenGlow.state = "thinking";
  }
  try {
    const res = await api("/api/refresh", { method: "POST" });
    if (!res.ok) $("laststate").textContent = `too soon — wait ${Math.ceil(res.wait)}s`;
    setTimeout(load, 2500);
  } finally {
    setTimeout(() => (btn.disabled = false), 4000);
  }
});

// Ask once for desktop notifications so alerts still land when the tab is hidden.
if ("Notification" in window && Notification.permission === "default") {
  window.addEventListener("click", function ask() {
    Notification.requestPermission().catch(() => {});
    window.removeEventListener("click", ask);
  }, { once: true });
}

/* Status is ~1.3KB and answers in 3ms; the full deal list is ~144KB and 29ms.
   Polling the cheap one often and pulling deals only when a cycle actually
   finished cuts an alert's on-screen delay from up to 20s down to a few
   seconds, while sending far less data than the old blanket refresh. */
let lastCycles = null;

async function pollStatus() {
  try {
    const status = await api("/api/status");
    applyStatus(status);
    if (status.cycles !== lastCycles) {
      const firstSample = lastCycles === null;
      lastCycles = status.cycles;
      // The initial load() already fetched deals; only later changes need one.
      if (!firstSample) load();
    }
  } catch {
    $("pulse").className = "pulse bad";
  }
}

load();
setInterval(pollStatus, 4000);
// Safety net in case a change is ever missed; the status poll does the work.
setInterval(load, 120000);
setInterval(tick, 1000);
