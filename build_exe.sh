#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"

python_cmd=
for candidate in python3 python /usr/bin/python3; do
    if ! command -v "$candidate" >/dev/null 2>&1; then
        continue
    fi
    if "$candidate" -c 'import sysconfig; raise SystemExit(sysconfig.get_config_var("Py_ENABLE_SHARED") != 1)' \
        >/dev/null 2>&1; then
        python_cmd="$candidate"
        break
    fi
done

if [[ -z "$python_cmd" ]]; then
    echo "Error: PyInstaller requires Python built with a shared library." >&2
    echo "Install a shared-library Python build and run this script again." >&2
    exit 1
fi

venv_dir="$script_dir/.venv-build"
pip_args=()
if [[ -x "$venv_dir/bin/python" ]] &&
    "$venv_dir/bin/python" -m pip --version >/dev/null 2>&1; then
    python_cmd="$venv_dir/bin/python"
elif "$python_cmd" -m venv "$venv_dir" >/dev/null 2>&1; then
    python_cmd="$venv_dir/bin/python"
else
    pip_args=(--break-system-packages)
    echo "Warning: python3-venv is unavailable; installing build dependencies into the selected Python." >&2
fi

"$python_cmd" -m pip install "${pip_args[@]}" -r requirements-dev.txt
"$python_cmd" -m PyInstaller \
    --noconfirm \
    --clean \
    --onedir \
    --windowed \
    --exclude-module pytest \
    --collect-all rapidocr \
    --name PotteryVolume_ScaleOCR \
    --distpath dist \
    --workpath build \
    pottery_volume_gui.pyw

echo
echo "Built: $script_dir/dist/PotteryVolume_ScaleOCR/PotteryVolume_ScaleOCR"
