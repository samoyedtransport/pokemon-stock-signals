"""Bounded public retail catalogue checks. Never infer stock from missing entries."""
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ALLOWED = {
    '401_games': 'https://store.401games.ca',
    'hobbiesville': 'https://www.hobbiesville.com',
    'kanzen_games': 'https://kanzengames.com',
    'face_to_face': 'https://facetofacegames.com',
}
MAX_PAGES = 3
PAGE_SIZE = 250


def read_json(url, base):
    request = urllib.request.Request(url, headers={'User-Agent': 'PokemonStockMonitor/2.0 (personal retail availability monitor)', 'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=20) as response:
        if not response.url.startswith(base + '/'):
            raise ValueError('Unexpected retail redirect')
        raw = response.read(4_000_001)
        if len(raw) > 4_000_000:
            raise ValueError('Catalogue response too large')
        return json.loads(raw)


def product_kind(product):
    title = product.get('title', '').lower().replace('é', 'e')
    tags = product.get('tags', [])
    if isinstance(tags, str):
        tags = tags.split(',')
    metadata = ' '.join([title, product.get('product_type', ''), product.get('vendor', ''), *tags]).lower().replace('é', 'e')
    # Only recognizable factory product formats. Exclude secondary-market conditions,
    # imported languages, cases, reservations and event tickets.
    if re.search(r'pre[ -]?order|used|second.hand|reseal|damaged|\bopened\b|\bempty\b|\bcase\b|japanese|korean|chinese|french|\bsingles\b|\bgraded\b|\brepack\b|mystery|\bevent\b|\bticket\b|app.exclusive|in.store.only', metadata):
        return None
    if 'pokemon' not in metadata:
        return None
    for term, kind in [('booster bundle', 'booster_bundle'), ('elite trainer', 'elite_trainer_box'), ('booster box', 'booster_box'), ('premium collection', 'premium_collection')]:
        if term in title:
            return kind
    return None


def observations_for_product(product, store, limits, now):
    kind = product_kind(product)
    handle = product.get('handle', '')
    if not kind or not re.fullmatch(r'[a-z0-9-]+', handle):
        return []
    result = []
    for variant in product.get('variants', []):
        variant_title = str(variant.get('title', ''))
        if re.search(r'pre[ -]?order|damaged|used|opened|french|japanese|korean|chinese|case', variant_title, re.I):
            continue
        variant_id = str(variant.get('id', ''))
        available = variant.get('available')
        try:
            price = float(variant['price'])
        except (ValueError, TypeError, KeyError):
            continue
        if not variant_id.isdigit() or type(available) is not bool or not 0 < price <= 10000:
            continue
        result.append({'title': product['title'] + ('' if variant_title == 'Default Title' else ' — ' + variant_title),
            'retailer': store['id'], 'retailer_name': store['name'], 'location': store['location'],
            'url': f"{store['base_url']}/products/{handle}?variant={variant_id}",
            'stock': 'in_stock' if available else 'out_of_stock', 'price': price,
            'max_price': limits[kind], 'kind': kind, 'checked_at': now, 'check_error': None,
            'source': 'retail_catalogue'})
    return result


def check_store(store, limits, fetch=read_json):
    now = datetime.now(timezone.utc).isoformat()
    observations = {}
    health = {'store': store['id'], 'checked_at': now, 'ok': False, 'pages': 0, 'truncated': False}
    try:
        base = store['base_url']
        if ALLOWED.get(store['id']) != base or not re.fullmatch(r'[a-z0-9-]+', store['collection']):
            raise ValueError('Unapproved retailer configuration')
        if fetch(base + '/cart.js', base).get('currency') != 'CAD':
            raise ValueError('Canadian currency unconfirmed')
        for page in range(1, MAX_PAGES + 1):
            data = fetch(f"{base}/collections/{store['collection']}/products.json?limit={PAGE_SIZE}&page={page}", base)
            products = data.get('products')
            if not isinstance(products, list):
                raise ValueError('Invalid catalogue')
            health['pages'] = page
            for product in products:
                for observation in observations_for_product(product, store, limits, now):
                    observations[observation['url']] = observation
            if len(products) < PAGE_SIZE:
                break
        else:
            health['truncated'] = True
        if not observations:
            raise ValueError('No matching sealed retail products')
        health.update(ok=True, matched_variants=len(observations))
    except Exception as exc:
        # Do not emit partially fetched stores as complete or treat missing as sold out.
        health['error'] = type(exc).__name__
        return [], health
    return list(observations.values()), health


def check_catalogues():
    path = Path('retailers.json')
    if not path.exists():
        return [], []
    config = json.loads(path.read_text())
    for limit in config['price_limits'].values():
        if not isinstance(limit, (int, float)) or not 0 < limit <= 250:
            raise ValueError('Invalid retail price limit')
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda store: check_store(store, config['price_limits']), config['stores']))
    return [p for products, _ in results for p in products], [h for _, h in results]
