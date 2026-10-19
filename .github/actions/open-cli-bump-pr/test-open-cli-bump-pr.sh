#!/usr/bin/env bash
# Tests open-cli-bump-pr.sh against a local bare repository and a stub gh.
set -euo pipefail

script="$(cd "$(dirname "$0")" && pwd)/open-cli-bump-pr.sh"
test_root="$(mktemp -d)"
trap 'rm -rf "$test_root"' EXIT
remote="$test_root/remote/acme/tool.git"
branch="release/cloudsmith-cli"
bump="printf '%s\\n' \"\$VERSION\" > version.txt"

mkdir -p "$test_root/bin"
cat > "$test_root/bin/gh" <<'EOF'
#!/usr/bin/env bash
echo "gh $*" >> "$STUB_DIR/gh.log"
case "$1 $2" in
  "pr list") cat "$STUB_DIR/pr-number" 2>/dev/null || true ;;
  "pr view")
    if [[ -f "$STUB_DIR/pr-closed" ]]; then
      echo CLOSED
      rm "$STUB_DIR/pr-number" "$STUB_DIR/pr-closed"
    else
      echo OPEN
    fi ;;
esac
EOF
printf '#!/bin/sh\n' > "$test_root/bin/sleep"
chmod +x "$test_root/bin/gh" "$test_root/bin/sleep"
printf '[user]\n\tname = Test\n\temail = test@example.com\n' > "$test_root/gitconfig"
export PATH="$test_root/bin:$PATH" STUB_DIR="$test_root/stub"
export GIT_CONFIG_GLOBAL="$test_root/gitconfig" GIT_CONFIG_NOSYSTEM=1
export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0="url.file://$test_root/remote/.insteadOf" GIT_CONFIG_VALUE_0="https://github.com/"

reset_remote() {
  rm -rf "$test_root/remote" "$test_root/seed" "$STUB_DIR"
  mkdir -p "$STUB_DIR"
  git init --quiet --bare --initial-branch main "$remote"
  git init --quiet --initial-branch main "$test_root/seed"
  echo 1.0.0 > "$test_root/seed/version.txt"
  git -C "$test_root/seed" add version.txt
  git -C "$test_root/seed" commit --quiet -m init
  git -C "$test_root/seed" push --quiet "$remote" main
}

open_pending_pr() {
  git -C "$test_root/seed" checkout --quiet -b "$branch"
  echo "$1" > "$test_root/seed/version.txt"
  git -C "$test_root/seed" commit --quiet -am "Bump cloudsmith-cli to v$1"
  git -C "$test_root/seed" push --quiet "$remote" "$branch"
  echo 7 > "$STUB_DIR/pr-number"
}

pushed_version() {
  git -C "$remote" show "$branch:version.txt"
}

assert_nothing_pushed() {
  if git -C "$remote" rev-parse --quiet --verify "$branch" > /dev/null; then exit 1; fi
}

# A new release opens a pull request with one bump commit.
reset_remote
"$script" acme/tool 1.1.0 "$bump"
test "$(pushed_version)" = 1.1.0
test "$(git -C "$remote" log -1 --format=%s "$branch")" = "Bump cloudsmith-cli to v1.1.0"
grep -q "^gh pr create --repo acme/tool --head $branch" "$STUB_DIR/gh.log"

# A repository that already uses the release changes nothing.
reset_remote
"$script" acme/tool 1.0.0 "$bump"
assert_nothing_pushed

# An older release keeps a newer pending bump.
reset_remote
open_pending_pr 1.2.0
"$script" acme/tool 1.1.0 "$bump"
test "$(pushed_version)" = 1.2.0
if grep -q "^gh pr edit" "$STUB_DIR/gh.log"; then exit 1; fi

# A newer release replaces an older pending bump.
reset_remote
open_pending_pr 1.2.0
"$script" acme/tool 1.3.0 "$bump"
test "$(pushed_version)" = 1.3.0
grep -q "^gh pr edit 7" "$STUB_DIR/gh.log"

# A pull request that closes during the update makes the update start again.
reset_remote
open_pending_pr 1.2.0
touch "$STUB_DIR/pr-closed"
"$script" acme/tool 1.3.0 "$bump"
test "$(pushed_version)" = 1.3.0
grep -q "^gh pr create" "$STUB_DIR/gh.log"

# --merge merges the pushed commit when the checks pass.
reset_remote
"$script" --merge acme/tool 1.1.0 "$bump"
grep -q "^gh pr checks $branch --repo acme/tool --watch --fail-fast" "$STUB_DIR/gh.log"
grep -q "^gh pr merge $branch --repo acme/tool --admin --squash --match-head-commit $(git -C "$remote" rev-parse "$branch")" "$STUB_DIR/gh.log"

# --dry-run shows the commit and pushes nothing.
reset_remote
"$script" --dry-run acme/tool 1.1.0 "$bump" | grep -q '^+1.1.0'
assert_nothing_pushed

# A failed bump command fails the script and pushes nothing.
reset_remote
if "$script" acme/tool 1.1.0 'exit 3'; then exit 1; fi
assert_nothing_pushed

# A version that is not MAJOR.MINOR.PATCH is rejected.
if "$script" acme/tool 1.1 "$bump" 2> /dev/null; then exit 1; fi

echo "all open-cli-bump-pr.sh tests passed"
