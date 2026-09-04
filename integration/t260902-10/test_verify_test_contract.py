#!/usr/bin/env python3
"""t260902-10 集成场景①：verify_lane 新 check 类型 test 的黑盒契约（用户=任何接入项目）。

黑盒口径：经 admin.py call（与合并闸同款调用路径）驱动真引擎，对 /tmp 沙箱迷你项目
断言——声明在位+命令绿=绿、命令非零=红、cwd=声明目录、声明畸形=整道 fail-closed 红、
不声明=检查关闭、skip_slow 跳过 test。不硬编码检查项名称（以「相对基线多出的检查项」
定位 test 项），防实现改名打碎测试。stdlib-only、无网络、无真 git。
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

LANE = Path.cwd()
PY = sys.executable


def run_verify(project_root, extra=None, skip_slow=False):
    args = {"lane": "code", "path": str(project_root)}
    if skip_slow:
        args["skip_slow"] = True
    if extra:
        args.update(extra)
    p = subprocess.run([PY, "server/admin.py", "call", "verify_lane", json.dumps(args)],
                       capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise AssertionError("admin call verify_lane 非零退出: %s" % (p.stderr or p.stdout)[-300:])
    payload = json.loads(p.stdout)
    assert payload.get("ok"), "admin call 报错: %s" % payload
    return payload["result"]


def check_names(res):
    return [c["check"] for c in res["checks"]]


def items_of(res):
    return [(c["check"], i.get("detail", "")) for c in res["checks"] if c["level"] == "red"
            for i in c.get("items", [])]


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


BASE_YAML = "schema: v1\nlanes:\n  code:\n    write_allow:\n      - .\n"


def make_project(yaml_text):
    root = Path(tempfile.mkdtemp(prefix="t26090210-testcheck-"))
    write(root / "verify.yaml", yaml_text)
    (root / "sub").mkdir()
    write(root / "sub" / "keep.txt", "x")
    return root


def main():
    failures = []

    def case(name, fn):
        try:
            fn()
            print("PASS %s" % name)
        except AssertionError as e:
            failures.append(name)
            print("FAIL %s: %s" % (name, e))
        except Exception as e:
            failures.append(name)
            print("FAIL %s（异常 %s: %s）" % (name, type(e).__name__, e))

    # 基线：无 test 声明
    def yaml_with(test_body):
        return BASE_YAML + "    checks:\n" + test_body  # v2 列表命令制（宿主令 t260902 迁移）

    root_a = make_project(BASE_YAML)
    base_res = run_verify(root_a)
    base_names = check_names(base_res)
    assert base_res["green"], "基线项目（无任何检查声明）应为绿: %s" % items_of(base_res)

    # ① 声明在位+命令绿 → 多出一个绿检查项；且 cwd 语义=声明目录（marker 落 sub/ 不落根）
    def t_green_and_cwd():
        root = make_project(yaml_with(
            "      - id: mytest\n        cmd: touch marker.txt\n        cwd: sub\n"))
        res = run_verify(root)
        extra = [n for n in check_names(res) if n not in base_names]
        assert res["green"], "test 项命令应跑绿: %s" % items_of(res)
        assert len(extra) == 1, "test 声明应恰好多出一个检查项，实际 %s（基线 %s）" % (extra, base_names)
        assert (root / "sub" / "marker.txt").is_file(), "cmd 应在声明 cwd（sub/）下执行"
        assert not (root / "marker.txt").exists(), "cmd 不应落在项目根（cwd 语义被无视）"
        shutil.rmtree(root)
    case("test声明_命令绿且cwd等于声明目录", t_green_and_cwd)

    # ② 命令非零 → 该检查项红、整道绿=False
    def t_red():
        root = make_project(yaml_with(
            "      - id: mytest\n        cmd: false\n        cwd: sub\n"))
        res = run_verify(root)
        extra = [n for n in check_names(res) if n not in base_names]
        assert not res["green"], "命令非零必须红"
        red_extra = [n for n in extra if n in [c["check"] for c in res["checks"] if c["level"] == "red"]]
        assert len(red_extra) == 1, "非零退出应只红 test 项，实际红: %s / 全部 %s" % (red_extra, check_names(res))
        shutil.rmtree(root)
    case("test声明_命令非零判红", t_red)

    # ③ 声明畸形（缺 cmd）→ 整道 fail-closed 红，不执行任何检查
    def t_malformed_missing_cmd():
        root = make_project(yaml_with("      - id: mytest\n        cwd: sub\n"))
        res = run_verify(root)
        assert not res["green"], "声明缺 cmd 必须 fail-closed 红"
        assert len(check_names(res)) == 1 and check_names(res)[0] != "", \
            "畸形应只出 verify.yaml 单红项，实际: %s" % check_names(res)
        shutil.rmtree(root)
    case("test声明_缺cmd整道红", t_malformed_missing_cmd)

    # ④ cmd 非字符串（行内列表）→ 整道 fail-closed 红
    def t_malformed_cmd_type():
        root = make_project(yaml_with(
            "      - id: mytest\n        cmd: [not-a-cmd]\n        cwd: sub\n"))
        res = run_verify(root)
        assert not res["green"], "cmd 非字符串必须 fail-closed 红（不得把列表当命令跑）"
        shutil.rmtree(root)
    case("test声明_cmd非字符串整道红", t_malformed_cmd_type)

    # ⑤ skip_slow=true → test 项与 tsc/smoke 同口径跳过（检查项集合与基线一致）
    def t_skip_slow():
        root = make_project(yaml_with(
            "      - id: mytest\n        cmd: touch marker2.txt\n        cwd: sub\n"))
        res = run_verify(root, skip_slow=True)
        leaked = [n for n in check_names(res) if n not in base_names]
        assert not leaked, "skip_slow 应跳过 test 项，实际多出: %s" % leaked
        assert not (root / "sub" / "marker2.txt").exists(), "skip_slow 下命令不应被执行"
        shutil.rmtree(root)
    case("skip_slow跳过test项", t_skip_slow)

    shutil.rmtree(root_a, ignore_errors=True)
    if failures:
        print("SUMMARY: %d/%d 失败: %s" % (len(failures), 6, "、".join(failures)))
        return 1
    print("SUMMARY: 6/6 PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
