#!/usr/bin/env bash
# Publish the npm package in the working directory, unless that exact version is
# already on the registry.
#
# Without this, recovering a half-failed release is impossible: the npm job
# publishes two packages in sequence, and if the second one fails, re-running
# replays the first, which exits non-zero with "You cannot publish over the
# previously published versions" and the second never runs again.
set -euo pipefail

name=$(node -p "require('./package.json').name")
version=$(node -p "require('./package.json').version")

# `npm view <pkg>@<version> version` exits non-zero when that version does not
# exist, which is the whole test. 2>/dev/null because the miss is expected.
if npm view "$name@$version" version >/dev/null 2>&1; then
  echo "$name@$version is already on the registry; skipping publish."
else
  echo "Publishing $name@$version"
  npm publish
fi
