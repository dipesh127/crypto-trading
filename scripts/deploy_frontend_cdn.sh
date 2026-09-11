#!/usr/bin/env bash
set -euo pipefail
: "${CDN_BUCKET:?Set CDN_BUCKET, e.g. s3://my-dashboard-bucket}"
cd "$(dirname "$0")/../frontend"
if [[ -f package-lock.json ]]; then npm ci; else npm install; fi
npm run build
aws s3 sync dist/ "$CDN_BUCKET/" --delete --cache-control "public,max-age=31536000,immutable" --exclude index.html
aws s3 cp dist/index.html "$CDN_BUCKET/index.html" --cache-control "no-cache,max-age=0,must-revalidate" --content-type "text/html"
if [[ -n "${CLOUDFRONT_DISTRIBUTION_ID:-}" ]]; then aws cloudfront create-invalidation --distribution-id "$CLOUDFRONT_DISTRIBUTION_ID" --paths /index.html; fi
