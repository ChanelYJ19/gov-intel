#!/usr/bin/env bash
# One-time sync: copy latest main from Cursor Origin onto GitHub.
set -euo pipefail

GITHUB_REMOTE="${GITHUB_REMOTE:-github}"
CURSOR_REMOTE="${CURSOR_REMOTE:-cursor}"

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "Run this inside your gov-intel clone." >&2
  exit 1
fi

if ! git remote | grep -qx "$CURSOR_REMOTE"; then
  git remote add "$CURSOR_REMOTE" "https://origin.cursor.com/chanel-johnson/gov-intel.git"
  echo "Added remote '$CURSOR_REMOTE' -> Cursor Origin"
fi

if ! git remote | grep -qx "$GITHUB_REMOTE"; then
  git remote add "$GITHUB_REMOTE" "https://github.com/ChanelYJ19/gov-intel.git"
  echo "Added remote '$GITHUB_REMOTE' -> GitHub"
fi

echo "Fetching main from Cursor Origin (origin auth login if this fails)..."
git fetch "$CURSOR_REMOTE" main

git checkout main
git merge "$CURSOR_REMOTE"/main -m "Sync main from Cursor Origin"

echo "Pushing to GitHub..."
git push "$GITHUB_REMOTE" main

echo "Done. Verify: ls coverage_test.py fixtures/coverage_test_set.csv"
