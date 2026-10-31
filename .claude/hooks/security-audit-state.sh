#!/usr/bin/env bash
# Tracks which source changes have been audited.
#
#   security-audit-state.sh digest   prints a digest of the current unstaged+staged source diff
#   security-audit-state.sh save     records the current digest as audited
#   security-audit-state.sh check    exits 0 when the current diff is already audited, 1 otherwise
#
# The state file lives in .claude/.security-audit-state and is per working tree, not committed.
set -u

ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
STATE="$ROOT/.claude/.security-audit-state"
# Paths never worth auditing: docs, planning artifacts, lock files, images, and tests.
# Tests are excluded deliberately: a defect in a test is not an exploitable defect in the
# product, and test fixtures are full of patterns that look alarming and are not.
SKIP_RE='(^|/)\.security-audit-state$|(^|/)(docs|openspec|\.openspec|node_modules|\.venv|dist|build)/|\.(md|txt|lock|png|jpe?g|svg|gif|ico|snap)$|(^|/)__screenshots__/|(^|/)(tests?|__tests__|__mocks__|fixtures|cassettes|e2e)/|(^|/)conftest\.py$|(^|/)test_[^/]*\.py$|_test\.py$|\.(test|spec|visual)\.[jt]sx?$'

# Hashing, portably: macOS has shasum, most Linux images have sha1sum, Git Bash on Windows may
# have either. cksum is the last resort and exists everywhere.
hash_stdin() {
  if command -v shasum >/dev/null 2>&1; then shasum
  elif command -v sha1sum >/dev/null 2>&1; then sha1sum
  elif command -v md5sum >/dev/null 2>&1; then md5sum
  else cksum
  fi | cut -d' ' -f1
}

# Changed tracked files and brand-new untracked ones: a new module is the commonest way new
# code arrives, and it has no diff against HEAD, so it must be listed separately.
candidates() {
  {
    git -C "$ROOT" diff HEAD --name-only 2>/dev/null
    git -C "$ROOT" ls-files --others --exclude-standard 2>/dev/null
  } | sort -u | grep -Ev "$SKIP_RE"
}

digest() {
  candidates |
    while IFS= read -r file; do
      [ -n "$file" ] || continue
      printf '%s\n' "$file"
      if git -C "$ROOT" ls-files --error-unmatch "$file" >/dev/null 2>&1; then
        git -C "$ROOT" diff HEAD -- "$file" 2>/dev/null
      else
        cat "$ROOT/$file" 2>/dev/null
      fi
    done | hash_stdin
}

case "${1:-digest}" in
  digest) digest ;;
  save)
    mkdir -p "$(dirname "$STATE")"
    digest > "$STATE"
    echo "security audit recorded for the current changes"
    ;;
  check)
    now="$(digest)"
    # An empty source diff is nothing to audit.
    [ "$now" = "$(printf '' | hash_stdin)" ] && exit 0
    [ -f "$STATE" ] && [ "$now" = "$(cat "$STATE")" ] && exit 0
    exit 1
    ;;
  *)
    echo "usage: $0 [digest|save|check]" >&2
    exit 2
    ;;
esac
