"""L1 unit battery for the statement-level emit-anchor predicate (t261004-26 B3a).

The predicate lib (integration/lib_emit_anchor.py) is a pure function
(text, filename) -> violations; this battery pins its truth table, including
the exact escape shape that motivated the change: the -23 fix was an extra
wrapping pair of parentheses, which the old substring guard could not see.
Run: python3 -m pytest integration/test_lib_emit_anchor.py -q  (unit run, not
an integration entry — the sc_ guard file is never executed here).
"""
import importlib.util
import pathlib
import sys

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "lib_emit_anchor", _HERE / "lib_emit_anchor.py")
lib_emit_anchor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lib_emit_anchor)

fn = lib_emit_anchor.emit_anchor_violations

COMPLIANT = ('import json\n'
             'print(json.dumps(payload, ensure_ascii=False).encode("utf-8",'
             ' "backslashreplace").decode("utf-8"))\n')
WRAP_NO_FB = 'print((json.dumps(payload, ensure_ascii=False)))\n'      # the -23 shape
WRAP_FB = ('print((json.dumps(payload, ensure_ascii=False)'
           '.encode("utf-8", "backslashreplace").decode("utf-8")))\n')
WRAP_FB_MULTILINE = ('print((\n'
                     '    json.dumps(payload, ensure_ascii=False)\n'
                     '    .encode("utf-8", "backslashreplace")\n'
                     '    .decode("utf-8")\n'
                     '))\n')
WRAP_FB_MULTILINE_NO_FB = ('print((\n'
                           '    json.dumps(payload, ensure_ascii=False)\n'
                           '    .decode("utf-8")\n'
                           '))\n')
SYNTAX_ERR = 'def broken(:\n  print((json.dumps(x, ensure_ascii=False)))\n'
NOT_PYTHON = 'this is ::: not python at all (((\n'
PLAIN_PRINT = 'print("hello world")\n'
ASCII_TRUE = 'print(json.dumps(payload))\n'          # ensure_ascii default = out of scope
ATTR_PRINT = ('import json\n'
              'out.print(json.dumps(payload, ensure_ascii=False))\n')
INTERPOLATED = ('import json\n'
                'print("trace: " + json.dumps(payload, ensure_ascii=False))\n')


def test_compliant_is_clean():
    assert fn(COMPLIANT, "compliant.py") == []


def test_minus23_wrap_without_fallback_is_red():
    v = fn(WRAP_NO_FB, "wrap.py")
    assert v and "wrap.py" in v[0]


def test_minus23_wrap_with_fallback_is_clean():
    assert fn(WRAP_FB, "wrap.py") == []


def test_multiline_wrapped_call_is_seen():
    assert fn(WRAP_FB_MULTILINE, "ml.py") == []


def test_multiline_without_fallback_is_red_with_lineno():
    v = fn(WRAP_FB_MULTILINE_NO_FB, "ml.py")
    assert v and ":1:" in v[0]


def test_syntax_error_is_fail_closed_and_names_file():
    v = fn(SYNTAX_ERR, "broken.py")
    assert v and "broken.py" in str(v)


def test_non_python_input_is_fail_closed_not_silent_green():
    v = fn(NOT_PYTHON, "garbage.py")
    assert v and "garbage.py" in str(v)


def test_empty_input_is_clean():
    assert fn("", "empty.py") == []


def test_plain_print_out_of_scope():
    assert fn(PLAIN_PRINT, "plain.py") == []


def test_ensure_ascii_default_out_of_scope():
    assert fn(ASCII_TRUE, "ascii.py") == []


def test_attribute_print_is_in_scope():
    assert fn(ATTR_PRINT, "attr.py") != []


def test_interpolated_print_seen_by_ast_not_substring():
    # the old substring guard (`print(json.dumps(` literal) could NOT see this
    assert fn(INTERPOLATED, "interp.py") != []


def test_violation_carries_lineno():
    src = "x = 1\ny = 2\n" + WRAP_NO_FB
    v = fn(src, "lines.py")
    assert v and ":3:" in v[0]


def test_module_has_exactly_one_two_arg_callable():
    # discovery contract: the guard-chain scenario locates the predicate by
    # "the single two-argument callable defined in this module"
    two_arg = [n for n, f in vars(lib_emit_anchor).items()
               if callable(f) and getattr(f, "__module__", None) == "lib_emit_anchor"
               and getattr(f, "__code__", None) is not None
               and f.__code__.co_argcount == 2]
    assert two_arg == ["emit_anchor_violations"]
