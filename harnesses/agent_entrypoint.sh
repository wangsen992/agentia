#!/bin/bash
#
# Custom entrypoint for agent containers.
# Copies mounted workspace files on top of /workspace/, then runs the real entrypoint.
#
# Workspace files are mounted at /workspace-src/ (from host's workspace mount).
# We copy them over the image's /workspace/ without hiding the harness scripts.
#

if [ -d /workspace-src ] && [ "$(ls -A /workspace-src 2>/dev/null)" ]; then
    echo "[entrypoint] Copying workspace files from /workspace-src..." >&2
    cp -r /workspace-src/* /workspace/
    # Ensure workspace subdirs exist
    mkdir -p /workspace/memory /workspace/logs
fi

# Run the standard harness entrypoint
exec /workspace/runners/entrypoint.sh "$@"
