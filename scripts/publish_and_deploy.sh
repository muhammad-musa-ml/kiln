#!/usr/bin/env bash
# Rebuild the public site, refuse to ship if it leaks, then deploy.
set -e
cd "$(dirname "$0")/.."
python -m kiln.publish
python scripts/audit_public.py   # exits non-zero on any finding
cd public
npx --yes vercel deploy --prod --yes
