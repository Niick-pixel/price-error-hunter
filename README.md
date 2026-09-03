# Price Error Hunter

A Windows desktop tool that watches the [Hidden Clearances online feed](https://www.hiddenclearances.com/deals/online)
and surfaces the deals that look like genuine **pricing mistakes** rather than ordinary sales.

## Running it

Double-click **`run.bat`**. The first launch builds a local Python environment and
installs two packages; after that it starts in a second or two and opens your browser.

Close the console window to stop it.

## Alerts

When a newly found deal scores at or above the alert threshold, a notification
card slides in at the bottom right showing the product image, price and
discount. **Clicking it opens the deal**; the × dismisses it.

The sound is a soft two-note chime generated in the browser with WebAudio.
Earlier versions called `winsound.MessageBeep`, which played the Windows
*exclamation* sound — an error noise for something that is good news. Browsers
only allow audio after a user gesture, so the audio context is primed on your
first click.

If you grant notification permission, alerts also appear as desktop
notifications that open the deal when clicked, so they still reach you while the
tab is in the background.

### The glow

Any deal at **50% off or more** is backlit: a warm halo spills out behind the
card and breathes slowly, so the strongest finds are obvious while scrolling
without needing another badge. It is a light behind the card, not an outline —
the border itself stays ordinary, just faintly warmed.

It has to be a `box-shadow` rather than a blurred pseudo-element, because
`.card` sets `overflow: hidden` for the image zoom and would clip a child.
Shadows paint outside the border box and escape that clip. Under
`prefers-reduced-motion` the breathing stops and a steady halo remains. The
threshold is `GLOW_DISCOUNT` at the top of `web/app.js`.

### Chime at — sound without the interruption

**Chime at** in the toolbar is a second, quieter trigger: pick a discount
(50–90%) and any *new* deal at or above it plays the chime and nothing else. No
card, no desktop notification, nothing to dismiss — just a cue to glance at the
feed.

The two triggers do not double up. A deal that already raised the visual alert
is excluded from the chime pass, so it never sounds twice for the same find.
Both respect the **Sound alert** checkbox, and neither fires on first load.

## Where deals come from

Three public feeds are polled, each costing one request per cycle. A failing feed
never stops the others, and each source only ever expires its own deals.

| Source | What it adds |
|---|---|
| **Hidden Clearances** | Curated clearance and price errors across major US retailers |
| **CamelCamelCamel top drops** | The biggest recent **Amazon** price drops, with ASIN and exact before/after prices |
| **Slickdeals front page** | Community-vetted deals across many retailers, roughly half Amazon |
| **Slickdeals popular** | Runs deeper than the front page and only partly overlaps it |
| **TechBargains** | Amazon-heavy; its links are already product URLs, so ASINs come free |

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

## Hiding product types you do not care about

**Hide products…** in the toolbar opens two controls:

- **Category pills** — Books & Kindle, Food & drink, Vitamins & supplements,
  Beauty, Clothing. **Books are hidden by default**, because Kindle price drops
  otherwise dominate CamelCamelCamel: in a typical batch 13–14 of its 20 items
  are ebooks.
- **Hide titles containing** — a comma-separated free-text list.

Every deal is classified once at ingest and the category is stored, so toggling a
pill re-filters instantly without re-fetching anything.

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

## Two sections

The tabs at the top split the app in two:

- **Deals Feed** — everything the Hidden Clearances online feed is carrying.
- **Amazon** — only deals that resolve to an Amazon product, each with its ASIN,
  a direct product link, and a real Amazon price-history chart.

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
a public platform. The client is isolated in `pricehunter/creators.py`, so Keepa
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

A paid alternative is **Keepa**, which also exposes historical data through a
proper API. The client is isolated in `pricehunter/creators.py`, so it can be
swapped behind the same interface.

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
