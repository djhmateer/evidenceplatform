#!/bin/bash
# Build script for production deployment.
# Run from the project root on the production server.
# Stops on any error (set -e) so the service is never started with a broken build.
set -e

# Sync Python dependencies and upgrade to latest allowed versions
uv sync --upgrade

# Build the React frontend
cd browsing_platform/client
pnpm install
pnpm build
cd ../..

# Start the evidenceplatform service (assumes it was stopped before deploying)
sudo systemctl start evidenceplatform

echo "Done. Service started."
sudo systemctl status evidenceplatform --no-pager  # --no-pager prints directly to terminal instead of opening interactive less
