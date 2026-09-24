from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


OUTPUT = Path("signals.json")

USER_AGENT = (
    "Mozilla/5.0 PokemonStockDiscovery/1.0 "
    "(personal retail availability monitor)"
)

MAX_PRICE = 250.00

PRODUCT_TERMS = (
    "pokemon",
    "elite trainer",
    "etb",
    "booster bundle",
    "booster box",
    "ultra-premium",
    "ultra premium",
    "upc",
    "super-premium",
    "super premium",
    "collection",
    "151",
    "prismatic",
    "destined rivals",
    "journey together",
    "team rocket",
)

SEARCHES = (
    (
        "walmart_ca",
        'site:walmart.ca/en/ip pokemon tcg '
        '"sold by walmart"',
    ),
    (
        "costco_ca",
        'site:costco.ca pokemon cards pokemon tcg',
    ),
    (
        "pokemon_center_ca",
        'site:pokemoncenter.com pokemon tcg '
        '"elite trainer box" OR "booster bundle"',
    ),
)


def fetch(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,*/*;q=0.8",
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=20,
    ) as response:
        return response.read().decode(
            "utf-8",
            errors="replace",
        )


def host_allowed(url: str, retailer: str) -> bool:
    try:
        host = (
            urllib.parse.urlparse(url)
            .hostname
            or ""
        ).lower()
    except Exception:
        return False

    if retailer == "walmart_ca":
        return (
            host == "walmart.ca"
            or host.endswith(".walmart.ca")
        )

    if retailer == "costco_ca":
        return (
            host == "costco.ca"
            or host.endswith(".costco.ca")
        )

    if retailer == "pokemon_center_ca":
        return (
            host == "pokemoncenter.com"
            or host.endswith(".pokemoncenter.com")
        )

    return False


def product_relevant(text: str) -> bool:
    lower = text.lower()

    return (
        "pokemon" in lower
        and any(
            term in lower
            for term in PRODUCT_TERMS
        )
    )


def extract_price(text: str):
    matches = re.findall(
        r'\$\s*([0-9]{1,4}(?:\.[0-9]{2})?)',
        text,
    )

    prices = []

    for value in matches:
        try:
            price = float(value)

            if 5 <= price <= 1000:
                prices.append(price)
        except ValueError:
            pass

    return min(prices) if prices else None


def normalize_url(url: str) -> str:
    url = urllib.parse.unquote(url)

    parsed = urllib.parse.urlparse(url)

    # Some search engines wrap the actual URL.
    query = urllib.parse.parse_qs(parsed.query)

    for key in ("uddg", "url", "u"):
        if key in query:
            candidate = query[key][0]

            if candidate.startswith("http"):
                url = candidate
                break

    return url.split("#", 1)[0]


def search_duckduckgo(query: str):
    url = (
        "https://html.duckduckgo.com/html/?q="
        + urllib.parse.quote(query)
    )

    try:
        html = fetch(url)
    except Exception as exc:
        print(
            "Search unavailable:",
            type(exc).__name__,
            str(exc)[:100],
        )
        return []

    results = []

    pattern = re.compile(
        r'<a[^>]+class="[^"]*result__a[^"]*"'
        r'[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        re.I | re.S,
    )

    for href, title_html in pattern.findall(html):
        title = re.sub(
            r"<[^>]+>",
            " ",
            title_html,
        )

        title = re.sub(
            r"\s+",
            " ",
            title,
        ).strip()

        href = normalize_url(
            href.replace("&amp;", "&")
        )

        results.append(
            {
                "title": title,
                "url": href,
            }
        )

    return results


def inspect_candidate(
    retailer: str,
    title: str,
    url: str,
):
    if not host_allowed(url, retailer):
        return None

    if not product_relevant(
        title + " " + url
    ):
        return None

    page_text = ""

    try:
        page_text = fetch(url)
    except Exception:
        # Search discovery is still useful, but
        # verification requirements below remain.
        pass

    combined = (
        title
        + " "
        + re.sub(
            r"<[^>]+>",
            " ",
            page_text[:300000],
        )
    )

    price = extract_price(combined)

    if (
        price is not None
        and price > MAX_PRICE
    ):
        return None

    lower = combined.lower()

    stock = "unknown"

    if any(
        marker in lower
        for marker in (
            "add to cart",
            "add to bag",
            "in stock",
        )
    ):
        stock = "in_stock"

    if any(
        marker in lower
        for marker in (
            "out of stock",
            "sold out",
            "currently unavailable",
        )
    ):
        stock = "out_of_stock"

    verified = False

    if retailer == "pokemon_center_ca":
        verified = True

    elif retailer == "costco_ca":
        # Official Costco domain.
        verified = True

    elif retailer == "walmart_ca":
        # Walmart domain alone is NOT enough because
        # Walmart Marketplace uses the same website.
        verified = any(
            marker in lower
            for marker in (
                "sold by walmart",
                "sold and shipped by walmart",
            )
        )

    if not verified:
        print(
            "Rejected unverified:",
            retailer,
            title[:70],
        )
        return None

    return {
        "title": title,
        "url": url,
        "price": price,
        "stock": stock,
        "retailer": retailer,
        "verified_retailer": True,
    }


def load_existing():
    if not OUTPUT.exists():
        return {}

    try:
        data = json.loads(
            OUTPUT.read_text(
                encoding="utf-8"
            )
        )
    except Exception:
        return {}

    existing = {}

    for product in data.get(
        "products",
        [],
    ):
        url = product.get("url")

        if url:
            existing[url] = product

    return existing


def main():
    existing = load_existing()
    discovered = {}

    for retailer, query in SEARCHES:
        print(
            f"Searching {retailer}..."
        )

        results = search_duckduckgo(
            query
        )

        print(
            f"  Search results: {len(results)}"
        )

        for result in results[:20]:
            product = inspect_candidate(
                retailer,
                result["title"],
                result["url"],
            )

            if product:
                discovered[
                    product["url"]
                ] = product

                print(
                    "  Accepted:",
                    product["title"][:80],
                )

    # Preserve previously discovered products so that
    # temporary search-index changes do not erase our
    # watch list.
    for url, product in existing.items():
        if url not in discovered:
            discovered[url] = product

    payload = {
        "version": 1,
        "updated_at": (
            datetime.now(timezone.utc)
            .isoformat()
        ),
        "products": list(
            discovered.values()
        ),
    }

    OUTPUT.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    print()
    print(
        "Discovery complete:",
        len(discovered),
        "verified product(s)",
    )


if __name__ == "__main__":
    main()
