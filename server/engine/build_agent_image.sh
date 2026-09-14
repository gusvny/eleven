#!/bin/sh
# 造 agent 执行面镜像（sandbar-agent:dsh-<dsh版本>-s<序>）——引擎「每票一容器」基座
# （t260913-04，方案 gen1 §4 Step 1；家族范式对齐 server/build-test-dsh.sh）。
#
# 用法（任意 cwd）：sh server/engine/build_agent_image.sh [dsh版本] [镜像序号]
# 产物：本地镜像 sandbar-agent:dsh-<dsh版本>-s<序>（本机自建、不入 registry）。
# 需联网（npm registry + pypi），只在建镜像时联网一次，之后起容器零网络。
# 版本三处同步：本脚本缺省 + Dockerfile.agent ARG 缺省 + agent_runtime.py
# DEFAULT_AGENT_IMAGE（单测 test_agent_runtime.py 机械防漂移）。
# 缺省产物 tag：sandbar-agent:dsh-0.1.1-rc.2-s1（观测位，与 compose 头注一致）。
set -eu

DV="${1:-0.1.1-rc.2}"
SEQ="${2:-s1}"
TAG="sandbar-agent:dsh-${DV}-${SEQ}"
DIR="$(cd "$(dirname "$0")" && pwd)"
# 最小 build context（只带 Dockerfile + supervisor 源码，不打包 server/ 树）；
# supervisor 用 COPY 从同一源文件进镜像，杜绝手抄两份漂移。
OUT=$(mktemp -d /tmp/agent-image-build.XXXXXX)
trap 'rm -rf "$OUT"' EXIT
cp "$DIR/Dockerfile.agent" "$OUT/Dockerfile"
cp "$DIR/sandbar_exec.py" "$OUT/sandbar_exec.py"
# 构建期网络走宿主栈（--network=host）：260913 实建两次实测，构建 VM 默认桥接路径对
# registry 不稳（EIDLETIMEOUT 575s / ECONNRESET 658s）；只影响 build 一次，运行期仍零网络。
docker build --network="${DOCKER_BUILD_NET:-host}" -f "$OUT/Dockerfile" -t "$TAG" \
    --build-arg "DSH_VERSION=${DV}" "$OUT" >/dev/null
docker run --rm "$TAG" sh -c 'dsh --version && python3 -c "import pytest, temporalio, yaml" && git --version && zstd --version'
echo "镜像就绪：$TAG"
