#!/usr/bin/env bash
# build.sh — Full build orchestration script
#
# Pipeline:
#   1. Clone / update source repos (.sources/)
#   2. Filter published notes → content/
#   3. Build Quartz → public/
#   4. Build Eleventy in cconrad.github.io → _site/
#   5. Merge into _combined/: Eleventy at root, Quartz at /notes/
#   6. Optionally serve _combined/ locally or deploy to Netlify
#
set -euo pipefail

# ── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCES_DIR="${SCRIPT_DIR}/.sources"
CONTENT_DIR="${SCRIPT_DIR}/content"
PUBLIC_DIR="${SCRIPT_DIR}/public"
COMBINED_DIR="${SCRIPT_DIR}/_combined"
OBSIDIAN_DIR="${SOURCES_DIR}/obsidian-personal"
GH_PAGES_DIR="${SOURCES_DIR}/cconrad.github.io"

SERVE_PORT="${SERVE_PORT:-8080}"

# ── Helpers ──────────────────────────────────────────────────────────────────
log()  { echo "==> $*"; }
err()  { echo "Error: $*" >&2; exit 1; }

check_tool() {
  command -v "$1" &>/dev/null || err "'$1' is required but not found in PATH."
}

current_node_major() {
  node -p "process.versions.node.split('.')[0]"
}

load_nvm() {
  if [[ -n "${NVM_DIR:-}" && -s "${NVM_DIR}/nvm.sh" ]]; then
    # shellcheck disable=SC1090
    . "${NVM_DIR}/nvm.sh"
    return 0
  fi

  if [[ -s "${HOME}/.nvm/nvm.sh" ]]; then
    export NVM_DIR="${HOME}/.nvm"
    # shellcheck disable=SC1090
    . "${NVM_DIR}/nvm.sh"
    return 0
  fi

  return 1
}

use_node_major() {
  local major="$1"
  if load_nvm; then
    nvm install "${major}" >/dev/null
    nvm use "${major}" >/dev/null
    return 0
  fi

  return 1
}

ensure_node_for_quartz() {
  if use_node_major 22; then
    log "Using Node $(node -v) for Quartz build."
    return
  fi

  local major
  major="$(current_node_major)"
  if (( major < 22 )); then
    err "Quartz build requires Node 22+ and nvm was not found. Install nvm or use Node 22+."
  fi

  log "Using existing Node $(node -v) for Quartz build."
}

ensure_node_for_eleventy() {
  if use_node_major 20; then
    log "Using Node $(node -v) for Eleventy build."
    return
  fi

  local major
  major="$(current_node_major)"
  if (( major != 20 )); then
    err "Eleventy build requires Node 20 and nvm was not found. Install nvm or switch to Node 20."
  fi

  log "Using existing Node $(node -v) for Eleventy build."
}

# ── Argument parsing ─────────────────────────────────────────────────────────
SERVE=false
DEPLOY_NETLIFY=false
SKIP_CLONE=false

usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Options:
  --serve            Build then serve the site locally (port \$SERVE_PORT, default: 8080)
  --deploy-netlify   Deploy _combined/ to Netlify after building
  --skip-clone       Skip cloning/updating source repos (use existing .sources/)
  -h, --help         Show this help
EOF
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --serve)           SERVE=true;           shift ;;
    --deploy-netlify)  DEPLOY_NETLIFY=true;  shift ;;
    --skip-clone)      SKIP_CLONE=true;      shift ;;
    -h|--help)         usage ;;
    *) echo "Unknown option: $1" >&2; usage ;;
  esac
done

# ── Tool checks ──────────────────────────────────────────────────────────────
log "Checking required tools..."
check_tool node
check_tool npm
check_tool npx
check_tool uv
check_tool git

if [[ "${DEPLOY_NETLIFY}" == "true" ]]; then
  check_tool netlify
  [[ -n "${NETLIFY_AUTH_TOKEN:-}" ]] || err "NETLIFY_AUTH_TOKEN env var is not set."
  [[ -n "${NETLIFY_SITE_ID:-}"    ]] || err "NETLIFY_SITE_ID env var is not set."
fi

# ── Clone / update source repos ──────────────────────────────────────────────
if [[ "${SKIP_CLONE}" == "false" ]]; then
  [[ -n "${GH_TOKEN:-}" ]] || err "GH_TOKEN env var is required to clone private repos."

  mkdir -p "${SOURCES_DIR}"

  if [[ -d "${OBSIDIAN_DIR}/.git" ]]; then
    log "Updating obsidian-personal..."
    git -C "${OBSIDIAN_DIR}" pull --ff-only
  else
    log "Cloning obsidian-personal (private)..."
    git clone "https://${GH_TOKEN}@github.com/cconrad/obsidian-personal.git" "${OBSIDIAN_DIR}"
  fi

  if [[ -d "${GH_PAGES_DIR}/.git" ]]; then
    log "Updating cconrad.github.io..."
    git -C "${GH_PAGES_DIR}" pull --ff-only
  else
    log "Cloning cconrad.github.io..."
    git clone "https://github.com/cconrad/cconrad.github.io.git" "${GH_PAGES_DIR}"
  fi
fi

# ── Filter notes ─────────────────────────────────────────────────────────────
log "Cleaning content/ directory..."
rm -rf "${CONTENT_DIR}"
mkdir -p "${CONTENT_DIR}"

log "Filtering published notes..."
uv run "${SCRIPT_DIR}/scripts/filter_notes.py" "${OBSIDIAN_DIR}" "${CONTENT_DIR}"

# ── Build Quartz ─────────────────────────────────────────────────────────────
log "Building Quartz..."
ensure_node_for_quartz
cd "${SCRIPT_DIR}"
npx quartz build

# ── Build Eleventy ───────────────────────────────────────────────────────────
ensure_node_for_eleventy
log "Installing Eleventy dependencies..."
cd "${GH_PAGES_DIR}"
npm install --no-save

log "Building Eleventy..."
npm run build

cd "${SCRIPT_DIR}"

# ── Merge into _combined/ ────────────────────────────────────────────────────
# Eleventy at root, Quartz at /notes/ (overwrites any /notes/ from Eleventy).
log "Merging outputs into _combined/..."
rm -rf "${COMBINED_DIR}"
mkdir -p "${COMBINED_DIR}/notes"

cp -r "${GH_PAGES_DIR}/_site/." "${COMBINED_DIR}/"
cp -r "${PUBLIC_DIR}/." "${COMBINED_DIR}/notes/"

# ── Deploy to Netlify ────────────────────────────────────────────────────────
if [[ "${DEPLOY_NETLIFY}" == "true" ]]; then
  log "Deploying to Netlify..."
  netlify deploy \
    --prod \
    --dir="${COMBINED_DIR}" \
    --auth="${NETLIFY_AUTH_TOKEN}" \
    --site="${NETLIFY_SITE_ID}"
fi

# ── Local preview ─────────────────────────────────────────────────────────────
if [[ "${SERVE}" == "true" ]]; then
  log ""
  log "Build complete! Serving site at http://localhost:${SERVE_PORT}"
  log "Press Ctrl+C to stop."
  uv run "${SCRIPT_DIR}/scripts/serve.py" --port "${SERVE_PORT}" --dir "${COMBINED_DIR}"
else
  log ""
  log "Build complete! Output: ${COMBINED_DIR}"
  log "  Eleventy root:  ${COMBINED_DIR}/index.html"
  log "  Quartz notes:   ${COMBINED_DIR}/notes/index.html"
  log "Run with --serve to preview locally, or --deploy-netlify to push to Netlify."
fi

