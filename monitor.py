"""Direct Canadian stock checks; blocked/ambiguous responses remain unknown."""
import argparse
import html
import json
import math
import os
import re
import urllib.parse
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
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


def item_id(url):
    return urllib.parse.urlparse(url).path.rstrip('/').rsplit('/', 1)[-1]


def valid_price(value):
    try:
        price = float(value)
        return price if math.isfinite(price) and 0 < price <= 250 else None
    except (ValueError, TypeError):
        return None


def walmart_offer(page, expected_url):
    match = re.search(r'<script\b[^>]*id=[\"\']__NEXT_DATA__[\"\'][^>]*>(.*?)</script>', page, re.I | re.S)
    if not match or not expected_url:
        return 'unknown', None
    try:
        data = json.loads(match.group(1))
        product = data['props']['pageProps']['initialData']['data']['product']
        if str(product.get('usItemId')) != item_id(expected_url):
            return 'unknown', None
        if str(product.get('sellerId')) != '0' or product.get('sellerName') != 'Walmart' or product.get('offerType') != '1P':
            return 'unknown', None
        current = product['priceInfo']['currentPrice']
        price = valid_price(current['price'])
        if current.get('currencyUnit') != 'CAD' or price is None:
            return 'unknown', None
        availability = product.get('availabilityStatus')
        if availability == 'OUT_OF_STOCK':
            return 'out_of_stock', price
        # An available pickup-only offer is not an online shipping restock.
        shipping = product.get('shippingOption') or {}
        can_ship = shipping.get('availabilityStatus') == 'AVAILABLE' or any(
            option.get('fulfillment') == 'SHIPPING' and option.get('availability') == 'AVAILABLE'
            for option in product.get('fulfillmentSummary', [])
        )
        if availability == 'IN_STOCK' and product.get('showAtc') is True and can_ship:
            return 'in_stock', price
    except (ValueError, KeyError, TypeError, AttributeError):
        pass
    return 'unknown', None


def parse_product(page, retailer, expected_url=None):
    if retailer == 'walmart_ca' and expected_url:
        return walmart_offer(page, expected_url)
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
            if not isinstance(product_offers, list):
                continue
            for offer in product_offers:
                if not isinstance(offer, dict):
                    continue
                if expected_url:
                    offer_url = offer.get('url') or node.get('url')
                    if not isinstance(offer_url, str) or not host_allowed(offer_url, retailer) or item_id(offer_url) != item_id(expected_url):
                        continue
                seller = offer.get('seller', {})
                seller = seller.get('name', '') if isinstance(seller, dict) else seller
                if retailer == 'walmart_ca' and str(seller).lower().strip() not in ('walmart', 'walmart canada', 'walmart.ca'):
                    continue
                price = valid_price(offer.get('price'))
                if offer.get('priceCurrency') != 'CAD' or price is None:
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


def send_discord(webhook, content):
    webhook = webhook.strip()
    parsed = urllib.parse.urlparse(webhook)
    if parsed.scheme != 'https' or parsed.hostname not in ('discord.com', 'discordapp.com', 'canary.discord.com', 'ptb.discord.com') or not re.fullmatch(r'/api(?:/v\d+)?/webhooks/\d+/[A-Za-z0-9_.-]+', parsed.path):
        raise RuntimeError('Invalid Discord webhook URL format')
    query = urllib.parse.parse_qs(parsed.query)
    query['wait'] = ['true']
    endpoint = urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query, doseq=True)))
    body = json.dumps({'content': content, 'allowed_mentions': {'parse': []}}).encode()
    request = urllib.request.Request(endpoint, data=body, headers={
        'Content-Type': 'application/json',
        'User-Agent': 'DiscordBot (https://github.com/samoyedtransport/pokemon-stock-signals, 1.0)',
    }, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read())
            if response.status != 200 or not result.get('id'):
                raise RuntimeError('Discord did not confirm a saved message')
    except urllib.error.HTTPError as exc:
        code = None
        try:
            payload = json.loads(exc.read(4096))
            code = payload.get('code')
            if not isinstance(code, int):
                code = None
        except (ValueError, AttributeError):
            pass
        # No URL, token, arbitrary response text or request object enters logs.
        raise RuntimeError(f'Discord HTTP {exc.code}; API code {code}') from None
    except urllib.error.URLError:
        raise RuntimeError('Discord connection failed') from None
    except (TimeoutError, ValueError, AttributeError):
        raise RuntimeError('Discord returned no usable message confirmation') from None


def notify(webhook, product):
    send_discord(webhook, f"Confirmed CAD online stock: {product['title']} — ${product['price']:.2f}\n{product['url']}")


def load_products():
    # Explicit watchlist controls alerts. Search discovery is a separate candidate feed.
    source = Path('watchlist.json') if Path('watchlist.json').exists() else Path('signals.json')
    products = json.loads(source.read_text())['products']
    unique = {}
    for product in products:
        url, retailer = product['url'], product['retailer']
        if not url.startswith('https://') or not host_allowed(url, retailer):
            raise ValueError('Invalid watchlist domain')
        max_price = valid_price(product.get('max_price', 250))
        if max_price is None:
            raise ValueError('Invalid price ceiling')
        unique[(retailer, item_id(url))] = {**product, 'max_price': max_price}
    return list(unique.values())


def check_product(product):
    product = dict(product)
    now = datetime.now(timezone.utc).isoformat()
    try:
        stock, price = parse_product(fetch_page(product['url'], product['retailer']), product['retailer'], product['url'])
        error = None if stock != 'unknown' else 'No verified Canadian online offer'
    except Exception as exc:
        stock, price, error = 'unknown', None, type(exc).__name__
    product.update(stock=stock, price=price, checked_at=now, check_error=error)
    return product


def apply_observation(product, state, deliver):
    state = dict(state)
    stock = product['stock']
    eligible = stock == 'in_stock' and product['price'] <= product.get('max_price', 250)
    previous_eligible = state.get('alert_eligible', False)
    if eligible and not previous_eligible:
        # Delivery succeeds before recording alert state. Failure leaves it retryable.
        deliver(product)
    if stock != 'unknown':
        state.update(confirmed_stock=stock, alert_eligible=eligible)
    state.update(checked_at=product['checked_at'], observed_stock=stock, error=product['check_error'])
    return state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='Check live stock and write a report without sending or changing alert history')
    parser.add_argument('--test-alert', action='store_true', help='Send one clearly labeled connection test; no stock claim')
    args = parser.parse_args()
    webhook = os.environ.get('DISCORD_WEBHOOK_URL', '')
    products = load_products()
    previous = json.loads(STATE.read_text()) if STATE.exists() else {}
    failures = 0
    delivery_failures = 0
    test_alert_delivered = False
    with ThreadPoolExecutor(max_workers=3) as executor:
        observations = list(executor.map(check_product, products))
    for product in observations:
        url = product['url']
        print(f"{product['retailer']} {product['stock']} CAD {product['price']}: {product['title']}")
        if product['stock'] == 'unknown':
            failures += 1
        if args.dry_run or not webhook:
            continue
        try:
            previous[url] = apply_observation(product, previous.get(url, {}), lambda p: notify(webhook, p))
        except RuntimeError as exc:
            failures += 1
            delivery_failures += 1
            print(f'{exc}; alert will retry next run.')
    if args.test_alert and webhook and not args.dry_run:
        try:
            send_discord(webhook, 'Pokemon monitor connection test — this is NOT a stock alert.')
            test_alert_delivered = True
            print('Discord confirmed the connection test message was saved.')
        except RuntimeError as exc:
            failures += 1
            delivery_failures += 1
            print(f'Discord test delivery failed: {exc}')
    unknown = sum(p['stock'] == 'unknown' for p in observations)
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'dry_run': args.dry_run, 'discord_configured': bool(webhook), 'test_alert_delivered': test_alert_delivered, 'products_checked': len(observations), 'unknown_products': unknown, 'delivery_failures': delivery_failures, 'failures': failures, 'products': observations}
    Path('monitor-report.json').write_text(json.dumps(report, indent=2) + '\n')
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as output:
            output.write(f"## Stock monitor health\n\nChecked: {len(observations)} | Verified: {len(observations)-unknown} | Unknown: {unknown}\n\nDiscord configured: {bool(webhook)} | Test delivered: {test_alert_delivered} | Delivery failures: {delivery_failures}\n\n")
            output.write('| Product | Stock | CAD price |\n|---|---|---|\n')
            for product in observations:
                title = product['title'].replace('|', '/')
                output.write(f"| {title} | {product['stock']} | {product['price']} |\n")
    if not args.dry_run and webhook:
        STATE.write_text(json.dumps(previous, indent=2) + '\n')
    if not args.dry_run and not webhook:
        raise SystemExit('DISCORD_WEBHOOK_URL is missing; checks completed but alerts are not configured.')
    if unknown:
        print(f'::warning::{unknown} products have unverified availability; inspect monitor-report.json.')
    if not observations or unknown == len(observations) or delivery_failures:
        raise SystemExit('Monitor has no verified products or failed delivery; inspect monitor-report.json.')


if __name__ == '__main__':
    main()
