# GoAI Ultra · 围棋人机对战（Windows / macOS）

开箱即用的围棋人机对战程序：**你执黑先行，AI 执白应手**，鼠标点交叉点就能下。
程序通过 **GTP 协议**直接驱动官方 [KataGo](https://github.com/lightvector/KataGo) 引擎，
不依赖任何第三方 Python 库（只用标准库 + tkinter）；引擎与神经网络权重都已打包在内，
**下载解压即可开局**。

## 一、下载哪个文件夹

| 你的电脑 | 进这个目录 | 自带引擎 | 双击这个文件 |
| --- | --- | --- | --- |
| Windows 10 / 11（64 位）| [`windows/`](windows) | `katago.exe` + 13 个运行库 DLL（AVX2）| `一键开始下棋.bat` |
| macOS（Apple 芯片）| [`macos/`](macos) | 原生 arm64 引擎 | `一键开始下棋.command` |
| 其它（Linux / Intel Mac）| 任选一个目录 | 首次运行自动下载或编译本机版本 | 见该目录的 使用说明.md |

> 在 GitHub 上可以只下载你需要的那个目录（也可以点 *Code → Download ZIP* 下整个仓库）。

## 二、三步开始

### Windows

1. 安装 **Python 3.9+**：<https://www.python.org/downloads/> ，安装时务必勾选 **Add Python to PATH**
2. 双击 **`windows/一键开始下棋.bat`**（若中文名显示乱码，就用 `START-Windows.bat`）
3. 出现棋盘即可下棋 —— 你执黑先行，AI 自动应手

### macOS

1. 安装 python.org 版 **Python 3.9+**（自带 tkinter）
2. 双击 **`macos/一键开始下棋.command`**
   （若提示"无法打开"：右键 → 打开 → 打开；中文名乱码时用 `START-macOS.command`）
3. 出现棋盘即可下棋

## 三、功能

- 你执黑先行，AI 执白自动应手，鼠标左键点交叉点落子（绿色虚线框为预览）
- 停一手、悔棋（撤销一个回合）、认输、形势判断、地盘估算
- 运行时调整 **AI 强度**（每手访问次数）与 **棋盘大小**（9 / 13 / 19 路）
- **完整版界面**（`play.py`，双击 `完整版界面.bat` / `完整版界面.command`）额外提供：
  让子 2–9 子、贴目设置、实时胜率条、AI 目差与推荐变化图（PV）、
  **导出 SGF 棋谱**（可用 Sabaki / Lizzie / KaTrain 复盘）、引擎日志面板
- 引擎崩溃自动重启、缺少组件时弹窗指引、跨平台一键安装/修复脚本
- 坐标遵循国际惯例：列 `A B C D E F G H J K …`（**跳过字母 I**），行从下往上数

## 四、AI 强度对照

| 强度（每手访问次数）| 19 路每手耗时 | 9 路每手耗时 | 大致水平 |
| --- | --- | --- | --- |
| 100 | 约 0.35 秒 | 约 0.12 秒 | 入门 ~ 10 级 |
| 400（默认）| 约 1.3 秒 | 约 0.5 秒 | 5 级左右 |
| 1200 | 约 4 秒 | 约 1.5 秒 | 1 段左右 |
| 4000 | 约 13 秒 | 约 5 秒 | 更强，CPU 上偏慢 |

> 机器不同速度会有差异，可用 `python3 tools/benchmark.py` 测出本机的最佳设置。

## 五、目录结构

```
GoAI Ultra/
├── README.md                 本文件
├── LICENSE                   MIT 许可
├── windows/                  Windows 版（自带 katago.exe + 运行库 DLL + 权重）
│   ├── 一键开始下棋.bat       主入口（双击开始）
│   ├── 完整版界面.bat         功能齐全的界面
│   ├── 自检.bat               环境诊断（GTP/坐标/规则/界面）
│   ├── 安装修复KataGo.bat     引擎与权重一键安装/修复
│   ├── 使用说明.md            给使用者的说明
│   ├── go_ai.py               程序本体（单文件）
│   ├── play.py / gogame/      完整版界面与其模块
│   └── katago/                引擎 + 权重 + 配置
├── macos/                    macOS 版（同上，使用 .command 启动脚本与原生 arm64 引擎）
├── tools/                    开发/打包工具（不参与游戏运行）
│   ├── benchmark.py           本机性能基准
│   ├── gui_smoke_test.py      界面自动化冒烟测试
│   └── make_friend_package.py 生成分平台发布包
└── docs/
    └── TECHNICAL.md           技术文档（协议实现、调优、降级方案、排查手册）
```

## 六、常见问题

| 现象 | 处理 |
| --- | --- |
| 双击没反应 / 窗口一闪而过 | 没装 Python：装 3.9+ 并勾选 *Add Python to PATH* |
| 提示"没有找到可用的 KataGo" | 弹窗选"是"自动安装；或双击 `安装修复KataGo` |
| 提示引擎无法运行 | 引擎不是本机版本（例如把 Windows 包给 Mac 用）→ 双击 `安装修复KataGo` 重新获取 |
| 引擎启动失败 / 没出现 GTP ready | 双击 `自检`，日志在同目录 `go_ai_katago.log`；常见原因是配置里同时写了 logDir 和 logFile |
| 找不到模型 | 双击 `安装修复KataGo` 重新下载权重（约 11 MB），确认 `katago/models/` 下有 `.bin.gz` |
| 权限错误 | macOS/Linux：`chmod +x *.command *.sh katago/bin/katago`；Windows：右键 → 属性 → 解除锁定 |
| 被杀毒/安全中心拦截 | 选"仍要运行"，或将文件夹加入白名单（引擎是官方预编译包，未做商业签名）|
| AI 太慢 | 强度调小（如 150）、改玩 9 路、关闭占用 CPU 的程序 |
| 想让 AI 更强 | 强度调到 1200–4000；或 `python3 setup_katago.py --model b10c384` 换更大网络（更慢）|

更完整的排查手册见 [docs/TECHNICAL.md](docs/TECHNICAL.md)。

## 七、技术说明

- **通信**：以子进程方式运行 `katago gtp -model … -config …`，用标准 GTP 命令
  （`boardsize` / `komi` / `clear_board` / `play` / `genmove` / `final_score`）下棋，
  并用 KataGo 扩展 `kata-set-param maxVisits` 在运行时调强度。
- **线程模型**：tkinter 只在主线程绘制；引擎加载、思考、形势判断都在子线程，
  结果经队列回到主线程（`root.after` 轮询），所以 AI 思考时界面不会卡死。
- **规则**：程序自带提子 / 打劫 / 禁自杀 / 面积计分 / 悔棋还原，用于即时合法性判断与终局数子。
- **引擎与权重来源**（均为公开发布，遵循其原始许可）：
  - KataGo v1.18.2 引擎：<https://github.com/lightvector/KataGo/releases>
  - 神经网络 `g170e-b10c128-s1141046784-d204142634.bin.gz`：<https://katagoarchive.org/g170/neuralnets/>
  - Windows 版为官方预编译包（Eigen CPU 后端，AVX2）；macOS 版在 Apple 芯片上源码编译（Eigen，原生 arm64）
- **运行环境**：Python 3.9+（含 tkinter）、Windows x64 / macOS（Apple 芯片或 Intel）。

## 八、自己重新打包

仓库自带打包脚本，可在本机重新生成任意平台的发布包：

```bash
python3 tools/make_friend_package.py --platform windows
python3 tools/make_friend_package.py --platform macos
```

## 九、许可与致谢

- 本程序代码：MIT License（见 [LICENSE](LICENSE)）
- 引擎 [KataGo](https://github.com/lightvector/KataGo)：MIT License，作者 David Wu（lightvector）及贡献者
- 神经网络权重：来自 KataGo 官方发布的 g170 系列

祝下棋愉快！
