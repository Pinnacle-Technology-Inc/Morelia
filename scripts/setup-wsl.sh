#!/usr/bin/env bash
# Ubuntu/Debian installer. Can also run directly inside an existing WSL distro.
set -Eeuo pipefail
trap 'echo "Setup failed at line $LINENO. Fix the error above and rerun." >&2' ERR
repo_url=${1:-https://github.com/Pinnacle-Technology/Morelia.git}
branch=${2:-watchdog}
repo_dir=${3:-~/Morelia}
repo_dir=${repo_dir/#\~/$HOME}
[[ "$repo_dir" = /* ]] || { echo 'Repository path must be absolute or start with ~/.' >&2; exit 1; }
[[ $EUID -ne 0 ]] || { echo 'Open Ubuntu and create/use a regular Linux user first; do not run setup as root.' >&2; exit 1; }
source /etc/os-release
case " ${ID:-} ${ID_LIKE:-} " in
    *' ubuntu '*|*' debian '*) ;;
    *) echo "This installer uses Ubuntu/Debian apt packages; detected ${PRETTY_NAME:-unknown Linux}." >&2; exit 1 ;;
esac
command -v apt-get >/dev/null || { echo 'apt-get is required.' >&2; exit 1; }
echo "Setting up Morelia on ${PRETTY_NAME:-$ID}."

sudo apt-get update
sudo apt-get install -y git curl ca-certificates xz-utils build-essential cmake pkg-config \
    python3 python3-venv python3-dev usbutils libusb-1.0-0-dev libftdi1-dev
sudo usermod -aG dialout "$USER"

if [[ -e "$repo_dir" ]]; then
    [[ -d "$repo_dir/.git" ]] || { echo "$repo_dir exists but is not a Git checkout; choose another path." >&2; exit 1; }
    [[ "$(git -C "$repo_dir" remote get-url origin)" = "$repo_url" ]] || { echo 'Existing checkout has a different origin; choose another path.' >&2; exit 1; }
    [[ "$(git -C "$repo_dir" branch --show-current)" = "$branch" ]] || { echo 'Existing checkout is on a different branch; switch it yourself or choose another path.' >&2; exit 1; }
    echo 'Using existing checkout without pulling or resetting local changes.'
else
    git clone --branch "$branch" -- "$repo_url" "$repo_dir"
fi
[[ -f "$repo_dir/vue-dashboard/backend/pyproject.toml" ]] || { echo 'Selected branch does not contain the Vue dashboard backend.' >&2; exit 1; }

# Install a private Node 24 LTS runtime; Ubuntu's default Node is too old for Vite 8.
case "$(uname -m)" in
    x86_64) node_arch=x64 ;;
    aarch64) node_arch=arm64 ;;
    *) echo 'Only x64 and ARM64 are supported.' >&2; exit 1 ;;
esac
node_root="$HOME/.local/share/morelia-node"
if [[ ! -x "$node_root/bin/node" ]] || [[ "$("$node_root/bin/node" -p 'process.versions.node.split(".")[0]')" != 24 ]]; then
    temp_dir=$(mktemp -d)
    trap 'rm -rf -- "$temp_dir"' EXIT
    base=https://nodejs.org/dist/latest-v24.x
    curl --fail --show-error --location "$base/SHASUMS256.txt" -o "$temp_dir/SHASUMS256.txt"
    archive=$(awk -v arch="$node_arch" '$2 ~ ("^node-v24\\.[0-9]+\\.[0-9]+-linux-" arch "\\.tar\\.xz$") {print $2}' "$temp_dir/SHASUMS256.txt")
    [[ -n "$archive" && "$archive" != *$'\n'* ]] || { echo 'Could not identify Node archive.' >&2; exit 1; }
    curl --fail --show-error --location "$base/$archive" -o "$temp_dir/$archive"
    (cd "$temp_dir"; grep -F " $archive" SHASUMS256.txt | sha256sum --check -)
    mkdir -p "$node_root"
    tar -xJf "$temp_dir/$archive" -C "$node_root" --strip-components=1
fi
export PATH="$node_root/bin:$PATH"

python="$repo_dir/.venv-wsl/bin/python"
if [[ -e "$repo_dir/.venv-wsl" ]]; then
    # Never silently replace an existing environment or its interpreter.
    if [[ ! -x "$python" ]] || ! "$python" -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
        echo 'Existing .venv-wsl is broken or uses Python older than 3.11. Rename it and rerun setup.' >&2
        exit 1
    fi
elif python3 -c 'import sys; sys.exit(sys.version_info[:2] != (3, 12))'; then
    python3 -m venv "$repo_dir/.venv-wsl"
else
    # Use the same interpreter target on older and newer Ubuntu releases.
    # Native dependencies may not have wheels for the newest system Python.
    echo 'Installing a private Python 3.12 through uv for the project.'
    tools_dir="$HOME/.local/share/morelia-bootstrap"
    python3 -m venv "$tools_dir"
    "$tools_dir/bin/python" -m pip install --upgrade pip uv
    "$tools_dir/bin/uv" venv --python 3.12 --managed-python --seed "$repo_dir/.venv-wsl"
fi
"$python" -m pip install --upgrade pip
"$python" -m pip install -e "$repo_dir" -e "$repo_dir/vue-dashboard/backend[dev,hardware,all-sinks]"
"$python" -m pip check
(
    cd "$repo_dir/vue-dashboard/backend"
    "$python" -m flask --app app db upgrade
)
(
    cd "$repo_dir/vue-dashboard/frontend"
    npm ci
    npm run build
)
echo
echo 'Setup complete. Open a fresh Ubuntu login session for dialout group membership.'
printf 'Start the dashboard: cd %q && bash scripts/run-dashboard.sh\n' "$repo_dir"
echo 'Windows browser: http://localhost:5173'
echo 'USB serial ports in Linux use /dev/ttyUSB* or /dev/ttyACM*, not COM names.'
