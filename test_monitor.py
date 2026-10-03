import json
import unittest
import io
import urllib.error
from unittest.mock import patch, MagicMock
from monitor import parse_product, apply_observation, send_discord
from worker import run_loop


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


class WorkerTests(unittest.TestCase):
    def test_failed_cycles_back_off_and_success_resets_interval(self):
        stop = MagicMock()
        stop.is_set.return_value = False
        stop.wait.side_effect = [False, False, False, True]
        checks = MagicMock(side_effect=[1, 1, 1, 0])
        run_loop(60, stop, checks, clock=lambda: 0)
        self.assertEqual([call.args[0] for call in stop.wait.call_args_list], [60, 120, 240, 60])

    def test_stopped_worker_does_not_check_or_wait(self):
        stop = MagicMock()
        stop.is_set.return_value = True
        checks = MagicMock()
        run_loop(60, stop, checks)
        checks.assert_not_called()
        stop.wait.assert_not_called()


class DiscordTests(unittest.TestCase):
    url = 'https://discord.com/api/webhooks/123/example-test-token'

    def test_confirmation_and_client_header(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = b'{"id":"456"}'
        with patch('monitor.urllib.request.urlopen', return_value=response) as opener:
            send_discord('  ' + self.url + '  ', 'connection test')
            request = opener.call_args.args[0]
            self.assertIn('wait=true', request.full_url)
            self.assertTrue(request.get_header('User-agent').startswith('DiscordBot ('))
            self.assertEqual(json.loads(request.data)['allowed_mentions'], {'parse': []})

    def test_http_error_does_not_expose_token(self):
        error = urllib.error.HTTPError(self.url, 404, 'Not found', {}, io.BytesIO(b'{"code":10015,"message":"Unknown Webhook"}'))
        with patch('monitor.urllib.request.urlopen', side_effect=error):
            with self.assertRaisesRegex(RuntimeError, 'Discord HTTP 404; API code 10015') as caught:
                send_discord(self.url, 'connection test')
        self.assertNotIn('example-test-token', str(caught.exception))

    def test_invalid_url_never_sent(self):
        with patch('monitor.urllib.request.urlopen') as opener:
            with self.assertRaisesRegex(RuntimeError, 'Invalid Discord'):
                send_discord('https://example.com/api/webhooks/123/token', 'test')
            opener.assert_not_called()


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
