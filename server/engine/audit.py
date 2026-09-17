#!/usr/bin/env python3
"""无差别自审计 + entry_hint 单一真源（KI-067，t260910-06）+ admin.log 轮转面
（t260916-21：按天轮转/保留窗/同日过大顺切/写失败点名）。

背景（260910 两实证）：唯一审计点在 server 层 tools_registry.call()，client.py
进程自身不进账——裸调用（含被拒收调用）admin.log 零痕迹，回执也不提示正规入口。
本模块把两件事收成单一真源：

  1. audit_call()：client.py main() 每个出口（含 -h/无参/未知子命令/argsJSON
     非法/连接失败兜底）与 ticket.py 直 spawn 路径，各记一行 JSONL 到
     server/admin.log（与 tools_registry 同文件；行形状：<4KB，POSIX O_APPEND
     原子）。**连被拒收的调用也记**（拒收不记录=盲区仍在，KI-067 钦点）。
  2. attach_entry_hint()：非正规入口的回执（**含成功回执**——260910 的错发生
     在成功回执里）附 entry_hint 指路 server/tools/ticket.py。

admin.log 轮转面（t260916-21，写路径唯一收口=_append_line）：
  - 按天轮转（验收①）：本地日界（time.localtime 口径，勿混 UTC）首个跨日写入
    时惰性轮转，归档名 admin.log.YYYYMMDD=文件「关闭日」（按其 mtime 日）。
    存量迁移（验收②）：现存文件原样改名归档，不删不截断（两代 schema 行留考古）。
  - 恰好一次（验收①）：两步原子挪移——先把活跃文件 rename 到唯一私有名
    <logname>.rolling.<pid>.<uuid6>（POSIX rename 原子，赢家唯一；输家收到
    FileNotFoundError=别人已轮转，直接续写新文件），赢家再用 _publish（硬链
    原子 no-clobber）把私有名文件发布成最终归档名；目标名已存在（重启残留/
    同秒双切）自动去重后缀，**永不覆盖**。rename 前后做 inode 身份复核：
    stat→rename 窗口内若别的进程已轮转并重建了新文件，rename 抓到的是新文件
    ——原样送还原位（原位被占则停在私有名，清扫面收编），不算本进程轮转，
    杜绝「把别人的新文件误归档」。
  - 同日过大顺切（验收④，宿主 260916 定稿措辞：无「熔断」语义——同日文件过
    大就顺切下一个文件，纯拆分无告警）：同日文件 ≥ admin_log.max_mb（内置缺省
    512MB，≤0=关顺切）当日再切 admin.log.YYYYMMDD-HHMMSS。
  - 保留窗（验收③）：默认保留 **14 天**（宿主 260916 定稿），仅归档赢家进程
    跑一次清扫；删除面=归档命名面 <logname>.<8位日>[-<6位时>[-<去重后缀>]]
    且日期 < 今日-keep_days。命名面之外（admin.log.bak 等）一律不碰。rolling
    孤儿（轮转中途崩溃残，含完整审计行）**先收编入归档命名面（按其 mtime 日），
    不静默删**（数据保全，review C2）；收编失败才降级删除并 stderr 点名；
    收编后超窗的孤儿由下次清扫按归档面政策处置。
  - 配置面（宿主 260916 定稿：配在 project metadata，不用环境变量）：读
    「引擎所属项目」条目 ~/.sandbar/projects/<key>/project.yaml 顶层
    `admin_log: {keep_days, max_mb}`（additive 字段，旧读取方零感知——shared
    装载器已同步容忍，先例=paths.model_routes 指路键）；缺省内置兜底
    14 天/512MB。注册表解析走既有三态 env 优先级（SANDBAR_PROJECTS_DIR 覆盖/
    缺省 ~/.sandbar/projects——测试隔离走同一套面；SANDBAR_PROJECTS_YAML
    legacy 单文件模式不认 admin_log=缺省兜底）。引擎所属项目=条目 dirs 含
    引擎仓根（等值或祖先，主仓与 worktree 两态都命中）。读不到/条目未命中/
    解析失败=内置缺省兜底（fail-open 显式口径：配置读不到不阻断审计写）。
  - O_APPEND 语义保持：本模块所有写=按路径 open('a') 单行 write，无跨轮转持
    fd。admin.log 全部已知写者（audit.py / tools_registry.py /
    workbench node.ts / knowledge review_store.py——后三者在写集外）同为此
    语义，轮转后按路径自然续写新文件，无「双写者各写各文件」分叉面。
  - 口径（KI-010 边界）：轮转是 containment（防失控+保考古），不是根因治理——
    日均增长主体（workbench 轮询+读操作通胀，known-issues KI-010）未除。

审计写失败点名（验收⑤）：admin.log 不可写（权限/只读 fs/路径为目录等）时
三通道留痕，绝不吞回执、绝不 raise（回执是主契约；降级显式声明于此，非静默）：
  a. stderr（既有面）；
  b. logging.getLogger(__name__).warning——已配 logging 的宿主进程（worker 族）
     自动出 WARN 记录；client.py 子进程内经 lastResort 落 stderr；
  c. 回执 dict 就地点名 audit_write_failed——打印回执的出口必须**先审计后
     打印**（client.py _emit 已按此序，t260916-21 改）：打印在前则写失败永远
     无感（nusuyou/dengzhufpv 实测病灶）。

自报家门标记（普通 env，非密钥、非安全语义——宿主 260910 拍板）：
  - env SANDBAR_CLIENT_ENTRY 精确等值 'ticket'（ticket.py _poc 注入）→ 回执
    安静（不附 hint）。
  - **其余任意值一律按 bare 待遇**（回执附 hint）；静默待遇与 source 原文解耦。
  - admin.log 的 source 记 env 原值（≤32 字符截断，缺省字面量 'bare'）——保留
    自称原文便于排查伪造/误配。
  - 口径声明：source 是 **claimed-source 而非系统判定身份**（env 由调用方自带，
    泳道 agent 理论上可自称 'ticket'）。宿主已裁非安全语义，本模块只保证
    「静默待遇仅由代码路径注入的精确值触发」这一合同，不做身份鉴别
    （身份=调用方凭证闸，宿主明确不做，多实例架构未定）。

仅依赖 stdlib（与 shared.py 同独立性），engine 与 tools 两侧共用，双份必漂移
（KI-032 教训）。
"""
import errno
import json
import logging
import os
import re
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

# 自报家门 env 名（普通 env，非密钥）；'ticket' 是唯一获静默待遇的精确值。
ENTRY_ENV = 'SANDBAR_CLIENT_ENTRY'
ENTRY_MARK = 'ticket'
# ticket.py → client.py 的调用关联键 env（一次直调 = admin.log 两行同 call_id）。
CALL_ID_ENV = 'SANDBAR_CLIENT_CALL_ID'
# admin.log 路径（server/admin.log；env SANDBAR_ADMIN_LOG 覆盖，供测试隔离）。
ADMIN_LOG = Path(__file__).resolve().parent.parent / 'admin.log'
ENTRY_HINT = '此为裸入口，请走 server/tools/ticket.py'

# ---- 轮转面配置（t260916-21；宿主 260916 定稿：project metadata，不用 env 旋钮）----
DEFAULT_KEEP_DAYS = 14   # 保留窗内置缺省（project.yaml admin_log.keep_days 缺席/读不到时兜底）
DEFAULT_MAX_MB = 512     # 同日过大顺切阈值内置缺省（admin_log.max_mb 兜底；≤0=关顺切）
ROLLING_TAG = 'rolling'
# 归档命名面后缀形状：<YYYYMMDD>[-<HHMMSS>[-<去重后缀 hex>]]（去重后缀按生成面
# 是 uuid4 hex[:6]；>8 位不认=命名面外，清扫面跳过）。
_ARCH_SUFFIX_RE = re.compile(r'^(\d{8})(?:-(\d{6}))?(?:-([0-9a-f]{1,8}))?$')


def _log_path():
    return Path(os.environ.get('SANDBAR_ADMIN_LOG') or ADMIN_LOG)


# ---- 轮转面：配置与命名面解析（外部输入面，畸形必回落不炸） ----

def _day_key(ts=None):
    """本地日界 → YYYYMMDD（time.localtime 口径，勿混 UTC）。"""
    return time.strftime('%Y%m%d', time.localtime(time.time() if ts is None else ts))


def _projects_root():
    """注册表根（镜像 shared.registry_root 的 env 现读口径，不复造其装载器）：
    SANDBAR_PROJECTS_DIR 覆盖 > ~/.sandbar/projects。"""
    return Path(os.environ.get('SANDBAR_PROJECTS_DIR')
                or (Path.home() / '.sandbar' / 'projects'))


def _strip_yaml_line(raw):
    """去行尾注释与尾空白；整行注释/空行返回 None（与本注册表「值不含 #」的
    既有口径一致，同 shared.strip_registry_line 语义）。"""
    line = re.sub(r'#.*$', '', raw).rstrip()
    return line if line.strip() else None


def _parse_admin_log_overrides(text):
    """从 project.yaml 文本提取顶层 `admin_log:` 块的 keep_days/max_mb（additive
    字段，宿主 260916 定稿的配置位）。最小容错解析（stdlib；块风格，行内 flow
    `admin_log: {…}` 不认=整块回落缺省）：块起于顶层 `admin_log:` 行、收于下一个
    顶层键；子键值可解析为 int 才收（畸形值/缺键=该键回落内置缺省，不炸不猜）。
    返回 dict（仅含认得的键，缺省填充由调用方做）。"""
    out = {}
    in_block = False
    for raw in text.split('\n'):
        line = _strip_yaml_line(raw)
        if line is None:
            continue
        if not line[:1].isspace():  # 顶层
            in_block = (line == 'admin_log:')
            continue
        if not in_block:
            continue
        m = re.match(r'^([a-z_]+):\s*(\S+)\s*$', line.strip())
        if m and m.group(1) in ('keep_days', 'max_mb'):
            try:
                out[m.group(1)] = int(m.group(2))
            except ValueError:
                pass  # 畸形值=该键回落缺省（外部输入面，不炸）
    return out


# 引擎仓根（audit.py= <repo>/server/engine/audit.py）：「引擎所属项目」判定的锚。
ENGINE_REPO = Path(__file__).resolve().parents[2]


def _dirs_cover_engine(text):
    """条目 dirs 是否覆盖引擎仓根（等值或祖先——主仓命中等值，worktree 命中祖先
    （.lane 在主仓树下））。最小解析：只认 dirs: 块内的 `- /abs` 列表项。"""
    repo = ENGINE_REPO
    in_dirs = False
    for raw in text.split('\n'):
        line = _strip_yaml_line(raw)
        if line is None:
            continue
        if not line[:1].isspace():
            in_dirs = False
            continue
        s = line.strip()
        if s == 'dirs:':
            in_dirs = True
            continue
        if in_dirs:
            m = re.match(r'^-\s+(\S+)\s*$', s)
            if m:
                try:
                    p = Path(os.path.realpath(m.group(1)))
                except OSError:
                    continue
                if p == repo or p in repo.parents:
                    return True
            else:
                in_dirs = False
    return False


def _engine_project_yaml(root):
    """定位「引擎所属项目」条目的 project.yaml：条目 dirs 覆盖引擎仓根的首个条目
    （按目录名排序取稳定序）。找不到/根不可读→None（调用方走内置缺省兜底）。"""
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return None
    for d in entries:
        y = d / 'project.yaml'
        try:
            if not y.is_file():
                continue
            text = y.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        if _dirs_cover_engine(text):
            return y
    return None


_CONFIG_CACHE = {'key': None, 'keep_days': DEFAULT_KEEP_DAYS, 'max_mb': DEFAULT_MAX_MB}


def _reset_config():
    """配置缓存复位（测试钩子；生产路径零调用）。"""
    _CONFIG_CACHE['key'] = None


def _admin_log_config():
    """admin.log 配置单点（宿主 260916 定稿）：引擎所属项目 project.yaml 顶层
    `admin_log: {keep_days, max_mb}`，缺省内置兜底 14 天/512MB。缓存键=(注册表根
    路径, 根目录 mtime, 引擎 yaml mtime)——env 现读（测试隔离面）+注册表/配置变更
    可感知，每写一行只多两次 stat，绝无每写扫盘。fail-open 兜底：注册表缺席/
    条目未命中/解析失败=内置缺省（配置读不到不阻断审计写）。"""
    root = _projects_root()
    try:
        key = (str(root), root.stat().st_mtime_ns)
    except OSError:
        key = (str(root), None)
    if _CONFIG_CACHE['key'] == key:
        return _CONFIG_CACHE
    keep, mb = DEFAULT_KEEP_DAYS, DEFAULT_MAX_MB
    y = _engine_project_yaml(root)
    if y is not None:
        try:
            key = key + (y.stat().st_mtime_ns,)
        except OSError:
            key = key + (None,)
        try:
            overrides = _parse_admin_log_overrides(
                y.read_text(encoding='utf-8', errors='replace'))
        except OSError:
            overrides = {}
        keep = overrides.get('keep_days', DEFAULT_KEEP_DAYS)
        mb = overrides.get('max_mb', DEFAULT_MAX_MB)
    _CONFIG_CACHE.update(key=key, keep_days=keep, max_mb=mb)
    return _CONFIG_CACHE


def _keep_days():
    """保留窗天数（project.yaml admin_log.keep_days，缺省 14；≤0=永不删）。"""
    return _admin_log_config()['keep_days']


def _oversize_bytes():
    """同日过大顺切阈值（admin_log.max_mb，缺省 512MB；≤0=0=关顺切，调用方判 falsy）。"""
    mb = _admin_log_config()['max_mb']
    if mb <= 0:
        return 0
    return mb * 1024 * 1024


def _parse_archive_day(name, log_name):
    """归档命名面解析（外部输入面，review C3）：非 <logname>.<归档后缀形状>
    或日期非法（如 20269999）→ None（清扫面跳过不炸、不删）。"""
    if not name.startswith(log_name + '.'):
        return None
    m = _ARCH_SUFFIX_RE.match(name[len(log_name) + 1:])
    if m is None:
        return None
    day = m.group(1)
    try:
        time.strptime(day, '%Y%m%d')
    except ValueError:
        return None
    return day


def _announce_write_failure(err):
    """验收⑤三通道之一/之二：stderr + logging WARN（回执点名在 audit_call）。"""
    msg = 'audit: admin.log 写失败（回执不受影响）：%s' % err
    print(msg, file=sys.stderr)
    try:
        logging.getLogger(__name__).warning(msg)
    except Exception:
        pass  # logging 面故障不吞写路径主逻辑


def _announce_rotation_failure(msg):
    """轮转/清扫面异常留痕（内容均有保全位，非审计丢失）：stderr 点名。"""
    print('audit: %s' % msg, file=sys.stderr)


def _publish(src, dst, attempts=3):
    """同目录原子挪移，绝不覆盖已存在目标（验收②/数据保全底座）。
    首选 link+unlink（POSIX 原子 no-clobber：目标被占=FileExistsError，不存在
    「半写」态）；目标名被占→去重后缀重试（同秒双切/重启残留/孤儿撞名）；
    fs 不支持硬链→回落「存在检查+rename」（窗口极窄+uuid 名，碰撞可忽略）。
    返回最终落点名；挪不动 raise OSError。"""
    cur = dst
    for _ in range(attempts):
        try:
            os.link(src, cur)
        except FileExistsError:
            cur = dst.with_name('%s-%s' % (dst.name, uuid.uuid4().hex[:6]))
            continue
        except OSError as e:
            if e.errno not in (errno.EPERM, errno.EOPNOTSUPP, errno.EXDEV, errno.ENOSYS):
                raise
            # 硬链不可用面：回落存在检查+rename（最后一线窗口，uuid 名兜底）
            if cur.exists():
                cur = dst.with_name('%s-%s' % (dst.name, uuid.uuid4().hex[:6]))
                continue
            os.rename(src, cur)
            return cur
        os.unlink(src)
        return cur
    raise OSError('归档去重名连续冲突：%s' % dst.name)


def _rotate_active(log_path, kind, expect_ino=None):
    """两步轮转：活跃文件 → rolling 私有名（rename 原子，赢家唯一）→ 归档名
    （_publish 原子 no-clobber）。kind='day' 归档名取文件 mtime 日（关闭日语义）；
    kind='oversize' 取当前时刻（同日过大顺切）。返回 True=本进程完成归档（调用方触发
    清扫）；False=别人已轮转/身份复核失败（无归档动作）。"""
    rolling = log_path.with_name('%s.%s.%d.%s' % (
        log_path.name, ROLLING_TAG, os.getpid(), uuid.uuid4().hex[:6]))
    try:
        os.rename(log_path, rolling)
    except FileNotFoundError:
        return False  # 别的进程已轮转走：直接续写新文件（输家零动作）
    except OSError as e:
        _announce_rotation_failure('轮转 rename 失败（原文件继续活跃）：%s' % e)
        return False
    if expect_ino is not None:
        # 身份复核：rename 到手的必须还是 stat 时所见 inode；否则是 stat→rename
        # 窗口内别人已轮转并重建的新文件——原样送还原位（原子 no-clobber），
        # 原位被占则停在私有名（清扫面收编），零丢失、不算本进程轮转。
        try:
            ino = os.stat(rolling).st_ino
        except OSError:
            ino = None
        if ino != expect_ino:
            try:
                os.link(rolling, log_path)
            except OSError:
                _announce_rotation_failure(
                    '轮转身份复核：抓到新文件且原位被占/不可硬链（内容暂存 %s，清扫面收编）'
                    % rolling.name)
            else:
                os.unlink(rolling)
                _announce_rotation_failure('轮转身份复核：抓到新文件，已原样还原（零丢失）')
            return False
    if kind == 'day':
        try:
            day = _day_key(os.stat(rolling).st_mtime)
        except OSError:
            day = _day_key()
        target = log_path.with_name('%s.%s' % (log_path.name, day))
    else:
        target = log_path.with_name('%s.%s-%s' % (log_path.name, _day_key(),
                                                  time.strftime('%H%M%S')))
    try:
        _publish(rolling, target)
    except OSError as e:
        # 归档名发布失败：内容仍完整在 rolling 私有名下（清扫面会收编），不算丢。
        _announce_rotation_failure('归档发布失败（内容暂存 %s）：%s' % (rolling.name, e))
    return True


def _adopt_orphan(p, log_path):
    """rolling 孤儿收编（review C2）：孤儿=轮转中途崩溃残，含完整审计行——按其
    mtime 日收编入归档命名面（不删不截断）；收编失败才降级删除并 stderr 点名；
    删除也失败则保留（数据保全优先）。收编后超保留窗的，下次清扫按归档面处置。"""
    try:
        day = _day_key(p.stat().st_mtime)
    except FileNotFoundError:
        return  # 竞态：别的进程已收编
    except OSError as e:
        _announce_rotation_failure('rolling 孤儿 stat 失败（跳过 %s）：%s' % (p.name, e))
        return
    target = log_path.with_name('%s.%s' % (log_path.name, day))
    try:
        _publish(p, target)
    except FileNotFoundError:
        pass  # 竞态：别的进程已收编
    except OSError as e:
        _announce_rotation_failure('rolling 孤儿收编失败，降级删除点名（%s）：%s' % (p.name, e))
        try:
            p.unlink()
        except OSError as e2:
            _announce_rotation_failure('rolling 孤儿降级删除也失败（保留 %s）：%s' % (p.name, e2))


def _sweep(now=None):
    """保留窗清扫（验收③，仅归档赢家进程跑一次）：删除面=归档命名面且日期
    < 今日-KEEP；KEEP≤0=永不删；rolling 孤儿先收编（C2）。删除/收编失败一律
    stderr 留痕不 raise——清扫永不破坏写路径。"""
    log_path = _log_path()
    log_name = log_path.name
    keep = _keep_days()
    now_ts = time.time() if now is None else now
    cutoff = None
    if keep > 0:
        cutoff = (datetime.fromtimestamp(now_ts) - timedelta(days=keep)).strftime('%Y%m%d')
    try:
        entries = sorted(log_path.parent.iterdir())
    except OSError as e:
        _announce_rotation_failure('保留窗目录不可读，本轮跳过：%s' % e)
        return
    for p in entries:
        name = p.name
        if not name.startswith(log_name + '.'):
            continue
        if name.startswith(log_name + '.' + ROLLING_TAG + '.'):
            _adopt_orphan(p, log_path)
            continue
        day = _parse_archive_day(name, log_name)
        if day is None or cutoff is None or day >= cutoff:
            continue
        try:
            p.unlink()
        except OSError as e:
            _announce_rotation_failure('保留窗删除失败（跳过 %s）：%s' % (name, e))


def _maybe_rotate(log_path, st):
    """写前检查：跨日→日切（优先）；同日超阈→过大顺切。返回是否发生了归档。"""
    if _day_key(st.st_mtime) != _day_key():
        return _rotate_active(log_path, 'day', expect_ino=st.st_ino)
    max_b = _oversize_bytes()
    if max_b and st.st_size >= max_b:
        return _rotate_active(log_path, 'oversize', expect_ino=st.st_ino)
    return False


def _append_line(line):
    """单行落盘唯一收口：跨日惰性日切 → 同日过大顺切 → 保留窗（仅归档时）→
    O_APPEND 追加。返回 None=成功；返回异常对象=写失败（回执点名由调用方附着）。"""
    log_path = _log_path()
    try:
        st = log_path.stat()
    except OSError:
        st = None  # 不存在/不可及：留给下方 open 走创建或报错点名
    if st is not None and st.st_size > 0:
        try:
            if _maybe_rotate(log_path, st):
                _sweep()
        except Exception as e:  # 轮转/清扫面任何意外都不阻断写路径主逻辑
            _announce_rotation_failure('轮转面意外（继续追加原文件）：%s' % e)
    try:
        with log_path.open('a', encoding='utf-8') as f:
            f.write(line + '\n')
    except OSError as e:
        _announce_write_failure(e)
        return e
    return None


def claimed_source():
    """claimed-source：env 原值（≤32 字符截断），缺省 'bare'。非身份鉴别（见模块头）。"""
    raw = os.environ.get(ENTRY_ENV, '')
    if not raw:
        return 'bare'
    return raw[:32]


def is_ticket_entry():
    """静默待遇判定：精确等值才认（'ticket.py'/'1'/空串/带空白一律不认）。"""
    return os.environ.get(ENTRY_ENV) == ENTRY_MARK


def attach_entry_hint(receipt):
    """非正规入口回执附 entry_hint（含成功回执）；已是 'ticket' 或非 dict 则原样返回。"""
    if isinstance(receipt, dict) and not is_ticket_entry() and 'entry_hint' not in receipt:
        receipt['entry_hint'] = ENTRY_HINT
    return receipt


def audit_call(sub, receipt, call_id=None, source=None,
               caller_project=None, identity_class=None, identity_src=None,
               override=None):
    """记一行审计到 admin.log，返回本行 call_id。

    sub：子命令/操作名（client.py 传 argv[1]；ticket.py 直 spawn 传 'ticket.<op>'）。
    receipt：回执 dict（只读摘要进 summary，不整抄 args——畸形/超长输入在此截断）。
    call_id：缺省取 env SANDBAR_CLIENT_CALL_ID（ticket.py 直调的关联键），再缺省自生成。
    source：调用方覆盖（ticket.py 直 spawn 行用 'ticket.py-direct'；缺省 claimed_source）。
    caller_project/identity_class/identity_src/override：跨项目闸身份键（t260915-12，
    client.py _emit 从回执同键提取传入）。None=不落该键；override 由 _emit 恒传布尔
    （闸面的对账 grep 语义=override=false 也是一笔记录）。caller_project 同样是
    claimed 值非身份鉴别（口径同 source）。
    写失败只 stderr/logging 留痕 + 回执点名 audit_write_failed（验收⑤），绝不
    raise——审计不吞回执（主契约优先，见模块头）。
    """
    if not call_id:
        call_id = os.environ.get(CALL_ID_ENV) or uuid.uuid4().hex[:12]
    if source is None:
        source = claimed_source()
    try:
        summary = json.dumps(receipt, ensure_ascii=False, default=repr)
    except Exception:
        summary = repr(receipt)
    rec = {
        'ts': int(time.time()),
        'call_id': str(call_id)[:64],
        'source': str(source)[:32],
        'sub': str(sub)[:64],
        'ok': bool(receipt.get('ok')) if isinstance(receipt, dict) else False,
        'summary': summary[:800],
    }
    # 跨项目闸身份键（可选，缺省不写=旧消费者零感知）：admin.log 的对账观测面。
    if caller_project is not None:
        rec['caller_project'] = str(caller_project)[:41]
    if identity_class is not None:
        rec['identity_class'] = str(identity_class)[:16]
    if identity_src is not None:
        rec['identity_src'] = str(identity_src)[:16]
    if override is not None:
        rec['override'] = bool(override)
    line = json.dumps(rec, ensure_ascii=False, default=repr)
    write_err = None
    try:
        write_err = _append_line(line)
    except Exception as e:  # 轮转/清扫面的非 OSError 意外同样不吞回执
        write_err = e
        _announce_write_failure(e)
    # 验收⑤：写失败在回执就地点名（summary 已先按写前 receipt 生成，marker 不会
    # 反进本行审计——失败行根本没写出去）。非 dict receipt 无处附着，跳过不炸。
    if write_err is not None and isinstance(receipt, dict) and 'audit_write_failed' not in receipt:
        receipt['audit_write_failed'] = str(write_err)[:200]
    return call_id
