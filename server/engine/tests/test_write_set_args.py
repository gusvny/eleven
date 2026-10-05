"""validate_write_set_args 边界与畸形输入（t260902-10，逐例钉死期望元组）。"""
from shared import validate_write_set_args as v


def test_valid_non_empty():
    assert v(["app/src", "server/admin.py"], False) == (True, {"no_file_changes": False}, "")
    assert v(["a"], True) == (True, {"no_file_changes": False}, "")


def test_empty_set():
    assert v([], False)[0] is False
    assert v([], False)[2]  # 拒收文案含两条出路
    assert v([], True) == (True, {"no_file_changes": True}, "")


def test_illegal_entries():
    for ws in (["/abs/path"], ["a/../b"], ["a\\b"], ["C:/x"], [""], [None], [123], ["ok", "/bad"]):
        ok, flags, err = v(ws, False)
        assert ok is False and flags == {} and err, ws


def test_string_write_set_rejected():
    """字符串写集拒收：不拒会被 for 迭代成单字符列表（"app"→['a','p','p']）变假护栏
    （t260902-10 新增形态校验）。"""
    ok, flags, err = v("app", False)
    assert ok is False and flags == {} and "character-by-character" in err
    ok, _, _ = v("app/", False)  # 含斜杠字符串旧实现碰巧被拒（巧合），现属显式校验
    assert ok is False
    assert v(42, False)[0] is False
    assert v({"a": 1}, False)[0] is False


def test_none_keeps_empty_set_semantics():
    """None=按空集口径（既有自检 selfcheck_write_lifecycle 与 client 建票口锁定的容错）。"""
    ok, flags, err = v(None, False)
    assert ok is False and err  # 无声明 → 拒收
    assert v(None, True) == (True, {"no_file_changes": True}, "")


def test_dot_and_glob_entries_rejected():
    """t260915-04 口径统一：'.' 形态与 git 通配哨兵建票期不再判合法——旧判合法、
    写集闸本就拒（unauthorized_path / _is_safe_path 哨兵立场），收「建票说合法、
    闸说不合法」漂移。"""
    for ws in (["."], ["./"], [".//"], [" . "], ["*"], ["**"], ["a/*"], ["src/*.py"],
               ["a?"], ["a!b"], ["a[b]"]):
        ok, flags, err = v(ws, False)
        assert ok is False and flags == {} and err, ws


def test_directory_form_entry_still_legal():
    """存量目录形条目（'server/'）是仓内子目录、不是仓根——t260915-04 不误伤。"""
    assert v(["server/"], False) == (True, {"no_file_changes": False}, "")
    assert v(["server/engine/x.py"], False) == (True, {"no_file_changes": False}, "")
