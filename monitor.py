"""Conservative direct-page monitor. Unknown/blocked pages never mean in stock."""
import html
import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from discover import host_allowed

STATE = Path('stock-state.json')


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def parse_product(page, retailer):
    """Only product-specific structured offers qualify, never generic cart text."""
    offers = []
    for raw in re.findall(r'<script\b[^>]*type=[\"\']application/ld\+json[\"\'][^>]*>(.*?)</script>', page, re.I | re.S):
        try:
            data = json.loads(html.unescape(raw))
        except ValueError:
            continue
        for node in walk(data):
            types = node.get('@type', [])
            if isinstance(types, str):
                types = [types]
            if 'Product' not in types:
                continue
            product_offers = node.get('offers', [])
            if isinstance(product_offers, dict):
                product_offers = [product_offers]
            for offer in product_offers:
                if not isinstance(offer, dict):
                    continue
                seller = offer.get('seller', {})
                seller = seller.get('name', '') if isinstance(seller, dict) else seller
                if retailer == 'walmart_ca' and str(seller).lower().strip() not in ('walmart', 'walmart canada', 'walmart.ca'):
                    continue
                try:
                    price = float(offer.get('price'))
                except (ValueError, TypeError):
                    continue
                if offer.get('priceCurrency') != 'CAD' or not 0 < price <= 250:
                    continue
                availability = str(offer.get('availability', '')).rsplit('/', 1)[-1]
                if availability in ('InStock', 'OutOfStock', 'SoldOut'):
                    offers.append(('in_stock' if availability == 'InStock' else 'out_of_stock', price))
    if not offers or len(set(offers)) != 1:
        return 'unknown', None
    return offers[0]


def fetch_page(url, retailer):
    if not url.startswith('https://') or not host_allowed(url, retailer):
        raise ValueError('Unsupported product URL')
    request = urllib.request.Request(url, headers={'User-Agent': 'PokemonStockMonitor/1.0 (personal availability monitor)'})
    with urllib.request.urlopen(request, timeout=20) as response:
        if not host_allowed(response.url, retailer):
            raise ValueError('Unexpected redirect domain')
        return response.read(2_000_000).decode('utf-8', errors='replace')


def notify(webhook, product):
    body = json.dumps({'content': f"Confirmed CAD stock: {product['title']} — ${product['price']:.2f}\n{product['url']}", 'allowed_mentions': {'parse': []}}).encode()
    request = urllib.request.Request(webhook, data=body, headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(request, timeout=20) as response:
        if response.status not in (200, 204):
            raise RuntimeError('Discord rejected alert')


def main():
    webhook = os.environ.get('DISCORD_WEBHOOK_URL', '')
    if not webhook:
        raise SystemExit('DISCORD_WEBHOOK_URL is missing; stock alerts are not configured.')
    payload = json.loads(Path('signals.json').read_text())
    previous = json.loads(STATE.read_text()) if STATE.exists() else {}
    now = datetime.now(timezone.utc).isoformat()
    failures = 0
    for product in payload['products']:
        url = product['url']
        state = previous.get(url, {})
        try:
            stock, price = parse_product(fetch_page(url, product['retailer']), product['retailer'])
            error = None if stock != 'unknown' else 'No unambiguous CAD product offer'
        except Exception as exc:
            stock, price, error = 'unknown', None, type(exc).__name__
        product.update(stock=stock, price=price, checked_at=now, check_error=error)
        if stock == 'unknown':
            failures += 1
            print(f"UNKNOWN {product['retailer']}: {error}")
        # Unknown checks preserve the last confirmed state to prevent duplicate alerts.
        if stock == 'in_stock' and state.get('confirmed_stock') != 'in_stock':
            try:
                notify(webhook, product)
            except Exception:
                failures += 1
                print('Discord delivery failed; alert will retry next run.')
                continue
        if stock != 'unknown':
            state['confirmed_stock'] = stock
        state.update(checked_at=now, observed_stock=stock, error=error)
        previous[url] = state
    payload['updated_at'] = now
    Path('signals.json').write_text(json.dumps(payload, indent=2) + '\n')
    STATE.write_text(json.dumps(previous, indent=2) + '\n')
    if not payload['products'] or failures == len(payload['products']):
        raise SystemExit('No successfully verified products; monitor needs attention.')
    if failures:
        raise SystemExit('Some checks or deliveries failed; review monitor output.')


if __name__ == '__main__':
    main()
