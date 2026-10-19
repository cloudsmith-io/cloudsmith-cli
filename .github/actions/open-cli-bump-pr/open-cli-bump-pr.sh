#!/usr/bin/env bash
# Opens or updates a pull request that moves a downstream repository to a
# Cloudsmith CLI release.
# The script clones REPOSITORY and runs COMMAND in the clone, with VERSION in
# the environment. It commits the changes to the release/cloudsmith-cli branch
# and opens a pull request against the default branch. A newer release
# replaces a bump that is not merged yet, but an older release never replaces
# a newer one.
# Usage: open-cli-bump-pr.sh [--merge] [--dry-run] REPOSITORY VERSION COMMAND
#   --merge    Wait for the checks to pass, then squash-merge as an admin.
#   --dry-run  Show the commit, but do not push it.
set -euo pipefail

usage() {
  echo "usage: $0 [--merge] [--dry-run] OWNER/NAME MAJOR.MINOR.PATCH COMMAND" >&2
  exit 1
}

merge=false
dry_run=false
while [[ "${1:-}" == --* ]]; do
  case "$1" in
    --merge) merge=true ;;
    --dry-run) dry_run=true ;;
    *) usage ;;
  esac
  shift
done
[[ $# -eq 3 ]] || usage
repository="$1"
version="$2"
update_command="$3"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || usage

branch="release/cloudsmith-cli"
title="Bump cloudsmith-cli to v$version"
body="Automated update to Cloudsmith CLI v$version."
if [[ "$merge" == true ]]; then
  body="$body The workflow merges it when the checks pass."
fi
clone="$(mktemp -d)"
trap 'rm -rf "$clone"' EXIT

pending_bump_is_newer() {
  local pending_version newest_version
  git -C "$clone" fetch --quiet --depth 1 origin "$branch"
  pending_version="$(git -C "$clone" log -1 --format=%s FETCH_HEAD | sed -n 's/^Bump cloudsmith-cli to v//p')"
  newest_version="$(printf '%s\n' "$pending_version" "$version" | sort -V | tail -n 1)"
  [[ "$pending_version" != "$version" && "$pending_version" == "$newest_version" ]]
}

commit_update() {
  git -C "$clone" checkout --quiet -b "$branch"
  git -C "$clone" add --all
  git -C "$clone" commit --quiet -m "$title"
}

merge_when_checks_pass() {
  # gh pr checks fails when no checks are registered yet.
  sleep 60
  gh pr checks "$branch" --repo "$repository" --watch --fail-fast
  gh pr merge "$branch" --repo "$repository" --admin --squash \
    --match-head-commit "$(git -C "$clone" rev-parse HEAD)"
}

for attempt in 1 2 3; do
  find "$clone" -mindepth 1 -delete
  git clone --quiet --depth 1 "https://github.com/$repository.git" "$clone"
  pr_number="$(gh pr list --repo "$repository" --head "$branch" --state open --json number --jq '.[].number')"
  if [[ -n "$pr_number" ]] && pending_bump_is_newer; then
    echo "pull request #$pr_number already moves $repository to a newer release; skipping"
    exit 0
  fi
  (cd "$clone" && VERSION="$version" bash -c "$update_command")
  if [[ -z "$(git -C "$clone" status --porcelain)" ]]; then
    echo "$repository already uses cloudsmith-cli v$version; skipping"
    exit 0
  fi
  commit_update
  if [[ "$dry_run" == true ]]; then
    git -C "$clone" show
    exit 0
  fi
  git -C "$clone" push --quiet --force origin "$branch"
  if [[ -z "$pr_number" ]]; then
    gh pr create --repo "$repository" --head "$branch" --title "$title" --body "$body"
  elif [[ "$(gh pr view "$pr_number" --repo "$repository" --json state --jq .state)" == OPEN ]]; then
    gh pr edit "$pr_number" --repo "$repository" --title "$title" --body "$body"
  else
    echo "pull request #$pr_number closed during attempt $attempt; starting again from the default branch"
    continue
  fi
  if [[ "$merge" == true ]]; then
    merge_when_checks_pass
  fi
  exit 0
done
echo "pull request for $branch kept closing during the update" >&2
exit 1
