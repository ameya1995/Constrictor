#!/usr/bin/env bash
# Install the Constrictor SKILL.md into standard agent runtime skill directories.
#
# Usage:
#   bash scripts/install-agent-skill.sh
#
# The script:
#   1. Generates a fresh SKILL.md via `constrictor agent skill`
#   2. Creates each target directory if it does not exist
#   3. Symlinks (or copies) the SKILL.md into each agent runtime location
#
# Supported runtimes:
#   - Codex        ~/.codex/skills/constrictor/SKILL.md
#   - Claude Code  ~/.claude/skills/constrictor/SKILL.md
#   - Copilot      ~/.copilot/skills/constrictor/SKILL.md
#   - OpenCode     ~/.config/opencode/skills/constrictor/SKILL.md
#   - Cursor       ~/.cursor/skills/constrictor/SKILL.md

set -euo pipefail

# ── Helpers ───────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
RESET='\033[0m'

info()    { echo -e "${BOLD}[constrictor]${RESET} $*"; }
success() { echo -e "${GREEN}[constrictor]${RESET} $*"; }
warn()    { echo -e "${YELLOW}[constrictor]${RESET} $*"; }
error()   { echo -e "${RED}[constrictor]${RESET} $*" >&2; }

# ── Check prerequisites ───────────────────────────────────────────────────

if ! command -v constrictor &>/dev/null; then
    error "'constrictor' not found on PATH."
    error "Install it first:  pip install constrictor"
    exit 1
fi

# ── Generate a canonical SKILL.md ─────────────────────────────────────────

TMPDIR_SKILL="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_SKILL"' EXIT

SKILL_SOURCE="${TMPDIR_SKILL}/SKILL.md"
info "Generating SKILL.md (version $(constrictor --version 2>/dev/null | awk '{print $2}'))..."
constrictor agent skill -o "$SKILL_SOURCE"

# ── Target directories ────────────────────────────────────────────────────

declare -a TARGETS=(
    "${HOME}/.codex/skills/constrictor"
    "${HOME}/.claude/skills/constrictor"
    "${HOME}/.copilot/skills/constrictor"
    "${HOME}/.config/opencode/skills/constrictor"
    "${HOME}/.cursor/skills/constrictor"
)

# ── Install ───────────────────────────────────────────────────────────────

INSTALLED=0
SKIPPED=0

for TARGET_DIR in "${TARGETS[@]}"; do
    TARGET_FILE="${TARGET_DIR}/SKILL.md"

    mkdir -p "$TARGET_DIR"

    if [ -L "$TARGET_FILE" ]; then
        # Already a symlink — update it
        ln -sf "$SKILL_SOURCE" "$TARGET_FILE"
        warn "Updated symlink: ${TARGET_FILE}"
        INSTALLED=$((INSTALLED + 1))
    elif [ -f "$TARGET_FILE" ]; then
        # Regular file exists — overwrite with a copy
        cp "$SKILL_SOURCE" "$TARGET_FILE"
        success "Installed (copy): ${TARGET_FILE}"
        INSTALLED=$((INSTALLED + 1))
    else
        # Fresh install — copy (not symlink, since tmpdir is ephemeral)
        cp "$SKILL_SOURCE" "$TARGET_FILE"
        success "Installed: ${TARGET_FILE}"
        INSTALLED=$((INSTALLED + 1))
    fi
done

echo ""
info "Done. Installed to ${INSTALLED} location(s), skipped ${SKIPPED}."
