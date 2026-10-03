# Pokemon stock signals

Discovery finds candidate links. It does not prove stock. `monitor.py` revisits
each URL in `signals.json` directly and alerts Discord only for an unambiguous
CAD product offer at $250 or less. Walmart offers require an explicit Walmart
seller. Generic cart buttons, blocked responses and ambiguous offers remain
unknown. This initial adapter supports Product JSON-LD; retailers without that
data need a separately verified adapter or a permitted stock feed.

Set repository Actions secret `DISCORD_WEBHOOK_URL` to your existing Discord
webhook. Never commit the webhook. The monitor fails visibly if it is missing.
The scheduled job requests a check every five minutes; GitHub may delay runs,
so this is not a guaranteed five-minute service or a fast-drop buying system.

Add official Canadian product URLs to `signals.json` with title, url, retailer
(`costco_ca`, `walmart_ca`, `pokemon_center_ca`), stock (`unknown` initially),
price (`null` initially), and verified_retailer. Discovery retains these URLs.
Use Canadian Pokemon Center links; CAD verification is required for alerts.

An initially available product alerts once. A confirmed out-of-stock to
in-stock transition alerts again. Unknown checks preserve the last confirmed
state. Failed Discord deliveries retry on the next check. State is committed
to `stock-state.json`. Workflow logs show unavailable verification, without
printing the webhook. There is no checkout automation or CAPTCHA bypass.

Run `python -m unittest -v test_monitor` for parser checks. Real retailer access
and Discord delivery must be tested before treating the monitor as operational.
