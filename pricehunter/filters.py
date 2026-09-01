"""Classify deals into product categories so unwanted ones can be hidden.

There is no category field in any feed and Amazon's category API is out of
reach, so classification works from the title, the ASIN shape and the price
band. Books are the hard case: Kindle editions get ordinary B0 ASINs, so an
ISBN check alone misses most of them, and plenty of titles ("Blindfold Game")
carry no bookish words at all. The rules below therefore combine explicit
wording with a media price band, and the UI keeps a per-deal hide for whatever
still slips through.
"""

import re

# Ordered most to least specific; the first match wins.
CATEGORIES = {
    "books": {
        "label": "Books & Kindle",
        "patterns": (
            r"\ba novel\b", r"\bnovels?\b", r"\bkindle\b", r"\bpaperback\b",
            r"\bhardcover\b", r"\baudiobooks?\b", r"\be-?books?\b",
            r"\bbook \d+\b", r"\(.*\bbook \d+.*\)", r"\bboxed set\b",
            r"\bomnibus\b", r"\banthology\b", r"\bmemoirs?\b", r"\btextbooks?\b",
            r"\bcookbook\b", r"\bhandbook\b", r"\bworkbook\b", r"\bmanual\b",
            r"\bvol\.?\s*\d+\b", r"\b\d+(?:st|nd|rd|th) edition\b",
            r"\(the .+ series\)", r"\b(?:trilogy|saga)\b",
            r":\s*a (?:memoir|thriller|mystery|romance|story|history|biography)\b",
            r"\bcomplete series\b", r"\blarge print\b", r"\bbestselling\b",
            r"\bauthor collection\b",
            r":\s*the (?:untold |true |secret )?(?:story|history|life|rise|fall)\b",
        ),
    },
    "grocery": {
        "label": "Food & drink",
        "patterns": (
            r"\b(?:oz|fl\.? ?oz|lb|lbs|pack of \d+)\b.*\b(?:coffee|tea|snack|cereal|"
            r"candy|chocolate|protein|drink|soda|water|juice|sauce|seasoning)\b",
            r"\b(?:k-cups?|granola|oatmeal|jerky|popcorn)\b",
        ),
    },
    "supplements": {
        "label": "Vitamins & supplements",
        "patterns": (
            r"\b(?:vitamin|supplement|probiotic|collagen|melatonin|magnesium|"
            r"ashwagandha|omega-?3|fish oil|multivitamin)\b",
            r"\b\d+\s*(?:mg|mcg|iu)\b.*\b(?:capsules?|tablets?|gummies|softgels?)\b",
        ),
    },
    "beauty": {
        "label": "Beauty & personal care",
        "patterns": (
            r"\b(?:shampoo|conditioner|lotion|serum|moisturizer|mascara|lipstick|"
            r"foundation|concealer|nail polish|perfume|cologne|hair dye|toner)\b",
        ),
    },
    "clothing": {
        "label": "Clothing & shoes",
        "patterns": (
            r"\b(?:t-?shirts?|hoodies?|sweater|jacket|jeans|leggings|socks|"
            r"sneakers|boots|sandals|dress|blouse|bra|underwear|swimsuit)\b",
        ),
    },
}

COMPILED = {
    key: [re.compile(p, re.I) for p in spec["patterns"]]
    for key, spec in CATEGORIES.items()
}

# A 10-character all-digit ASIN is an ISBN, so the item is a book.
ISBN_ASIN = re.compile(r"^\d{9}[\dXx]$")

# Kindle deals cluster in a narrow price band; combined with a weak title
# signal this catches titles that name no format at all.
MEDIA_MAX_PRICE = 5.99
MEDIA_MAX_LIST = 30.0


def category_labels():
    """[{key, label}] for the settings UI."""
    return [{"key": k, "label": v["label"]} for k, v in CATEGORIES.items()]


def classify(deal):
    """Return a category key, or '' when nothing matches."""
    title = deal.get("title") or ""
    asin = (deal.get("asin") or "").strip()

    if asin and ISBN_ASIN.match(asin):
        return "books"

    for key, patterns in COMPILED.items():
        if any(p.search(title) for p in patterns):
            return key

    if _looks_like_cheap_media(deal, title):
        return "books"
    return ""


# Counts are written "32-Oz" and "24-ct" as often as "32 oz", so the separator
# has to allow a hyphen or nothing at all.
SPEC_UNITS = re.compile(
    # "in" excludes "2-in-1", which is wording, not a measurement in inches.
    r"\d+[-\s]*(?:oz|ml|l|lb|lbs|kg|g|mm|cm|in(?!-)|\"|inch|ft|pack|pk|ct|count|"
    r"pcs?|piece|watt|w|v|mah|gb|tb|qt|quart|gallon|amp|cup|k)\b",
    re.I,
)
# Model numbers appear as "PR011" and as "Fusion19", so the letters may be
# mixed case rather than an all-caps prefix.
MODEL_NUMBER = re.compile(r"\b[A-Za-z]{2,}[- ]?\d{2,}\b")
# Pipes and ampersands chain specifications together and effectively never
# appear in a book title. Commas are deliberately NOT included: book subtitles
# use them freely ("Obsession, Fury, and the Scandal Behind ..."), and the unit
# and model-number checks already keep spec-style product titles out.
SPEC_PUNCTUATION = re.compile(r"[|&]")


def _looks_like_cheap_media(deal, title):
    """A cheap item whose title reads as prose rather than a spec sheet.

    Kindle deals sit in a tight price band and their titles carry no sizes,
    counts or model numbers. Requiring the absence of every spec marker keeps
    real products out even without an explicit book word.
    """
    price = deal.get("price")
    list_price = deal.get("list_price")
    if price is None or price > MEDIA_MAX_PRICE:
        return False
    if list_price is not None and list_price > MEDIA_MAX_LIST:
        return False
    if SPEC_UNITS.search(title) or MODEL_NUMBER.search(title):
        return False
    if SPEC_PUNCTUATION.search(title):
        return False
    # A bare cheap prose title at this point is almost always an ebook.
    return len(title.split()) >= 2


def excluded(deal, excluded_categories, keywords):
    """True when a deal should be hidden."""
    if excluded_categories:
        category = classify(deal)
        if category and category in excluded_categories:
            return True
    if keywords:
        haystack = f"{deal.get('title') or ''} {deal.get('retailer') or ''}".lower()
        return any(word and word.lower() in haystack for word in keywords)
    return False
