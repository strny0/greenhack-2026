#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
DATASET_URL="https://cloud.jastr.dev/public.php/dav/files/greenhack-2026-data"
DEST="$REPO_ROOT/dataset"
TMP_ZIP="$(mktemp /tmp/greenhack-dataset-XXXXXX.zip)"
TMP_DIR="$(mktemp -d /tmp/greenhack-dataset-XXXXXX)"

cleanup() {
    rm -f "$TMP_ZIP"
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT

# Download
if command -v curl &>/dev/null; then
    echo "Downloading dataset with curl..."
    curl -L --fail --progress-bar -o "$TMP_ZIP" "$DATASET_URL"
elif command -v wget &>/dev/null; then
    echo "Downloading dataset with wget..."
    wget --show-progress -O "$TMP_ZIP" "$DATASET_URL"
else
    echo "Error: neither curl nor wget is available." >&2
    exit 1
fi

# Unzip
echo "Extracting..."
unzip -q "$TMP_ZIP" -d "$TMP_DIR"

# Find the single top-level directory inside the zip
TOP_DIRS=("$TMP_DIR"/*)
if [ "${#TOP_DIRS[@]}" -ne 1 ] || [ ! -d "${TOP_DIRS[0]}" ]; then
    echo "Error: expected exactly one top-level directory in the zip, got: ${TOP_DIRS[*]}" >&2
    exit 1
fi

EXTRACTED_DIR="${TOP_DIRS[0]}"

# Merge the downloaded payload into $DEST, preserving repo-tracked files such as
# dataset/overrides/ (operator coordinate/label CSVs that are versioned here, not
# shipped in the zip). Each top-level entry from the zip replaces its counterpart
# in $DEST; "overrides" is never touched.
mkdir -p "$DEST"
shopt -s dotglob nullglob
for entry in "$EXTRACTED_DIR"/*; do
    name="$(basename "$entry")"
    if [ "$name" = "overrides" ]; then
        echo "Keeping existing $DEST/overrides (not overwritten)"
        continue
    fi
    rm -rf "$DEST/$name"
    mv "$entry" "$DEST/$name"
done
shopt -u dotglob nullglob
echo "Dataset ready at: $DEST"
