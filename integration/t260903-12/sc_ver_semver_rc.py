#!/usr/bin/env python3
"""sc_ver_semver_rc.py — VERSION 单源 semver 校验 fail-closed 守护（t260903-12）。

intent（守护的用户可感知契约）：仓根 VERSION 是 sandbar 版本唯一真源（契约⑧-4），
server/version.py 的校验=「semver 全集（含 -rc/-rc.<N> prerelease 段）、畸形 fail-closed」。
version.py 0.1.0 期曾收窄为纯三段（拒 rc 串）；放宽后仓内唯一自动跑的负例守护点
（installer/tests 写集外且无自动跑点）。本场景锁两件事：

  A. 仓根 VERSION 读回自证（单源语义，零字面量锚——升版不触红）：
     read_version()==文件内容 strip；version_tuple()==核心三段整数；
     串本身能被现行 _SEMVER_RE 全匹配（prerelease 后缀不进三元组）。
  B. semver 行为契约（固定串，锚的是正则行为而非当前版本值）：
     正例回归 纯三段 / -rc / -rc.N；负例 12 例全部仍抛 VersionError（fail-closed 不松）。

Hermetic：标准库 + 仓内 version.py 直 import，零端口零网络，不碰 3099。
cwd=仓库根；秒级。退出契约：stdout 末行 SUMMARY pass=N fail=K；exit 1 iff fail>0。
"""
import os
import re
import sys

sys.path.insert(0, os.path.join("server"))
import version  # noqa: E402

passed, failed = 0, 0


def check(cond, label):
    global passed, failed
    if cond:
        passed += 1
        print("  ok %s" % label)
    else:
        failed += 1
        print("  FAIL %s" % label)
    return cond


def expect_verror(s):
    """负例：必须恰抛 VersionError（其他异常类型也算红——fail-closed 靠显式类型）。"""
    try:
        version.parse_semver(s)
    except version.VersionError:
        return True
    except Exception:
        return False
    return False


def main():
    print("== A 仓根 VERSION 读回自证（单源语义，零字面量锚）")
    try:
        raw = open("VERSION", encoding="utf-8").read()
    except OSError as e:
        check(False, "仓根 VERSION 可读（%s）" % e)
        print("SUMMARY pass=%d fail=%d" % (passed, failed))
        return 1
    ver = raw.strip()
    check(ver == raw.strip() and "\n" not in ver and raw.endswith("\n"),
          "VERSION 恰一行（尾换行、无多余空白行）")
    check(version.read_version() == ver,
          "read_version()==文件内容 strip（单源一致）")
    check(re.fullmatch(version._SEMVER_RE, ver) is not None,
          "现行正则可全匹配仓根值（%s）" % ver)
    core = tuple(int(x) for x in ver.split("-")[0].split("."))
    check(version.version_tuple() == core,
          "version_tuple()==核心三段 %s（prerelease 后缀不进三元组）" % (core,))

    print("== B 正例回归（semver 全集）")
    for s, want in [("0.1.0", (0, 1, 0)), ("1.2.3", (1, 2, 3)),
                    ("0.2.0-rc", (0, 2, 0)), ("0.2.0-rc.2", (0, 2, 0)),
                    ("1.0.0-rc.11", (1, 0, 0))]:
        try:
            check(version.parse_semver(s) == want, "正例 %s -> %s" % (s, want))
        except Exception as e:
            check(False, "正例 %s 误拒: %s" % (s, e))

    print("== B 负例（fail-closed 不松，12 例）")
    for s in ["0.02.0-rc",      # 核心段前导零
              "0.2.0-rc.01",    # prerelease 段前导零
              "0.2.0-rc.x",     # prerelease 非数字
              "0.2.0-rc1",      # 无点直接接数字
              "0.2.0-RC",       # 大写
              "v0.2.0-rc",      # v 前缀
              "0.2.0-rc.1.2",   # 双段 prerelease
              "",               # 空串
              "0.2.0\n0.3.0",   # 多行（read_version 层拦，parse 层也须拒）
              "０.２.０",        # 全角数字
              "0.1",            # 缺段
              "0.1.0.0"]:       # 四段
        check(expect_verror(s), "负例拒 %r" % s)

    print("SUMMARY pass=%d fail=%d" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
