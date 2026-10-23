#!/usr/bin/env bash
# Convenience entry point for a dashboard checkout.
set -Eeuo pipefail
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
exec bash "$repo_dir/scripts/setup-wsl.sh" "${1:-https://github.com/Pinnacle-Technology/Morelia.git}" "${2:-watchdog}" "${3:-$repo_dir}"
