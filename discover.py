from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUTPUT = Path("signals.json")
USER_AGENT = "Mozilla/5.0 PokemonStockDiscovery/2.0 (personal retail availability monitor)"
MAX_PRICE = 250.00

RETAILERS = {
    "walmart_ca": {
        "hosts": ("walmart.ca",),
        "sitemaps": (
            "https://www.walmart.ca/sitemap.xml",
            "https://www.walmart.ca/sitemap_index.xml",
        ),
    },
    "costco_ca": {
        "hosts": ("costco.ca",),
        "sitemaps": (
            "https://www.costco.ca/sitemap.xml",
            "https://www.costco.ca/sitemap_index.xml",
        ),
    },
    "pokemon_center_ca": {
        "hosts": ("pokemoncenter.com",),
        "sitemaps": (
            "https://www.pokemoncenter.com/sitemap.xml",
            "https://www.pokemoncenter.com/sitemap_index.xml",
        ),
    },
}

PRODUCT_TERMS = (
    "elite trainer", "etb", "booster bundle", "booster box", "booster pack",
    "ultra-premium", "ultra premium", "upc", "super-premium",
    "super premium", "collection box", "boxed set", "battle deck",
    "151", "prismatic", "destined rivals", "journey together", "team rocket",
)

NON_PRODUCT_PATHS = (
    "/account", "/cart", "/category/", "/about", "/help", "/collections/",
    "/collection/", "/brand/", "/search", "/pages/",
)

def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xml,text/xml,*/*;q=0.8"})
    with urllib.request.urlopen(req, timeout=20) as response:
        return response.read().decode("utf-8", errors="replace")

def host_allowed(url: str, retailer: str) -> bool:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in RETAILERS[retailer]["hosts"])

def product_relevant(text: str) -> bool:
    lower = urllib.parse.unquote(text).lower().replace("-", " ")
    return any(term in lower for term in PRODUCT_TERMS)

def looks_like_product_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.lower()
    if any(marker in path for marker in NON_PRODUCT_PATHS):
        return False
    if parsed.query and not any(marker in path for marker in ("/product", "/products", "/p/")):
        return False
    return product_relevant(path)

def extract_price(text: str):
    prices = []
    for value in re.findall(r'\$\s*([0-9]{1,4}(?:\.[0-9]{2})?)', text):
        try:
            price = float(value)
            if 5 <= price <= 1000:
                prices.append(price)
        except ValueError:
            pass
    return min(prices) if prices else None

def sitemap_urls(xml_text: str) -> list[str]:
    return [html.unescape(x.strip()) for x in re.findall(r"<loc>\s*(.*?)\s*</loc>", xml_text, re.I | re.S)]

def discover_from_sitemaps(retailer: str) -> list[dict]:
    queue = list(RETAILERS[retailer]["sitemaps"])
    seen = set()
    candidates = []
    while queue and len(seen) < 80:
        sitemap = queue.pop(0)
        if sitemap in seen:
            continue
        seen.add(sitemap)
        try:
            body = fetch(sitemap)
        except Exception as exc:
            print("  Sitemap unavailable:", sitemap, type(exc).__name__)
            continue
        for url in sitemap_urls(body):
            lower = url.lower()
            if lower.endswith(".xml") or "sitemap" in lower:
                if host_allowed(url, retailer) and url not in seen:
                    queue.append(url)
                continue
            if host_allowed(url, retailer) and looks_like_product_url(url):
                candidates.append({"title": urllib.parse.unquote(url.rsplit("/", 1)[-1]).replace("-", " "), "url": url})
        if len(candidates) >= 100:
            break
    return candidates[:100]

def inspect_candidate(retailer: str, title: str, url: str):
    if not host_allowed(url, retailer) or not looks_like_product_url(url):
        return None
    try:
        page = fetch(url)
    except Exception:
        page = ""
    text = title + " " + re.sub(r"<[^>]+>", " ", page[:300000])
    price = extract_price(text)
    if price is not None and price > MAX_PRICE:
        return None
    lower = text.lower()
    stock = "unknown"
    if any(x in lower for x in ("add to cart", "add to bag", "in stock")):
        stock = "in_stock"
    if any(x in lower for x in ("out of stock", "sold out", "currently unavailable")):
        stock = "out_of_stock"

    verified = retailer in ("pokemon_center_ca", "costco_ca")
    if retailer == "walmart_ca":
        verified = any(x in lower for x in ("sold by walmart", "sold and shipped by walmart"))
    if not verified:
        return None
    return {"title": title, "url": url, "price": price, "stock": stock, "retailer": retailer, "verified_retailer": True}

def load_existing():
    if not OUTPUT.exists():
        return {}
    try:
        data = json.loads(OUTPUT.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {p["url"]: p for p in data.get("products", []) if p.get("url")}

def main():
    existing = load_existing()
    discovered = {}
    for retailer in RETAILERS:
        print(f"Discovering {retailer} from retailer sitemaps...")
        candidates = discover_from_sitemaps(retailer)
        print(f"  Candidate URLs: {len(candidates)}")
        for candidate in candidates:
            product = inspect_candidate(retailer, candidate["title"], candidate["url"])
            if product:
                discovered[product["url"]] = product
                print("  Accepted:", product["title"][:80])

    for url, product in existing.items():
        if url not in discovered:
            discovered[url] = product

    payload = {
        "version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "products": list(discovered.values()),
    }
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Discovery complete:", len(discovered), "verified product(s)")

if __name__ == "__main__":
    main()
