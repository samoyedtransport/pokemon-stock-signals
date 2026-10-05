# Pokemon stock monitor — free setup

## Start on Windows

1. Download https://github.com/samoyedtransport/pokemon-stock-signals/archive/refs/heads/main.zip
2. Extract the entire ZIP to a normal folder; do not launch from inside the ZIP.
3. Double-click `Start-Monitor.cmd`. The launcher checks for Python 3.10+.
   If missing, install Python from https://www.python.org/downloads/windows/
   and reopen the launcher. It accepts either `py -3` or `python`.
4. Paste your existing Discord webhook at the hidden prompt and press Enter.
   Characters will not appear while entering the URL.
5. Check Discord for `Pokemon local monitor started — connection test, NOT a stock alert.`
   The terminal confirms connection before starting product checks. Keep the
   window open and the PC awake. Closing the window or sleeping the PC stops it.

There is no hosting subscription for this setup. The default check target is
60 seconds, subject to page response time and failure backoff. To request
30-second checks, run `py -3 worker.py --interval 30` from the extracted folder.
The webhook is not written to disk, so you enter it again after restarting.
Only confirmed first-party Canadian online stock within your configured price
ceiling triggers a restock alert. A connection test is never a stock claim.

## Free GitHub fallback

Your connected GitHub workflow can run while the PC is off, but scheduled runs
can be delayed. Local and GitHub alert histories are separate, so the same
restock may notify twice while both are enabled. Leave the fallback enabled
until the local monitor is confirmed working.

`monitor.py` directly checks the explicit Canadian product list in `watchlist.json`.
Search discovery in `discover.py` is a separate candidate feed and cannot silently
expand alert coverage. The initial list contains 12 Costco/Walmart products with
an editable CAD $100 ceiling per product.

Costco checks match product-specific JSON-LD offers to the requested product URL.
Walmart checks embedded product data for the exact item ID, seller ID 0, seller
name Walmart, first-party offer, CAD price, and online shipping availability.
Marketplace offers, pickup-only availability, wrong products, and ambiguous or
blocked responses cannot generate stock alerts. Pokemon Center still needs live
adapter/access verification before it can be considered covered.

## Setup

Set GitHub repository Actions secret `DISCORD_WEBHOOK_URL` to your existing Discord
webhook. The legacy secret name `DISCORD_WEBHOOK` also works. Never commit it.
Checks run even without a secret, but the workflow fails visibly and alert history
never advances. Deployment of code or watchlist changes sends a labeled connection
test when configured. The scheduled workflow requests a check every five minutes;
GitHub can delay runs, so this is not a guaranteed fast-drop service.

Add official Canadian product URLs to `watchlist.json` with title, url, retailer
(`costco_ca`, `walmart_ca`, `pokemon_center_ca`), and max_price in CAD. A Product
JSON-LD offer on another supported retailer is only accepted with matching product
URL and CAD currency. All fetching uses normal public pages; there is no checkout
automation or CAPTCHA bypass.

## Alerts and health

Initially available products alert once if below the price ceiling. A confirmed
out-of-stock to in-stock transition alerts again. A price drop below the ceiling
also qualifies. Unknown checks preserve confirmed state. Delivery failures leave
alerts retryable. Delivered-alert history is saved in `stock-state.json`.

Each run uploads `monitor-report.json` as a seven-day workflow artifact and shows
per-product results in the Actions summary. Partial verification warns; zero
verified products, missing webhook, or failed Discord delivery fail the job.
Search discovery and monitoring share a concurrency group to serialize writes.

## Verification

Run `python -m unittest -v test_monitor` for parser and alert-history tests.
Run `python monitor.py --dry-run` to check live stock and produce a report without
sending messages or changing alert history. `python monitor.py --test-alert`
also sends a clearly labeled connection test, requiring the webhook environment
variable. Live retailer checks and successful Discord delivery are required before
calling the system operational.

## Continuous runner (prepared; requires an always-on host)

GitHub's requested five-minute schedule can be delayed or dropped. For steadier
checks, run `python worker.py` on an awake PC or a hosted background service.
The default target interval is 60 seconds; `--interval 30` requests 30 seconds.
Slow page responses can lengthen a cycle. Whole-job failures use capped backoff.
An unknown individual product does not prevent checks for other products.

On Windows with Python 3 installed, download/extract this repository and double
click `Start-Monitor.cmd`. Paste your Discord webhook at the hidden prompt; it
is kept in the child process environment and is not written to disk. The PC must
stay awake and the window open. Ctrl+C stops the monitor after the current check.

For a hosted background worker, use start command `python worker.py`, set the
private environment variable `DISCORD_WEBHOOK_URL`, and attach persistent storage
at the path specified by `MONITOR_DATA_DIR`. No third-party Python dependencies
are required. Configure the host to restart the process after crashes/reboots.
Do not run multiple workers against the same state directory. Local `.state`
contains operational history and reports and must persist to avoid repeat alerts.
A separately hosted worker and GitHub fallback have separate histories and can
send duplicate stock alerts; use one primary alerting runner after setup.

Run `python worker.py --once --dry-run` to verify access without notifications.
The faster runner is not hosted or running continuously until you launch it on
an always-on computer/service. The existing GitHub fallback remains enabled.

## Expanded Canadian retail coverage

`retailers.json` contains optional, **disabled-by-default** configurations for 401 Games (Toronto/Vaughan), Hobbiesville (Toronto/Ottawa), KanZen Games (GTA), and Face to Face Games (Toronto/Montreal). These independent card shops can charge above major-retailer prices. They are not checked and produce no stock or coverage alerts unless a store is explicitly set to `"enabled": true`. Default monitoring remains Walmart first-party and Costco. Pokémon Center, GameStop/EB Games, Best Buy and Toys “R” Us are priorities for future verified adapters; they are not currently enabled monitors. We select recognizable sealed product formats and exclude listings marked singles, used, opened, damaged, resealed, cases, imports, preorders, app exclusive, or in-store only. This filtering cannot establish a shop's upstream sourcing or guarantee factory condition: verify the actual listing before buying.

The catalogue reader verifies CAD using the public cart response, then checks up to three pages of 250 products per store each cycle. It reports truncated catalogues and failures in `monitor-report.json`; a failed/missing listing never becomes a false sold-out observation. Catalogue `available` is the store's public online availability signal, not a checkout reservation or a guarantee of shipping or local pickup.

Default alert ceilings (CAD before taxes/shipping): booster bundles $60, ETBs $90, booster boxes $180, premium collections $150. Edit `price_limits` in `retailers.json` to change them. These are spending filters, not MSRP claims or profit estimates. Existing Walmart/Costco product ceilings remain in `watchlist.json`.

The first successful check for each new store creates a silent baseline. Later restocks, newly listed available items, and prices crossing below the ceiling alert automatically with a variant-specific purchase link, retailer, location and check time. Existing eligible stock does not flood Discord at setup. Failed Discord stock deliveries remain retryable. After three consecutive failed store checks, Discord gets one coverage warning; it gets a recovery message when that store works again.

### Updating your Windows copy

1. Stop the old monitor with Ctrl+C and close it.
2. Download the latest main ZIP and Extract All.
3. Copy your old `.state` folder into the new extracted folder to retain local delivered-alert history.
4. Open `Start-Monitor.cmd` in the new folder and paste your webhook again.

Downloading a new ZIP is required; an already running Windows copy does not update itself. Keep only one local monitor running. GitHub cloud checks and local checks have separate state and may both alert for the same change. No subscriptions or extra Python packages are required.

The monitor still checks Walmart first-party only. Some Walmart pages are blocked or missing embedded data, these remain explicitly unknown rather than fabricated stock. The White Flare URL has been replaced with a canonical product path verified to expose Walmart first-party stock data. Pokémon Center is not currently verified. More catalogue coverage helps detection, but stock can sell out before manual checkout and local in-store availability must be checked with the store.
