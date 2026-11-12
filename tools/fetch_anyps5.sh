#!/bin/sh
# Obtain the AnyPS5 sources for study or for an execution-layer build.
#
# Prefers the archive supplied with this repository; falls back to a clone of
# the upstream project. AnyPS5 is GPL-2.0-only and is not affiliated with Sony.
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
dest="$root/vendor/anyps5/src"

if [ -e "$dest" ]; then
    echo "already present: $dest"
    exit 0
fi

archive=$(ls "$root"/AnyPS5-main*.zip 2>/dev/null | head -n 1 || true)
mkdir -p "$dest"

if [ -n "$archive" ]; then
    echo "extracting $archive"
    python3 - "$archive" "$dest" <<'PY'
import sys, zipfile, shutil, os, tempfile
archive, dest = sys.argv[1], sys.argv[2]
with tempfile.TemporaryDirectory() as tmp:
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(tmp)
    entries = [e for e in os.listdir(tmp) if os.path.isdir(os.path.join(tmp, e))]
    src = os.path.join(tmp, entries[0]) if entries else tmp
    for item in os.listdir(src):
        shutil.move(os.path.join(src, item), os.path.join(dest, item))
print("extracted to", dest)
PY
    echo "note: 3rdparty/ are git submodules and are not in the archive"
    echo "      fetch them with: git submodule update --init --recursive (inside a clone)"
    exit 0
fi

if command -v git >/dev/null 2>&1; then
    echo "cloning upstream AnyPS5"
    git clone --recurse-submodules --depth 1 https://github.com/boykopovar/AnyPS5 "$dest"
    exit 0
fi

echo "no archive found and git is unavailable" >&2
exit 1
