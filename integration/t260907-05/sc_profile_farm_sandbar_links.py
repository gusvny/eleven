#!/usr/bin/env python3
"""sc_profile_farm_sandbar_links.py —— profile 软链农场重指一致性（t260907-05，灰盒 L3）。

intent（守护的用户可感知契约 / 工单验收③＋正文③④）：
- 宿主重启 console 后插件按新名装载——装载链的每一环必须同指一个新名：cordis.patch.yml
  的 id/name（装载声明）== node_modules/<包名> 软链名（裸包名解析锚）== 插件目录
  package.json 的 name（包真源）。任何一环留在旧名=装载断链或双名并存，用户看到的
  是「插件消失/重复」而非一次顺畅改名。
- 容器侧同一契约（gen1 补完，docker-compose.test.yml 农场构造段）：docker 测试台的
  profile 装配脚本（continue 跳过名＋ln -sfn 直链名）与 patch id 必须同 token——
  容器断链在本环境被 ENV_FAIL（docker 缺席）捂着（KI-046/051 同族：环境红捂真红），
  静态层一致性断言是该形态唯一能在无 docker 环境掐死的防线。
- suyou-tools.ts→sandbar-tools.ts 随票：真身、两 profile 内软链、三处 import 必须同步；
  任一环漏改=console 启动即 import 错误（宿主重启边界上炸给用户看）。
- headless profile 的 cordis.patch.yml 必须仍是软链（两份同源的机制锚）——若被替换成
  独立文件，两 profile 声明可静默漂移（宿主令「两 profile 都改」的机制保障被掏空）。

对抗面（developer 最易犯的错）：
- 链建了但指错目录（../../ui 拼错层）、链名拼写与 patch id 差一字符、只建 web profile
  漏 headless、删旧链漏删、mv 真身漏改 import。本场景逐环独立断言，不信任任何单点自检。

与既有资产 intent 区别（防 intent 级重复）：
- sc_naming_residue_fulltext 守文本面收口（谁都不许残留旧 token）；本条守**装载链
  结构一致性**（软链指向/三方对齐/headless 同源机制）——文本干净不等于链指对了。
- KI-037①（profile 软链缺→capture-stale-banner 红）属环境债已 fixed；本条守的是
  迁移后的**新链正确性**，环境债复发形态（链缺）在本条同样红，但 intent 是迁移不是环境。

high-level steps：
  1. 真身面：server/sandbar-tools.ts 在场（旧 suyou-tools.ts 不在）、内部工具
     注册名 sandbar-tools；
  2. import 面：ui/node.ts、workbench/node.ts、workbench/src/host/metrics.ts 三处
     import 指向 sandbar-tools.ts 且零 suyou-tools.ts 残留；
  3. 软链面：两 profile 的 sandbar-tools.ts → ../sandbar-tools.ts（realpath 命中真身），
     旧 suyou-tools.ts 软链不在；
  4. 农场面：两 profile 的 node_modules/ 五链（sandbar-{admin-ui,workbench,knowledge,
     providers,temporal-tools}）各自 realpath → 对应实际目录，旧 suyou-* 链零残留；
  5. 声明面：profile/cordis.patch.yml 全部 insert 条目 id==name 且均为 sandbar-*，
     每条 id 在 web 农场链名集合中（三方一致）；headless/cordis.patch.yml 是指向
     ../profile/cordis.patch.yml 的软链；
  6. 容器侧面：docker-compose.test.yml 农场构造段的 continue 跳过名与 ln -sfn
     直链名 == patch 中指向 ../../workbench 的插件 id（动态联动，不写死字面）；
     顶层拷贝清单注释的 tools 文件名与 patch 顶层 tools id 同 token。

Hermetic：纯文件系统读（os.path.islink/realpath），零端口零网络零 spawn，不碰 3099。
cwd=仓库根；秒级。三态契约：stdlib 文件读无环境依赖——不设 ENV_FAIL 路径；末行
SUMMARY pass=N fail=N；exit 1 iff fail>0。实现段落地前（农场未建/软链未重建）红属
预期；arbitrate/merge 期必须绿。
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DSH = os.path.join(REPO, "server")
PROFILES = ["profile", "profile-headless"]
# 裸包名解析锚 → 实际插件目录（农场五链的「应指」映射）。
# t260907-10 摊平后插件住 server/plugins/<name>（农场链 ../../plugins/<name>）
FARM = {
    "sandbar-admin-ui": "plugins/ui",
    "sandbar-workbench": "plugins/workbench",
    "sandbar-knowledge": "plugins/knowledge",
    "sandbar-providers": "plugins/providers",
    "sandbar-temporal-tools": "plugins/temporal-tools",
}
IMPORTERS = [
    "server/plugins/workbench/node.ts",
    "server/plugins/ui/node.ts",
    "server/plugins/workbench/src/host/metrics.ts",
]

passed, failed = 0, 0


def check(cond, label):
    global passed, failed
    if cond:
        passed += 1
        print("  ok   %s" % label)
    else:
        failed += 1
        print("  FAIL %s" % label)


def rd(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def main():
    print("== 1. 真身面：sandbar-tools.ts 在场，旧名不在")
    body = rd(os.path.join(DSH, "sandbar-tools.ts"))
    check(body is not None, "server/sandbar-tools.ts 在场")
    check(not os.path.exists(os.path.join(DSH, "suyou-tools.ts")), "server/suyou-tools.ts 已不在")
    check(bool(body) and re.search(r"name\s*[:=]\s*['\"]sandbar-tools['\"]", body) is not None,
          "工具注册名 name='sandbar-tools' 在文")

    print("== 2. import 面：三处消费方指向新名")
    for rel in IMPORTERS:
        text = rd(os.path.join(REPO, rel))
        check(text is not None and "sandbar-tools.ts" in text and "suyou-tools.ts" not in text,
              "%s import sandbar-tools.ts（零旧名）" % rel)

    print("== 3. 软链面：两 profile 的 sandbar-tools.ts → 真身")
    truth = os.path.realpath(os.path.join(DSH, "sandbar-tools.ts"))
    for prof in PROFILES:
        link = os.path.join(DSH, prof, "sandbar-tools.ts")
        check(os.path.islink(link) and os.path.realpath(link) == truth,
              "%s/sandbar-tools.ts 软链→真身" % prof)
        check(not os.path.lexists(os.path.join(DSH, prof, "suyou-tools.ts")),
              "%s 旧 suyou-tools.ts 软链已删" % prof)

    print("== 4. 农场面：node_modules 五链指对、旧链零残留（两 profile）")
    for prof in PROFILES:
        farm_dir = os.path.join(DSH, prof, "node_modules")
        for link_name, want_dir in sorted(FARM.items()):
            link = os.path.join(farm_dir, link_name)
            want = os.path.realpath(os.path.join(DSH, want_dir))
            check(os.path.islink(link) and os.path.realpath(link) == want,
                  "%s/node_modules/%s → ../../%s" % (prof, link_name, want_dir))
        stale = sorted(n for n in (os.listdir(farm_dir) if os.path.isdir(farm_dir) else [])
                       if n.startswith("suyou-"))
        check(not stale, "%s 农场旧 suyou-* 链零残留%s" % (prof, ("——残: %s" % stale) if stale else ""))

    print("== 5. 声明面：cordis.patch.yml id==name 全 sandbar-*，且与 web 农场链逐条对齐")
    patch = rd(os.path.join(DSH, "profile", "cordis.patch.yml"))
    if patch is None:
        check(False, "profile/cordis.patch.yml 可读")
    else:
        # 插件面=insert 块内「sandbar-* id 紧随 name」的条目（farm 五链）；patch 里
        # 另有 config 型顶层条目（agent-default-model/agent-presets/webserver：无 name、
        # 走 config 不走插件装载）与 schedule（insert 但 name=npm 别名
        # @deepseek-ai/dsh-schedule，走 pnpm 依赖解析非农场链）——三方一致断言只对
        # 插件面成立（config 条目加 name 会改运行时语义，全局 zip 配对任何实现都过不了）；
        # 全局面只查零 suyou-* 残留。
        pairs = re.findall(
            r"- id:\s*['\"]?(sandbar-[\w.-]+)['\"]?\s*\n\s*name:\s*['\"]([^'\"]+)['\"]", patch)
        all_ids = re.findall(r"-\s*id:\s*['\"]?([\w.-]+)", patch)
        all_names = re.findall(r"-?\s*name:\s*['\"]([^'\"]+)['\"]", patch)
        check(len(pairs) == len(FARM) and all(i == n for i, n in pairs),
              "patch 插件面 insert 恰 %d 条 id==name 成对（实 %d）" % (len(FARM), len(pairs)))
        bad_old = [v for v in all_ids + all_names if v.startswith("suyou-")]
        check(not bad_old, "patch id/name 值零 suyou-* 残留%s" % (("——残: %s" % bad_old) if bad_old else ""))
        farm_names = set(FARM)
        orphan = [i for i, _ in pairs if i not in farm_names]
        check(not orphan, "patch 插件面每条 id 有农场链对应%s" % (("——缺链: %s" % orphan) if orphan else ""))
    head_patch = os.path.join(DSH, "profile-headless", "cordis.patch.yml")
    check(os.path.islink(head_patch)
          and os.path.realpath(head_patch) == os.path.realpath(os.path.join(DSH, "profile", "cordis.patch.yml")),
          "headless/cordis.patch.yml 仍是指向 profile 真身的软链（两份同源机制锚）")

    print("== 6. 容器侧面：compose 农场构造链名与 patch id 动态联动一致")
    compose = rd(os.path.join(DSH, "docker-compose.test.yml"))
    if compose is None:
        check(False, "server/docker-compose.test.yml 可读")
    elif patch is not None:
        # 动态锚：patch 里 name 指向 ../../workbench 的插件 id（不写死字面——未来再
        # 改名时本子用例自动跟随声明侧，只验「compose 与 patch 同 token」的结构性契约）。
        wb_ids = [i for i, n in pairs if "workbench" in n]
        wb_id = wb_ids[0] if len(wb_ids) == 1 else None
        check(wb_id is not None,
              "patch 中指向 workbench 的插件 id 恰一条（动态锚可解析）%s" % (("" if wb_id else "——实: %s" % wb_ids)))
        cont = re.search(r'\[\s*"\$\$b"\s*=\s*"([\w.-]+)"\s*\]\s*&&\s*continue', compose)
        lnn = re.search(r'ln -sfn /repo/server/plugins/workbench "\$\$NM/([\w.-]+)"', compose)
        check(cont is not None and cont.group(1) == wb_id,
              "compose continue 跳过名 == patch workbench id（实: %s）" % (cont.group(1) if cont else "未找到"))
        check(lnn is not None and lnn.group(1) == wb_id,
              "compose ln -sfn 直链名 == patch workbench id（实: %s）" % (lnn.group(1) if lnn else "未找到"))
        check(lnn is not None and "/repo/server/plugins/workbench" in compose,
              "compose 直链目标=/repo/server/plugins/workbench（被测树，非依赖树回落）")
        # 顶层拷贝清单契约：注释声明的 tools 文件名完整名锚定（cordis 顶层文件装载——
        # 拷错了=容器台起不了，同样被 ENV_FAIL 捂着）。注：patch 顶层 tools 条目是
        # config 型（无 name、不在插件面 pairs 内）——其 id 已由第 5 节「零 suyou-* 残留」
        # 与场景 1 全文扫守住；本子用例直接锚 compose 注释的完整文件名。
        check("sandbar-tools.ts" in compose,
              "compose 顶层拷贝清单注释含 sandbar-tools.ts（完整名锚定）")
        check("suyou-workbench" not in compose and "suyou-tools" not in compose,
              "compose 农场构造段零旧 token（与场景 1 全文扫交叉复验）")

    print("SUMMARY pass=%d fail=%d" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
