#!/bin/sh
# pi-agent installer for AgentServer
# Downloads and installs the pi binary and all its companion files.
# pi is a Bun application — it needs package.json, wasm, and other files
# to run. We install the entire extracted directory intact.

set -e

DEST="${PI_INSTALL_DIR:-/usr/local/pi}"
PI_VERSION="${PI_VERSION:-v0.66.1}"
BIN_LINK="${PI_INSTALL_DIR:-/usr/local/bin}/pi"

# Detect architecture
ARCH="$(uname -m)"
OS="$(uname -s)"

case "$OS" in
    Linux)
        case "$ARCH" in
            x86_64)  PI_ASSET="pi-linux-x64.tar.gz" ;;
            aarch64|arm64) PI_ASSET="pi-linux-arm64.tar.gz" ;;
            *)        echo "[pi-agent installer] Unsupported architecture: $ARCH" >&2; exit 1 ;;
        esac
        ;;
    Darwin)
        case "$ARCH" in
            x86_64)  PI_ASSET="pi-darwin-x64.tar.gz" ;;
            arm64)   PI_ASSET="pi-darwin-arm64.tar.gz" ;;
            *)        echo "[pi-agent installer] Unsupported architecture: $ARCH" >&2; exit 1 ;;
        esac
        ;;
    *)
        echo "[pi-agent installer] Unsupported OS: $OS" >&2
        exit 1
        ;;
esac

PI_URL="https://github.com/badlogic/pi-mono/releases/download/${PI_VERSION}/${PI_ASSET}"

echo "[pi-agent installer] Fetching ${PI_URL} ..."
WORKDIR="$(mktemp -d)"
cd "$WORKDIR"
curl -fsSL "$PI_URL" -o pi-archive.tar.gz
echo "[pi-agent installer] Extracting..."
tar -xzf pi-archive.tar.gz
# The tarball extracts to a "pi/" subdirectory containing binary + companion files
PI_EXTRACTED="$WORKDIR/pi"
if [ ! -f "$PI_EXTRACTED/pi" ]; then
    echo "[pi-agent installer] ERROR: pi binary not found at $PI_EXTRACTED/pi" >&2
    echo "[pi-agent installer] Extracted contents:" >&2
    ls -la "$PI_EXTRACTED/" >&2
    exit 1
fi

# Install the entire pi directory to $DEST
echo "[pi-agent installer] Installing to $DEST ..."
mkdir -p "$(dirname "$DEST")"
rm -rf "$DEST"
cp -r "$PI_EXTRACTED" "$DEST"
chmod +x "$DEST/pi"

# Create a symlink /usr/local/bin/pi -> $DEST/pi so 'pi' is on PATH
if [ -L "$BIN_LINK" ]; then
    rm "$BIN_LINK"
elif [ -e "$BIN_LINK" ]; then
    echo "[pi-agent installer] WARNING: $BIN_LINK exists and is not a symlink, not overwriting" >&2
else
    # Create parent dir and symlink
    mkdir -p "$(dirname "$BIN_LINK")"
    ln -s "$DEST/pi" "$BIN_LINK"
fi

rm -rf "$WORKDIR"
echo "[pi-agent installer] Installed pi to $DEST (symlinked to $BIN_LINK)"

# Copy skills if provided
if [ -n "$PI_SKILLS_DIR" ] && [ -d "$PI_SKILLS_DIR" ]; then
    DEST_SKILLS="${PI_DIR:-/root/.pi/agent}/.pi/skills"
    mkdir -p "$DEST_SKILLS"
    cp -r "$PI_SKILLS_DIR/"* "$DEST_SKILLS/" 2>/dev/null || true
    echo "[pi-agent installer] Installed skills to $DEST_SKILLS"
fi

echo "[pi-agent installer] Done."
