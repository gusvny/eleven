# integration/ 薄 conftest（t260910-13）：装配失败分类协议钩子。K5——
# pytest_plugins 声明在非根 conftest 是新版 pytest 移除项；以 integration/
# 为 rootdir 跑 pytest 时本文件即根 conftest，声明合法。模块名可被
# pytest 自动 import 的前提是 rootdir 在 sys.path（rootdir conftest 语义）。
pytest_plugins = ["conftest_result_protocol"]
