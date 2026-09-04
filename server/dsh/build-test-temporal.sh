#!/bin/sh
# 造 sandbar 测试引擎镜像（test-temporal:cli-<版本>）——替代已归档的
# temporalio/temporalite：官方 temporal CLI 自带同源 dev server（Server/UI 内嵌），
# 与本仓 bin/temporal 同版即行为一致；旗标兼容 temporalite（同名同义），
# 子命令=start-dev（start 不存在——cobra 会打组帮助假旗标表，别被骗）。
#
# 用法（仓库根执行）：  sh server/dsh/build-test-temporal.sh [版本号，缺省 1.8.3]
# 产物：本地镜像 test-temporal:cli-<版本>（不入任何 registry，不占外网持久位）。
# 网络注意：GitHub 直连常被墙——脚本按序试 本机代理(7897) → gh-proxy.com →
# ghfast.top → mirror.ghproxy.com，全败则报错退出（fail-closed，不产半截镜像）。
set -eu

V="${1:-1.8.3}"
ASSET="temporal_cli_${V}_linux_arm64.tar.gz"
URL="https://github.com/temporalio/cli/releases/download/v${V}/${ASSET}"
OUT=$(mktemp -d /tmp/test-temporal-build.XXXXXX)
trap 'rm -rf "$OUT"' EXIT

sz=0
try() { sz=$(curl -sL --connect-timeout 20 -o "$OUT/cli.tgz" "$1" -w '%{size_download}' || true); }

[ "$sz" -lt 10000000 ] && try "http://127.0.0.1:7897|$URL" 2>/dev/null || true
for G in "http://127.0.0.1:7897|$URL" "https://gh-proxy.com/$URL" "https://ghfast.top/$URL" "https://mirror.ghproxy.com/$URL"; do
  [ "$sz" -ge 10000000 ] && break
  try "${G#*|}"
done
if [ "$sz" -lt 10000000 ]; then
  echo "错误：四条下载路全败（得到 ${sz}B）——检查代理/网络后重试" >&2; exit 1
fi

tar xzf "$OUT/cli.tgz" -C "$OUT"
cp "$(dirname "$0")/Dockerfile.test-temporal" "$OUT/Dockerfile"
# 版本戳进镜像 tag，升版即换 tag（compose 同步改 image: 行）
docker build -t "test-temporal:cli-${V}" "$OUT" >/dev/null
docker run --rm --entrypoint /bin/sh "test-temporal:cli-${V}" -c '/temporal --version'
echo "镜像就绪：test-temporal:cli-${V}"
