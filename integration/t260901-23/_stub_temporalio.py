"""t260901-23 测试共用：temporalio 导入桩。

黑盒口径不依赖真 Temporal——但 client.py 在模块顶层 import temporalio，本沙箱
环境未装该包。这里在 import client 之前往 sys.modules 塞最小桩：只保证模块
顶层导入与类定义（装饰器）不炸，不模拟任何引擎语义；查询/handle 全部由各测试
自己的 Fake 对象承担。装了真 temporalio 的环境本桩不生效（不覆盖已有模块）。
"""
import sys
import types


def _identity_decorator(*args, **kwargs):
    """@workflow.defn / @workflow.run / @workflow.query 等的桩：原样返回被装饰物。"""
    if args and (isinstance(args[0], (type, types.FunctionType))):
        return args[0]

    def deco(obj):
        return obj
    return deco


class _Unsafe:
    """workflow.unsafe 桩：导入期 imports_passed_through() 只需是上下文管理器。"""

    def imports_passed_through(self):
        import contextlib
        return contextlib.nullcontext()


class _WorkflowModule(types.ModuleType):
    """temporalio.workflow 桩：导入期用到的名字全部走恒等装饰器。"""

    def __getattr__(self, name):
        if name == "unsafe":
            return _Unsafe()
        if name in ("logger",):
            import logging
            return logging.getLogger("stub.temporalio.workflow")
        return _identity_decorator


def install():
    if "temporalio" in sys.modules:
        return
    pkg = types.ModuleType("temporalio")
    pkg.__path__ = []  # 允许 from temporalio.<sub> import … 形式
    sys.modules["temporalio"] = pkg

    client_mod = types.ModuleType("temporalio.client")

    class Client:  # 类型注解位：只需是类
        pass
    client_mod.Client = Client
    sys.modules["temporalio.client"] = client_mod
    pkg.client = client_mod

    common_mod = types.ModuleType("temporalio.common")

    class SearchAttributeKey:  # 仅 for_keyword 静态构造；测试打桩绕开真 SA
        @staticmethod
        def for_keyword(name):
            return ("kw", name)

    class RetryPolicy:  # 导入期占位；测试不打真引擎，重试语义不经过它
        def __init__(self, *args, **kwargs):
            pass

    common_mod.SearchAttributeKey = SearchAttributeKey
    common_mod.RetryPolicy = RetryPolicy

    class SearchAttributePair:  # 函数内导入占位
        def __init__(self, key, value):
            self.key, self.value = key, value

    class TypedSearchAttributes:  # 函数内导入占位
        def __init__(self, pairs=()):
            self.pairs = list(pairs)

        def get(self, key):
            for p in self.pairs:
                if p.key == key:
                    return p.value
            return None
    common_mod.SearchAttributePair = SearchAttributePair
    common_mod.TypedSearchAttributes = TypedSearchAttributes
    sys.modules["temporalio.common"] = common_mod
    pkg.common = common_mod

    wf_mod = _WorkflowModule("temporalio.workflow")
    sys.modules["temporalio.workflow"] = wf_mod
    pkg.workflow = wf_mod

    exc_mod = types.ModuleType("temporalio.exceptions")

    class ApplicationError(Exception):  # 导入期占位；测试不抛真引擎异常
        def __init__(self, message, *args, **kwargs):
            super().__init__(message)
    exc_mod.ApplicationError = ApplicationError
    sys.modules["temporalio.exceptions"] = exc_mod
    pkg.exceptions = exc_mod

    act_mod = _WorkflowModule("temporalio.activity")  # @activity.defn 等同走恒等装饰器
    sys.modules["temporalio.activity"] = act_mod
    pkg.activity = act_mod
