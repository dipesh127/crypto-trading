# Operations

## Prometheus / Grafana

The dashboard exposes Prometheus metrics at `/metrics`. `docker-compose.dashboard.yml` includes Prometheus and Grafana with a provisioned datasource/dashboard.

## CDN

Vite produces hashed `/assets/*` files. `frontend/nginx.conf` marks them immutable and keeps `index.html` revalidating. `scripts/deploy_frontend_cdn.sh` uploads assets to an S3-compatible CDN origin and invalidates CloudFront when `CLOUDFRONT_DISTRIBUTION_ID` is supplied.

## Alerts

Set `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` and/or `DISCORD_WEBHOOK_URL` to enable risk/reconciliation notifications. Credentials are read from environment variables and are never stored in the database.

## Historical backfill

`python scripts/backfill_market_data.py --days 90` paginates klines over the requested period. Use `--symbols BTCUSDT,ETHUSDT --batch 1000` to control scope and request size.

## Database query verification

Run `python scripts/verify_dashboard_indexes.py --json` against the deployed production-sized database. The command executes real `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` statements and exits non-zero when required plans/index assertions fail.
