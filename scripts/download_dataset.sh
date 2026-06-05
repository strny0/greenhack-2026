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

# Replace existing dataset folder
if [ -e "$DEST" ]; then
    echo "Removing existing $DEST..."
    rm -rf "$DEST"
fi

mv "$EXTRACTED_DIR" "$DEST"
echo "Dataset ready at: $DEST"
