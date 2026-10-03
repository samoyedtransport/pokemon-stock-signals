import json
import unittest
from monitor import parse_product


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


if __name__ == '__main__':
    unittest.main()
