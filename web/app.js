const TOKEN = document.body.dataset.token;
const $ = (id) => document.getElementById(id);

let openId = null;
let settings = {};
let firstLoad = true;
let view = "feed";
let lastAlertId = null;
let lastSoundPing = null;

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
};

/* Discount at which a card gets the animated glow border. */
const GLOW_DISCOUNT = 50;

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
  // Anything at or above this discount gets the animated edge glow.
  if ((deal.discount_pct || 0) >= GLOW_DISCOUNT) card.classList.add("glow");

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

  renderAlert(status.top_new);
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
  }
}

/* The alert used to be an unlabelled bar that only marked things read, which is
   why clicking it appeared to do nothing. It now opens the deal, and dismissing
   is a separate control so the two actions cannot be confused. */
function renderAlert(top) {
  const alert = $("alert");
  if (!top) {
    alert.classList.add("hidden");
    lastAlertId = null;
    return;
  }

  if (top.id !== lastAlertId) {
    lastAlertId = top.id;
    if (settings.sound_alerts) chime();
    notifyDesktop(top);
  }

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
  body.append(el("span", "alertkicker", `Possible price error · ${Math.round(top.score)}/100`));
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

/* A soft two-note chime built with WebAudio, replacing the Windows
   exclamation sound the app used to trigger through winsound. */
let audioCtx = null;
function chime() {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    audioCtx = audioCtx || new Ctx();
    if (audioCtx.state === "suspended") audioCtx.resume();
    const now = audioCtx.currentTime;
    [
      { f: 880.0, t: 0 },      // A5
      { f: 1318.51, t: 0.13 }, // E6
    ].forEach(({ f, t }) => {
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
    firstLoad = false;
  }
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

async function load() {
  const params = new URLSearchParams({
    amazon: view === "amazon" ? "1" : "0",
    min: $("mindiscount").value,
    sort: $("sort").value,
  });
  try {
    const data = await api(`/api/deals?${params}`);
    renderCategories(data.categories, data.settings.excluded_categories);
    applySettings(data.settings);
    applyStatus(data.status);
    render(data.deals);
    refreshTabCounts();
  } catch (err) {
    $("laststate").textContent = "lost contact with the local service";
    $("pulse").className = "pulse bad";
  }
}

/* Counts for the inactive tab need their own lookup. */
async function refreshTabCounts() {
  const other = view === "amazon" ? "0" : "1";
  try {
    const data = await api(`/api/deals?amazon=${other}&min=${$("mindiscount").value}`);
    const mine = document.querySelectorAll(".card").length;
    $(view === "amazon" ? "count-amazon" : "count-feed").textContent = mine;
    $(view === "amazon" ? "count-feed" : "count-amazon").textContent = data.deals.length;
  } catch {}
}

function setView(next) {
  view = next;
  document.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("active", t.dataset.view === next)
  );
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
    excluded_categories: selectedCategories(),
    exclude_keywords: $("keywords").value,
  };
  api("/api/settings", { method: "POST", body: JSON.stringify(payload) }).catch(() => {});
}

$("hidebtn").addEventListener("click", () => {
  const panel = $("hidepanel");
  const open = panel.classList.toggle("hidden");
  $("hidebtn").setAttribute("aria-expanded", String(!open));
  $("hidebtn").textContent = open ? "Hide products…" : "Done";
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

$("refresh").addEventListener("click", async () => {
  const btn = $("refresh");
  btn.disabled = true;
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

load();
setInterval(load, 20000);
setInterval(tick, 1000);
