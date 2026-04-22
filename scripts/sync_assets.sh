#!/usr/bin/env bash
# =============================================================================
# sync_assets.sh — pull heavy runtime data into a fresh deepgis-xr checkout.
#
# These paths are .gitignored on purpose so the repo stays small. On `dreamslab`
# (or anywhere /mnt/dreamslab-store is mounted) this script rsyncs the assets
# into their expected locations.
#
# Usage:
#     bash scripts/sync_assets.sh                 # interactive (asks before)
#     bash scripts/sync_assets.sh --yes           # non-interactive
#     bash scripts/sync_assets.sh --dry-run       # just show what would run
#     STORE=/some/other/path bash scripts/sync_assets.sh   # override source
# =============================================================================
set -euo pipefail

# --- config -------------------------------------------------------------------
STORE="${STORE:-/mnt/dreamslab-store/deepgis-xr-assets}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

DRY=""
YES=""
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY="--dry-run" ;;
        --yes|-y)  YES="1" ;;
        *)         echo "unknown arg: $arg"; exit 64 ;;
    esac
done

# mapping: <source under $STORE>   →   <destination under $REPO_ROOT>
# keep in sync with .gitignore entries
declare -a PAIRS=(
    "data/                deepgis-xr/data"
    "models/              deepgis-xr/models"
    "deepgis_results/     deepgis-xr/deepgis_results"
    "static/models/       deepgis-xr/static/models"
    "static/tifs/         deepgis-xr/static/tifs"
    "stl_models/          deepgis-xr/stl_models"
)

# --- sanity ------------------------------------------------------------------
if [[ ! -d "$STORE" ]]; then
    echo "ERROR: source store not found: $STORE" >&2
    echo "Set STORE=<path> env var to override." >&2
    exit 1
fi

if ! command -v rsync >/dev/null 2>&1; then
    echo "ERROR: rsync not installed." >&2
    exit 1
fi

echo "Will sync from:  $STORE"
echo "Into repo:       $REPO_ROOT"
echo
for pair in "${PAIRS[@]}"; do
    src="$STORE/${pair%% *}"
    dst="$REPO_ROOT/${pair##* }"
    src="${src// /}"       # strip padding spaces
    dst="${dst// /}"
    printf "  %-45s -> %s\n" "$src" "$dst"
done
echo

if [[ -z "$YES" && -z "$DRY" ]]; then
    read -r -p "Proceed? [y/N] " reply
    [[ "$reply" =~ ^[Yy]$ ]] || { echo "aborted."; exit 2; }
fi

# --- sync --------------------------------------------------------------------
for pair in "${PAIRS[@]}"; do
    src="$STORE/${pair%% *}"
    dst="$REPO_ROOT/${pair##* }"
    src="${src// /}"
    dst="${dst// /}"

    if [[ ! -d "$src" ]]; then
        echo "[skip] missing source:  $src"
        continue
    fi

    mkdir -p "$dst"
    echo "[sync] $src -> $dst"
    rsync -ah --info=progress2 $DRY --partial "$src"/ "$dst"/
done

echo
echo "Done. Verify with:"
echo "  du -sh $REPO_ROOT/{data,models,deepgis_results,static/models,static/tifs,stl_models}"
