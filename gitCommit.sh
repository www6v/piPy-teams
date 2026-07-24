#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT_DIR}"

REMOTE="origin"

if ! git rev-parse --git-dir > /dev/null 2>&1; then
  echo "error: not a git repository" >&2
  exit 1
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "${BRANCH}" == "HEAD" ]]; then
  echo "error: detached HEAD, checkout a branch first" >&2
  exit 1
fi

commit_msg="${1:-chore: update $(date +%Y-%m-%d\ %H:%M:%S)}"

if ! git diff --quiet || ! git diff --cached --quiet || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
  git add -A
  git commit -m "${commit_msg}"
else
  echo "nothing to commit, pushing existing commits"
fi

git push "${REMOTE}" "${BRANCH}"

echo "pushed ${BRANCH} to ${REMOTE}"
