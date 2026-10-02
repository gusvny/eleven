#!/usr/bin/env bash
# 起 temporal dev server（SQLite 落盘，免 docker/postgres）。
# gRPC 7233 / Web UI http://127.0.0.1:8233
# --search-attribute：多项目化（260823）ProjectKey=Keyword，工单 workflow 按项目区分用；
# 立项关联（epic-linkage）EpicCode=Keyword，工单按立项代号关联查询用。
# KI-191（t261002-11）InspectionFixture=Keyword（夹具期标记）+
# InspectionSlotTakenAt=Keyword（期槽占坑时刻）——缺注册时**所有**新巡检起票都会在
# start_workflow 显式失败（fail-closed 点名 "no mapping defined for search attribute"，
# 真班排程同样起不了票）；重启本脚本即注册。在跑 server 补注册（幂等容 already）：
#   bin/temporal operator search-attribute create --name ProjectKey --type Keyword
#   bin/temporal operator search-attribute create --name EpicCode --type Keyword
#   bin/temporal operator search-attribute create --name InspectionFixture --type Keyword
#   bin/temporal operator search-attribute create --name InspectionSlotTakenAt --type Keyword
# 保留期（t260829-06 实测）：start-dev 建 default namespace 默认 retention=24h——
# 关闭的 workflow 24h 后**物理删除**（工单历史/审计/建议上下文蒸发，台面失忆）。
# 启动后幂等校正为 100 年（配置落数据卷，设置一次永久生效；新库/重建库也会被本脚本校正）。
set -euo pipefail
POC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$POC_DIR/data"
"$POC_DIR/bin/temporal" server start-dev \
  --db-filename "$POC_DIR/data/temporal.db" \
  --ip 127.0.0.1 --port 7233 --ui-port 8233 \
  --search-attribute ProjectKey=Keyword \
  --search-attribute EpicCode=Keyword \
  --search-attribute InspectionInstance=Keyword \
  --search-attribute InspectionPeriod=Keyword \
  --search-attribute InspectionFixture=Keyword \
  --search-attribute InspectionSlotTakenAt=Keyword \
  --log-level warn &
SERVER_PID=$!
# 等 gRPC 就绪（最多 60s），把 default namespace 保留期改为 100 年（幂等）
for _ in $(seq 1 60); do
  if "$POC_DIR/bin/temporal" operator namespace update \
      --retention 876000h --address 127.0.0.1:7233 default >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
wait "$SERVER_PID"
