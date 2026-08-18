#!/usr/bin/env bash

set -euo pipefail

# Determine paths relative to where deploy.sh is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# If running inside 'dev', set project root to parent directory
if [[ "$(basename "$SCRIPT_DIR")" == "dev" ]]; then
    DEV_DIR="$SCRIPT_DIR"
    ROOT_DIR="$(dirname "$SCRIPT_DIR")"
else
    ROOT_DIR="$SCRIPT_DIR"
    DEV_DIR="${ROOT_DIR}/dev"
fi

PROD_DIR="${ROOT_DIR}/prod"
DEV_CHANGELOG="${DEV_DIR}/changelog.md"
PROD_CHANGELOG="${PROD_DIR}/changelog.md"

# 1. Prompt user to clean data
read -rp "Ready to clean the data? [y/N]: " clean_response
if [[ ! "$clean_response" =~ ^[Yy] ]]; then
    echo "Aborted. Please come back when you are ready."
    exit 0
fi

echo "--- Cleaning Data ---"
python "${DEV_DIR}/clean_pipeline.py"
echo "--- Data Cleansing Complete ---"

# 2. Check changelog versions
if [[ -f "$DEV_CHANGELOG" && -f "$PROD_CHANGELOG" ]]; then
    dev_version=$(awk 'NR==1 {print $2}' "$DEV_CHANGELOG")
    prod_version=$(awk 'NR==1 {print $2}' "$PROD_CHANGELOG")

    if [[ "$dev_version" == "$prod_version" ]]; then
        echo "No new version detected (both are v${prod_version}). Nothing to deploy."
        exit 0
    fi

    echo "New version detected: Dev (v${dev_version}) -> Prod (v${prod_version})"
else
    echo "Notice: Changelog file(s) not found. Proceeding with deployment prompt."
fi

# 3. Confirm promotion to production
read -rp "Move dev artifacts to prod? [y/N]: " deploy_response
if [[ ! "$deploy_response" =~ ^[Yy] ]]; then
    echo "Deployment cancelled."
    exit 0
fi

# 4. Copy designated production artifacts
mkdir -p "$PROD_DIR"
artifacts=(
    "cademy_cleansed.db"
    "cademycode_cleansed.csv"
    "changelog.md"
)

echo "--- Deploying to Production ---"
for file in "${artifacts[@]}"; do
    src="${DEV_DIR}/${file}"
    if [[ -f "$src" ]]; then
        cp -v "$src" "${PROD_DIR}/"
    else
        echo "Warning: ${src} not found, skipping."
    fi
done

echo "Deployment complete to ${PROD_DIR}."