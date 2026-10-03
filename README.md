# Pokemon stock signals

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
