#!/usr/bin/env bash

# ==============================================================================
# ChatGPT Native Source Uninstaller for Amazon Linux 2023
# Safely removes the repacked Electron app, purges local cache/state data,
# and cleans up system-wide application shortcuts and MIME handlers.
# ==============================================================================

set -euo pipefail

# --- Logging Helpers ---
log_info() { echo -e "\e[34m[INFO]\e[0m $1"; }
log_success() { echo -e "\e[32m[SUCCESS]\e[0m $1"; }
log_warn() { echo -e "\e[33m[WARNING]\e[0m $1"; }
log_error() { echo -e "\e[31m[ERROR]\e[0m $1"; exit 1; }

# --- Pre-flight Checks ---
if [ "$EUID" -eq 0 ]; then
    log_error "Do not run this script as root. Run as a standard user so it can correctly clean your local user cache."
fi

echo "=========================================================================="
log_warn "This will completely remove ChatGPT Desktop Native and all local app data."
echo "=========================================================================="
read -p "Press [Enter] to continue or [Ctrl+C] to cancel..."

# ==============================================================================
# 1. Terminate Running Processes
# ==============================================================================
log_info "Stopping any running instances of the application..."
# We use || true so the script doesn't fail if the app isn't currently running
pkill -f chatgpt-desktop-native || true

# ==============================================================================
# 2. Remove System Directories and Binaries
# ==============================================================================
log_info "Removing core application files from /opt..."
sudo rm -rf /opt/chatgpt-desktop-native

log_info "Removing executable symlinks..."
sudo rm -f /usr/local/bin/chatgpt-desktop-native

# ==============================================================================
# 3. Clean Up Desktop Integration & Icons
# ==============================================================================
log_info "Removing desktop shortcuts..."
sudo rm -f /usr/share/applications/chatgpt-desktop-native.desktop

log_info "Scrubbing icons from /usr/share/icons..."
# Safely find and delete only icons specifically named after the app
sudo find /usr/share/icons -type f -name "*chatgpt-desktop-native*" -exec rm -f {} +

# ==============================================================================
# 4. Wipe Local User Cache & State Data
# ==============================================================================
log_info "Wiping local user configuration and cache directories..."
rm -rf ~/.config/chatgpt-desktop-native
rm -rf ~/.config/chatgpt

# Clean up orphaned URL handler registrations in the user's mimeapps.list
if [ -f ~/.config/mimeapps.list ]; then
    log_info "Cleaning up user MIME associations..."
    sed -i '/chatgpt-desktop-native.desktop/d' ~/.config/mimeapps.list || true
fi

# ==============================================================================
# 5. Refresh System Registries
# ==============================================================================
log_info "Refreshing system desktop database..."
if command -v update-desktop-database &> /dev/null; then
    sudo update-desktop-database /usr/share/applications/
else
    log_warn "update-desktop-database command not found, skipping."
fi

log_success "Uninstallation Complete!"
echo "-> ChatGPT Desktop Native has been entirely removed from your system."
