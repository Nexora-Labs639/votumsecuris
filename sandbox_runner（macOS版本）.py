"""
sandbox_runner.py —— 可在 macOS / Linux 使用的进程级沙箱执行器。

与 sandbox_v0.py 接口兼容：
    run_sandboxed(cmd, timeout_ms=5000, mem_limit_mb=256)
    -> {"stdout", "stderr", "exit_code", "status", ...}

status 取值：
    ok        正常结束，退出码 0
    error     正常结束，退出码非 0（含被信号杀死）
    timeout   超时，已被强制终止
    oom       进程组内存超过 mem_limit_mb，已被强制终止
    rejected  被静态策略拒绝，根本没有执行

macOS 实测结论（直接决定了下面的实现方式）：
  1. RLIMIT_AS / RLIMIT_DATA 无法设置，内核对任意数值都返回 EINVAL(22)。
     所以 macOS 上内存限制只能靠 RSS 采样看门狗，不能靠 rlimit。
  2. RLIMIT_CPU / RLIMIT_FSIZE / RLIMIT_NOFILE / RLIMIT_CORE 可正常设置。
  3. 超时必须杀「整个进程组」：只杀直接子进程会留下孤儿。
  4. 统计内存不能调用 ps（可能被外层沙箱拒绝），走 libproc。
  5. preexec_fn 内抛异常会毁掉整个 Popen（"Exception occurred in preexec_fn"），
     所以里面所有 setrlimit 都必须吞异常，能力探测放在子进程里预先做。

已知局限（不要当成安全边界）：
  * 没有内核级内存上限，RSS 靠采样。实测本机：
      - 渐进增长（每 20ms 申请 1MB，上限 128MB）过冲仅 0.3MB，基本精确；
      - 极端突发（~138ms 内申请 600MB，上限 64MB）会过冲到 100~230MB 才被杀。
    过冲量约等于「分配速率 × sample_ms」，调小 sample_ms 可压缩，代价是 CPU 占用。
    需要硬上限请上 Linux 的 RLIMIT_AS / cgroup，或把进程放进独立容器。
    一次极快的「分配后立刻释放」可能完全采不到。
  * 文件系统与网络默认不隔离，只靠 cwd / env / 参数策略约束。
    需要真隔离请用 use_seatbelt=True（macOS），或外层容器 / bwrap（Linux）。
  * 这是「资源与行为约束」，不是「安全沙箱」。不可信代码请放进独立容器或 VM。
"""

from __future__ import annotations

import ctypes
import ctypes.util
import math
import os
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
from typing import Mapping, Sequence

try:
    import resource as _resource
except ImportError:  # pragma: no cover - 非 POSIX
    _resource = None

__all__ = [
    "run_sandboxed",
    "seatbelt_profile",
    "group_rss_mb",
    "group_pids",
    "rlimit_support",
]

# 未加引号时会被 shell 解释的字符。命中即拒绝，
# 避免「本想走管道，却变成字面参数」这种静默的错误语义。
_SHELL_META = re.compile(r"[;&|<>`$\n\r\\]")

_DEFAULT_ENV_KEYS = ("PATH", "LANG", "LC_ALL", "TMPDIR", "TZ")

_RUSAGE_INFO_V2 = 2
_PROC_PIDTBSDINFO = 3
_PBI_PGID_OFFSET = 100  # struct proc_bsdinfo 中 pbi_pgid 的偏移，已实测确认

_RLIMIT_CANDIDATES = (
    "RLIMIT_CPU",
    "RLIMIT_FSIZE",
    "RLIMIT_NOFILE",
    "RLIMIT_NPROC",
    "RLIMIT_CORE",
    "RLIMIT_AS",
    "RLIMIT_DATA",
)


class _Rejected(Exception):
    """命令未通过静态策略检查。"""


# --------------------------------------------------------------------------
# 0. rlimit 名称映射
# --------------------------------------------------------------------------

_RLIMIT_BY_NAME: dict = {}
if _resource is not None:
    for _name in _RLIMIT_CANDIDATES:
        _lim = getattr(_resource, _name, None)
        if _lim is not None:
            _RLIMIT_BY_NAME[_name] = _lim


def _limit_value(name: str):
    return _RLIMIT_BY_NAME.get(name)


# --------------------------------------------------------------------------
# 1. 平台能力探测（结果缓存）
# --------------------------------------------------------------------------

_rlimit_support: dict | None = None

# 每个 limit 用「有限且确有约束力」的试探值，并回读确认。
# 关键教训：早先版本用 RLIM_INFINITY 试探，而把 limit 设成无穷大等于什么都没设，
# 于是一律返回成功 —— macOS 上明明返回 EINVAL 的 RLIMIT_AS 被误判成「支持」，
# 内存限制看起来生效了，实际完全没有。
_PROBE_VALUES = {
    "RLIMIT_CORE": 0,
    "RLIMIT_NOFILE": 256,
    "RLIMIT_FSIZE": 1 << 20,
    "RLIMIT_DATA": 64 << 20,
    "RLIMIT_AS": 64 << 20,
    "RLIMIT_NPROC": 64,
    "RLIMIT_CPU": 5,
}

# 每个 limit 单独起一个进程探测：RLIMIT_AS 一旦生效，子进程可能连 print 都做不了，
# 塞在同一个进程里会连带污染其他 limit 的结论。
_PROBE_SRC = r"""
import resource, sys
name, value = sys.argv[1], int(sys.argv[2])
lim = getattr(resource, name, None)
if lim is None:
    print("0"); raise SystemExit
try:
    resource.setrlimit(lim, (value, value))
    ok = resource.getrlimit(lim)[0] == value   # 回读确认，而不是「没抛异常就算成功」
except Exception:
    ok = False
print("1" if ok else "0")
"""


def rlimit_support(refresh: bool = False) -> dict:
    """
    探测本机支持哪些 rlimit，结果缓存。

    在独立子进程里探测，而不是在 preexec_fn 里试错：后者一旦抛异常，
    整个 Popen 调用就废了，而且拿不到任何诊断信息。
    探测失败一律按「不支持」处理（保守），此时内存限制只剩 RSS 看门狗。
    """
    global _rlimit_support
    if _rlimit_support is not None and not refresh:
        return _rlimit_support

    support = {}
    for name in _RLIMIT_CANDIDATES:
        value = _PROBE_VALUES.get(name, 1 << 20)
        ok = False
        try:
            proc = subprocess.run(
                [sys.executable, "-c", _PROBE_SRC, name, str(value)],
                capture_output=True,
                text=True,
                timeout=10,
            )
            ok = proc.stdout.strip() == "1"
        except Exception:
            ok = False
        support[name] = ok

    _rlimit_support = support
    return support


# --------------------------------------------------------------------------
# 2. 进程组枚举 + RSS（macOS 走 libproc，Linux 走 /proc）
# --------------------------------------------------------------------------

class _RUsageInfoV2(ctypes.Structure):
    """
    struct rusage_info_v2 的完整镜像。

    必须按内核真实大小定义：proc_pid_rusage 会把整个结构体写进来（160 字节），
    如果只定义前几个字段，内核就越界写穿缓冲区，随后在别处
    （实测是在 group_pids 里）以段错误的形式炸掉，极难定位。
    末尾留余量，以防将来结构体变长。
    """
    _fields_ = [
        ("ri_uuid", ctypes.c_uint8 * 16),  # 16 字节，后续 uint64 从偏移 16 开始
        ("ri_user_time", ctypes.c_uint64),
        ("ri_system_time", ctypes.c_uint64),
        ("ri_pkg_idle_wkups", ctypes.c_uint64),
        ("ri_interrupt_wkups", ctypes.c_uint64),
        ("ri_pageins", ctypes.c_uint64),
        ("ri_wired_size", ctypes.c_uint64),
        ("ri_resident_size", ctypes.c_uint64),
        ("ri_phys_footprint", ctypes.c_uint64),
        ("ri_proc_start_abstime", ctypes.c_uint64),
        ("ri_proc_exit_abstime", ctypes.c_uint64),
        ("ri_child_user_time", ctypes.c_uint64),
        ("ri_child_system_time", ctypes.c_uint64),
        ("ri_child_pkg_idle_wkups", ctypes.c_uint64),
        ("ri_child_interrupt_wkups", ctypes.c_uint64),
        ("ri_child_pageins", ctypes.c_uint64),
        ("ri_child_elapsed_abstime", ctypes.c_uint64),
        ("ri_diskio_bytesread", ctypes.c_uint64),
        ("ri_diskio_byteswritten", ctypes.c_uint64),
        ("_reserved", ctypes.c_uint64 * 8),
    ]


_libproc = None
_libproc_loaded = False


def _load_libproc():
    global _libproc, _libproc_loaded
    if _libproc_loaded:
        return _libproc
    _libproc_loaded = True
    if sys.platform != "darwin":
        return None
    try:
        path = ctypes.util.find_library("proc") or "/usr/lib/libproc.dylib"
        lib = ctypes.CDLL(path, use_errno=True)
        lib.proc_listallpids.restype = ctypes.c_int
        lib.proc_listallpids.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.proc_pidinfo.restype = ctypes.c_int
        lib.proc_pidinfo.argtypes = [
            ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int
        ]
        lib.proc_pid_rusage.restype = ctypes.c_int
        lib.proc_pid_rusage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
        _libproc = lib
    except Exception:
        _libproc = None
    return _libproc


def _pid_rss_mb(pid: int) -> float:
    lib = _load_libproc()
    if lib is not None:
        ru = _RUsageInfoV2()
        if lib.proc_pid_rusage(pid, _RUSAGE_INFO_V2, ctypes.byref(ru)) == 0:
            # phys_footprint 才是 macOS 认定的内存压力，比 resident_size 更贴近
            return ru.ri_phys_footprint / 1048576.0
        return 0.0
    try:  # Linux 回退
        with open("/proc/%d/status" % pid, "r") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024.0
    except OSError:
        pass
    return 0.0


def group_pids(pgid: int, fallback: bool = True) -> list:
    """
    列出进程组内所有存活 pid（不依赖 ps）。

    fallback=True 时枚举失败会退回「组长自己」这个保守假设；
    判断「是否还需要发信号」时请用 fallback=False，否则会误判为仍存活。
    """
    lib = _load_libproc()
    if lib is None:
        pids = []
        try:
            for entry in os.listdir("/proc"):
                if not entry.isdigit():
                    continue
                try:
                    if os.getpgid(int(entry)) == pgid:
                        pids.append(int(entry))
                except OSError:
                    continue
        except OSError:
            pass
        return pids if pids else ([pgid] if fallback else [])

    n = lib.proc_listallpids(None, 0)
    if n <= 0:
        return [pgid] if fallback else []
    buf = (ctypes.c_int * (n + 128))()
    got = lib.proc_listallpids(buf, ctypes.sizeof(buf))
    if got <= 0:
        return [pgid] if fallback else []

    info = ctypes.create_string_buffer(256)
    pids = []
    for i in range(got):
        pid = buf[i]
        if pid <= 0:
            continue
        if lib.proc_pidinfo(pid, _PROC_PIDTBSDINFO, 0, info, 256) <= 0:
            continue
        if ctypes.c_uint32.from_buffer(info, _PBI_PGID_OFFSET).value == pgid:
            pids.append(pid)
    if pids:
        return pids
    return [pgid] if fallback else []


def group_rss_mb(pgid: int) -> float:
    """整个进程组的 RSS 合计（MB）。"""
    pids = group_pids(pgid, fallback=False) or [pgid]
    return sum(_pid_rss_mb(pid) for pid in pids)


# --------------------------------------------------------------------------
# 3. 命令解析与终止
# --------------------------------------------------------------------------

def _prepare_argv(cmd, allow_shell: bool):
    if isinstance(cmd, (list, tuple)):
        if not cmd:
            raise _Rejected("空命令")
        return [str(part) for part in cmd], False

    if not isinstance(cmd, str) or not cmd.strip():
        raise _Rejected("空命令")

    if allow_shell:
        return cmd, True

    if _SHELL_META.search(cmd):
        raise _Rejected(
            "命令行含 shell 元字符（; & | < > ` $ \\ 换行）。"
            "allow_shell=False 时拒绝执行，请改用 list 形式的 argv。"
        )
    try:
        argv = shlex.split(cmd)
    except ValueError as exc:
        raise _Rejected("命令行引号不配对: %s" % exc) from exc
    if not argv:
        raise _Rejected("空命令")
    return argv, False


def _signal_group(pgid: int, sig: int) -> None:
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _terminate_group(pgid: int, grace_ms: int) -> None:
    """SIGTERM → 宽限期 → SIGKILL，全程作用于整个进程组。"""
    _signal_group(pgid, signal.SIGTERM)
    deadline = time.monotonic() + max(0, grace_ms) / 1000.0
    while time.monotonic() < deadline:
        if not group_pids(pgid, fallback=False):
            return
        time.sleep(0.02)
    _signal_group(pgid, signal.SIGKILL)


def _read_stream(stream, sink: list, cap: int, state: dict) -> None:
    """
    独立线程读管道。

    必须一直读到 EOF：一旦停止读取，子进程在管道写满后会永久阻塞，
    于是「输出太多」会表现成「莫名超时」。超过上限的内容丢弃，只留前 cap 字节。
    """
    total = 0
    try:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            if total < cap:
                keep = chunk[: cap - total]
                sink.append(keep)
                total += len(keep)
            if total >= cap:
                state["truncated"] = True
    except Exception as exc:
        state["read_error"] = str(exc)
    finally:
        try:
            stream.close()
        except Exception:
            pass


def seatbelt_profile(write_roots: Sequence[str],
                     allow_network: bool = False,
                     read_deny_roots: Sequence[str] | None = None) -> str:
    """
    生成 macOS seatbelt(sandbox-exec) profile。

    这是 macOS 上唯一能同时约束文件系统与网络的手段，但 Apple 已不推荐，
    且在被别的沙箱包住的进程里无法嵌套应用
    （报 sandbox_apply: Operation not permitted，退出码 71）。

    读权限默认是全局放开的（`allow file-read*`）—— 因为 dyld / 系统库 / 解释器
    都要读一大堆东西，改成白名单很容易让子进程连 exec 都起不来。
    要演示「读沙箱外被拒」，用 read_deny_roots 点名禁止某个子树：
        read_deny_roots=["/path/outside"]
    放在 `allow file-read*` **之后**，seatbelt 里后写的规则覆盖先写的，于是该子树被拒。
    写权限本来就不是全局放开（只有 write_roots 下的 subpath 能写），无需额外参数。
    """
    rules = [
        "(version 1)",
        "(deny default)",
        "(allow process-exec*)",
        "(allow process-fork)",
        "(allow sysctl-read)",
        "(allow mach-lookup)",
        "(allow file-read*)",  # 读权限仍全局放开；要收紧就换成精确 subpath 白名单
    ]
    for root in (read_deny_roots or ()):
        # 后写的规则优先：这一条把上面那句全局放开的读权限收回来
        rules.append('(deny file-read* (subpath "%s"))' % root)
    for root in write_roots:
        rules.append('(allow file-write* (subpath "%s"))' % root)
    rules.append(
        '(allow file-write-data (literal "/dev/null") (literal "/dev/stdout") (literal "/dev/stderr"))'
    )
    if not allow_network:
        rules.append("(deny network*)")
    return "\n".join(rules)


# --------------------------------------------------------------------------
# 4. 主入口
# --------------------------------------------------------------------------

def run_sandboxed(
    cmd,
    timeout_ms: int = 5000,
    mem_limit_mb: int = 256,
    *,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    max_output_bytes: int = 1_000_000,
    allow_shell: bool = False,
    kill_grace_ms: int = 200,
    write_root: str | None = None,
    cpu_seconds: int | None = None,
    max_file_bytes: int | None = None,
    reap_orphans: bool = True,
    use_seatbelt: bool = False,
    allow_network: bool = False,
    deny_read_roots: Sequence[str] | None = None,
    sample_ms: int = 25,
) -> dict:
    """
    在受控子进程中执行命令。

    cmd             : list[str]（推荐）或 str。str 且 allow_shell=False 时用 shlex 拆分，
                      含 shell 元字符直接拒绝。
    timeout_ms      : 墙上时钟超时，到点杀整个进程组。
    mem_limit_mb    : 进程组内存上限。macOS 走 RSS 采样终止；Linux 额外叠加 RLIMIT_AS。
    write_root      : 可写根目录；cwd 为空时同时用作工作目录。
    use_seatbelt    : macOS 上套 sandbox-exec 做真实 FS/网络隔离（不可嵌套）。
    deny_read_roots : 配合 use_seatbelt，点名**禁止读取**的子树
                      （读权限默认全局放开，要演示「读外面被拒」就靠这个）。
    reap_orphans    : 命令结束后再清扫一次进程组内的后台残留。
    """
    started = time.monotonic()

    try:
        argv, use_shell = _prepare_argv(cmd, allow_shell)
    except _Rejected as exc:
        return _result("rejected", -1, stderr=str(exc), started=started)

    if cwd is None and write_root:
        cwd = write_root
    if write_root and cwd:
        real_root = os.path.realpath(write_root)
        real_cwd = os.path.realpath(cwd)
        if real_cwd != real_root and not real_cwd.startswith(real_root + os.sep):
            return _result(
                "rejected", -1,
                stderr="cwd %s 不在 write_root %s 之内" % (real_cwd, real_root),
                started=started,
            )
    if cwd and not os.path.isdir(cwd):
        return _result("rejected", -1, stderr="cwd 不存在: %s" % cwd, started=started)

    if use_seatbelt:
        if sys.platform != "darwin":
            return _result("rejected", -1, stderr="seatbelt 仅 macOS 可用", started=started)
        profile = seatbelt_profile(
            [write_root] if write_root else [],
            allow_network,
            deny_read_roots,
        )
        if use_shell:
            argv = ["/usr/bin/sandbox-exec", "-p", profile, "/bin/sh", "-c", argv]
            use_shell = False
        else:
            argv = ["/usr/bin/sandbox-exec", "-p", profile] + list(argv)

    support = rlimit_support()
    limits_unsupported = sorted(name for name, ok in support.items() if not ok)

    # 在父进程里算好「打算施加哪些限制」：
    # 不能在 preexec_fn 里 append —— 那是 fork 出的子进程内存副本，父进程读不到。
    planned = []
    if support.get("RLIMIT_CPU"):
        planned.append("RLIMIT_CPU")
    if max_file_bytes and support.get("RLIMIT_FSIZE"):
        planned.append("RLIMIT_FSIZE")
    if support.get("RLIMIT_NOFILE"):
        planned.append("RLIMIT_NOFILE")
    if support.get("RLIMIT_CORE"):
        planned.append("RLIMIT_CORE")
    if mem_limit_mb:
        if support.get("RLIMIT_AS"):
            planned.append("RLIMIT_AS")
        elif support.get("RLIMIT_DATA"):
            planned.append("RLIMIT_DATA")

    timeout_s = max(0.001, timeout_ms / 1000.0)
    if cpu_seconds is None:
        # 墙钟之外再压一道 CPU 时间硬闸：即使看门狗线程卡住，死循环也会被内核收掉
        cpu_seconds = int(math.ceil(timeout_s * 3)) + 1

    def _preexec():
        # 这里绝不能抛异常，否则整个 Popen 直接失败
        _try_set("RLIMIT_CPU", cpu_seconds)
        _try_set("RLIMIT_CORE", 0)
        if max_file_bytes:
            _try_set("RLIMIT_FSIZE", max_file_bytes)
        if support.get("RLIMIT_NOFILE"):
            _try_set("RLIMIT_NOFILE", 256)
        if mem_limit_mb:
            if support.get("RLIMIT_AS"):
                _try_set("RLIMIT_AS", mem_limit_mb * 1024 * 1024)
            elif support.get("RLIMIT_DATA"):
                _try_set("RLIMIT_DATA", mem_limit_mb * 1024 * 1024)

    try:
        proc = subprocess.Popen(
            argv,
            shell=use_shell,
            cwd=cwd,
            env=_build_env(env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,  # 关键：自成进程组，才能整组清理
            preexec_fn=_preexec,
            close_fds=True,
        )
    except FileNotFoundError as exc:
        return _result("error", 127, stderr=str(exc), started=started,
                       extra={"limits_unavailable": limits_unsupported})
    except OSError as exc:
        return _result("error", -1, stderr=str(exc), started=started,
                       extra={"limits_unavailable": limits_unsupported})

    # setsid 之后子进程自己就是组长，pgid == pid
    pgid = proc.pid

    out_chunks: list = []
    err_chunks: list = []
    state: dict = {"truncated": False}
    readers = [
        threading.Thread(target=_read_stream,
                         args=(proc.stdout, out_chunks, max_output_bytes, state), daemon=True),
        threading.Thread(target=_read_stream,
                         args=(proc.stderr, err_chunks, max_output_bytes, state), daemon=True),
    ]
    for thread in readers:
        thread.start()

    deadline = started + timeout_s
    # 全系统枚举 pid 逐个查 pgid 不便宜（本机约 900 个进程），
    # 所以「全组求和」降频，「直接子进程」每次循环都读（单次 syscall，很便宜）。
    mem_interval = max(sample_ms * 4, 100) / 1000.0
    last_mem_sample = 0.0
    peak_rss = _pid_rss_mb(pgid)
    killed_by = None
    orphans_reaped = False

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            killed_by = "timeout"
            _terminate_group(pgid, kill_grace_ms)
            break
        try:
            proc.wait(timeout=min(sample_ms / 1000.0, remaining))
            break
        except subprocess.TimeoutExpired:
            pass

        rss = _pid_rss_mb(pgid)
        if rss > peak_rss:
            peak_rss = rss
        # 关键：每一轮都要判一次，不能只在低频的全组采样分支里判。
        # 否则快速分配会在两次全组采样之间冲过去，实测能冲到上限的 10 倍才被杀。
        if mem_limit_mb and rss > mem_limit_mb:
            killed_by = "oom"
            _terminate_group(pgid, kill_grace_ms)
            break
        if mem_limit_mb:
            now = time.monotonic()
            if (now - last_mem_sample) >= mem_interval:
                last_mem_sample = now
                total = group_rss_mb(pgid)
                if total > peak_rss:
                    peak_rss = total
                if total > mem_limit_mb:
                    killed_by = "oom"
                    _terminate_group(pgid, kill_grace_ms)
                    break

    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _signal_group(pgid, signal.SIGKILL)
        proc.wait(timeout=5)

    if reap_orphans:
        # 命令本体可能已退出，却把活留在了后台（如 sh -c "daemon &"）
        leftovers = [pid for pid in group_pids(pgid, fallback=False) if pid != proc.pid]
        if leftovers:
            _signal_group(pgid, signal.SIGKILL)
            orphans_reaped = True

    for thread in readers:
        thread.join(timeout=2)

    stdout = b"".join(out_chunks).decode("utf-8", errors="replace")
    stderr = b"".join(err_chunks).decode("utf-8", errors="replace")
    exit_code = proc.returncode if proc.returncode is not None else -1

    if killed_by == "timeout":
        status, exit_code = "timeout", -1
    elif killed_by == "oom":
        status, exit_code = "oom", -1
    else:
        status = "ok" if exit_code == 0 else "error"

    if state["truncated"]:
        stdout += "\n[输出超过 %d 字节，已截断]" % max_output_bytes

    return _result(
        status, exit_code, stdout=stdout, stderr=stderr, started=started,
        extra={
            "truncated": bool(state["truncated"]),
            "memory_peak_mb": round(peak_rss, 1),
            "killed_by": killed_by,
            "limits_enforced": sorted(set(planned)),
            "limits_unavailable": limits_unsupported,
            "pgid": pgid,
            "orphans_reaped": orphans_reaped,
        },
    )


# --------------------------------------------------------------------------
# 5. 小工具
# --------------------------------------------------------------------------

def _build_env(env: Mapping[str, str] | None) -> dict:
    if env is not None:
        return {str(k): str(v) for k, v in env.items()}
    base = {key: os.environ[key] for key in _DEFAULT_ENV_KEYS if key in os.environ}
    base.setdefault("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
    base.setdefault("LC_ALL", "C.UTF-8")
    return base


def _try_set(name: str, value: int) -> None:
    """preexec_fn 专用：任何失败都必须吞掉，否则 Popen 直接报错。"""
    limit = _limit_value(name)
    if limit is None or _resource is None:
        return
    try:
        _resource.setrlimit(limit, (value, value))
    except Exception:
        pass


def _result(status: str, exit_code: int, stdout: str = "", stderr: str = "",
            started: float | None = None, extra: dict | None = None) -> dict:
    res = {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "status": status,
        "truncated": False,
        "memory_peak_mb": 0.0,
        "killed_by": None,
        "limits_enforced": [],
        "limits_unavailable": [],
        "duration_ms": int((time.monotonic() - started) * 1000) if started else 0,
    }
    if extra:
        res.update(extra)
    return res


if __name__ == "__main__":
    print("rlimit 支持情况:", rlimit_support())
    print(run_sandboxed("echo hello"))
    print(run_sandboxed(["echo", "argv 形式"]))
    print(run_sandboxed(["sleep", "10"], timeout_ms=800))
    print(run_sandboxed("echo hi; touch /tmp/pwned", timeout_ms=1000))
