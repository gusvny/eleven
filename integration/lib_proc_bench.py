"""Process-bench endpoint for scenarios that only need a Temporal server.

Why this exists (host order 261024 "can we drop docker and move to the process
bench"): the online journeys used to require the shared docker stage on
127.0.0.1:17233 (integration/stage_docker.py). That dependency is what turned a
red round into "unverified" for hours and, when the stage was up but cold, into
false reds. integration/process_bench.py already serves the same gRPC front end
as a plain process in a fraction of a second; this module is the one call a
scenario makes to get that endpoint.

Contract:
  ensure(modules=(...), namespace="default", host=None) -> dict
    {"started": bool, "port": int, "namespace": str, "handle": dict|None}
  - If something already answers on the endpoint (a bench the caller did not
    start, e.g. a shared stage), nothing is started and nothing will be stopped.
  - Otherwise a process bench is started ON THE ENDPOINT'S PORT, the namespace
    env is pinned, and the TEST_TARGET_HOST / TEST_NAMESPACE constants of every
    module handed in are rewritten in place (libs that did `from lib_x import
    TEST_TARGET_HOST` bound the value at import, so env alone is not enough for
    in-process SDK connects).
  - The bench is reaped at interpreter exit (process_bench's own handle), so a
    scenario that returns early still leaves no residue.
  - A bench that refuses raises RuntimeError carrying process_bench's named
    reason; a scenario turns that into its own ENV_FAIL, never a silent skip.

Non-goals (same as process_bench): no namespace isolation per scenario, no
filesystem sandbox, no cpu/memory caps. Cases that assert a stage lease, the
sweep of a stale stage, or the container agent runtime stay on the docker stage.
"""
from __future__ import annotations

import atexit
import os
import socket
import sys

DEFAULT_HOST = "127.0.0.1:17233"
DEFAULT_NAMESPACE = "default"


def _integ_dir():
    return os.path.dirname(os.path.abspath(__file__))


def _answers(port, timeout=0.3):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        return sock.connect_ex(("127.0.0.1", int(port))) == 0
    finally:
        sock.close()


def _endpoint(modules, host):
    """The endpoint the caller's modules already agree on, else the argument."""
    if host:
        return host
    env = os.environ.get("SANDBAR_TARGET_HOST")
    if env:
        return env
    for mod in modules:
        value = getattr(mod, "TEST_TARGET_HOST", None)
        if isinstance(value, str) and value.count(":") == 1:
            return value
    return DEFAULT_HOST


def _namespace(modules, namespace):
    for mod in modules:
        value = getattr(mod, "TEST_NAMESPACE", None)
        if isinstance(value, str) and value.strip():
            return value
    return namespace or DEFAULT_NAMESPACE



def _namespace_exists(port, ns, modules=()):
    """Does the answering bench serve this namespace? Probed through the CLI."""
    bin_path = os.environ.get("SANDBAR_TEMPORAL_BIN")
    if not bin_path:
        for mod in modules:
            cand = getattr(mod, "TP_DIR", None)
            if isinstance(cand, str) and cand:
                bin_path = os.path.join(cand, "bin", "temporal")
                break
    if not bin_path or not os.path.exists(bin_path):
        return True            # no CLI: keep the declared namespace (never guess)
    import subprocess
    proc = subprocess.run([bin_path, "--address", "127.0.0.1:%d" % port,
                           "--namespace", ns, "operator", "namespace", "describe"],
                          capture_output=True, text=True, timeout=15)
    blob = ((proc.stdout or "") + (proc.stderr or "")).lower()
    if proc.returncode == 0:
        return True
    return not ("not found" in blob or "notfound" in blob)


def ensure(modules=(), namespace=DEFAULT_NAMESPACE, host=None):
    """Make sure a Temporal endpoint answers; start the process bench if not."""
    modules = tuple(m for m in modules if m is not None)
    endpoint = _endpoint(modules, host)
    port = int(str(endpoint).rsplit(":", 1)[1])
    if _answers(port):
        # A bench is already there (a shared stage or a bench another caller
        # started): use it exactly as the modules declare, never stop it - unless
        # that namespace does not exist on it (measured 261024: a leftover
        # process bench answers on the stage port but only serves "default", and
        # every child then died with "Namespace sandbar-test is not found").
        ns = _namespace(modules, namespace)
        if not _namespace_exists(port, ns, modules):
            ns = namespace or DEFAULT_NAMESPACE
        os.environ.setdefault("SANDBAR_TARGET_HOST", "127.0.0.1:%d" % port)
        os.environ.setdefault("SANDBAR_NAMESPACE", ns)
        return {"started": False, "port": port, "namespace": ns, "handle": None}
    # We start the bench, so the namespace is the bench's own: the docker stage's
    # namespace name does not exist here and every child would ask for it.
    ns = namespace or DEFAULT_NAMESPACE

    integ = _integ_dir()
    if integ not in sys.path:
        sys.path.insert(0, integ)
    import process_bench  # noqa: PLC0415 — the bench is optional until needed

    handle = process_bench.start(port=port)
    if not handle.get("ok"):
        raise RuntimeError("process bench refused on port %d: %s"
                           % (port, handle.get("reason")))
    # The bench serves its own namespaces (default only): pin the env the child
    # processes read AND the module constants the in-process SDK calls use.
    os.environ["SANDBAR_TARGET_HOST"] = "127.0.0.1:%d" % port
    os.environ["SANDBAR_NAMESPACE"] = ns
    for mod in modules:
        if hasattr(mod, "TEST_TARGET_HOST"):
            mod.TEST_TARGET_HOST = "127.0.0.1:%d" % port
        if hasattr(mod, "TEST_NAMESPACE"):
            mod.TEST_NAMESPACE = ns

    def _stop():
        try:
            process_bench.stop(port=port, pid=handle.get("pid"),
                               db=handle.get("db"))
        except Exception:  # noqa: BLE001 — a failed teardown is not a case fault
            pass

    atexit.register(_stop)
    return {"started": True, "port": port, "namespace": ns, "handle": handle}
