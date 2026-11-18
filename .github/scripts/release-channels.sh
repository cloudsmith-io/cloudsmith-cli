# Copyright 2026 Cloudsmith Ltd
# Print the release channels that VERSION moves, as key=value lines for
# $GITHUB_OUTPUT. A channel (latest, MAJOR, MAJOR.MINOR) moves only when VERSION
# is the highest published release in that channel. A pre-release moves no
# channel.
set -euo pipefail
if [[ ! "${VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  printf '%s\n' prerelease=true latest=false major-latest=false minor-latest=false
  exit 0
fi
RELEASES="$(gh api --paginate "repos/${GITHUB_REPOSITORY}/releases" \
  --jq '.[] | select(.draft == false and .prerelease == false) | .tag_name' \
  | sed -n 's/^v\([0-9]\+\.[0-9]\+\.[0-9]\+\)$/\1/p')"
is_highest() {
  # Args: <version prefix>. Prints true when VERSION is the highest release with that prefix.
  local release highest
  highest="$(for release in "${VERSION}" ${RELEASES}; do
    case "${release}" in "$1"*) echo "${release}" ;; esac
  done | sort -V | tail -n 1)"
  if [ "${highest}" = "${VERSION}" ]; then echo true; else echo false; fi
}
MAJOR="${VERSION%%.*}"
MINOR="${VERSION#*.}"; MINOR="${MINOR%%.*}"
echo "prerelease=false"
echo "latest=$(is_highest "")"
echo "major-latest=$(is_highest "${MAJOR}.")"
echo "minor-latest=$(is_highest "${MAJOR}.${MINOR}.")"
