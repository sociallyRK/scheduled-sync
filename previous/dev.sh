set -euo pipefail
echo "==> Sync and check"
git fetch origin
git diff --quiet origin/main -- app.py index.html && echo "OK: matches remote" || echo "DIFF: differs from remote"
echo "==> Last-touch commits"
git log -n 1 --pretty='[%h] %ad %an: %s' --date=iso -- app.py
git log -n 1 --pretty='[%h] %ad %an: %s' --date=iso -- index.html
