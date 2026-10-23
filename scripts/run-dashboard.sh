#!/usr/bin/env bash
set -Eeuo pipefail
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# Accept scripts/ or a copy placed in the checkout root. Resolve from the
# script's location so launching from another working directory also works.
while [[ ! -f "$repo_dir/vue-dashboard/backend/pyproject.toml" || ! -f "$repo_dir/vue-dashboard/frontend/package.json" ]]; do
    parent_dir=$(dirname -- "$repo_dir")
    if [[ "$parent_dir" = "$repo_dir" ]]; then
        echo 'Cannot find the Morelia repository above this launcher. Place it in Morelia/ or Morelia/scripts/.' >&2
        exit 1
    fi
    repo_dir=$parent_dir
done
export PATH="$HOME/.local/share/morelia-node/bin:$repo_dir/.venv-wsl/bin:$PATH"
missing=false
for executable in "$repo_dir/.venv-wsl/bin/python" "$repo_dir/.venv-wsl/bin/pinnacle" "$HOME/.local/share/morelia-node/bin/node"; do
    if [[ ! -x "$executable" ]]; then
        printf 'Missing executable: %s\n' "$executable" >&2
        missing=true
    fi
done
if [[ ! -f "$repo_dir/vue-dashboard/frontend/node_modules/vite/bin/vite.js" ]]; then
    printf 'Missing frontend dependencies: %s/vue-dashboard/frontend/node_modules\n' "$repo_dir" >&2
    missing=true
fi
if [[ "$missing" = true ]]; then
    printf 'Setup is incomplete for %s. Resolve the setup error and rerun the installer for this checkout.\n' "$repo_dir" >&2
    exit 1
fi
# Keep the existing Vite proxy and the daemon on the same loopback address.
export PINNACLE_DAEMON_URL=http://127.0.0.1:5000
"$repo_dir/.venv-wsl/bin/python" - <<'PY'
import socket
for port in (5000, 5173):
    with socket.socket() as sock:
        try:
            sock.bind(('127.0.0.1', port))
        except OSError:
            raise SystemExit(f'Port {port} is occupied. Stop the existing server first.')
PY
backend_pid=''
frontend_pid=''
cleanup() {
    trap - EXIT INT TERM
    [[ -z "$frontend_pid" ]] || kill -TERM "$frontend_pid" 2>/dev/null || true
    [[ -z "$backend_pid" ]] || kill -TERM "$backend_pid" 2>/dev/null || true
    wait || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
(
    cd "$repo_dir/vue-dashboard/backend"
    exec pinnacle start --debug
) &
backend_pid=$!
ready=false
for ((attempt=0; attempt<60; attempt++)); do
    kill -0 "$backend_pid" 2>/dev/null || { echo 'Backend failed to start.' >&2; exit 1; }
    if curl --fail --silent http://127.0.0.1:5000/health >/dev/null; then ready=true; break; fi
    sleep 1
done
[[ "$ready" = true ]] || { echo 'Backend did not become healthy within 60 seconds.' >&2; exit 1; }
(
    cd "$repo_dir/vue-dashboard/frontend"
    exec node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173 --strictPort
) &
frontend_pid=$!
echo 'Open http://localhost:5173 in Windows. Press Ctrl+C to stop both servers.'
wait -n "$backend_pid" "$frontend_pid"
