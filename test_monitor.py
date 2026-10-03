import json
import unittest
from monitor import parse_product, apply_observation


def page(availability='InStock', currency='CAD', seller='Walmart', price='49.99'):
    data = {'@type': 'Product', 'offers': {'@type': 'Offer', 'availability': 'https://schema.org/' + availability, 'price': price, 'priceCurrency': currency, 'seller': {'name': seller}}}
    return '<script type="application/ld+json">' + json.dumps(data) + '</script>'


class StockTests(unittest.TestCase):
    def test_confirmed_offer(self):
        self.assertEqual(parse_product(page(), 'walmart_ca'), ('in_stock', 49.99))

    def test_sold_out(self):
        self.assertEqual(parse_product(page('OutOfStock'), 'costco_ca'), ('out_of_stock', 49.99))

    def test_marketplace_rejected(self):
        self.assertEqual(parse_product(page(seller='Other seller'), 'walmart_ca'), ('unknown', None))

    def test_us_price_rejected(self):
        self.assertEqual(parse_product(page(currency='USD'), 'pokemon_center_ca'), ('unknown', None))

    def test_generic_cart_and_blocked_page_rejected(self):
        self.assertEqual(parse_product('Add to cart In stock Verify you are human', 'costco_ca'), ('unknown', None))

    def test_conflicting_offers_rejected(self):
        self.assertEqual(parse_product(page() + page('OutOfStock'), 'costco_ca'), ('unknown', None))

    def test_wrong_product_rejected(self):
        self.assertEqual(parse_product(page(), 'costco_ca', 'https://www.costco.ca/p/-/pokemon/123'), ('unknown', None))


def walmart_page(**overrides):
    product = {'usItemId': '6000206890893', 'sellerId': '0', 'sellerName': 'Walmart', 'offerType': '1P', 'priceInfo': {'currentPrice': {'price': 42.97, 'currencyUnit': 'CAD'}}, 'availabilityStatus': 'IN_STOCK', 'showAtc': True, 'fulfillmentSummary': [{'fulfillment': 'SHIPPING', 'availability': 'AVAILABLE'}]}
    product.update(overrides)
    return '<script id="__NEXT_DATA__" type="application/json">' + json.dumps({'props': {'pageProps': {'initialData': {'data': {'product': product}}}}}) + '</script>'


class WalmartTests(unittest.TestCase):
    url = 'https://www.walmart.ca/en/ip/seort/6000206890893?selectedSellerId=0'

    def test_walmart_shipping_offer(self):
        self.assertEqual(parse_product(walmart_page(), 'walmart_ca', self.url), ('in_stock', 42.97))

    def test_marketplace_offer(self):
        self.assertEqual(parse_product(walmart_page(sellerId='123', sellerName='Other', offerType='3P'), 'walmart_ca', self.url), ('unknown', None))

    def test_pickup_only_is_not_online_stock(self):
        self.assertEqual(parse_product(walmart_page(fulfillmentSummary=[{'fulfillment': 'PICKUP', 'availability': 'AVAILABLE'}]), 'walmart_ca', self.url), ('unknown', None))

    def test_product_mismatch(self):
        self.assertEqual(parse_product(walmart_page(usItemId='other'), 'walmart_ca', self.url), ('unknown', None))

    def test_out_of_stock(self):
        self.assertEqual(parse_product(walmart_page(availabilityStatus='OUT_OF_STOCK', showAtc=False), 'walmart_ca', self.url), ('out_of_stock', 42.97))


class AlertTests(unittest.TestCase):
    def observation(self, stock='in_stock', price=50):
        return {'stock': stock, 'price': price, 'max_price': 100, 'checked_at': 'now', 'check_error': None}

    def test_initial_alert_and_duplicate_suppression(self):
        sent = []
        state = apply_observation(self.observation(), {}, sent.append)
        apply_observation(self.observation(), state, sent.append)
        self.assertEqual(len(sent), 1)

    def test_unknown_does_not_duplicate(self):
        sent = []
        state = apply_observation(self.observation(), {}, sent.append)
        state = apply_observation(self.observation('unknown', None), state, sent.append)
        apply_observation(self.observation(), state, sent.append)
        self.assertEqual(len(sent), 1)

    def test_confirmed_restock_alerts_again(self):
        sent = []
        state = apply_observation(self.observation(), {}, sent.append)
        state = apply_observation(self.observation('out_of_stock'), state, sent.append)
        apply_observation(self.observation(), state, sent.append)
        self.assertEqual(len(sent), 2)

    def test_delivery_failure_keeps_retry_state(self):
        state = {}
        def fail(product):
            raise RuntimeError('delivery failure')
        with self.assertRaises(RuntimeError):
            apply_observation(self.observation(), state, fail)
        self.assertEqual(state, {})
        sent = []
        apply_observation(self.observation(), state, sent.append)
        self.assertEqual(len(sent), 1)

    def test_price_ceiling_and_drop(self):
        sent = []
        state = apply_observation(self.observation(price=150), {}, sent.append)
        self.assertEqual(len(sent), 0)
        apply_observation(self.observation(price=50), state, sent.append)
        self.assertEqual(len(sent), 1)


if __name__ == '__main__':
    unittest.main()
