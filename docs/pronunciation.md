# 英语发音训练

独立一级入口 `/vocab/#/pronunciation`，兼容 `/vocab/#/speaking`。不嵌入数字人口语页面。
提供单词重音、句子重音、指定语境语调、意群节奏四类共 12 道原创练习，附合成示范音。

## 运行

从仓库根目录安装。主站与声学服务使用两个独立环境；Python 3.11 已完成本机验证。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
python -m venv .speech-venv
.\.speech-venv\Scripts\python.exe -m pip install -r speech_service/requirements.txt
cd vocab-frontend
npm ci
npm run build
cd ..
.\.venv\Scripts\python.exe scripts/run_pronunciation.py
```

Linux 将 `Scripts/python.exe` 换成 `bin/python`。FFmpeg 由 imageio-ffmpeg 的平台包提供，无需全局安装。
默认主站 `127.0.0.1:8000`、声学服务 `127.0.0.1:8001`；启动器只结束自己启动的子进程，端口被占用时直接报错，不停止已有服务。
可用 `--port 8010 --worker-port 8011` 改端口。通过 HTTPS 代理公开主站时，保持声学端口仅内部可达。
Docker 部署见 `compose.pronunciation.yaml`；手机使用麦克风需要受信任 HTTPS，localhost 可直接录音。

## 模型配置与隐私

声学提取、文本对齐、规则反馈和语调试听均在本地运行，无需模型 Key。
教学问答优先读取 `SPEAKING_API_KEY` / `SPEAKING_BASE_URL`，留空则复用 `WRITING_API_KEY` / `WRITING_BASE_URL`。
网页支持选择 DeepSeek Flash 或 V4 Pro。无 Key 或模型请求失败时，明确显示“本地实测建议”；模型只接收结构化证据和开启的历史摘要，不接收录音。
保留已有 `.env`，只添加需要的配置项，编辑后重启主站。不要把 `.env.example` 覆盖到已有 `.env`。

每个浏览器使用独立的 HttpOnly、SameSite=Strict 随机会话。当前 CET 主站尚无完整登录系统，发音历史按浏览器会话隔离，不宣称跨设备账号同步。
SQLite、录音和教学记录保存在 `data/speaking/`。原始录音在提交分析时上传；未提交前只在浏览器。
启动时清理超过 30 天的练习和录音；删除练习会同时删除原音频和对应教学记录，并从记忆摘要移除。
记忆可关闭和清空；关闭期间的新结果不会成为学习摘要，重新开启也不会补写。清空摘要不会删除历史录音。

`.env`、`.env.*`（保留 `.env.example`）、数据库、录音目录、虚拟环境和测试截图均由 Git 忽略。
推送前运行 `python scripts/check_secrets.py --base origin/feat/writing-multi-agent`，扫描暂存区全部文件和待推送提交。
它会比较本地 `.env` 中的敏感值，但不打印它们；还检查常见密钥格式及禁止提交的文件。

## 分析、进度与复练

音频解码 → 质量门控 → Praat F0 → 英文对齐 → 特征 → 专项判断 → 图表校验 → 参照条件 → 练习/记忆保存。
声学服务通过 SSE 发送真实步骤，主站保存每步状态和时间，页面轮询恢复任务。没有虚构百分比；失败节点停止下游。
步骤顺序在代码中强制执行，加载 `speech_service/protocol.md` 并记录 SHA-256 版本；教学流程单独加载 `skill/speaking-coach.md`。
教学智能体流程：读取本次证据与可用记忆 → 加载规范 → 模型/本地生成 → 数值依据检查 → 保存对话。

图表包含原始振幅、相对半音曲线、RMS dBFS、词语时间位置和单词元音核线索；缺失 F0 保持断开。
参照可选内置合成音、自己标记的已分析录音，或不使用参照。可以先上传教师录音、分析后设为个人参照，当前版本不认证上传者的教师身份。
复练比较必须同题、同算法版本、同音高参数、同参照 ID/hash；时间归一化只用于看走势，实际选区时长独立显示。
语调调整试听使用 Praat PSOLA，仅按参照调整音高，保留本人的原节奏、音量与发音动作；它是教学试听，不作为正确音素或自然发音的证明。

## 方法与限制

PocketSphinx 5.1.1 en-US 是轻量级近似强制对齐基线。句子使用词级定位，单词重音练习增加音素级第二遍定位。
它没有逐词识别验证，要求学习者先回听确认读的是当前题目；不能据其输出宣称无漏读或音素正确。
词重音规则使用元音核时长与相对能量线索；句子重音以目标词相对数字能量提示，不能独立裁定语用重音。
语调使用末段有效 F0 的首尾半音差；节奏使用词级对齐间隔。所有阈值是版本化工程规则，未校准为真实评分概率。
使用 Parselmouth 0.4.7 的 Praat raw autocorrelation、10 ms 步长；参数、算法版本和真实时间随每次测量保存。
检测到倍频跳变时暂停专项判定，允许调整 F0 范围复测。英语清辅音的 F0 缺失不会直接判为失败。
后续可在保持 HTTP 契约的条件下更换为 MFA 等更强对齐器；需要用真实学习者和人工边界标注比较误差。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.speech-venv\Scripts\python.exe -m pip install pytest httpx
.\.speech-venv\Scripts\python.exe -m pytest tests/test_speech_engine.py -q
```

浏览器实测脚本 `node tests/pronunciation.browser.cjs` 使用 Playwright，需另在测试环境安装 Playwright 和 Chromium。
可通过 `PLAYWRIGHT_MODULE_ROOT` 指定已有的 node_modules 根目录。测试仅使用公开的固定合成示范作为虚拟麦克风输入，不访问真实麦克风。
覆盖上传分析、真实节点、教学进度、语调试听、CSV、MediaRecorder 释放、复练、刷新历史、记忆开关、390px 手机布局、会话隔离与拒绝授权。
合成音和模拟浏览器测试证明工程链路，真实 iOS/Android 麦克风以及教学效果需要实机和学习者验收。

## 来源与许可

原声调项目的交互和流程经验被用于设计本模块；汉语四声模板没有作为英语评分规则。
主站新增代码和原创题目沿用 MIT；独立 `speech_service` 声学代码以 GPL-3.0-or-later 提供，并保留该组件许可。
Praat/Parselmouth 为 GPL-3.0-or-later；PocketSphinx 及其随包资源按上游许可；分发服务或镜像时一并提供相应源代码和许可。
内置示范来源和合成方式见 `speech_service/samples/NOTICE.md`。

- PocketSphinx 对齐 API：https://pocketsphinx.readthedocs.io/en/latest/pocketsphinx.html
- Praat 音高分析：https://praat.org/manual/how_to_choose_a_pitch_analysis_method.html
- Parselmouth 音高操作：https://parselmouth.readthedocs.io/en/stable/examples/pitch_manipulation.html
