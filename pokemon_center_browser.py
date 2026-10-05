"""Optional visible-browser Pokémon Center monitor; challenges require manual handling."""
import argparse
import getpass
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from major_retailers import parse_direct_ld
from monitor import apply_observation, notify, send_discord, write_json

ROOT = Path(__file__).resolve().parent


def load_watchlist():
    products = json.loads((ROOT / 'pokemon-center-watchlist.json').read_text())['products']
    for p in products:
        u=urlparse(p['url'])
        if u.scheme!='https' or u.hostname!='www.pokemoncenter.com' or not u.path.startswith('/en-ca/product/'):
            raise ValueError('Only official Canadian Pokemon Center product URLs are supported')
        if not 0 < p['max_price'] <= 250: raise ValueError('Invalid price limit')
    return products


def browser_observation(page, product):
    """Only rendered structured data and the product's own purchase control count."""
    actual=urlparse(page.url);expected=urlparse(product['url'])
    if actual.hostname != expected.hostname or actual.path.rstrip('/') != expected.path.rstrip('/'):
        raise ValueError('Unexpected product navigation')
    stock,price=parse_direct_ld(page.content(), 'pokemon_center_ca', product['url'])
    error=None if stock!='unknown' else 'No verified CAD offer; preorders are not stock alerts'
    if stock=='in_stock':
        buttons=page.locator('button[class*="add-to-cart-button"]')
        if buttons.count()!=1 or not buttons.first.is_enabled() or not buttons.first.is_visible() or buttons.first.inner_text().strip().lower()!='add to cart':
            stock,price,error='unknown',None,'Purchase control unconfirmed'
    return {**product,'retailer':'pokemon_center_ca','stock':stock,'price':price,'checked_at':datetime.now(timezone.utc).isoformat(),'check_error':error}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--interval',type=int,default=120)
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    if args.interval<60: raise SystemExit('Use an interval of at least 60 seconds')
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as BrowserTimeout
    except ImportError:
        raise SystemExit('Playwright is missing. Run Start-PokemonCenter.cmd to install the free dependency.')
    products=load_watchlist()
    if not products:raise SystemExit('Pokemon Center watchlist is empty')
    webhook=os.environ.get('DISCORD_WEBHOOK_URL','').strip()
    if not webhook and not args.dry_run:webhook=getpass.getpass('Discord webhook URL (hidden; not saved): ').strip()
    if not args.dry_run:
        send_discord(webhook,'Pokemon Center browser monitor starting — connection test, NOT a stock alert.')
    data_dir=ROOT / '.state';data_dir.mkdir(exist_ok=True)
    state_path=data_dir/'pokemon-center-state.json'
    previous=json.loads(state_path.read_text()) if state_path.exists() else {}
    with sync_playwright() as p:
        # A separate, ordinary visible Chrome profile. No stealth patches, proxy,
        # fingerprint changes, exported cookies or automatic CAPTCHA handling.
        try:context=p.chromium.launch_persistent_context(str(data_dir/'pokemon-center-browser'),channel='chrome',headless=False)
        except Exception:raise SystemExit('Could not open Google Chrome. Install Chrome or close another Pokemon Center monitor using this profile.')
        page=context.pages[0] if context.pages else context.new_page()
        page.goto(products[0]['url'],wait_until='domcontentloaded',timeout=60000)
        print('A normal Chrome window has opened. No account login is needed.')
        print('Check that the Canadian product page loads. Handle any site verification yourself.')
        input('When the product page is visible, press Enter here to start checks: ')
        try:
            while True:
                start=time.monotonic();observations=[]
                for product in products:
                    try:
                        if page.url!=product['url']:page.goto(product['url'],wait_until='domcontentloaded',timeout=30000)
                        page.locator('script[type="application/ld+json"]').first.wait_for(state='attached',timeout=20000)
                        observation=browser_observation(page,product)
                    except (BrowserTimeout,ValueError):
                        observation={**product,'retailer':'pokemon_center_ca','stock':'unknown','price':None,'checked_at':datetime.now(timezone.utc).isoformat(),'check_error':'Product page not verified'}
                    body=page.locator('body').inner_text(timeout=5000)
                    blocked=bool(re.search(r'pardon our interruption|verifying the device|verify you are human|access denied|unusual traffic',body,re.I)) or page.locator('iframe[src*="captcha-delivery"]').count()>0
                    if blocked:
                        print('Pokemon Center requested verification. Automatic checks are PAUSED; no stock claim was made.')
                        input('Resolve the page manually, then press Enter to resume (Ctrl+C to stop): ')
                        # No automatic reload or alternate-route retry while blocked.
                        observation=browser_observation(page,product)
                    observations.append(observation)
                    print(f"{observation['stock']} CAD {observation['price']}: {product['title']}")
                    if not args.dry_run:
                        try:
                            previous[product['url']]=apply_observation(observation,previous.get(product['url'],{}),lambda item:notify(webhook,item))
                            write_json(state_path,previous)
                        except RuntimeError as exc:print(f'{exc}; alert will retry next cycle.')
                write_json(data_dir/'pokemon-center-report.json',{'checked_at':datetime.now(timezone.utc).isoformat(),'products':observations,'dry_run':args.dry_run})
                if args.once:break
                # Normal scheduled checks only; no retry loop for a site-served challenge.
                time.sleep(max(1,args.interval-(time.monotonic()-start)))
        except KeyboardInterrupt:print('Pokemon Center monitor stopped.')
        finally:context.close()

if __name__=='__main__':main()
