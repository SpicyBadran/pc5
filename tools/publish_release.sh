#!/bin/sh
# Publish the three PC5 release assets to a GitHub release.
#
# Used by the `release` job in ci/build.yml (installed as
# .github/workflows/build.yml once the workflow permission is granted) and
# testable on its own with any `gh` on PATH.
#
#   tools/publish_release.sh --tag v0.2.0 --dist build/release
#
# Behaviour
#   * refuses to run unless all three assets are present and the checksum in
#     pc5.iso.sha256 matches pc5.iso (no publishing an unverified image),
#   * refuses to publish when build-info.json's verification verdict is not PASS,
#   * creates the release if it does not exist, otherwise updates its notes,
#   * uploads with --clobber so re-running a release is safe (no duplicate
#     assets), and finally asserts that all three assets are attached.
#
# Everything it needs is in the asset directory; the only credentials are the
# ones `gh`/git already has (in CI: the automatic GITHUB_TOKEN).
set -eu

tag=""
dist=""
repo=""

usage() {
    echo "usage: $0 --tag TAG [--dist DIR] [--repo OWNER/NAME]" >&2
    exit 2
}

while [ $# -gt 0 ]; do
    case "$1" in
        --tag) tag="${2:-}"; shift 2 ;;
        --dist) dist="${2:-}"; shift 2 ;;
        --repo) repo="${2:-}"; shift 2 ;;
        -h|--help) usage ;;
        *) echo "publish-release: unknown argument: $1" >&2; usage ;;
    esac
done

[ -n "$tag" ] || usage
[ -n "$dist" ] || dist="build/release"

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(CDPATH= cd -- "$here/.." && pwd)

if [ ! -d "$dist" ]; then
    echo "publish-release: asset directory not found: $dist" >&2
    exit 2
fi

for asset in pc5.iso pc5.iso.sha256 build-info.json; do
    if [ ! -f "$dist/$asset" ]; then
        echo "publish-release: missing asset: $dist/$asset" >&2
        exit 2
    fi
done

echo "publish-release: checking the assets before publishing"
( cd "$dist" && sha256sum -c pc5.iso.sha256 )

python3 - "$dist/build-info.json" <<'PY'
import json, sys
info = json.load(open(sys.argv[1]))
build = info.get("build", {})
verdict = build.get("verification", {}).get("verdict")
artifact = build.get("artifact", {}).get("sha256")
print(f"publish-release: version={build.get('version')} commit={build.get('commit')} "
      f"verdict={verdict}")
if verdict != "PASS":
    raise SystemExit(f"publish-release: refusing to publish, verification verdict is {verdict!r}")
if artifact != info.get("sha256"):
    raise SystemExit("publish-release: build record and image hash disagree")
PY

notes=$(mktemp)
trap 'rm -f "$notes"' EXIT
python3 "$root/tools/release_notes.py" --info "$dist/build-info.json" --out "$notes"

gh_args=""
if [ -n "$repo" ]; then
    gh_args="--repo $repo"
fi

title="PC5 ${tag}"
existing=""
# shellcheck disable=SC2086
existing=$(gh release view "$tag" $gh_args --json tagName --jq .tagName 2>/dev/null || true)

if [ -n "$existing" ]; then
    echo "publish-release: release ${tag} exists, updating its notes"
    # shellcheck disable=SC2086
    gh release edit "$tag" $gh_args --notes-file "$notes"
else
    echo "publish-release: creating release ${tag}"
    # shellcheck disable=SC2086
    gh release create "$tag" $gh_args --title "$title" --notes-file "$notes"
fi

echo "publish-release: uploading assets (idempotent, --clobber)"
# shellcheck disable=SC2086
gh release upload "$tag" $gh_args \
    "$dist/pc5.iso" "$dist/pc5.iso.sha256" "$dist/build-info.json" --clobber

echo "publish-release: confirming the published assets"
# shellcheck disable=SC2086
gh release view "$tag" $gh_args --json tagName,url,assets \
    --jq '"release: \(.tagName)\nurl:     \(.url)\nassets:", (.assets[] | "  \(.name)  \(.size) bytes")'

published=$(gh release view "$tag" $gh_args --json assets --jq '.assets[].name')
for want in pc5.iso pc5.iso.sha256 build-info.json; do
    if ! printf '%s\n' "$published" | grep -qx "$want"; then
        echo "publish-release: asset $want is missing from release $tag" >&2
        exit 1
    fi
done

echo "publish-release: ${tag} carries pc5.iso, pc5.iso.sha256 and build-info.json"
