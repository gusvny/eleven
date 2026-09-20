#!/usr/bin/env python3
"""探针离线自检子用例（t260916-24，dsh-upgrade epic T4）。

场景包装只跑 probe_dsh_seam.py --selftest（零网络/零 npm/秒级），防探针断言语义
腐烂；live 档（隔离 npm 安装 + 真凭据 + 分钟级五断言对账）按验收④**不入**默认跑分
面，升级门槛时显式调用（integration/t260916-24/RUNBOOK_GATE.md 有门槛文本）。
退出码透传探针三态：0=绿；1=探针腐烂（产品红）；2=环境红。
"""
import subprocess
import sys
from pathlib import Path

PROBE = Path(__file__).resolve().parent / "probe_dsh_seam.py"


def main():
    proc = subprocess.run([sys.executable, str(PROBE), "--selftest"])
    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
