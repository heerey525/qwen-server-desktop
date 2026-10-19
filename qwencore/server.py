"""llama-server 进程管理：参数构建、启停、健康探测与日志采集。

行为严格对齐 ~/.local/bin/qwen-server，保证图形界面与命令行产出的
命令行参数一致，不会出现"界面上能跑、终端里跑不起来"的分裂。
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from enum import Enum
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from . import paths
from .models import ModelInfo

# 日志文件超过该体积即截断，避免无限增长
LOG_ROTATE_BYTES = 4 * 1024 * 1024


class ServerState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


STATE_TEXT = {
    ServerState.STOPPED: "已停止",
    ServerState.STARTING: "启动中…",
    ServerState.RUNNING: "运行中",
    ServerState.STOPPING: "停止中…",
    ServerState.ERROR: "异常退出",
}


# ── 参数构建 ────────────────────────────────────────────────────────

def build_command(cfg, model: Optional[ModelInfo] = None) -> List[str]:
    """把配置翻译成 llama-server 的完整命令行。

    router 模式不传 -m/--alias，模型名由 llama-server 从文件名自动生成；
    单模型模式则显式传 -m 与 --alias。
    """
    exe = cfg.llama_server
    if not exe:
        raise ValueError("尚未指定 llama-server 可执行文件路径")

    argv: List[str] = [exe]

    if cfg.mode == "router":
        argv += ["--models-dir", cfg.models_dir, "--models-max", str(cfg.models_max)]
    else:
        if model is None:
            raise ValueError("单模型模式必须先在列表里选择一个模型")
        if model.api_name:
            api_name = model.api_name
        elif model.filename.endswith(".gguf"):
            api_name = model.filename[:-5]
        else:
            api_name = model.filename
        argv += ["-m", str(model.path), "--alias", api_name]

    argv += ["-c", str(cfg.ctx), "-ngl", str(cfg.ngl)]

    if cfg.use_flash_attn:
        argv += ["-fa", "on"]

    if cfg.kv_cache_type:
        argv += ["--cache-type-k", cfg.kv_cache_type, "--cache-type-v", cfg.kv_cache_type]

    # 脚本里只有单模型模式显式传 -np
    if cfg.mode != "router":
        argv += ["-np", str(cfg.parallel)]

    argv += ["--host", cfg.host, "--port", str(cfg.port)]

    if cfg.use_jinja:
        argv += ["--jinja"]

    if model is not None and model.mmproj:
        argv += ["--mmproj", str(model.mmproj)]

    if cfg.mcp_config and Path(cfg.mcp_config).expanduser().is_file():
        argv += ["--mcp-servers-config", str(Path(cfg.mcp_config).expanduser())]

    argv += cfg.extra_arg_list()
    return argv


def preview_command(argv: List[str]) -> str:
    """把 argv 拼成一行可读文本（供界面展示）。"""
    out = []
    for a in argv:
        out.append('"%s"' % a if (" " in a or not a) else a)
    return " ".join(out)


# ── 端口 / 健康探测 ─────────────────────────────────────────────────

def _no_proxy_opener():
    """显式禁用代理。

    本机环境常挂着 HTTP_PROXY，若不绕开，访问 127.0.0.1 会被代理劫持，
    返回 502 并被误判成"服务未就绪"。
    """
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def is_port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def is_healthy(host: str, port: int, timeout: float = 1.5) -> bool:
    """探测 llama-server 的 /health 端点。"""
    url = "http://%s:%d/health" % (host, port)
    try:
        with _no_proxy_opener().open(url, timeout=timeout) as resp:
            return 200 <= getattr(resp, "status", resp.getcode()) < 300
    except Exception:
        return False


def probe_running(host: str, port: int) -> bool:
    """判断端口上是否已有 llama-server 在跑（可能是别处启动的）。"""
    if is_port_free(host, port):
        return False
    return is_healthy(host, port)


def list_served_models(host: str, port: int, timeout: float = 3.0) -> List[str]:
    """读取 /v1/models 里的模型 id，用于界面展示。"""
    url = "http://%s:%d/v1/models" % (host, port)
    try:
        with _no_proxy_opener().open(url, timeout=timeout) as resp:
            import json
            data = json.loads(resp.read().decode("utf-8", "replace"))
        return [m.get("id", "?") for m in data.get("data", [])]
    except Exception:
        return []


# ── 进程封装 ────────────────────────────────────────────────────────

class ServerProcess:
    """一个 llama-server 子进程的生命周期管理。"""

    def __init__(
        self,
        on_log: Optional[Callable[[str], None]] = None,
        on_state: Optional[Callable[[ServerState], None]] = None,
    ) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._on_log = on_log
        self._on_state = on_state
        self._state = ServerState.STOPPED
        self._lock = threading.Lock()
        self._stopping = False
        self._reader: Optional[threading.Thread] = None
        self._log_path = paths.default_log_dir() / "server.log"
        self.argv: List[str] = []

    # ── 状态 ────────────────────────────────────────────────────

    @property
    def state(self) -> ServerState:
        return self._state

    def _set_state(self, state: ServerState) -> None:
        if state == self._state:
            return
        self._state = state
        if self._on_state:
            try:
                self._on_state(state)
            except Exception:
                pass

    @property
    def pid(self) -> Optional[int]:
        return self._proc.pid if self._proc else None

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def returncode(self) -> Optional[int]:
        return self._proc.returncode if self._proc else None

    # ── 日志 ────────────────────────────────────────────────────

    def _emit(self, line: str) -> None:
        if self._on_log:
            try:
                self._on_log(line)
            except Exception:
                pass

    def _append_file(self, line: str) -> None:
        try:
            paths.ensure_dir(self._log_path.parent)
            if self._log_path.is_file() and self._log_path.stat().st_size > LOG_ROTATE_BYTES:
                self._log_path.write_text("", encoding="utf-8")
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write("[%s] %s\n" % (stamp, line))
        except OSError:
            pass

    @property
    def log_path(self) -> Path:
        return self._log_path

    # ── 启动 ────────────────────────────────────────────────────

    def start(self, argv: List[str]) -> None:
        if self.is_running():
            raise RuntimeError("服务已在运行")

        self.argv = list(argv)
        exe = Path(argv[0]).expanduser()
        cwd = exe.resolve().parent if exe.exists() else None

        env = os.environ.copy()
        # 让子进程的输出立即刷出，避免日志卡在缓冲区
        env.setdefault("PYTHONUNBUFFERED", "1")

        popen_kwargs = dict(
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=str(cwd) if cwd else None,
            env=env,
            bufsize=1,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        if paths.is_windows():
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            popen_kwargs["start_new_session"] = True  # 独立进程组，便于整组收尸

        self._stopping = False
        self._set_state(ServerState.STARTING)
        self._emit("$ %s" % preview_command(argv))

        try:
            self._proc = subprocess.Popen(argv, **popen_kwargs)
        except OSError as exc:
            self._set_state(ServerState.ERROR)
            self._emit("启动失败: %s" % exc)
            raise

        self._reader = threading.Thread(target=self._pump, name="llama-log", daemon=True)
        self._reader.start()

    def _pump(self) -> None:
        """后台线程：逐行读取子进程输出。"""
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for line in iter(proc.stdout.readline, ""):
                text = line.rstrip("\r\n")
                self._append_file(text)
                self._emit(text)
        except (ValueError, OSError):
            pass
        finally:
            try:
                proc.stdout.close()
            except Exception:
                pass
            code = proc.wait()
            if self._stopping:
                self._set_state(ServerState.STOPPED)
                self._emit("—— 服务已停止（退出码 %s）——" % code)
            elif code == 0:
                self._set_state(ServerState.STOPPED)
                self._emit("—— 进程正常退出 ——")
            else:
                self._set_state(ServerState.ERROR)
                self._emit("—— 进程异常退出，退出码 %s ——" % code)

    # ── 停止 ────────────────────────────────────────────────────

    def stop(self, timeout: float = 12.0) -> bool:
        """优雅停止；超时则强杀。返回是否确认已退出。"""
        with self._lock:
            proc = self._proc
            if proc is None or proc.poll() is not None:
                self._proc = None
                self._set_state(ServerState.STOPPED)
                return True

            self._stopping = True
            self._set_state(ServerState.STOPPING)
            self._emit("正在停止服务（PID %s）…" % proc.pid)

            try:
                if paths.is_windows():
                    proc.terminate()
                else:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    except (ProcessLookupError, PermissionError, OSError):
                        proc.terminate()
            except Exception:
                pass

            deadline = time.time() + timeout
            while time.time() < deadline:
                if proc.poll() is not None:
                    break
                time.sleep(0.15)

            if proc.poll() is None:
                self._emit("优雅停止超时，强制结束进程")
                try:
                    if paths.is_windows():
                        proc.kill()
                    else:
                        try:
                            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                        except (ProcessLookupError, PermissionError, OSError):
                            proc.kill()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._emit("⚠ 进程仍未退出，可能需要手动处理")
                    self._proc = None
                    self._set_state(ServerState.ERROR)
                    return False

            self._proc = None
            self._set_state(ServerState.STOPPED)
            return True

    def wait_ready(self, host: str, port: int, timeout: float = 120.0) -> bool:
        """等待 /health 就绪。模型加载慢时可能需要数十秒。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.is_running():
                return False
            if is_healthy(host, port, timeout=1.5):
                self._set_state(ServerState.RUNNING)
                return True
            time.sleep(0.5)
        return False


# ── 按端口定位并终止进程 ────────────────────────────────────────────
#
# 用于"端口被别的进程占着不放手"的场景：先按端口查出 PID，
# 解析出进程名让用户确认，再优雅终止、超时强杀。


def _probe_via_lsof(port: int) -> List[Tuple[int, str]]:
    """lsof 是 macOS / 多数 Linux 上最可靠的途径。

    用 `-F pc` 取机器可读输出（p=PID，c=命令名），既省掉解析表格，
    又能顺带拿到进程名 —— 不必再调 ps（受限环境里 ps 会被拦下）。
    """
    try:
        result = subprocess.run(
            ["lsof", "-nP", "-iTCP:%d" % port, "-sTCP:LISTEN", "-F", "pc"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return []

    entries: List[Tuple[int, str]] = []
    pending: Optional[int] = None
    for line in (result.stdout or "").splitlines():
        if not line:
            continue
        tag, value = line[0], line[1:]
        if tag == "p" and value.isdigit():
            pending = int(value)
        elif tag == "c" and pending is not None:
            entries.append((pending, value))
            pending = None
    return entries


def _probe_via_fuser(port: int) -> List[Tuple[int, str]]:
    """lsof 缺席时的兜底（部分精简 Linux 发行版）。"""
    try:
        result = subprocess.run(
            ["fuser", "-n", "tcp", str(port)],
            capture_output=True, text=True, timeout=10,
        )
        # fuser 把结果写到 stderr，形如 "3098/tcp:  1234 5678"
        blob = (result.stdout or "") + " " + (result.stderr or "")
        tail = blob.split(":", 1)[1] if ":" in blob else blob
        pids = sorted({int(x) for x in tail.split() if x.strip().isdigit()})
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return []
    return [(pid, process_name(pid)) for pid in pids]


def _probe_via_ss(port: int) -> List[Tuple[int, str]]:
    """再退一步：ss + /proc（仅 Linux）。"""
    pids: List[int] = []
    try:
        import re
        result = subprocess.run(
            ["ss", "-lptnH", "sport = :%d" % port],
            capture_output=True, text=True, timeout=10,
        )
        for match in re.finditer(r"pid=(\d+)", result.stdout or ""):
            pids.append(int(match.group(1)))
    except (OSError, subprocess.SubprocessError):
        pass
    return [(pid, process_name(pid)) for pid in sorted(set(pids))]


def _probe_via_netstat_windows(port: int) -> List[Tuple[int, str]]:
    pids: List[int] = []
    try:
        result = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True, text=True, timeout=15,
        )
        for line in (result.stdout or "").splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            proto, local, state, pid = parts[0], parts[1], parts[3], parts[4]
            if not proto.upper().startswith("TCP"):
                continue
            if not local.endswith(":%d" % port):
                continue
            if state.upper() not in ("LISTENING", "LISTEN"):
                continue
            if pid.isdigit():
                pids.append(int(pid))
    except (OSError, subprocess.SubprocessError):
        pass
    return [(pid, process_name(pid)) for pid in sorted(set(pids))]


def _probe_port(port: int) -> List[Tuple[int, str]]:
    """返回占用该端口的 [(pid, 进程名)]，多路探测、逐个兜底。"""
    if paths.is_windows():
        return _probe_via_netstat_windows(port)
    for probe in (_probe_via_lsof, _probe_via_fuser, _probe_via_ss):
        rows = probe(port)
        if rows:
            return rows
    return []


def process_name(pid: int) -> str:
    """取进程名，取不到就返回占位符。"""
    if pid <= 0:
        return "—"
    try:
        if paths.is_windows():
            result = subprocess.run(
                ["tasklist", "/FI", "PID eq %d" % pid, "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=10,
            )
            first = (result.stdout or "").strip().splitlines()
            if first and "," in first[0]:
                return first[0].split(",")[0].strip('"')
        else:
            result = subprocess.run(
                ["/bin/ps", "-p", str(pid), "-o", "comm="],
                capture_output=True, text=True, timeout=10,
            )
            name = (result.stdout or "").strip()
            if name:
                return os.path.basename(name)
    except (OSError, subprocess.SubprocessError):
        pass
    return "未知进程"


def find_port_pids(port: int) -> List[int]:
    """列出正在监听指定端口的进程 PID（跨平台，多路兜底）。"""
    return sorted({pid for pid, _ in _probe_port(port)})


def describe_port(port: int) -> List[Tuple[int, str]]:
    """返回 [(pid, 进程名), ...]，供界面或脚本展示后再决定是否终止。"""
    return _probe_port(port)


def _signal_pids(pids, force: bool) -> None:
    for pid in pids:
        if force:
            _force_kill(pid)
        else:
            _terminate(pid)


def kill_pids(pids, force: bool = False, timeout: float = 6.0) -> Tuple[List[int], List[int]]:
    """按 PID 终止进程。

    返回 (已结束的 PID, 仍存活的 PID)。
    force=False 时先发 SIGTERM 等它自己退，超时才升级为强杀。
    """
    targets = [int(p) for p in pids if int(p) > 0]
    if not targets:
        return [], []

    _signal_pids(targets, force)

    deadline = time.time() + timeout
    while time.time() < deadline:
        if not any(_is_alive(pid) for pid in targets):
            break
        time.sleep(0.15)

    # 还没走的，强杀
    for pid in targets:
        if _is_alive(pid):
            _force_kill(pid)
    time.sleep(0.3)

    dead = [pid for pid in targets if not _is_alive(pid)]
    alive = [pid for pid in targets if _is_alive(pid)]
    return dead, alive


def kill_port(port: int, force: bool = False, timeout: float = 6.0) -> Tuple[List[int], List[int]]:
    """按端口定位并终止监听进程。返回 (已结束, 仍存活)。

    判据用「端口是否已释放」而不是「进程是否还能被 kill 探测到」：
    进程退出后若父进程尚未回收，会短暂处于僵尸态，此时 os.kill(pid, 0)
    仍然成功，直接按 PID 判定会误报「仍在运行」。
    """
    pids = find_port_pids(port)
    if not pids:
        return [], []

    _signal_pids(pids, force)

    deadline = time.time() + timeout
    while time.time() < deadline:
        if not find_port_pids(port):
            break
        time.sleep(0.15)

    still = find_port_pids(port)
    if still:
        # 没松手的升级强杀
        _signal_pids(still, True)
        deadline = time.time() + 4.0
        while time.time() < deadline:
            if not find_port_pids(port):
                break
            time.sleep(0.15)
        still = find_port_pids(port)

    finished = [pid for pid in pids if pid not in still]
    return finished, sorted(still)


def _is_alive(pid: int) -> bool:
    if paths.is_windows():
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "PID eq %d" % pid, "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=8,
            )
            return str(pid) in (result.stdout or "")
        except (OSError, subprocess.SubprocessError):
            return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True      # 存在但不归我们管
    except OSError:
        return False


def _terminate(pid: int) -> None:
    if paths.is_windows():
        try:
            subprocess.run(["taskkill", "/PID", str(pid)],
                           capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _force_kill(pid: int) -> None:
    if paths.is_windows():
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"],
                           capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass
