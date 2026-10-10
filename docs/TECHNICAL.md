# KataGo 人机对战（围棋）· 开箱即用

一个跨平台的 **Python + tkinter** 围棋人机对战程序，通过 **GTP 协议**直接调用官方
[KataGo](https://github.com/lightvector/KataGo) 引擎。项目自带"一键安装器"：自动探测系统、
下载/编译引擎、下载神经网络权重、生成配置并完成自检。

---

## 一、这台机器上已经完成的工作

| 项目 | 结果 |
| --- | --- |
| 运行环境 | macOS 26.6.2 / Apple M5（arm64）/ 10 核 / Python 3.14.7 |
| 引擎 | **KataGo v1.18.2**（官方无 macOS 预编译包 → 已自动源码编译，原生 arm64 + Eigen CPU 后端）|
| 引擎路径 | `katago/bin/katago`（7.7 MB，`Using Eigen(CPU) backend`）|
| 权重 1（默认）| `g170e-b10c128-s1141046784-d204142634.bin.gz`（11 MB，CPU 上最快）|
| 权重 2（可选）| `b10c384h6nbttflrs.bin.gz`（38 MB，棋力更强，CPU 上约慢 10 倍）|
| 配置 | `katago/configs/default_gtp.cfg`（中国规则、每手 400 次访问、10 线程）|
| 自检 | `python3 test_katago.py` → **16/16 项全部通过**，可直接运行 |

macOS 官方 Release 只有 Linux/Windows 的 CUDA 包，所以本机是**从源码编译**的；安装器已把这套
流程自动化（见第七节），在其它 Mac 上同样适用。

---

## 二、马上开始

```bash
# macOS（终端）
./run_game.sh                    # 或双击 run_game.command

# Linux
./run_game.sh

# Windows：双击 run_game.bat
```

也可以直接用 Python 启动：

```bash
python3 play.py                  # 图形界面（缺组件会自动提示安装）
python3 test_katago.py           # 环境 / GTP 连接自检
python3 setup_katago.py          # 安装或修复
```

> 首次启动需要 1–6 秒加载神经网络（界面右侧会显示"引擎加载中"），之后每手即时思考。

---

## 三、目录结构

```
go-katago-human-vs-ai/
├── go_ai.py                   # ★ 单文件版人机对战 (tkinter, 默认 9 路, 一个文件跑起来)
├── test_go_ai.py              # go_ai.py 的自检: GTP 会话 / 坐标转换 / 规则 / 界面
├── play.py                    # 入口：启动 tkinter 图形界面
├── setup_katago.py            # 跨平台安装器（下载/编译引擎 + 权重 + 配置 + 自检）
├── test_katago.py             # 环境自检 / GTP 连接测试（16 项检查）
├── run_game.command/.sh/.bat  # 各平台双击启动
├── setup_katago.command/.bat  # 各平台双击安装
├── test_katago.command        # macOS 双击自检
├── tools/
│   ├── benchmark.py           # 性能基准（访问/秒、建议难度）
│   └── gui_smoke_test.py      # 界面自动化冒烟测试（真开窗口 + 引擎）
├── gogame/                    # Python 包
│   ├── paths.py               #   跨平台路径与系统探测
│   ├── gtp.py                 #   GTP 协议客户端（线程安全 + 流式分析）
│   ├── board.py               #   围棋规则：提子 / 打劫 / 禁自杀 / 面积计分
│   ├── ai.py                  #   KataGo 对手封装（难度、参数、走子、形势判断）
│   ├── installer.py           #   自动下载 / 源码编译 / 校验
│   ├── gui.py                 #   tkinter 界面
│   └── assets/default_gtp.cfg #   配置模板（重装时使用）
├── katago/
│   ├── bin/katago             # 引擎可执行文件
│   ├── models/*.bin.gz        # 神经网络权重
│   └── configs/*.cfg          # GTP 配置
├── logs/                      # 引擎日志（出问题时看这里）
└── .build/                    # 源码与编译产物缓存（235 MB，可安全删除）
```

---

## 四、界面与玩法

| 区域 | 说明 |
| --- | --- |
| 棋盘 | 9 / 13 / 19 路，带坐标（列 A–T 跳过 I，行从下往上）与星位 |
| 落子 | 鼠标点击交叉点；绿色虚线框是预览；已有子 / 打劫 / 自杀会即时拒绝并提示 |
| 形势（黑棋视角）| 实时显示 KataGo 的胜率条（搜索过程中不断刷新）|
| AI 信息 | 访问量、目差、主变化（PV）前几手 |
| 新局设置 | 棋盘大小、执黑/执白、贴目、让子（2–9 子）、难度、显示地盘估算、AI 劣势认输 |
| 对局操作 | 停一手（pass）、悔棋（撤销一个回合）、形势判断（约 1.5 秒重新评估全局）、认输 |
| 引擎面板 | 引擎名称/线程数/难度 + 实时日志 |

- **难度**：入门 30 / 初级 100 / 中级 400 / 高级 1200 / 专家 4000（每手神经网络访问次数）。
- **让子**：让子局自动把贴目改为 0.5 并让白棋先行。
- **终局**：双方都停一手自动数子（面积计分/中国规则），并附上 KataGo 的终局判定。
- **悔棋原理**：客户端保留完整棋谱，悔棋后用 `clear_board` + 重放方式重建引擎局面，因此
  即使跨越打劫、提子也完全一致。

---

## 五、命令行参数

```bash
python3 play.py --visits 1200         # 指定每手访问次数
python3 play.py --threads 6           # 指定搜索线程数
python3 play.py --setup               # 先跑安装器再开界面
python3 play.py --check               # 只做安装校验

python3 setup_katago.py --list-models         # 查看可选网络
python3 setup_katago.py --model b10c384       # 换更强的网络
python3 setup_katago.py --backend opencl      # 用 OpenCL (GPU) 预编译包
python3 setup_katago.py --force               # 强制重装（重新下载/编译）
python3 setup_katago.py --verify-only         # 只自检

python3 test_katago.py --quick        # 跳过完整对局烟测

python3 tools/benchmark.py             # 本机性能基准, 用来挑难度/线程数
python3 tools/gui_smoke_test.py        # 界面自动化冒烟测试 (会真的弹出窗口)
```

---

## 六、性能实测与调优建议

### 6.1 本机实测（Apple M5 / 10 核 / Eigen CPU 后端）

| 网络 | 棋盘 | 每手访问 | 实测每手耗时 | 吞吐 |
| --- | --- | --- | --- | --- |
| b10c128（默认）| 19 路 | 400 | **1.15 s** | ≈350 访问/秒 |
| b10c128 | 19 路 | 1200 | 3.4 s | ≈350 访问/秒 |
| b10c128 | 9 路 | 400 | **0.51 s** | ≈800 访问/秒 |
| b10c384 | 19 路 | 400 | 13.7 s | ≈29 访问/秒 |
| b10c384 | 9 路 | 400 | 2.2 s | ≈180 访问/秒 |

难度 → 预计耗时（19 路 / b10c128）：入门 0.1 s、初级 0.3 s、中级 1.2 s、高级 3.5 s、专家 12 s。

`python3 tools/benchmark.py` 在本机的输出（10 线程）：

| 棋盘 | 访问/秒 | 建议难度 | 400 访问预计耗时 |
| --- | --- | --- | --- |
| 9 路 | 965 | 高级/中级 | 0.41 s |
| 13 路 | 531 | 高级/中级 | 0.75 s |
| 19 路 | 306 | 中级 | 1.31 s |

（换机器后重新跑一次这个脚本，就能得到属于你的最佳难度/线程设置。）

### 6.2 建议（按收益排序）

1. **先玩 9 路**：同样访问量下 9 路比 19 路快 2–3 倍，而且更适合人机对练。
2. **选对网络**：CPU 用户坚持用 `b10c128`；只有装了 GPU 才建议上 `b15c192` / `b10c384`。
3. **调线程数**：CPU 后端最佳值是"物理核心数左右"。本机实测（b10c384/19 路/300 访问）：

   | numSearchThreads | nnMaxBatchSize | 吞吐（访问/秒）|
   | --- | --- | --- |
   | 4 | 8 | 19.3 |
   | 6 | 16 | 25.1 |
   | 6 | 32 | 24.7 |
   | 8 | 16 | 28.2 |
   | 10 | 16 | **28.2** |

   界面启动时默认使用 `min(核心数-1, 16)` 个线程，可在 `play.py --threads N` 或
   `katago/configs/default_gtp.cfg` 的 `numSearchThreads` 中修改。
4. **访问量换棋力**：每提高一档难度，耗时线性增加；CPU 上 400–1200 次是性价比区间。
5. **想更像真人**：把 `chosenMoveTemperature` 设为 `0.1`–`0.3`（默认 0.0，下法固定）；
   或者换人类棋风网络 `b18c384nbt-humanv0`（99 MB，需配合 `-human-model` 参数）。
6. **充分利用空闲 CPU**：把 `ponderingEnabled` 改成 `true`（我方思考时 AI 也在后台算），
   棋力更强但会更耗电。
7. **时间制而非访问量**：想按时间下棋可用 GTP 的 `time_settings`（引擎会自行分配时间），
   本程序的难度默认走"访问量"模式。

### 6.3 GPU 加速（可选）

| 平台 | 推荐做法 |
| --- | --- |
| NVIDIA (Windows/Linux) | 下载 Release 里的 CUDA 包（如 `katago-v1.18.2-cuda12.8-cudnn9.8.0-*-x64.zip`），把 katago 可执行文件放到 `katago/bin/`，并安装匹配的 CUDA/cuDNN；可用 `python3 setup_katago.py --backend cuda` 尝试自动下载 |
| AMD / Intel GPU | OpenCL 包：`python3 setup_katago.py --backend opencl`（Windows/Linux x64）|
| Apple Silicon | 源码里已有 `USE_BACKEND=METAL`（CoreML + MPSGraph）实验后端，可自行编译尝试：在 `.build/KataGo/cpp` 下 `cmake -DUSE_BACKEND=METAL`；官方仍推荐 CPU/OpenCL |
| 通用 | 换 GPU 后无需改代码：程序只关心 `katago/bin/katago` 这一个可执行文件 |

> GPU 版的访问量可以开到几千甚至上万，棋力会显著强于 CPU；人机对战体验主要受**单次访问成本**影响。

---

## 七、跨平台安装（安装器做了什么）

`setup_katago.py`（或界面里的"重新安装/修复"）按下列顺序自动选择方案：

| 系统 | 引擎来源 | 说明 |
| --- | --- | --- |
| Windows x64 | 官方预编译 zip（`eigenavx2` → `eigen`，可选 `opencl`/`cuda`）| 自动检测 AVX2；解压后放 `katago/bin/katago.exe` |
| Linux x64 | 官方预编译 zip（同上）| 同样自动判断 AVX2 |
| Linux arm64 | 有预编译包就用，没有则**源码编译** | 需要 cmake / g++ / zlib |
| macOS（Intel & Apple Silicon）| **源码编译**（官方无 mac 预编译包）| 自动准备 CMake（系统 → pip → 下载官方二进制）、下载 KataGo 源码与 Eigen 头文件、`-DUSE_BACKEND=EIGEN` 编译出原生 arm64/x86_64 可执行文件 |

其它细节：

- **权重**：默认下载 `g170e-b10c128-s1141046784`（中等规模小网络），失败会自动回退到备用网络；
  下载后校验 gzip 魔数。
- **配置**：写入 `katago/configs/default_gtp.cfg`（模板在 `gogame/assets/`），关键值为
  中国规则、`maxVisits = 400`、`numSearchThreads = 核心数`、`nnMaxBatchSize = 16`、
  关闭思考日志、关闭引擎自动认输（改由界面判断）。
- **自检**：`katago version` → GTP 握手（`name/version`）→ `boardsize/komi/clear_board/play`
  → `genmove` 试下一手。
- **全部离线可用**：安装完成后不再需要联网。

---

## 八、常见问题

**Q1. 双击没反应 / 提示找不到 python3？**
安装 Python 3.9+（Windows/macOS 建议 [python.org](https://www.python.org/downloads/) 官方包，
自带 tkinter）。Linux 需要额外装界面库：`sudo apt install python3-tk`（Debian/Ubuntu）
或 `sudo dnf install python3-tkinter`（Fedora）。

**Q2. 提示 "缺少组件"？**
运行 `python3 setup_katago.py`，或在界面菜单里选"文件 → 重新安装 / 修复 KataGo"。

**Q3. AI 每手太慢？**
① 玩 9 路；② 降低难度（每手 100–400 次）；③ 确认用的是 `b10c128`（不是 b10c384）；
④ 减少 `numSearchThreads`（线程过多在 CPU 上反而抢核）。

**Q4. 想让 AI 更强？**
`python3 setup_katago.py --model b10c384`（或 `b15c192`）→ 难度选"高级/专家"；
有 GPU 时效果最好。

**Q5. 引擎启动报错 / 中途崩溃？**
看 `logs/katago_engine.log`（引擎 stderr 全文）与界面右侧日志；
再跑 `python3 test_katago.py` 定位。多数情况是权重损坏（重新 `--force` 下载）或被杀软拦截。

**Q6. 我想复盘 / 保存棋谱？**
界面"文件 → 保存棋谱(SGF)"可导出标准 SGF，Sabaki、Lizzie、KaTrain 等都能打开。

**Q7. 让子棋为什么白棋先走、贴目变成 0.5？**
这是标准让子规则：黑先摆好让子，白先行，且贴目很小。界面会自动处理。

**Q8. 坐标看不懂？**
采用 GTP 标准：列 `A B C D E F G H J K L M N O P Q R S T`（跳过 I），行从下往上 1..19。

**Q9. 会占多少磁盘？**
`katago/` 56 MB（引擎 + 两个权重）+ `.build/` 235 MB（源码/编译缓存，可删）。
删掉 `.build/` 不影响运行，只是下次修复安装需要重新下载源码。

**Q10. 怎么卸载？**
直接删除整个项目目录即可（不写注册表、不装系统服务、不改 PATH；唯一例外是 pip 装的
`cmake` 模块，仅 macOS 源码编译时需要）。

---

## 九、技术实现

- **通信**：程序不链接任何 KataGo 库，而是以子进程方式运行 `katago gtp -model ... -config ...`，
  用 stdin/stdout 走标准 **GTP** 协议（`boardsize` / `komi` / `clear_board` / `play` /
  `genmove` / `undo` / `final_score`），并用 KataGo 扩展 `kata-set-param`、`kata-analyze`、
  `kata-genmove_analyze` 实现难度调节与实时胜率。
- **流式分析**：`kata-analyze` 的响应是"先回 `=`，再把 `info move ...` 作为响应正文持续输出，
  最后以空行结束"。因此客户端用一条后台线程读取 stdout：普通响应按自增 id 投递给等待者，
  分析行投递给流回调，收到空行触发"分析结束"事件；发送空行即可中断分析。
- **线程模型**：tkinter 只在主线程绘图；引擎加载、思考、形势判断都在后台线程，结果经
  `queue` 回传，主线程每 80 ms 轮询刷新，所以 AI 思考时界面不卡。
- **规则**：客户端自带一套完整规则（提子、打劫、禁自杀、悔棋还原、Tromp-Taylor 面积计分），
  用于即时合法性判断、地盘估算与终局数子；引擎内部使用中国规则（`rules = chinese`）。
- **参数传递**：运行时通过 `-override-config` 注入 `maxVisits`/`numSearchThreads`/
  `ponderingEnabled`/`reportAnalysisWinratesAs=BLACK`，无需改配置文件即可切换难度。

---

## 十、验证记录（本机实测）

```
python3 test_katago.py          → 16/16 通过
  · 引擎/权重/配置完整性、权重 gzip 魔数校验
  · katago version = KataGo v1.18.2
  · 围棋规则单元测试: 提子 / 打劫(含劫材后回提) / 禁自杀 / 面积计分 / 悔棋还原
  · GTP: name / version / boardsize / komi / clear_board / play /
         kata-set-param / genmove_analyze / kata-analyze / final_score
  · 9 路完整对弈烟测 (双方各 9 手后数子)

python3 tools/gui_smoke_test.py → 10/10 通过 (真实窗口 + 引擎)
  · 引擎加载 → 自动开局 → 模拟点击落子 → AI 应手 1.1s →
    胜率刷新(黑 39.2%) → 分析信息(访问/目差/PV) → SGF 生成 → 悔棋 → 形势判断 → 无报错弹窗

python3 setup_katago.py --force → 安装器全流程复测通过
  · 源码编译(增量) → 重新下载 10.6MB 权重 → 生成配置 → 自检 "GTP 握手成功, 9x9 试下一手 -> C5"
```

> 注: 本机 CLI 环境没有屏幕录制权限, 因此截图不可用; 上述界面测试是通过脚本真实操作控件完成的。
> `python3 play.py` 已实测可正常启动并持续运行（窗口打开、引擎连接、可落子）。
---

## 十一、下载失败 / 系统不兼容时的降级方案

安装器（`setup_katago.py`）已内置多级降级；若仍失败，按下面顺序处理即可。

| 情况 | 降级方案 |
| --- | --- |
| 预编译包下载失败（网络不稳 / GitHub 限流） | 安装器自动重试 3 次并换备用网络；也可手动下载后按"最小摆放清单"摆放 |
| 系统没有官方预编译包（**macOS** / Linux arm64 …）| 自动降级为**源码编译 Eigen（纯 CPU）后端**：自动准备 CMake（系统 → pip → 官方二进制）、下载源码与 Eigen 头文件，编译出本机原生可执行文件。本机 macOS 就是这么装好的 |
| 没有编译器 / 编译失败 | 改用官方预编译的 **Eigen CPU 版**：Windows `katago-*-eigen-windows-x64.zip`、Linux `katago-*-eigen-linux-x64.zip`（老 CPU 用不带 avx2 的 eigen 包）；macOS 可 `brew install katago` 后 `export KATAGO_BIN=$(which katago)` |
| 有显卡但驱动/CUDA/cuDNN 不匹配 | 显式退回 CPU：`python3 setup_katago.py --backend eigen --force`；程序只认 `katago/bin/katago` 一个文件，换后端不用改代码 |
| OpenCL 版跑不起来 | 同上换 Eigen CPU 包；功能完全一致（本机就是纯 CPU：19 路约 306 访问/秒，够下棋）|
| 权重下载失败 | 安装器按 `b10c128 → b15c192 → b10c384` 顺序自动回退；也可手动下载 [g170e-b10c128-…bin.gz](https://katagoarchive.org/g170/neuralnets/)（约 11 MB）放进 `katago/models/` |
| 完全离线 | 在联网机器上装好后，把整个 `katago/`（约 56 MB）拷过来即可；程序运行时不联网 |
| 引擎装在别处 | 用环境变量指定：`KATAGO_BIN` / `KATAGO_MODEL` / `KATAGO_CONFIG`（`go_ai.py` 与整套工具都认）|

**最小摆放清单**（三个文件就能下棋）：

```
katago/bin/katago[.exe]          # 引擎 (CPU 版 = eigen / eigenavx2 包里的 katago)
katago/models/xxx.bin.gz         # 权重 (小网络约 11 MB)
katago/configs/default_gtp.cfg   # 配置 (缺失时 go_ai.py 会自动生成一份最小可用配置)
```

---

## 十二、单文件版 `go_ai.py`（任务二交付物）

一个文件搞定：人类执黑先行、AI 执白应手、鼠标点击落子、9/13/19 路切换、强度可调、
GTP 坐标转换（跳过 I）、子线程思考 + 主线程刷新、缺引擎时友好弹窗指引。

### 12.1 运行

```bash
python3 go_ai.py                      # 直接开玩 (默认 9 路 / 6.5 贴目 / 每手 400 次访问)
KATAGO_BIN=/usr/local/bin/katago python3 go_ai.py     # 用环境变量指定引擎
python3 test_go_ai.py                 # 自检: GTP 会话 + 坐标 + 规则 + 界面
python3 test_go_ai.py --no-gui        # 无显示器环境 (只测 GTP 与逻辑)
```

### 12.2 配置区（文件开头 30 行内）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `BOARD_SIZE` | `9` | **改成 19 就是 19 路**（界面里也能随时点选 9/13/19）|
| `KOMI` | `6.5` | 贴目 |
| `MAX_VISITS` | `400` | **AI 强度**：每手搜索访问次数；界面"强度"输入框可运行时修改（`kata-set-param maxVisits`）|
| `NUM_SEARCH_THREADS` | `0` | 0 = 自动（CPU 核心数 - 1，上限 16）|
| `HUMAN_COLOR` / `AI_COLOR` | `B` / `W` | 人类执黑先行 |
| `KATAGO_BIN` / `KATAGO_MODEL` / `KATAGO_CONFIG` | 空 | 留空则自动搜索：环境变量 → 同目录 `katago/` → 系统 PATH |
| `DEBUG_GTP` | `False` | 改成 `True` 可把每条 GTP 收发打印到控制台 |

### 12.3 强度对照（本机 CPU 实测，可直接参考）

| MAX_VISITS | 19 路每手耗时 | 9 路每手耗时 | 大致水平 |
| --- | --- | --- | --- |
| 100（初级）| ≈0.35 s | ≈0.12 s | 入门～10 级 |
| 400（中级，默认）| ≈1.3 s | ≈0.5 s | 5 级左右 |
| 1200（高级）| ≈4 s | ≈1.5 s | 1 段左右 |
| 4000（专家）| ≈13 s | ≈5 s | 更强，CPU 上偏慢 |

### 12.4 目录结构说明

```
项目目录/
├── go_ai.py                     ← 程序本体（单文件，可单独拷走）
├── test_go_ai.py                ← 自检脚本
├── setup_katago.py              ← 一键安装/修复引擎与权重（跨平台）
└── katago/                      ← 引擎与权重（go_ai.py 会自动在这里找）
    ├── bin/katago[.exe]         ←   可执行文件
    ├── models/*.bin.gz          ←   神经网络权重
    ├── configs/default_gtp.cfg  ←   GTP 配置（缺失会自动生成）
    └── logs/ 或 logs/           ←   引擎日志
```

### 12.5 排查手册

| 现象 | 原因与处理 |
| --- | --- |
| 弹窗"没有找到可用的 KataGo 引擎/模型/配置" | 运行 `python3 setup_katago.py`；或按 12.4 摆放三个文件；或用 `KATAGO_*` 环境变量指过去 |
| **找不到模型**（`katago/models` 为空 / .part 残留）| 重新下载：`python3 setup_katago.py --force`，或手动放 [g170e-b10c128-…bin.gz](https://katagoarchive.org/g170/neuralnets/)；确认文件以 `\x1f\x8b`(gzip) 开头且约 11 MB，删除同名 `.part` 文件 |
| **GTP ready 未出现** | 手动跑一次看报错：`katago/bin/katago gtp -model katago/models/xxx.bin.gz -config katago/configs/default_gtp.cfg`。常见原因：① 配置里同时出现 `logDir` 和 `logFile`（KataGo 会直接崩，删掉 `logFile` 那行）② 权重与引擎版本不匹配 ③ 配置键名拼错（日志会提示 `Unused key`）④ 端口/内存不足。正常应看到 `GTP ready, beginning main protocol loop` |
| **权限错误**（Permission denied / 无法执行） | macOS/Linux：`chmod +x katago/bin/katago`，必要时 `xattr -dr com.apple.quarantine katago/bin/katago`（绕过 Gatekeeper 隔离）；Windows：右键"属性→解除锁定"或把目录加入杀软白名单；引擎目录不要放在需要管理员权限的路径下 |
| `main thread is not in main loop` | tkinter 线程问题（早期版本已修复）：子线程只投递队列，`root.after` 一律在主线程调用 |
| AI 每手太久 | 调小 MAX_VISITS、改玩 9 路、或换小网络（本机默认已是 CPU 最快的 b10c128）|
| `kata-set-param` 无效 | 老版本引擎不支持该扩展；改配置区 `MAX_VISITS` 后重启程序即可 |
