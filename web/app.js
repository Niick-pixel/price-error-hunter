const TOKEN = document.body.dataset.token;
const $ = (id) => document.getElementById(id);

let openId = null;
let settings = {};
let firstLoad = true;
let view = "feed";

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
  if (deal.id === openId) card.classList.add("open");

  // thumbnail
  const thumb = el("div", "thumb");
  const img = safeUrl(deal.image);
  if (img) {
    const image = new Image();
    image.src = img;
    image.alt = deal.title || "";
    image.loading = "lazy";
    // Some retailers block hotlinking; drop the node rather than show a broken icon.
    image.onerror = () => image.remove();
    // Amazon answers unknown ASINs with a 1px placeholder that "loads" fine but
    // renders as an empty box, so treat anything tiny as no image at all.
    image.onload = () => {
      if (image.naturalWidth < 32 || image.naturalHeight < 32) image.remove();
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

  if (deal.id === openId) body.append(buildDetail(deal));
  card.append(body);

  card.addEventListener("click", (event) => {
    if (event.target.closest("a")) return;
    openId = openId === deal.id ? null : deal.id;
    render(window.__deals || []);
  });
  return card;
}

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
  wrap.append(actions);
  return wrap;
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

  // Price history comes from CamelCamelCamel and is loaded by the browser
  // directly, so no scraping happens and nothing can be blocked server-side.
  const chart = el("div", "chartwrap");
  const img = new Image();
  img.src =
    `https://charts.camelcamelcamel.com/us/${encodeURIComponent(deal.asin)}` +
    `/amazon-new-used.png?force=1&zero=0&w=725&h=440&desired=false&legend=1&ilt=1&tp=all&fo=0`;
  img.alt = `Amazon price history for ${deal.asin}`;
  img.loading = "lazy";
  img.onerror = () => chart.remove();
  chart.append(img);
  panel.append(chart);
  panel.append(el("p", "chartcap", "Amazon price history (CamelCamelCamel) — green is Amazon's own price."));

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

function render(deals) {
  window.__deals = deals;
  const grid = $("grid");
  grid.replaceChildren();
  deals.forEach((d) => grid.append(buildCard(d)));

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

  const alert = $("alert");
  if (status.top_new) {
    alert.classList.remove("hidden");
    alert.replaceChildren(
      el("strong", null, `Possible price error (${Math.round(status.top_new.score)}/100): `),
      el("span", null, status.top_new.title)
    );
  } else {
    alert.classList.add("hidden");
  }
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
    firstLoad = false;
  }
}

async function load() {
  const params = new URLSearchParams({
    amazon: view === "amazon" ? "1" : "0",
    min: $("mindiscount").value,
    sort: $("sort").value,
  });
  try {
    const data = await api(`/api/deals?${params}`);
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
  };
  api("/api/settings", { method: "POST", body: JSON.stringify(payload) }).catch(() => {});
}

["mindiscount", "sort"].forEach((id) =>
  $(id).addEventListener("change", () => {
    saveSettings();
    load();
  })
);
["sound", "interval", "livecheck"].forEach((id) =>
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

$("alert").addEventListener("click", async () => {
  const ids = (window.__deals || []).filter((d) => d.is_new).map((d) => d.id);
  await api("/api/seen", { method: "POST", body: JSON.stringify({ ids }) }).catch(() => {});
  $("alert").classList.add("hidden");
  load();
});

load();
setInterval(load, 20000);
setInterval(tick, 1000);
