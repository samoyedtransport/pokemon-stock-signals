import unittest
from catalogue import observations_for_product, product_kind, check_store, MAX_PAGES, PAGE_SIZE

STORE = {'id': '401_games', 'name': '401 Games', 'base_url': 'https://store.401games.ca', 'collection': 'pokemon-sealed-product', 'location': 'Toronto / Vaughan'}
LIMITS = {'booster_bundle': 60, 'elite_trainer_box': 90, 'booster_box': 180, 'premium_collection': 150}

def product(**changes):
    return dict({'title': 'Pokemon 151 Booster Bundle', 'handle': 'pokemon-151-bundle', 'tags': [], 'variants': [{'id': 123, 'title': 'Default Title', 'price': '49.99', 'available': True}]}, **changes)

class CatalogueTests(unittest.TestCase):
    def test_only_recognized_factory_formats(self):
        self.assertEqual(product_kind(product()), 'booster_bundle')
        for title in ['Pokemon 151 single', 'Pokemon Mystery Booster Box', 'Pokemon Used Elite Trainer Box', 'Pokemon Japanese Booster Box', 'Pokemon 151 Booster Bundle Sealed Case', 'Pokemon 151 Booster Bundle PRE-ORDER']:
            self.assertIsNone(product_kind(product(title=title)), title)

    def test_pokemon_vendor_and_accent(self):
        self.assertEqual(product_kind(product(title='Mega Evolution Booster Bundle', vendor='Pokémon')), 'booster_bundle')

    def test_variant_link_and_budget(self):
        p = observations_for_product(product(), STORE, LIMITS, 'now')[0]
        self.assertTrue(p['url'].endswith('?variant=123'))
        self.assertEqual(p['max_price'], 60)
        self.assertEqual(p['stock'], 'in_stock')

    def test_available_must_be_boolean(self):
        p = product(variants=[{'id':123, 'title':'Default Title', 'price':'50', 'available':'true'}])
        self.assertEqual(observations_for_product(p, STORE, LIMITS, 'now'), [])

    def test_condition_variants_excluded(self):
        p = product(variants=[{'id':123, 'title':'Damaged', 'price':'50', 'available':True}])
        self.assertEqual(observations_for_product(p, STORE, LIMITS, 'now'), [])

    def test_currency_verified_before_stock(self):
        calls=[]
        def fetch(url,base): calls.append(url); return {'currency':'USD'}
        ps,health=check_store(STORE,LIMITS,fetch)
        self.assertEqual(ps,[]);self.assertFalse(health['ok']);self.assertEqual(len(calls),1)

    def test_paginated_catalogue_and_missing_not_soldout(self):
        def fetch(url,base):
            if url.endswith('/cart.js'): return {'currency':'CAD'}
            return {'products':[product()]*PAGE_SIZE} if 'page=1' in url else {'products':[product(handle='pokemon-other', variants=[{'id':124,'title':'Default Title','price':'50','available':False}])]}
        ps,h=check_store(STORE,LIMITS,fetch)
        self.assertTrue(h['ok']);self.assertEqual(len(ps),2);self.assertEqual(h['pages'],2)

    def test_partial_failure_discards_observations(self):
        def fetch(url,base):
            if url.endswith('/cart.js'): return {'currency':'CAD'}
            if 'page=1' in url:return {'products':[product()]*PAGE_SIZE}
            raise TimeoutError()
        ps,h=check_store(STORE,LIMITS,fetch)
        self.assertEqual(ps,[]);self.assertFalse(h['ok'])

    def test_bounded_pages_and_health(self):
        def fetch(url,base):return {'currency':'CAD'} if url.endswith('/cart.js') else {'products':[product()]*PAGE_SIZE}
        ps,h=check_store(STORE,LIMITS,fetch)
        self.assertEqual(h['pages'],MAX_PAGES);self.assertTrue(h['truncated'])

    def test_unapproved_store_never_fetched(self):
        ps,h=check_store({**STORE,'base_url':'https://example.com'},LIMITS,lambda *args:self.fail('must not fetch'))
        self.assertEqual(ps,[]);self.assertFalse(h['ok'])

if __name__ == '__main__': unittest.main()

class MonitorCatalogueIntegrationTests(unittest.TestCase):
    def run_monitor(self, directory, products, dry=False, fail=False):
        import contextlib, io, os
        from unittest.mock import patch
        import monitor
        health=[{'store':'401_games','ok':True}]
        with patch.dict(os.environ, {'DISCORD_WEBHOOK_URL':'configured', 'MONITOR_DATA_DIR':str(directory), 'GITHUB_STEP_SUMMARY':''}), patch('sys.argv',['monitor.py']+(['--dry-run'] if dry else [])), patch.object(monitor,'load_products',return_value=[]), patch.object(monitor,'check_bestbuy_catalogue',return_value=([],[])), patch.object(monitor,'check_catalogues',return_value=(products,health)), patch.object(monitor,'send_discord',side_effect=RuntimeError('delivery failed') if fail else None) as send, contextlib.redirect_stdout(io.StringIO()):
            try: monitor.main()
            except SystemExit:
                if not fail: raise
            return send.call_count

    def test_initial_baseline_then_restock_and_duplicate_suppression(self):
        import tempfile
        from pathlib import Path
        p=observations_for_product(product(),STORE,LIMITS,'now')[0]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)
            self.assertEqual(self.run_monitor(path,[p]),0)
            self.assertEqual(self.run_monitor(path,[{**p,'stock':'out_of_stock'}]),0)
            self.assertEqual(self.run_monitor(path,[p]),1)
            self.assertEqual(self.run_monitor(path,[p]),0)

    def test_new_listing_and_failed_delivery_retry(self):
        import tempfile
        from pathlib import Path
        p=observations_for_product(product(),STORE,LIMITS,'now')[0]
        new=observations_for_product(product(handle='pokemon-new',variants=[{'id':456,'title':'Default Title','price':'50','available':True}]),STORE,LIMITS,'now')[0]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)
            self.run_monitor(path,[p])
            self.assertEqual(self.run_monitor(path,[p,new],fail=True),1)
            self.assertEqual(self.run_monitor(path,[p,new]),1)
            self.assertEqual(self.run_monitor(path,[p,new]),0)

    def test_dry_run_does_not_initialize_history(self):
        import tempfile
        from pathlib import Path
        p=observations_for_product(product(),STORE,LIMITS,'now')[0]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)
            self.assertEqual(self.run_monitor(path,[p],dry=True),0)
            self.assertFalse((path/'stock-state.json').exists())

class DisabledStoreTests(unittest.TestCase):
    def test_disabled_or_unspecified_stores_never_fetch(self):
        import json
        from unittest.mock import patch
        from catalogue import check_catalogues
        config={'stores':[STORE,{**STORE,'enabled':False}], 'price_limits':LIMITS}
        with patch('catalogue.Path.exists',return_value=True), patch('catalogue.Path.read_text',return_value=json.dumps(config)), patch('catalogue.check_store') as check:
            self.assertEqual(check_catalogues(), ([],[]))
            check.assert_not_called()

    def test_only_explicitly_enabled_store_checked(self):
        import json
        from unittest.mock import patch
        from catalogue import check_catalogues
        enabled={**STORE,'enabled':True}
        config={'stores':[STORE,{**STORE,'enabled':False},enabled], 'price_limits':LIMITS}
        with patch('catalogue.Path.exists',return_value=True), patch('catalogue.Path.read_text',return_value=json.dumps(config)), patch('catalogue.check_store',return_value=([],{'ok':True})) as check:
            self.assertEqual(check_catalogues(), ([],[{'ok':True}]))
            check.assert_called_once_with(enabled,LIMITS)
