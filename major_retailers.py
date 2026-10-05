"""Verified retailer-specific parsing and Best Buy first-party discovery."""
import html
import json
import math
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

BB_CATEGORY = 'https://www.bestbuy.ca/en-ca/category/pokemon-tcg/10857174'
BB_FILTER = 'category%3AToys%2C+Games+%26+Education%3Bcategory%3ABoard+Games%2C+Cards+%26+Puzzles%3Bcategory%3ATrading+Cards+%26+Accessories%3Bcategory%3APok%C3%A9mon+TCG%3Bsoldandshippedby0enrchstring%3ABest+Buy'


def price_value(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and 0 < value <= 250 else None
    except (ValueError, TypeError):
        return None


def ld_products(page):
    def walk(value):
        if isinstance(value, dict):
            if value.get('@type') == 'Product': yield value
            for child in value.values(): yield from walk(child)
        elif isinstance(value, list):
            for child in value: yield from walk(child)
    for raw in re.findall(r'<script\b[^>]*type=[\"\']application/ld\+json[\"\'][^>]*>(.*?)</script>', page, re.I | re.S):
        try: yield from walk(json.loads(html.unescape(raw)))
        except ValueError: continue


def parse_direct_ld(page, retailer, url):
    expected = urllib.parse.urlparse(url)
    if retailer == 'ebgames_ca':
        if expected.hostname != 'www.ebgames.ca' or not expected.path.startswith('/shop/'): return 'unknown', None
        sku = expected.path.rstrip('/').rsplit('/', 1)[-1].split('-')[0]
        # This is the product's condition label, not a site-wide 'Used' navigation link.
        new_label = bool(re.search(r'\bNew:\s*' + re.escape(sku) + r'\b', html.unescape(page)))
        condition_rows = [html.unescape(re.sub(r'<[^>]+>', ' ', row)) for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>', page, re.I | re.S)]
        new_row = any(re.fullmatch(r'\s*Condition\s+New\s*', row) for row in condition_rows)
        if not (new_label or new_row): return 'unknown', None
    else:
        if expected.hostname != 'www.pokemoncenter.com' or not expected.path.startswith('/en-ca/product/'): return 'unknown', None
        sku = expected.path.split('/')[3]
    offers = []
    for node in ld_products(page):
        if str(node.get('sku')) != sku: continue
        name = str(node.get('name', '')).lower()
        if re.search(r'french|japanese|chinese|korean|pre[ -]?order|used|damaged|reseal', name): continue
        offer = node.get('offers', {})
        if not isinstance(offer, dict): continue
        actual = urllib.parse.urlparse(offer.get('url') or node.get('url', ''))
        if actual.hostname != expected.hostname: continue
        if retailer == 'ebgames_ca':
            if actual.path.rstrip('/').rsplit('/',1)[-1] != expected.path.rstrip('/').rsplit('/',1)[-1]: continue
        elif actual.path.rstrip('/') != expected.path.rstrip('/'): continue
        if retailer == 'pokemon_center_ca':
            if offer.get('seller', {}).get('name') != 'Pokémon Center' or str(offer.get('itemCondition', '')).rsplit('/', 1)[-1] != 'NewCondition': continue
        price = price_value(offer.get('price'))
        if offer.get('priceCurrency') != 'CAD' or price is None: continue
        availability = str(offer.get('availability', '')).rsplit('/', 1)[-1]
        if availability in ('InStock', 'OutOfStock', 'SoldOut'):
            offers.append(('in_stock' if availability == 'InStock' else 'out_of_stock', price))
    return offers[0] if offers and len(set(offers)) == 1 else ('unknown', None)


def bestbuy_state(page):
    match = re.search(r'window\.__INITIAL_STATE__\s*=\s*', page)
    if not match: raise ValueError('Best Buy product data unavailable')
    data, _ = json.JSONDecoder().raw_decode(page[match.end():])
    return data


def parse_bestbuy(page, url):
    parsed = urllib.parse.urlparse(url)
    if parsed.hostname != 'www.bestbuy.ca' or not parsed.path.startswith('/en-ca/product/'): return 'unknown', None
    sku = parsed.path.rstrip('/').rsplit('/', 1)[-1]
    try:
        data = bestbuy_state(page)
        root = data['product']; product = root['product']; availability = root['availability']
        if data['intl']['locale'] != 'en-CA' or str(product.get('sku')) != sku or str(availability.get('sku')) != sku: return 'unknown', None
        # Canada storefront locale establishes the price currency. Seller is independently
        # verified from explicit marketplace flag, seller object and rendered seller marker.
        if product.get('isMarketplace') is not False or product.get('seller') is not None or 'data-testid="sold-by-best-buy"' not in page: return 'unknown', None
        if product.get('grade') != 'Brand New' or product.get('isPreorderable') is not False: return 'unknown', None
        if root.get('isAvailabilityError') is not False or root.get('isAvailabilityLoading') is not False: return 'unknown', None
        price = price_value(product.get('priceWithoutEhf'))
        if price is None: return 'unknown', None
        shipping = availability.get('shipping', {})
        if shipping.get('purchasable') is True and shipping.get('status') in ('InStock', 'InStockOnlineOnly'): return 'in_stock', price
        if shipping.get('purchasable') is False and shipping.get('status') in ('OutOfStock', 'OutOfStockOnline', 'OutOfStockOnlineOnly'): return 'out_of_stock', price
    except (ValueError, KeyError, TypeError, AttributeError): pass
    return 'unknown', None


def bestbuy_candidates(data):
    result=[]
    if data.get('intl', {}).get('locale') != 'en-CA': raise ValueError('Canadian storefront unconfirmed')
    search=data['search']['searchResult']
    for p in search['products']:
        title=p.get('name',''); text=title.lower().replace('é','e')
        if p.get('isMarketplace') is not False or p.get('seller') is not None: continue
        if 'pokemon' not in text or re.search(r'french|japanese|korean|chinese|\bcase\b|\bsingle\b|mystery|random booster|used|damaged',text): continue
        if 'booster bundle' in text: ceiling=60
        elif 'elite trainer' in text: ceiling=90
        elif 'booster' in text and ('box' in text or 'display' in text): ceiling=230
        elif '30th' in text and ('collection' in text or 'tin' in text or 'box' in text): ceiling=150 if '10-pack' in text else 50
        elif 'premium collection' in text: ceiling=180
        else: continue
        sku=str(p.get('sku','')); slug=p.get('seoName','')
        if not sku.isdigit() or not re.fullmatch(r'[a-z0-9-]+',slug): continue
        result.append({'title':title,'retailer':'bestbuy_ca','retailer_name':'Best Buy Canada','url':f'https://www.bestbuy.ca/en-ca/product/{slug}/{sku}','max_price':ceiling,'source':'retail_catalogue','location':'Canada — online shipping'})
    return result, search['totalPages']


def check_bestbuy_catalogue(fetch, check):
    now=datetime.now(timezone.utc).isoformat()
    health={'store':'bestbuy_ca','checked_at':now,'ok':False,'pages':0,'truncated':False}
    candidates={}
    try:
        for page in range(1,4):
            data=bestbuy_state(fetch(BB_CATEGORY+'?path='+BB_FILTER+f'&page={page}', 'bestbuy_ca'))
            products,pages=bestbuy_candidates(data)
            health['pages']=page
            for p in products:candidates[p['url']]=p
            if page >= pages:break
        else:health['truncated']=True
        with ThreadPoolExecutor(max_workers=2) as executor: observations=list(executor.map(check,candidates.values()))
        health.update(ok=all(p['stock'] != 'unknown' for p in observations),matched_variants=len(observations))
        return observations, [health]
    except Exception as exc:
        health['error']=type(exc).__name__
        return [],[health]
