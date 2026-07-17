#!/usr/bin/env bash

# ==============================================================================
# ChatGPT Native Source Builder for Amazon Linux 2023 (Production Release)
# Automates dependency resolution, Git LFS payload fetching, source patching,
# Debian tool mocking, nested Electron permission handling, and deep-link fixes.
# ==============================================================================

set -euo pipefail

# --- Logging Helpers ---
log_info() { echo -e "\e[34m[INFO]\e[0m $1"; }
log_success() { echo -e "\e[32m[SUCCESS]\e[0m $1"; }
log_error() { echo -e "\e[31m[ERROR]\e[0m $1"; exit 1; }

# --- Pre-flight Checks ---
if [ "$EUID" -eq 0 ]; then
    log_error "Do not run this script as root. Run as a standard user. It will prompt for sudo when necessary."
fi

# --- Workspace Setup & Cleanup Trap ---
WORK_DIR=$(mktemp -d)
log_info "Working directory created at $WORK_DIR"

cleanup() {
    log_info "Cleaning up temporary workspace ($WORK_DIR)..."
    rm -rf "$WORK_DIR"
}
# Ensures cleanup runs regardless of script success or failure
trap cleanup EXIT

# ==============================================================================
# 1. System Dependencies
# ==============================================================================
log_info "Installing system build dependencies..."
sudo dnf update -y
sudo dnf install -y nodejs npm git git-lfs unzip binutils wget xdg-utils \
    desktop-file-utils alsa-lib gtk3 nss libXScrnSaver libdrm mesa-libgbm \
    libxcb libxshmfence

# ==============================================================================
# 2. Source Cloning & Payload Fetching
# ==============================================================================
log_info "Cloning upstream patching repository..."
cd "$WORK_DIR"
git clone https://github.com/johnohhh1/chatgpt_desktop_ubuntu.git
cd chatgpt_desktop_ubuntu

log_info "Pulling Large Files (Git LFS) for MSIX payload..."
git lfs install
git lfs pull

# ==============================================================================
# 3. Node Tools & Electron Binary Verification
# ==============================================================================
log_info "Installing local Node tools..."
npm install electron @electron/asar --no-save

log_info "Forcing Electron binary download..."
node node_modules/electron/install.js
if [ ! -f "node_modules/electron/dist/electron" ]; then
    log_error "Electron binary failed to download. Check network or proxy settings."
fi

# ==============================================================================
# 4. Debian Interceptor (The Mock)
# ==============================================================================
log_info "Setting up Debian package interceptors..."
mkdir -p dummy_bin
echo '#!/usr/bin/env bash' > dummy_bin/dpkg
echo 'exit 0' >> dummy_bin/dpkg

# This fake dpkg-deb catches the fully patched directory right before the script 
# attempts to package it and delete it.
cat << 'EOF' > dummy_bin/dpkg-deb
#!/usr/bin/env bash
if [[ "$1" == "--build" ]] || [[ "$1" == "-b" ]]; then
    echo "INTERCEPTED: Saving patched files to a safe directory..."
    cp -a "$2" "$PWD/../safely_extracted_app"
fi
exit 0
EOF

chmod +x dummy_bin/*
export PATH="$PWD/dummy_bin:$PATH"

# ==============================================================================
# 5. Execute Upstream Patcher
# ==============================================================================
PAYLOAD=$(ls *.Msixbundle | head -n 1)
if [ -z "$PAYLOAD" ]; then
    log_error "Could not find the .Msixbundle payload in the repository."
fi

log_info "Running upstream patcher on $PAYLOAD..."
chmod +x build-chatgpt-native-deb.sh
./build-chatgpt-native-deb.sh --exe "./$PAYLOAD"

# ==============================================================================
# 6. System Installation
# ==============================================================================
STAGING_DIR="../safely_extracted_app"
if [ ! -d "$STAGING_DIR/opt" ]; then
    log_error "Failed to intercept the patched files. The trap didn't spring."
fi

log_info "Removing existing installation directories..."
sudo rm -rf /opt/chatgpt-desktop-native
sudo rm -f /usr/local/bin/chatgpt-desktop-native
sudo rm -f /usr/share/applications/chatgpt-desktop-native.desktop

log_info "Moving patched files to system directories..."
sudo cp -r "$STAGING_DIR/opt/chatgpt-desktop-native" /opt/
sudo cp -r "$STAGING_DIR/usr/share/applications/chatgpt-desktop-native.desktop" /usr/share/applications/
sudo cp -r "$STAGING_DIR/usr/share/icons/"* /usr/share/icons/

# ==============================================================================
# 7. Permissions & Linking
# ==============================================================================
log_info "Configuring execution permissions..."
sudo chmod -R 755 /opt/chatgpt-desktop-native

# Handle the nested electron binary structure from the upstream build
EXEC_PATH="/opt/chatgpt-desktop-native/electron/electron"
SANDBOX_PATH="/opt/chatgpt-desktop-native/electron/chrome-sandbox"

if [ ! -f "$EXEC_PATH" ]; then
    # Fallback just in case upstream changes their folder structure back
    EXEC_PATH="/opt/chatgpt-desktop-native/chatgpt-desktop-native"
fi

sudo chmod +x "$EXEC_PATH"

# Fix chrome-sandbox permissions (Mandatory for Electron on Linux)
if [ -f "$SANDBOX_PATH" ]; then
    sudo chown root:root "$SANDBOX_PATH"
    sudo chmod 4755 "$SANDBOX_PATH"
fi

log_info "Creating system symlink..."
sudo ln -sf "$EXEC_PATH" /usr/local/bin/chatgpt-desktop-native

# ==============================================================================
# 8. Desktop Fixes & URL Handlers
# ==============================================================================
log_info "Injecting %u argument into desktop file for URL handling..."
if ! grep -q '%u\|%U' /usr/share/applications/chatgpt-desktop-native.desktop; then
    sudo sed -i 's/^Exec=\(.*\)$/Exec=\1 %u/' /usr/share/applications/chatgpt-desktop-native.desktop
fi

log_info "Registering XDG mime types for OpenAI login callbacks..."
xdg-mime default chatgpt-desktop-native.desktop x-scheme-handler/chatgpt
xdg-mime default chatgpt-desktop-native.desktop x-scheme-handler/chatgpt-alt

log_info "Refreshing desktop application database..."
sudo update-desktop-database /usr/share/applications/

log_success "Source Build & Installation Complete!"
echo "-> You can now launch the application by running: chatgpt-desktop-native"
