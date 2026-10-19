# Qwen Server Desktop

把 `~/.local/bin/qwen-server` 那套命令行操作，收进一个能双击打开的窗口。

**零第三方依赖** —— 只用 Python 标准库（tkinter），不需要 `pip install` 任何东西。

---

## 它做了什么

原来你得敲 `qwen-server all`，还得记着 `MODELS_MAX=2`、`CTX=65536` 这些环境变量。
现在打开窗口，点「启动服务」就完事：

| 能力 | 说明 |
|---|---|
| 一键启停 | 启动 / 停止 llama-server，含优雅退出与超时强杀 |
| 双模式 | **Router**（多模型按需加载，省内存）/ **单模型**（启动更快） |
| 模型配置 | 自动扫描模型目录，识别别名并填入推荐上下文 |
| 参数配置 | 端口、上下文、GPU 层数、驻留上限、KV 缓存、Flash Attention、Jinja |
| 状态监视 | 指示灯 + PID + 端口 + 就绪进度 |
| 实时日志 | 子进程输出逐行回显，带级别着色，同时落盘 |
| **强制终止** | **按端口定位并结束进程（3098 qwen-server / 10100 opencodex）** |
| 跨平台 | macOS / Windows / Linux 外观一致 |

界面里的参数**和原脚本逐字对齐**，不会出现"界面上能跑、终端里跑不起来"。

---

## 快速开始

### 前置条件

只需要 **Python 3.8+**（自带 tkinter 即可，官方安装包默认包含）。

### macOS

```bash
cd qwen-desktop
./launchers/make_macos_app.sh --install
```

生成 `Qwen Server.app` 并装到「应用程序」文件夹，之后在启动台双击即可。
（去掉 `--install` 就只在当前目录生成，不装到系统里。）

不想打包也可以直接跑：

```bash
./launchers/launch.sh
```

### Windows

双击 `launchers\launch.bat`。

想放到桌面，右键 `launch.bat` → 发送到 → 桌面快捷方式，再在属性里把图标改掉。

### Linux

```bash
./launchers/install_linux.sh
```

会往 `~/.local/share/applications` 写菜单项，之后在应用菜单里搜 "Qwen" 就能找到。

---

## 手动终止进程

端口被别的进程占着不放手时，有两个入口可以处理。

### 界面里

窗口底部的**「强制终止」**面板会实时显示两个端口的占用情况：

```
3098    qwen-server    PID 39227 llama-server      [终止]
10100   opencodex      PID 32253 ocx               [终止]
```

点「终止」会先弹确认框列出将杀的 PID 和进程名，确认后执行。
先发 `SIGTERM` 让进程自己收拾，6 秒不响应才升级为 `SIGKILL`。

> ⚠️ 10100 是 OpenCodex 的代理进程。终止后 OpenCodex.app 会断开连接，
> 需要恢复的话在应用里重新启动即可。

### 命令行里

```bash
./launchers/kill-port.sh 3098              # 优雅终止占用 3098 的进程
./launchers/kill-port.sh 10100 -f -y       # 强杀 10100，不询问
./launchers/kill-port.sh --all             # 依次处理 3098 与 10100
./launchers/kill-port.sh 3098 --list       # 只看谁占着，不动手
```

| 选项 | 作用 |
|---|---|
| `-f, --force` | 跳过优雅等待，直接强杀 |
| `-y, --yes` | 不询问，直接执行（非交互环境必须加） |
| `-l, --list` | 只列出占用情况 |
| `-h, --help` | 显示帮助 |

脚本内部按 `lsof` → `fuser` → `ss` → `netstat`（Windows）的顺序探测，
哪个可用用哪个，不依赖 `ps`。

### 判定标准

终止是否成功，**以端口是否释放为准**，而不是看进程能不能被探测到。

这个区别很实际：进程退出后如果父进程还没回收，会短暂处于僵尸态，
此时 `kill -0` 依然返回成功。按 PID 判定会误报"仍在运行"，
实际端口早就空了。

---

## 配置文件

首次启动自动生成，路径按平台约定：

| 平台 | 位置 |
|---|---|
| macOS | `~/Library/Application Support/qwen-desktop/config.json` |
| Windows | `%APPDATA%\qwen-desktop\config.json` |
| Linux | `~/.config/qwen-desktop/config.json` |

日志文件在各自的 `logs/` 目录下（macOS 是 `~/Library/Logs/qwen-desktop/server.log`）。

---

## 打包成完全不依赖 Python 的程序

上面几种方式都要求机器上有 Python。如果要发给没有 Python 的人用：

```bash
./launchers/build_standalone.sh
```

用 PyInstaller 打成 `dist/Qwen Server.app`（Windows 是 `.exe`）。

> ⚠️ PyInstaller **不能交叉编译**：在 Mac 上只能打出 Mac 版，
> 要 Windows 版就得在 Windows 上跑一次这个脚本。

---

## 目录结构

```
qwen-desktop/
├── qwen_desktop.py            主程序（界面 + 事件循环）
├── selftest.py                无头自检，不开界面即可验证核心逻辑
├── qwencore/
│   ├── paths.py               跨平台路径解析、llama-server 探测
│   ├── models.py              模型扫描与别名表
│   ├── config.py              配置持久化
│   ├── server.py              进程管理、参数构建、健康探测
│   └── theme.py               配色与 ttk 样式
└── launchers/
    ├── launch.sh              macOS / Linux 通用启动器
    ├── launch.bat             Windows 启动器
    ├── kill-port.sh           按端口终止进程（命令行版）
    ├── make_macos_app.sh      生成 macOS .app
    ├── install_linux.sh       安装 Linux 菜单项
    ├── build_standalone.sh    PyInstaller 打包
    └── gen_icon.py            图标生成（纯标准库手写 PNG）
```

想验证核心逻辑有没有问题，跑这个就行（不弹窗）：

```bash
python3 selftest.py
```

---

## 排查

**「找不到带 tkinter 的 Python」**
Linux 上多半要单独装：`sudo apt install python3-tk`（Debian/Ubuntu）或
`sudo dnf install python3-tkinter`（Fedora）。macOS 建议用 python.org 的安装包。

**状态显示「端口已被占用」**
说明 3098 上已经有别的 llama-server 在跑。程序**不会**去抢或接管它，
换个端口，或者先把原来那个停掉。

**健康检查一直不过**
模型太大、显存不够时会卡在加载阶段。看下方日志最后几行，
通常会明确写出 `failed to allocate` 之类的信息。

**界面里改了模型目录，列表没更新**
改完目录按回车或点一下别处让输入框失焦，再重新打开下拉框。

---

## 设计上的几个取舍

- **用 clam 主题而不是各平台原生主题**：跨平台软件最怕"在 Mac 上长这样、
  到 Windows 上认不出来"，统一主题保证三端一致。
- **不用 Electron**：为了"独立运行"这四个字，200MB 的运行时和一堆
  依赖不值得，tkinter 是标准库自带。
- **探测本机服务时强制绕过 HTTP 代理**：本机环境常挂着 `HTTP_PROXY`，
  不绕开的话访问 `127.0.0.1` 会被代理劫持返回 502，误判成"服务未就绪"。
- **启动脚本硬编码 Python 候选路径**：从 Finder 双击时 PATH 只有
  `/usr/bin:/bin`，靠 `which python3` 找不到用户自己装的 Python。
