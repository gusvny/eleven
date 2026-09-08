#!/usr/bin/env bash
# Temporal POC 一键装环境（幂等，可重复跑）。
#
# 为什么不用 brew：本机 /opt/homebrew 对本 agent 沙箱只读（`brew install temporal`
# 会在 Cellar 写文件 → Operation not permitted），所以走「官方单二进制 + 仓库内 venv」
# 的最轻路径。产物全在本目录（bin/ .venv/ 均已 gitignore），零污染系统与仓库。
set -euo pipefail

POC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$POC_DIR/bin"
VENV_DIR="$POC_DIR/.venv"
CLI="$BIN_DIR/temporal"

ARCH="$(uname -m)"        # arm64 / x86_64
case "$ARCH" in
  arm64) T_ARCH=arm64 ;;
  x86_64) T_ARCH=amd64 ;;
  *) echo "不认识的架构 ${ARCH}，请手工下 temporal CLI 放 $CLI" >&2; exit 1 ;;
esac
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"   # darwin / linux

mkdir -p "$BIN_DIR"

# ---- 1) temporal CLI 单二进制（内含 dev server，SQLite 落盘，免 docker/postgres） ----
if [ -x "$CLI" ]; then
  echo "[setup] temporal CLI 已在：$("$CLI" --version 2>&1 | head -1)"
else
  URL="https://temporal.download/cli/archive/latest?platform=${OS}&arch=${T_ARCH}"
  echo "[setup] 下载 temporal CLI: $URL"
  TMP_TGZ="$(mktemp -t temporal-cli).tgz"
  curl -sSL --max-time 600 -o "$TMP_TGZ" "$URL"
  tar xzf "$TMP_TGZ" -C "$BIN_DIR" temporal
  rm -f "$TMP_TGZ"
  chmod +x "$CLI"
  xattr -d com.apple.quarantine "$CLI" 2>/dev/null || true
  echo "[setup] temporal CLI 就绪：$("$CLI" --version 2>&1 | head -1)"
fi

# ---- 2) python venv + temporalio SDK（不碰系统 python、不碰仓库 requirements） ----
if [ -x "$VENV_DIR/bin/python" ]; then
  echo "[setup] venv 已在：$("$VENV_DIR/bin/python" -V 2>&1)"
else
  echo "[setup] 建 venv：$VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/python" -m pip install --quiet --upgrade pip >/dev/null
if "$VENV_DIR/bin/python" -c "import temporalio" 2>/dev/null; then
  echo "[setup] temporalio 已装：$("$VENV_DIR/bin/python" -c 'import temporalio,sys;print(temporalio.__version__)')"
else
  echo "[setup] pip install temporalio ..."
  "$VENV_DIR/bin/python" -m pip install --quiet temporalio
  echo "[setup] temporalio 装好：$("$VENV_DIR/bin/python" -c 'import temporalio,sys;print(temporalio.__version__)')"
fi

echo "[setup] OK。下一步：./run_server.sh（另开一个 shell）→ ./run_worker.sh → ./demo.sh"
