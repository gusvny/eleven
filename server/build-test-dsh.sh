#!/bin/sh
# 造 sandbar 测试控制台镜像（test-dsh:dsh-<版本>）——docker-compose.test.yml dsh
# 服务基座，替代每次起台容器内联网 npm 装全局 dsh（456 包 ~2 分钟/台，病根与
# 口径见 Dockerfile.test-dsh 头注）。
#
# 用法（仓库根执行）：  sh server/build-test-dsh.sh [版本号，缺省 0.1.1-rc.2]
# 产物：本地镜像 test-dsh:dsh-<版本>（不入任何 registry，不占外网持久位）。
# 需联网（npm registry，与原容器内安装同源同版）——只在建镜像时联网一次，
# 之后每次起台零网络。
# dsh 升版三处同步：本脚本缺省版本 + Dockerfile.test-dsh ARG 缺省 + compose image: 行。
set -eu

V="${1:-0.1.1-rc.2}"
cd "$(dirname "$0")"
# 空 build context：Dockerfile 自含（ARG 带版本），不打包 server/ 树（含 node_modules）
OUT=$(mktemp -d /tmp/test-dsh-build.XXXXXX)
trap 'rm -rf "$OUT"' EXIT
docker build -f Dockerfile.test-dsh -t "test-dsh:dsh-${V}" --build-arg "DSH_VERSION=${V}" "$OUT" >/dev/null
docker run --rm "test-dsh:dsh-${V}" dsh --version
echo "镜像就绪：test-dsh:dsh-${V}"
