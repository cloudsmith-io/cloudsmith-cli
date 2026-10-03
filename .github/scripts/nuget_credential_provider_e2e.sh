#!/usr/bin/env bash
# Copyright 2026 Cloudsmith Ltd
#
# End-to-end test for the Cloudsmith NuGet credential provider.
#
# Packs a probe package, serves it from a local mock of a private Cloudsmith
# NuGet feed (which also mocks the custom-domains API), and checks that a real
# `dotnet restore` against the feed's custom domain:
#
#   1. fails with 401 while the provider is not installed;
#   2. succeeds once `cloudsmith credential-helper install nuget` has put the
#      `nuget-plugin-cloudsmith` launcher on PATH, with the custom domain found
#      by install-time discovery (warm cache);
#   3. succeeds again with a cold custom-domain cache, so the plugin itself
#      discovers the custom domain through the API at runtime;
#   4. fails with 401 again after `cloudsmith credential-helper uninstall nuget`.
#
# Requires `cloudsmith`, `python` (with cloudsmith_cli importable) and a .NET
# SDK with NuGet 6.13+ (.NET SDK 9.0.200+) on PATH.  Set DOTNET_SDK_VERSION to
# pin the SDK used (via global.json).  Runs under bash on Linux, macOS and
# Windows (Git Bash).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python}"

WORKSPACE_SLUG="ci-workspace"
REPO_SLUG="ci-repo"
CUSTOM_DOMAIN="localhost"
PACKAGE_ID="Cloudsmith.Ci.Probe"
PACKAGE_VERSION="1.0.0"

is_windows() {
  case "$(uname -s)" in
    MINGW* | MSYS* | CYGWIN*) return 0 ;;
    *) return 1 ;;
  esac
}

# A path both bash and native Windows programs understand (D:/a/b on Windows).
native_path() {
  if is_windows; then cygpath -m "$1"; else printf '%s' "$1"; fi
}

# A path usable in bash's colon-separated PATH.
posix_path() {
  if is_windows; then cygpath -u "$1"; else printf '%s' "$1"; fi
}

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

step() {
  echo
  echo "== $* =="
}

WORK="$(native_path "$(mktemp -d)")"
FEED_DIR="$WORK/feed"
mkdir -p "$FEED_DIR"
cd "$WORK"
if [ -n "${DOTNET_SDK_VERSION:-}" ]; then
  printf '{"sdk": {"version": "%s", "rollForward": "latestFeature"}}\n' \
    "$DOTNET_SDK_VERSION" >"$WORK/global.json"
fi

# The launcher goes where `install` puts it by default: beside `cloudsmith`,
# which is on PATH, so NuGet discovers it and `list` reports it.
BIN_DIR="$("$PYTHON" -c "
from cloudsmith_cli.credential_helpers.launchers import resolve_bin_dir
print(resolve_bin_dir().as_posix())
")"
case ":$PATH:" in
  *":$(posix_path "$BIN_DIR"):"*) ;;
  *) fail "$BIN_DIR (beside cloudsmith) is not on PATH" ;;
esac
export DOTNET_NOLOGO=1
export DOTNET_CLI_TELEMETRY_OPTOUT=1
export DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1
export NUGET_PLUGINS_CACHE_PATH="$WORK/nuget-plugins-cache"

# A throwaway key: only the mock server knows it.
API_KEY="ci-$("$PYTHON" -c 'import secrets; print(secrets.token_hex(16))')"
export CLOUDSMITH_API_KEY="$API_KEY"
export CLOUDSMITH_WORKSPACE="$WORKSPACE_SLUG"
export CLOUDSMITH_OIDC_DISCOVERY_DISABLED=true

MOCK_PID=""
cleanup() {
  if [ -n "$MOCK_PID" ]; then kill "$MOCK_PID" 2>/dev/null || true; fi
}
trap cleanup EXIT

CACHE_FILE="$("$PYTHON" -c "
from cloudsmith_cli.credential_helpers.custom_domains import get_cache_path
print(get_cache_path('$WORKSPACE_SLUG').as_posix())
")"
rm -f "$CACHE_FILE"

step "dotnet $(dotnet --version)"

step "Pack the probe package"
dotnet new classlib --name "$PACKAGE_ID" --output "$WORK/probe" >/dev/null
dotnet pack "$WORK/probe" --configuration Release --output "$FEED_DIR" \
  "-p:PackageId=$PACKAGE_ID" "-p:Version=$PACKAGE_VERSION" >/dev/null
ls "$FEED_DIR"

step "Start the mock Cloudsmith feed and API"
"$PYTHON" "$SCRIPT_DIR/nuget_mock_feed.py" \
  --port-file "$WORK/port" \
  --api-key "$API_KEY" \
  --workspace "$WORKSPACE_SLUG" \
  --repo "$REPO_SLUG" \
  --packages-dir "$FEED_DIR" \
  --custom-domain "$CUSTOM_DOMAIN" &
MOCK_PID=$!
for _ in $(seq 1 50); do
  [ -s "$WORK/port" ] && break
  sleep 0.2
done
[ -s "$WORK/port" ] || fail "mock server did not start"
PORT="$(cat "$WORK/port")"
BASE_URL="http://$CUSTOM_DOMAIN:$PORT"
SOURCE_URL="$BASE_URL/$WORKSPACE_SLUG/$REPO_SLUG/v3/index.json"
export CLOUDSMITH_API_HOST="$BASE_URL"
echo "feed: $SOURCE_URL"

stat_value() {
  "$PYTHON" -c "
import json, sys, urllib.request
stats = json.load(urllib.request.urlopen('$BASE_URL/__stats'))
print(stats.get(sys.argv[1], 0))
" "$1"
}

step "Create a consumer project that uses only the Cloudsmith feed"
CONSUMER="$WORK/consumer"
dotnet new console --name Consumer --output "$CONSUMER" >/dev/null
cat >"$CONSUMER/nuget.config" <<EOF
<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <packageSources>
    <clear />
    <add key="cloudsmith-ci" value="$SOURCE_URL" allowInsecureConnections="true" />
  </packageSources>
</configuration>
EOF
dotnet add "$CONSUMER" package "$PACKAGE_ID" --version "$PACKAGE_VERSION" --no-restore >/dev/null
cat >"$CONSUMER/Program.cs" <<EOF
System.Console.WriteLine(typeof($PACKAGE_ID.Class1).FullName);
EOF

RESTORE_RUN=0
# Restore with empty package and HTTP caches, so every run hits the feed.
restore() {
  RESTORE_RUN=$((RESTORE_RUN + 1))
  NUGET_PACKAGES="$WORK/packages-$RESTORE_RUN" \
    NUGET_HTTP_CACHE_PATH="$WORK/http-cache-$RESTORE_RUN" \
    dotnet restore "$CONSUMER" --force --verbosity normal >"$WORK/restore.log" 2>&1
}

expect_restore_unauthorized() {
  if restore; then
    cat "$WORK/restore.log"
    fail "restore succeeded without the credential provider"
  fi
  grep -q "401" "$WORK/restore.log" || {
    cat "$WORK/restore.log"
    fail "restore did not fail with 401"
  }
  echo "restore failed with 401, as expected"
}

expect_restore_success() {
  local before
  before="$(stat_value feed_downloads)"
  restore || {
    cat "$WORK/restore.log"
    fail "restore failed with the credential provider installed"
  }
  [ "$(stat_value feed_downloads)" -gt "$before" ] \
    || fail "restore succeeded without downloading from the Cloudsmith feed"
  local output
  output="$(NUGET_PACKAGES="$WORK/packages-$RESTORE_RUN" dotnet run --project "$CONSUMER" --no-restore)"
  [ "$output" = "$PACKAGE_ID.Class1" ] || fail "consumer printed '$output'"
  echo "restore authenticated through the plugin; consumer printed '$output'"
}

step "Restore without the credential provider"
cloudsmith credential-helper uninstall nuget >/dev/null
expect_restore_unauthorized

step "Install the credential provider (discovers the custom domain)"
api_calls="$(stat_value api_custom_domains)"
INSTALL_OUTPUT="$(cloudsmith credential-helper install nuget 2>&1)"
echo "$INSTALL_OUTPUT"
echo "$INSTALL_OUTPUT" | grep -q "discovered 1 NuGet custom domain(s): $CUSTOM_DOMAIN" \
  || fail "install did not discover the custom domain"
echo "$INSTALL_OUTPUT" | grep -q "WARNING" && fail "install emitted a warning"
[ "$(stat_value api_custom_domains)" -gt "$api_calls" ] \
  || fail "install did not query the custom-domains API"
if is_windows; then LAUNCHER="$BIN_DIR/nuget-plugin-cloudsmith.bat"; else LAUNCHER="$BIN_DIR/nuget-plugin-cloudsmith"; fi
[ -f "$LAUNCHER" ] || fail "launcher $LAUNCHER was not written"
cat "$LAUNCHER"
grep -q -- "--workspace $WORKSPACE_SLUG" "$LAUNCHER" \
  || fail "launcher does not pin the Workspace"

LIST_OUTPUT="$(cloudsmith credential-helper list -F json)"
echo "$LIST_OUTPUT"
echo "$LIST_OUTPUT" | "$PYTHON" -c "
import json, sys
nuget = next(e for e in json.load(sys.stdin)['data'] if e['helper'] == 'nuget')
assert nuget['launcher'], nuget
assert '$CUSTOM_DOMAIN' in nuget['hosts'], nuget
" || fail "credential-helper list does not report the NuGet custom domain"

run_launcher() {
  if is_windows; then
    cmd //c "$(cygpath -w "$LAUNCHER")" "$@"
  else
    "$LAUNCHER" "$@"
  fi
}

step "nuget.exe (v1) protocol through the launcher"
V1_OUTPUT="$(run_launcher -Uri "$SOURCE_URL" -NonInteractive -Verbosity detailed)"
echo "$V1_OUTPUT" | "$PYTHON" -c "
import json, sys
body = json.load(sys.stdin)
assert body['Username'] == 'token', body
assert body['Password'] == sys.argv[1], 'unexpected password'
" "$API_KEY" || fail "v1 response for the custom domain is wrong"
echo "custom domain: credentials returned"
set +e
run_launcher -Uri "https://api.nuget.org/v3/index.json" -NonInteractive >/dev/null
code=$?
set -e
[ "$code" -eq 1 ] || fail "v1 answered nuget.org with exit $code, expected 1"
echo "nuget.org: declined (exit 1)"

step "Restore with the credential provider (warm custom-domain cache)"
expect_restore_success

step "Restore with a cold custom-domain cache (runtime discovery)"
rm -f "$CACHE_FILE"
api_calls="$(stat_value api_custom_domains)"
expect_restore_success
[ "$(stat_value api_custom_domains)" -gt "$api_calls" ] \
  || fail "the plugin did not discover the custom domain through the API"
echo "the plugin discovered the custom domain at runtime"

step "Uninstall the credential provider"
cloudsmith credential-helper uninstall nuget
[ ! -e "$LAUNCHER" ] || fail "launcher still present after uninstall"
expect_restore_unauthorized

echo
echo "NuGet credential provider end-to-end test passed."
