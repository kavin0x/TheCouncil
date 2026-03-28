#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

if ! command -v socket >/dev/null 2>&1; then
  echo "[socket-hook] Socket CLI not found; skipping scan."
  exit 0
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "[socket-hook] Not in a git repository; skipping scan."
  exit 0
fi

# Diff against HEAD to include both staged and unstaged changes.
all_diff="$(git diff --unified=0 HEAD -- . || true)"

requirements_changed=0
imports_changed=0

if git diff --name-only HEAD -- requirements.txt | grep -q "^requirements\.txt$"; then
  requirements_changed=1
fi

if printf "%s\n" "$all_diff" | grep -Eq "^diff --git a/.*\.py b/.*\.py$"; then
  if printf "%s\n" "$all_diff" | grep -Eq "^[+-](from|import)[[:space:]]"; then
    imports_changed=1
  fi
fi

# Also consider imports in untracked Python files.
if [[ "$imports_changed" -eq 0 ]]; then
  while IFS= read -r file; do
    if grep -Eq "^(from|import)[[:space:]]" "$file"; then
      imports_changed=1
      break
    fi
  done < <(git ls-files --others --exclude-standard -- "*.py")
fi

if [[ "$requirements_changed" -eq 0 && "$imports_changed" -eq 0 ]]; then
  echo "[socket-hook] No requirements/import changes detected; skipping scan."
  exit 0
fi

echo "[socket-hook] Dependency changes detected; running Socket scan..."
socket scan create .
