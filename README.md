# GlitchGuard

**Catch real pricing mistakes before they vanish.**

A desktop tool for **Windows and macOS** that watches several public deal feeds
and surfaces the ones that look like genuine **pricing mistakes** rather than
ordinary sales.

It is local-first and account-free: everything runs on your own machine, there
is nothing to sign up for, and no data leaves the computer except the feed
requests themselves — plus, if you turn them on, the alerts you choose to send
to your own Discord or Telegram.

## Running it

| Platform | Launcher |
|---|---|
| Windows | double-click **`run-windows.bat`** |
| macOS / Linux | double-click **`run-mac.command`**, or `./run-mac.command` in a terminal |

Either one builds a local Python environment on first launch and installs two
packages; after that it starts in a second or two and opens your browser. Close
the console window to stop it.

Everything runs locally — the UI is a small page served on `127.0.0.1`, so
there is nothing platform-specific about the app itself, only the launcher.
Python 3.9+ is required; macOS ships `python3`, and the launcher says how to
install it if it is missing.

The `.command` extension is what makes Finder run the file on a double-click —
a plain `.sh` would open in a text editor instead.

If macOS refuses to open it, the file has lost its executable bit:

```bash
chmod +x run-mac.command
```

## Alerts

When a newly found deal scores at or above the alert threshold, a notification
card slides in at the bottom right showing the product image, price and
discount. **Clicking it opens the deal**; the × dismisses it.

The card carries its own opaque surface rather than being glass. It is the one
element that can land anywhere on the page — most often straight over a white
product photo — and as a translucent panel it took its contrast from whatever
happened to be behind it, dropping the title to around 1.4:1. Opaque, it reads
the same wherever it lands.

The sound is a soft two-note chime generated in the browser with WebAudio.
Earlier versions called `winsound.MessageBeep`, which played the Windows
*exclamation* sound — an error noise for something that is good news. Browsers
only allow audio after a user gesture, so the audio context is primed on your
first click.

If you grant notification permission, alerts also appear as desktop
notifications that open the deal when clicked, so they still reach you while the
tab is in the background.

### The glow

Any deal at **50% off or more** (adjustable) is lit with magenta, coral, indigo
and cyan blooming behind the card and slowly trading corners, so the strongest
finds are obvious while scrolling without needing another badge.

The light falls on the front of the card as well as behind it — four corner
blooms inside the border box, screened over the surface in dark mode and
multiplied into it in light — so a card reads as lit rather than outlined. The
wash sits underneath the thumbnail and the body, which are lifted a stacking
level, so it tints the card surface and never the title or the price.

Behind the card it is four offset coloured `box-shadow`s rather than a blurred
pseudo-element, for two reasons: `.card` sets `overflow: hidden` for the image
zoom, which would clip a child, and a negative z-index child paints *over* the
parent's own background rather than behind it. A shadow paints strictly outside
the border box, so it reads as a backlight with no clipping workaround and no
stray edge.

Two settings control it, under **Appearance**:

| Setting | What it does |
|---|---|
| **Glow strength** | 0–100, moving alpha, offset, blur and spread together |
| **Glow colour** | the rainbow preset, or a single colour of your choosing |

Strength moves all four values at once on purpose. Raising alpha by itself only
hardens the edge — a light that reads as brighter has to spread further at the
same time.

Choosing a single colour writes that one hue into all four corners, which
stills the rotation and gives one steady light instead of a cycle. Switching
back to rainbow *clears* those overrides rather than writing the dark-theme
hues back, so light mode keeps its own darker, more saturated set: a bright
halo is invisible on a pale ground, and what works there is coloured shade
rather than coloured light.

Every length and colour in the animation comes from a custom property, which is
what makes both settings possible without a second set of keyframes — the
animation only ever rotates which variable lands on which corner. Under
`prefers-reduced-motion` the rotation is paused and a static four-hue halo
remains.

### Screen glow

**Screen glow** in the toolbar lights the edges of the whole window when
something lands — a full-screen signed-distance-field glow, superellipse
corners, colour sampled around the perimeter in OKLCH (`web/siri-glow.js`).

It fires on three moments only, never on the routine background poll, which
would make it wallpaper:

| Trigger | Behaviour |
|---|---|
| Price-error alert | 5s, brightness scaled by the deal's score |
| Chime-at discount hit | 2.2s, dim — these raise no card, so it is a nudge |
| **Refresh now** pressed | pulses until that cycle finishes |

It sits above the alert card but below the detail modal, so opening a deal is
never washed out, and it is `pointer-events: none` throughout. Turning the
checkbox off stops it and skips creating the WebGL context at all.

`web/siri-glow-demo.html` is a tuning bench for it — sliders for lambda, drift,
bloom weights, corner shape, hairline, noise and a fake amplitude, plus an
opt-in microphone input. Open it at `/static/siri-glow-demo.html`.

### Why alerts are gated on posted time

A deal can be new *to the app* and already hours old. `slickdeals_popular` ranks
by popularity, so items enter it on average **ten hours** after being posted —
measured across live data, the median gap between a deal being posted and this
app first seeing it was **three hours**, and 49 of 74 recent finds were over an
hour old.

Alerting on discovery therefore meant notifications for stale deals that then
sorted to the bottom of the list. **Only alert on deals posted within**
(Settings, default 1 hour) gates every alert — score, keyword and chime — on how
long ago the deal went up, not on when we noticed it. Set it to *Any age* to get
the old behaviour.

### Keyword alerts

**Settings → Watch keywords** takes a comma-separated list. When a new deal's
title or retailer matches one, it raises a card naming the word that matched and
plays a **different sound** — a four-note arpeggio against the two-note chime
everything else uses, so you can tell them apart without looking.

A word you typed yourself is the strongest signal in the app, so a watch hit
outranks the score threshold: it fires even for a deal scoring well below
**Notify at score**, and it claims that deal so one find never makes two sounds.

Hidden product types still win. Watching `airpods` will not resurface something
excluded by category or by the hide list — the same `filters.suppressed` gate
applies first.

### Pinned products

**Settings → Watching → Pinned products** takes a list of ASINs or product
links, one per line. Paste whatever you have to hand — a bare `B0CV6WWPG2` or a
full `https://www.amazon.com/dp/...` link — and the ASIN is pulled out of it.

A pinned product **ignores the score and age gates entirely**. Asking for
something by name is the strongest signal in the app, stronger even than a watch
keyword, so a pinned find alerts whatever it scores and however long ago it was
posted, and it sorts to the top. The priority chain is:

    pinned product  >  watch keyword  >  score threshold

One find never makes two sounds: whichever rung claims a deal, the ones below it
skip it.

A pasted link yields its ASIN *and* is kept as a URL fragment, because the two
match different fields — a deal can carry a `direct_url` without a parsed ASIN,
and matching on only one of them silently misses it.

Hidden product types still win here too, the same way they do for keywords.

### Chime at — sound without the interruption

**Chime at** in the toolbar is a second, quieter trigger: pick a discount
(50–90%) and any *new* deal at or above it plays the chime and nothing else. No
card, no desktop notification, nothing to dismiss — just a cue to glance at the
feed.

The two triggers do not double up. A deal that already raised the visual alert
is excluded from the chime pass, so it never sounds twice for the same find.
Both respect the **Sound alert** checkbox, and neither fires on first load.

### Sending alerts elsewhere

**Settings → Send alerts elsewhere** can forward an alert to a **Discord**
channel or a **Telegram** chat, so a find still reaches you when you are not at
the machine. Both are optional and **off unless a destination is filled in**.

Only finds that already cleared the in-app gates are ever sent — turning this on
does not forward the whole feed to a chat channel. **Send a test message**
proves a destination before you rely on it, and reports the service's own error
text when it fails, since a wrong Telegram chat ID and a revoked token both come
back as a bare `400` otherwise.

| Destination | What you need |
|---|---|
| **Discord** | a webhook URL: channel settings → integrations → webhooks |
| **Telegram** | a bot token from `@BotFather`, plus your chat ID |

Sends happen on a background thread, so a slow or unreachable webhook can never
stall polling, and failures surface in the status line rather than raising.

> **Note on Discord:** a webhook is outbound only. It can post into a channel
> but cannot read one, so "watch a Discord server for deals" is a different
> feature needing a bot token and server permission. It is deliberately not
> attempted here.

Credentials are stored in `data/settings.json` on your machine, which is
gitignored, and are never sent anywhere except the service you configured.

## Where deals come from

Seven public feeds are polled, each costing one request per cycle. A failing
feed never stops the others, and each source only ever expires its own deals.

| Source | What it adds |
|---|---|
| **Hidden Clearances** | Curated clearance and price errors across major US retailers |
| **CamelCamelCamel top drops** | The biggest recent **Amazon** price drops, with ASIN and exact before/after prices |
| **Slickdeals front page** | Community-vetted deals across many retailers, roughly half Amazon |
| **Slickdeals popular** | Runs deeper than the front page and only partly overlaps it |
| **TechBargains** | Amazon-heavy; its links are already product URLs, so ASINs come free |
| **Woot** | Woot deals via Slickdeals' search feed, since Woot's own RSS is retired |
| **Walmart** | Walmart deals, gathered the same way |

Together they bring in around 150 live deals per cycle.

CamelCamelCamel is the important one for finding Amazon discounts independently:
its feed titles read `… - down 28.13% ($18.00) to $45.99 from $63.99` and the link
contains the ASIN, so every item arrives complete — product, ASIN, both prices and
the exact discount — with **no Amazon request involved**.

### Why not just script Amazon directly?

It was tried and measured, not assumed:

- Amazon returned a **CAPTCHA on the second automated request** from this machine's
  normal residential IP.
- A captured 1.5 MB product page held exactly **one** price string, with an empty
  `corePriceDisplay` placeholder — prices are rendered client-side and the markup
  varies per request.

Making a background crawler work anyway would mean rotating proxies, spoofing
fingerprints and solving CAPTCHAs — that is circumventing anti-bot protection,
against Amazon's Conditions of Use, and a good way to get an IP or account
flagged. Reading feeds that already track Amazon prices gets the same answer,
legitimately and far more reliably.

## Settings

The **Settings** tab holds everything that is set once and forgotten:

- **Appearance** — eight warm themes, five dark and three light; the discount
  at which cards get the glow; glow strength; glow colour; and a switch to turn
  the glow off.
- **When to alert** — the two independent gates: the score a find must reach,
  and how recently it must have been posted.
- **Watching** — watch keywords and the pinned product list.
- **What to show** — the maximum age of a listed deal.
- **Send alerts elsewhere** — Discord webhook and Telegram bot, both optional
  and both off unless filled in.
- **Deal sources** — all seven feeds, individually switchable. Turning one off
  stops polling it on the next cycle.
- **Hidden product types** — the category pills and keyword box.

Each group carries a sentence saying what it is for, because several of these
only make sense in relation to each other — the two alert gates in particular
are useless to reason about separately.

The toolbar keeps only what changes often, ordered dropdowns first and
checkboxes last: min discount, sort, poll interval, chime threshold, then sound
and screen glow.

## Hiding product types you do not care about

The controls live under **Settings → Hidden product types**:

- **Category pills** — Books & Kindle, Food & drink, Vitamins & supplements,
  Beauty, Clothing. **Books are hidden by default**, because Kindle price drops
  otherwise dominate CamelCamelCamel: in a typical batch 13–14 of its 20 items
  are ebooks.
- **Hide titles containing** — a comma-separated free-text list.

Every deal is classified once at ingest and the category is stored, so toggling a
pill re-filters instantly without re-fetching anything.

**Hidden types never raise an alert.** Visibility is decided in exactly one
place, `filters.suppressed`, which both the listing and the alert path call — so
a hidden book cannot ring a notification no matter how high it scores. The "new"
counter follows the same rule and counts only what you can actually see.

### How reliable is it?

Worth being straight about, because it is title-based guesswork. There is no
category field in any feed, and Amazon's category API needs the Associates
access described below. **Kindle editions get ordinary `B0` ASINs**, so an ISBN
check alone catches almost nothing.

The classifier combines explicit wording (`a novel`, `Book 3`, `Kindle`,
`bestselling`, …), ISBN-shaped ASINs, and a cheap-media rule: under about $6,
with no size, count or model number anywhere in the title. Product titles nearly
always carry one — `32-Oz`, `2-Pack`, `Fusion19`, `PR011` — and books nearly
never do.

Measured against live feeds, that hides **13 of 15 books with no real products
caught**. It is not perfect: a title like *Habsburgs on the Rio Grande* at $14.72
sits above the price band and stays. For those, use the keyword box or the
**Hide this deal** button on any card, which removes it permanently.

## How long deals stay listed

Most of these feeds are **rolling windows** — CamelCamelCamel publishes the
current top 20 drops, TechBargains 60 of hundreds — so an item falling off a
list means it was pushed down by newer entries, not that the deal ended.

Retiring deals on absence therefore killed almost everything: **99% of rows were
marked gone, and 10,512 of them vanished while still flagged new**, some within
the very cycle they were found. That is why an alert could point at a deal that
was no longer in the list.

**Hide deals older than** (Settings, default 12 hours) replaces that. Age is
measured from when the deal was posted — the same figure printed on the card —
and the limit is applied when the list is built, not only by the background
sweep, so changing it takes effect at once and nothing over the limit can slip
through. Deals already past the limit never raise an alert either, for the same
reason hidden categories do not: an alert should never point at something the
list will not show.

### Why the card ages were wrong

The age on a card used to come from whatever the feed last claimed. Two feeds
republish items with fresh timestamps, so **44 of 60 TechBargains rows were
labelled "4 hr ago" while genuinely nine days old**, and the setting appeared to
do nothing. The label now derives from `posted_at`, fixed when a deal is first
seen, which is also what the sort and the age limit read — so the three cannot
disagree.

## Four sections

The tabs at the top split the app in two:

- **Deals Feed** — everything all seven feeds are carrying.
- **Amazon** — only deals that resolve to an Amazon product, each with its ASIN,
  a direct product link, and a real Amazon price-history chart.
- **Woot** — Woot deals gathered from every source, not just the Woot feed.
- **Walmart** — the same, for Walmart.

A tab is a view over the same query rather than a separate fetch: one request
returns the listing and all three counts, so a tab can never advertise a number
its own list disagrees with. Membership is decided in Python
(`store.in_section`) for the same reason — counts and listing run through
identical logic.

Note on Woot: its own RSS is gone, every documented endpoint now 404s. The
`woot` source reads Slickdeals' search feed instead and drops anything that
does not resolve to woot.com, so neighbouring sites are never mislabelled.

## Links go straight to the product

Every deal's outbound link is resolved once, in the background, by walking the
affiliate redirect chain and reading only `Location` headers (the last hop is a
meta-refresh stub, which is parsed out of the tiny body). The result is stored,
so **clicking a deal lands directly on `amazon.com/dp/<ASIN>`** — or on Lowe's,
Woot, Dick's, etc. — instead of bouncing through the deals site in a new tab.
The affiliate tag in the resolved URL is left intact.

Crucially, the chain is walked with redirects disabled and stops the moment the
next URL leaves the known redirector hosts, so **the retailer page is never
requested** during resolution.

## How Amazon is analysed

This was the hard part, and the honest answer matters more than a nice-looking
number. Three things were tested directly:

1. **`robots.txt` permits it.** Amazon does not disallow `/dp/<ASIN>`; only
   sub-paths like `/dp/rate-this-item/`. So fetching a product page is not a
   robots violation. Their Conditions of Use still prohibit bulk data gathering.
2. **Bot detection is immediate.** In testing, Amazon served a CAPTCHA on the
   *second* automated request from a normal residential IP.
3. **The markup is not parseable in a trustworthy way.** A captured 1.5 MB
   product page contained exactly one price string and an *empty*
   `corePriceDisplay` placeholder — prices are rendered client-side, and the
   layout varies per request. An early parsing attempt produced `$7050.36` for a
   $16 item.

A wrong price in a price-error tool is worse than no price, so the app is built
around that reality:

- **Price history is the primary Amazon signal.** Each Amazon deal embeds its
  CamelCamelCamel chart, which is loaded **by your browser**, not by the app.
  Nothing is scraped and nothing can be blocked server-side. This is the single
  most useful view for spotting a genuine error — you can see instantly whether
  a price has ever been near this level.
- **Live price check is opt-in and best-effort** *(only used when Creators API
  credentials are absent — see below)*. Off by default. Enable it with
  the *Live Amazon check* toggle on the Amazon tab, or use the per-deal
  **Check live price** button. It is capped at 12 lookups an hour with a 25s
  minimum gap, and when Amazon blocks it, it says so plainly rather than
  guessing. Any figure wildly out of line with the known price is reported as
  unreliable instead of being displayed as fact.

## Amazon Creators API (optional — most people cannot get it)

> **Read this before spending time on it.** The Creators API is gated behind the
> Amazon Associates programme, which requires **a public website, app, or social
> channel that you own and actively publish on**. On top of that you need **10
> qualifying sales in a 30-day window** before API access is granted. If you are
> running this as a personal tool with no public platform, **you will not be able
> to get credentials, and that is fine** — everything described above works
> without them. The price-history chart is the practical Amazon signal.

> **PA-API 5.0 is gone.** Amazon deprecated it on **30 April 2026** and switched
> the endpoint off on **15 May 2026**. It is replaced by the **Creators API**.
> This app targets the Creators API; there is no reason to look for PA-API keys.

If you *do* qualify, the Creators API is the reliable way to read Amazon prices:
structured data, no scraping, no CAPTCHAs, and up to **10 ASINs per request** —
one call covers a whole screen of deals. When credentials are present the app
uses the API automatically and the scraper is not used at all.

### Getting credentials

1. Join the [Amazon Associates programme](https://affiliate-program.amazon.com/)
   for your marketplace. Signup requires a website, mobile app, or public social
   channel **that you own and publish original content on** — a YouTube channel
   or an Instagram/TikTok/Facebook page is accepted in place of a website, but it
   must be genuinely yours and active. Note your **partner tag** (`yourtag-20`).
2. Keep the account alive: **3 qualifying sales within 180 days** of joining.
3. **Make 10 qualifying sales within a 30-day window.** This is the real gate for
   API access, and it is stricter than PA-API's old threshold. No code works
   around it; until you clear it, requests return `AccessDenied`.
4. Register for API access in **Associates Central** and generate a
   **Client ID** and **Client Secret**. See Amazon's
   [Creators API docs](https://affiliate-program.amazon.com/creatorsapi/docs/en-us/introduction).

### Paid alternative, no Associates account needed

**Keepa** sells API access directly — no website, no affiliate account, no sales
requirement. It is **€49/month minimum with no free tier**, which is poor value
for personal use, but it is the only route to hard numeric Amazon pricing without
a public platform. The client is isolated in `glitchguard/creators.py`, so Keepa
can be dropped in behind the same interface if that ever becomes worthwhile.

### Adding them

Copy `amazon_api.example.json` to `data/amazon_api.json` and fill it in:

```json
{
  "client_id": "...",
  "client_secret": "...",
  "partner_tag": "yourtag-20",
  "marketplace": "www.amazon.com"
}
```

Or set `CREATORS_CLIENT_ID`, `CREATORS_CLIENT_SECRET` and
`CREATORS_PARTNER_TAG` as environment variables, which take priority. No restart
needed — the file is re-read when it changes, and a file still containing
`YOUR_CLIENT_ID` is treated as unconfigured.

`data/` is gitignored, credentials are never written into `settings.json`, and
the API status sent to the browser reports only *whether* credentials exist plus
the partner tag — never the secret.

Nineteen marketplaces are mapped across the three auth regions (NA/EU/FE); set
`marketplace` to e.g. `www.amazon.co.uk` and the right token endpoint is chosen.

### How the integration works

- **OAuth 2.0 client credentials**, not the old AWS SigV4 signing. The app posts
  to the regional token endpoint (`api.amazon.com/auth/o2/token` for NA) with
  scope `creatorsapi::default`, caches the bearer token for its hour of life, and
  re-authenticates automatically if a token is rejected early.
- **Single global catalog host**: `https://creatorsapi.amazon/catalog/v1/getItems`,
  with the region carried by the `x-marketplace` header.
- Prices are read from **OffersV2** — `price.money.amount`, with
  `price.savingBasis.money.amount` as the list price — preferring the Buy Box
  listing, and `availability.type` marks out-of-stock items.

### Once it is on

- The Amazon tab header turns green and names the active partner tag.
- Live prices come from the API, and the sanity guard that suppresses implausible
  *scraped* numbers is skipped, because API data is authoritative.
- Deal links switch to the API's detail page URL, which carries **your** associate
  tag — Amazon requires this once you are displaying their API data.
- Setup problems appear verbatim in the header with a plain-language hint (for
  example `invalid_client` → "Client ID or secret rejected — check for stray
  spaces").

Both endpoints were verified live: the token endpoint returns `invalid_client`
and the catalog endpoint returns `InvalidToken` for dummy credentials, confirming
the host, path, headers and request bodies are all correct.

## What you see

Every deal is a card showing the retailer, current price, list price and discount.
**Click any card** to expand it in place, which shows:

| | |
|---|---|
| Price now | what it is selling for |
| Real / list price | what it normally costs |
| You save | absolute saving |
| Discount | percentage off |
| Error score | 0-100, plus the reasons behind it |

and an **Open on … →** button that goes straight to the live product page in your
browser, where you can confirm the real price yourself.

Filter by minimum discount, and sort by score, recency, discount or saving.

## Promo codes

Plenty of deals need a code at checkout, and a deal whose code you never saw is
not a deal. When one is detected the card grows a **Copy Code** button, on the
card itself and again in the expanded detail; clicking it copies the code and
the button confirms with **Copied!**. Copying does not open the deal — the click
stops there.

**The button only appears when a code was actually found.** Detection fires only
on an explicit cue — `code:`, `coupon`, `promo`, `use … at checkout` — followed
by something code-shaped, and a stopword list throws out the words that
legitimately follow "code" in prose (`at`, `for`, `required`, `checkout`, …).
A pure-letter run has to be at least six characters to be accepted, since real
codes almost always mix letters and digits.

That is deliberately conservative. Pulling any capitalised token out of a title
produces far more matches, but most of them are junk — `FREE`, `NEW`, model
numbers — and a Copy Code button that copies rubbish is worse than no button.

## The price-error score

Ordinary clearance and a real glitch look different. The score weighs:

- discount percentage, with a strong bonus past 90%
- a few dollars against a substantial list price (the classic glitch shape)
- large absolute savings
- wording like "price error", "glitch" or "penny" in the listing
- freshness, since real errors get patched fast, with a penalty once a deal is over a week old

Anything at **78+** is flagged `LIKELY PRICE ERROR` in red, 58-77 is a strong deal.
The score is derived entirely from feed data, so ranking costs no extra requests.

## How it stays polite

Your concern about hammering the site is handled in several ways:

- **Conditional requests.** Each poll sends `If-None-Match`/`If-Modified-Since`.
  When nothing has changed the server replies `304` with no body, so a check costs
  almost nothing.
- **Jittered interval.** The configurable interval (default 3 min) is randomised
  ±20% so requests never form a detectable pattern.
- **Adaptive slowdown.** After three unchanged polls the gap stretches up to 3x,
  so a quiet feed is not polled as hard as a busy one.
- **Floor on manual refresh.** "Refresh now" refuses to fire within 45s of the last check.
- **Detail pages are rationed.** Only newly discovered deals are opened, at most 8
  per cycle, spaced 2s apart, and highest-scoring first.
- **Backoff.** A `429`/`503` triggers exponential backoff up to 15 minutes and
  honours `Retry-After`.

**Amazon is not touched at all unless you opt in.** Link resolution and price
history both avoid it entirely; only the optional live check ever contacts
Amazon, and it is capped as described above.

## Configuration

Settings are changed from the UI and stored in `data/settings.json`. The poll
interval, alert threshold and sound alert are all adjustable. `data/deals.db` is a
SQLite database holding deal history; delete the `data` folder to start fresh.

## Notes

- The service binds to `127.0.0.1` only, rejects requests with a foreign `Host`
  header, and requires a per-run random token, so no other site or machine can reach it.
- The feed's first page carries the 24 most recent deals, which is what matters for
  errors — they rarely survive long enough to be pushed off it.
- Hidden Clearances earns affiliate commission on its outbound links; using the
  `/go/` redirect keeps that attribution intact.
