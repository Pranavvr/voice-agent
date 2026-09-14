#!/usr/bin/env bash
#
# Auto-lint files that were just edited.
#
# CI runs `ruff check .` and fails the build on lint errors, so without this the
# loop is: edit -> push -> CI fails -> fix -> push. Fixing at edit time collapses
# that to zero round trips.
#
# Advisory only: this never blocks a tool call. If a linter is missing or a file
# cannot be fixed automatically, CI remains the source of truth.

set -uo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

for path in ${CLAUDE_FILE_PATHS:-}; do
  case "$path" in
    *.py)
      ruff check --fix "$path" >/dev/null 2>&1 || true
      ;;
    *"/frontend/"*.js | *"/frontend/"*.jsx)
      rel="${path#*"/frontend/"}"
      (cd "$repo_root/frontend" && npx --no-install eslint --fix "$rel") >/dev/null 2>&1 || true
      ;;
  esac
done

exit 0
