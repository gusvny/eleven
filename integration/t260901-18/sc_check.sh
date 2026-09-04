#!/usr/bin/env bash
# 工单 t260901-18 合并闸白名单口径热修（KI-010 解锁）—— 集成测试集
# 黑盒视角：用户可感知的行为变化 = 泳道并入他单文件不再被误判越界（解锁 16/14）、
# 真越界仍红、基线算不出时 fail-closed 精确报错。
# 用法：bash integration/t260901-18/check.sh <test-id> | all   （cwd = 泳道根）
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
DIR="integration/t260901-18"

run() {  # run <脚本>
  echo "== $1"
  python3 "$DIR/$1" || exit 1
}

case "${1:-}" in
  t01-whitelist-caliber)
    run t01_whitelist_caliber.py
    echo "PASS t01-whitelist-caliber"
    ;;
  t02-literal-main-hazard)
    run t02_literal_main_hazard.py
    echo "PASS t02-literal-main-hazard"
    ;;
  t03-mergecheck-wiring)
    run t03_mergecheck_wiring.py
    echo "PASS t03-mergecheck-wiring"
    ;;
  t04-mergecheck-failclosed)
    run t04_mergecheck_failclosed.py
    echo "PASS t04-mergecheck-failclosed"
    ;;
  all)
    for t in t01-whitelist-caliber t02-literal-main-hazard t03-mergecheck-wiring t04-mergecheck-failclosed; do
      bash "$0" "$t" || exit 1
    done
    echo "PASS all (t260901-18)"
    ;;
  *)
    echo "用法: bash integration/t260901-18/check.sh <t01-whitelist-caliber|t02-literal-main-hazard|t03-mergecheck-wiring|t04-mergecheck-failclosed|all>" >&2
    exit 2
    ;;
esac
