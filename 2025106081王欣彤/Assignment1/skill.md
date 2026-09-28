# 名著讲解视频自动生成技能 (Skill)

> 输入一本名著的名字 → 输出该书的短视频（7 张配图 + 7 段讲解音频 + 合成 mp4）。  
> 已通过《娱乐至死》《乌合之众》两本书完整验证。

---

## 〇、技能元信息

| 项      | 值                                            |
| ------ | -------------------------------------------- |
| 技能名称   | 名著讲解视频自动生成技能                                 |
| 版本     | 1.0.0（2026-09-15）                            |
| 适用对象   | 适合"主讲一个核心论点 + 收束警醒"型社科类书评短视频（2~3 分钟）         |
| 输入     | 任意一本已读过或可概括的社科/人文类书名（如《1984》《乌合之众》《娱乐至死》）    |
| 输出     | `书名/视频/最终视频.mp4` + `剧本/`、`音频/`、`图片/` 三组素材    |
| 处理耗时   | 约 3~5 分钟（图片 30s、TTS 25s、合成 30s，其余为文案生成与素材下载） |
| 依赖 API | 火山引擎 ARK（图片）+ 字节豆包语音 TTS 2.0（音频）             |
| 脚本语言   | Python 3.10+（TTS、视频合成）+ PowerShell 5.1（图片生成） |

---

## 一、技能概述

### 1.1 一句话定位

按统一剧本模板生成 7 段讲解稿，调用两个外部 API 自动产出图片与音频，再用 FFmpeg 拼接成短视频。

### 1.2 设计要点

- **统一节奏**：固定 7 段叙事结构（引子 / 报幕 / 背景 / 论点×3 / 收束），节奏一致便于规模化生产。
- **风格稳定**：所有图共享同一画面风格尾缀（`真实新闻纪录片风格、现代视觉设计感`），保证视觉统一。
- **时长对齐**：每张图片停留时长 = 对应音频时长，从不在中途拼接，避免爆音与节奏跳变。
- **产物隔离**：每本书一个子文件夹，互不污染；脚本可重跑、断点续跑。

### 1.3 流水线（5 阶段）

```
书名 ─→ [1] 剧本生成 ─→ 剧本/01-标题与旁白文案.md + 02-画面提示词.md + 分镜/s0~s6.md
                │
                ▼
        [2] 配图生成 (ARK) ─→ 图片/s0.jpeg ~ s6.jpeg
                │
                ▼
        [3] 音频生成 (TTS 2.0) ─→ 音频/s0.mp3 ~ s6.mp3
                │
                ▼
        [4] 动态视频生成 (Seedance i2v) ─→ 视频/动态片段/s0.mp4 ~ s6.mp4
                │
                ▼
        [5] 最终合成 (FFmpeg: Ken Burns推近 + 硬字幕) ─→ 视频/最终动态视频.mp4
```

> 降级备选：若无 Seedance 额度，可跳过阶段 4，用 `compose_video.py` 直接把静态图+音频合成为 `最终视频.mp4`（无动态效果）。

---

## 二、产物结构

每本书一个独立子文件夹：

```
<工作空间>/
└── 《书名》/
    ├── 剧本/
    │   ├── 01-标题与旁白文案.md     # 标题 + s0~s6 旁白 + speed（TTS 脚本解析用）
    │   ├── 02-画面提示词.md         # s0~s6 画面描述（人读版）
    │   └── 分镜/                    # 【必须】每段一个 sN.md，含 "## 字幕文案" + "## 画面描述"
    │       └── s0.md ~ s6.md        # Seedance / SRT / 字幕生成都从这里读
    ├── 脚本/
    │   ├── prompts.txt              # 图片提示词，每行 s编号|提示词
    │   ├── ffmpeg_bin/ffmpeg.exe    # 视频合成用的 ffmpeg（v7.1+）
    │   └── logs/                    # TTS 日志（UTF-8）
    ├── 图片/
    │   ├── s0.jpeg ~ s6.jpeg
    │   └── generate_report.json
    ├── 音频/
    │   ├── s0.mp3 ~ s6.mp3
    │   └── tts_report.json
    └── 视频/
        ├── 动态片段/                # 阶段 4 产物
        │   ├── s0.mp4 ~ s6.mp4      # 每段 5s, 480x864, 24fps
        │   └── _report.json
        └── 最终动态视频.mp4          # 阶段 5 最终成品（含硬字幕 + 软字幕轨）
```

---

## 三、环境依赖

### 3.1 系统

| 项          | 版本                    | 说明                                   |
| ---------- | --------------------- | ------------------------------------ |
| Python     | 3.10+ (本机 3.13.12)    | 跑 TTS 与视频合成                          |
| PowerShell | 5.1 (Windows 自带)      | 跑图片生成                                |
| FFmpeg     | 7.1+（含 libx264 + aac） | 视频合成；本技能默认使用 `imageio-ffmpeg` 自带的二进制 |

### 3.2 Python 包

```
pip install websockets Pillow
```

> ⚠ `imageio-ffmpeg` **不是必须**。本项目不依赖它，只是当系统没装 ffmpeg 时，用它的 wheel 解压出 `ffmpeg.exe`。详见 §八 避坑经验。

### 3.3 凭据

| API          | Key 格式                                                         | 控制台     |
| ------------ | -------------------------------------------------------------- | ------- |
| ARK 图片       | `ark-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx-xxxxxx`              | 火山方舟控制台 |
| 豆包语音 TTS 2.0 | `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`（UUID 格式，**不是 ark- 开头**） | 豆包语音控制台 |

⚠ 同一个火山账号下，ARK Key 和 豆包语音 Key 是**两套独立凭据**，不可互通。开通 `seed-tts-2.0` 服务后才能用本技能。

---

## 四、5 阶段处理流程

### 阶段 1：剧本生成（AI 对话阶段，无脚本）

**输入**：书名

**步骤**：

1. 用 §五.1 的标题 prompt 让 AI 生成 8 个候选标题，从选 1 个定稿
2. 用 §五.2 的旁白 prompt 生成 7 段文案（严格 `s序号|文案|speed=倍率` 格式，s0 和 s6 用 `speed=0.9`，其余 `speed=1.0`）
3. 用 §五.3 的画面 prompt 把每段旁白生成对应的画面描述，并统一加固定尾缀（如 `真实新闻纪录片风格、现代视觉设计感`）

**输出**：

- `剧本/01-标题与旁白文案.md`（格式模板见 §九.2）
- `剧本/02-画面提示词.md`（人读版）
- `剧本/分镜/s0.md ~ s6.md`（【必须】每段含 `## 字幕文案` 和 `## 画面描述` 两个章节，阶段 4/5 的脚本从这里解析）
- `脚本/prompts.txt`（脚本用，格式 `s编号|提示词`）

### 阶段 2：图片生成（ARK）

**调用**：`scripts/generate_images.ps1 -ApiKey <ark-key> -BookDir <书目录>`

**关键参数**：

- URL: `https://ark.cn-beijing.volces.com/api/v3/images/generations`
- Model: `doubao-seedream-4-0-250828`
- Size: `720x1280`（1K, 9:16 竖屏）
- 并发数：7（一次发 7 个 HTTP 请求）

**输出**：`图片/sN.jpeg` + `图片/generate_report.json`

### 阶段 3：音频生成（豆包 TTS 2.0 WebSocket 双向流）

**调用**：`python scripts/generate_tts_ws.py --book-dir <书目录>`

**协议流程**（每个段独立连接）：

```
start_connection → 等 ConnectionStarted (1xx)
→ start_session (speaker + audio_params, 不带 text) → 等 SessionStarted (150)
→ task_request (event=200, req_params.text=文案) → 立即 finish_session
→ 收 TTSResponse (352) 音频 chunks → SessionFinished (152) → finish_connection
```

**关键参数**：

- URL: `wss://openspeech.bytedance.com/api/v3/tts/bidirection`
- Resource-Id: `seed-tts-2.0`
- Speaker: `zh_male_m191_uranus_bigtts`（云舟 2.0，通用男声）
- Sample Rate: `24000`，Format: `mp3`
- speech_rate = `(speed - 1.0) × 100`，截断到 `[-50, 100]`

**输出**：`音频/sN.mp3` + `音频/tts_report.json`

### 阶段 4：动态视频生成（Seedance 图生视频）

**调用**：`python scripts/generate_seedance_videos.py --book-dir <书目录>`（Key 从环境变量 `ARK_API_KEY` 读取）

**关键参数**：

- URL: `https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks`（异步任务：POST 提交 → GET 轮询）
- Model: `doubao-seedance-1-0-pro-fast-251015`（备选 `doubao-seedance-1-0-pro-250528`；**lite 系列多数账户无权限**，勿用）
- 模式：**单图 i2v**（该模型**不支持** `flf2v` 首尾帧，服务端直接报错）
- ratio: `9:16`，resolution: `480p`，duration: `5`，watermark: `false`
- 提示词 = `剧本/分镜/sN.md` 的 `## 画面描述` 正文 + 固定 motion 后缀  
  （`"5 秒时长, 镜头缓慢推进, 主体保持轻微动态, 真实新闻纪录片风格"`）
- 并发 4 任务，轮询间隔 5s，单任务超时 240s

**输出**：`视频/动态片段/sN.mp4`（每段约 5.04s, 480×864, 24fps）+ `_report.json`

### 阶段 5：最终合成（FFmpeg：Ken Burns 推近 + 硬字幕）

**调用**：

```powershell
python scripts/compose_final_video.py `
  --book-dir <书目录> `
  --ffmpeg <ffmpeg.exe 绝对路径>
```

**五个子步骤**（`--stage srt|seg|concat|burn` 可分步重跑）：

1. 探测 7 段音频/视频时长
2. 按音频实际时长重新生成对齐 SRT（原 5 秒均分时间码作废；按句拆分 + 字符数加权 + 每行≤10 字）
3. 逐段对齐：`setpts` 慢放至音频时长 → `zoompan` 单向缓慢推近（Ken Burns，`z='1+0.0004*on'`，20s 段约放大 19%）→ `tpad` 0.6s 尾帧定格 → `-shortest` 以音频截齐。**禁止 reverse/乒乓循环凑时长**（见 §8.16）
4. concat demuxer `-c copy` 无损拼接
5. `subtitles` 滤镜烧录硬字幕（微软雅黑 16px 白字黑边）+ `mov_text` 软字幕轨双保险

**关键参数**：

- 输出分辨率: `480×864`（Seedance 原生，注意不是 480×854）
- zoompan 前先 `scale=960:1728:flags=lanczos` 2x 预放大（消除低分辨率抖动）
- 视频编码: `libx264 -crf 17 -preset medium -pix_fmt yuv420p`
- 音频编码: `aac -b:a 192k -ar 44100 -ac 2`
- 字幕: 硬烧 + `-c:s mov_text -metadata:s:s:0 language=chi`

**输出**：`视频/最终动态视频.mp4` + `视频/字幕验证帧_30s.jpg`（人工核验用）

**内置自测**：逐段动态性/突刺检测（0.2s 步进帧 diff）、像素 diff 验证字幕写入、ffprobe 字幕流检查、30s 抽帧。

### 备选：静态图合成（无 Seedance 额度时）

**调用**：`python scripts/compose_video.py --book-dir <书目录> --ffmpeg <ffmpeg.exe 路径>`

每张图展示时长 = 对应音频时长，输出 `视频/最终视频.mp4`（无动态画面、无字幕）。参数详见 §7.3。

---

## 五、关键提示词模板

### 5.1 标题生成 prompt

```
你是一位擅长解读社会科学的书评人。
我要做一期讲解"《{书名}》"的短视频（2~3 分钟，竖屏 9:16）。
请为我生成 8 个备选视频标题。
要求：
1. 必须包含书名《{书名}》
2. 副标题要有"金句感"，能让普通观众产生"想点开看"的冲动
3. 风格参照：xxx（按书的调性调整）
4. 不要使用感叹号，不要使用营销话术
返回格式：每行一个，编号 1-8。
```

### 5.2 7 段旁白生成 prompt

```
请为《{书名}》讲解视频写 7 段旁白。
严格按以下格式返回（每段一行，s0 和 s6 用 speed=0.9，其余用 speed=1.0）：
s序号|文案|speed=倍率

每段职能：
- s0 引子（speed=0.9）：从读者熟悉的当代场景切入，落点是一个让观众"愣了一下"的反直觉判断
- s1 报幕：报出书名《{书名}》+ 作者 + 出版年
- s2 背景：当年这本书是在什么社会背景下写成的
- s3 论点一：本书第一个核心判断
- s4 论点二：本书第二个核心判断
- s5 论点三：本书第三个核心判断
- s6 收束（speed=0.9）：警醒呼吁，回到自身

要求：
1. 总时长控制在 100~140 秒（每段 14~20 秒）
2. 文案口语化，避免学术腔
3. 每段首尾不要硬接，保持独立
4. 全程使用简体中文
```

### 5.3 画面描述生成 prompt

```
你将收到一系列字幕文本（s0-s6 共 7 段），请为每段撰写详细的画面描述。

【视觉风格统一规范】
- 世界观：xxx（按书的调性调整，如"现代媒介社会，信息爆炸、密集霓虹灯与广告牌"）
- 色彩：xxx（按书的调性调整）
- 排除：xxx（按书的调性调整）
- 固定尾缀：「xxx 风格」（例如「真实新闻纪录片风格、现代视觉设计感」）

【要求】
1. 主体、构图、色调、镜头运动都要写清楚
2. 单段提示词不超过 200 字
3. 必须以固定尾缀收尾
4. 每段提示词之间不要相互引用

请直接返回 7 段画面描述，每段以"## sN"开头，不要任何解释。
```

> ⚠ **关键经验**：风格规范（世界观 / 色彩 / 排除项 / 尾缀）必须每本书重新设计，不能照搬。《娱乐至死》用冷色霓虹 + 现代媒介；《乌合之众》用暖褐复古 + 1895 巴黎。

### 5.4 prompts.txt 格式

把 7 段画面描述去 `## sN` 标题后，每行写 `s编号|描述`，存为 `脚本/prompts.txt`：

```
s0|深夜的城市公寓...真实新闻纪录片风格、现代视觉设计感
s1|雨后的都市商业街...真实新闻纪录片风格、现代视觉设计感
...
```

---

## 六、API 关键参数表

### 6.1 火山引擎 ARK 图片生成

| 项                           | 值                                                             |
| --------------------------- | ------------------------------------------------------------- |
| URL                         | `https://ark.cn-beijing.volces.com/api/v3/images/generations` |
| Method                      | POST                                                          |
| Auth                        | `Authorization: Bearer <ark-key>`                             |
| Model                       | `doubao-seedream-4-0-250828`                                  |
| Size                        | `720x1280`（= 1K, 9:16）                                        |
| response_format             | `url`（拿到 URL 后再下载，避免 payload 过大）                              |
| watermark                   | `false`                                                       |
| sequential_image_generation | `disabled`（一次只生 1 张）                                          |
| 返回                          | `{data: [{url, size, output_format}]}`                        |

### 6.2 豆包语音 TTS 2.0 WebSocket 双向流

| 项                     | 值                                                                                                            |
| --------------------- | ------------------------------------------------------------------------------------------------------------ |
| URL                   | `wss://openspeech.bytedance.com/api/v3/tts/bidirection`                                                      |
| Auth Headers          | `X-Api-Key: <uuid>`, `X-Api-Resource-Id: seed-tts-2.0`                                                       |
| Sub-Protocol Headers  | `X-Api-Request-Id: <uuid>`（每次请求唯一）                                                                           |
| start_session payload | `{user: {uid}, req_params: {speaker, audio_params: {format, sample_rate, speech_rate}}}`                     |
| task_request payload  | `{user: {uid}, event: 200, namespace: "BidirectionalTTS", req_params: {text}}`                               |
| 协议字段                  | version=0b0001, header_size=0b0001, msg_type=FullClient/FullServer, flags, serialization=JSON                |
| 事件枚举                  | ConnectionStarted(150), SessionStarted(150), TTSResponse(352), SessionFinished(152), ConnectionFinished(152) |
| Speaker 推荐            | `zh_male_m191_uranus_bigtts`（云舟 2.0 通用男声）                                                                    |
| Speaker 必须            | `*_uranus_bigtts` 结尾（2.0 专属音色；BV 系列是 1.0 的，会 55000000 报错）                                                    |
| Format                | mp3, wav, pcm, ogg_opus, m4a（推荐 mp3）                                                                         |
| Sample Rate           | 8000 / 16000 / 22050 / 24000 / 32000 / 44100（推荐 24000）                                                       |
| speech_rate           | 范围 [-50, 100]，0=正常，+10 ≈ 1.1x，-10 ≈ 0.9x                                                                     |

### 6.3 FFmpeg 合成

| 阶段        | 关键参数                                                                                                                                                                                                    |
| --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 单段合成      | `-loop 1 -framerate 25 -i image.png -i audio.mp3 -t <duration> -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -r 25 -s 480x854 -c:a aac -b:a 192k -ar 44100 -ac 2 -shortest -movflags +faststart` |
| Concat 拼接 | `-f concat -safe 0 -i concat.txt -c copy`（前提：所有 seg 编码参数完全一致）                                                                                                                                           |
| Letterbox | Pillow `Image.resize(scale=min(W/sw,H/sh), LANCZOS)` + 黑边 `Image.new('RGB',(W,H),(0,0,0))` 居中粘贴                                                                                                         |

---

## 七、完整脚本代码

### 7.1 `scripts/generate_images.ps1`

> 路径：`scripts/generate_images.ps1`  
> 调用：`powershell -ExecutionPolicy Bypass -File scripts/generate_images.ps1 -ApiKey <ark-key> -BookDir <书目录>`  
> 依赖：`脚本/prompts.txt`、`图片/` 目录（自动建）

```powershell
param(
    [Parameter(Mandatory = $true)]
    [string]$ApiKey,
    [string]$Model  = 'doubao-seedream-4-0-250828',
    [string]$Size   = '720x1280',
    [int]$MaxRetry  = 2,
    [string]$BookDir = ''    # 书的项目根目录; 留空时默认取 $PSScriptRoot 的父目录
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Add-Type -AssemblyName System.Net.Http

$ApiUrl = 'https://ark.cn-beijing.volces.com/api/v3/images/generations'

# 推算根目录（全程 UTF-16 字符串操作，绕开控制台编码问题）
if ([string]::IsNullOrWhiteSpace($BookDir)) {
    $Root = Split-Path -Parent $PSScriptRoot
} else {
    $Root = $BookDir
}
$OutDir  = Join-Path $Root '图片'
$Prompts = Join-Path $Root '脚本\prompts.txt'
if (-not (Test-Path -LiteralPath $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir | Out-Null
}

Write-Host ("Root    : {0}" -f $Root)
Write-Host ("OutDir  : {0}" -f $OutDir)
Write-Host ("Prompts : {0}" -f $Prompts)
Write-Host ("Prompts Exists: {0}" -f (Test-Path -LiteralPath $Prompts))

$client = New-Object System.Net.Http.HttpClient
$client.Timeout = [TimeSpan]::FromSeconds(300)

# 读取分镜提示词：每行 s编号|提示词
$items = New-Object System.Collections.ArrayList
foreach ($line in [System.IO.File]::ReadAllLines($Prompts, [System.Text.Encoding]::UTF8)) {
    if ([string]::IsNullOrWhiteSpace($line)) { continue }
    $idx = $line.IndexOf('|')
    if ($idx -lt 1) { continue }
    $id     = $line.Substring(0, $idx).Trim()
    $prompt = $line.Substring($idx + 1)
    [void]$items.Add([pscustomobject]@{ Id = $id; Prompt = $prompt })
}
Write-Host ("Loaded {0} prompts" -f $items.Count)

function Send-ImageRequest([string]$prompt) {
    $body = @{
        model                       = $Model
        prompt                      = $prompt
        size                        = $Size
        response_format             = 'url'
        watermark                   = $false
        sequential_image_generation = 'disabled'
    } | ConvertTo-Json -Depth 5
    $content = New-Object System.Net.Http.StringContent($body, [System.Text.Encoding]::UTF8, 'application/json')
    $msg = New-Object System.Net.Http.HttpRequestMessage('Post', $ApiUrl)
    $msg.Headers.Authorization = New-Object System.Net.Http.Headers.AuthenticationHeaderValue('Bearer', $ApiKey)
    $msg.Content = $content
    return $client.SendAsync($msg)
}

$results = @{}
$pending = @($items)

for ($round = 1; $round -le ($MaxRetry + 1); $round++) {
    if ($pending.Count -eq 0) { break }
    Write-Host ("--- Round {0}: {1} pending ---" -f $round, $pending.Count)

    $tasks = @{}
    foreach ($it in $pending) {
        $tasks[$it.Id] = Send-ImageRequest $it.Prompt
    }
    [System.Threading.Tasks.Task]::WaitAll(@($tasks.Values))

    $next = New-Object System.Collections.ArrayList
    foreach ($it in $pending) {
        $id = $it.Id
        try {
            $resp = $tasks[$id].Result
            $text = $resp.Content.ReadAsStringAsync().Result
        } catch {
            Write-Host ("[{0}] attempt {1} exception: {2}" -f $id, $round, $_.Exception.Message)
            [void]$next.Add($it)
            continue
        }
        if (-not $resp.IsSuccessStatusCode) {
            Write-Host ("[{0}] attempt {1} HTTP {2}: {3}" -f $id, $round, [int]$resp.StatusCode, $text)
            [void]$next.Add($it)
            continue
        }
        $json = $text | ConvertFrom-Json
        if ($json.error) {
            Write-Host ("[{0}] attempt {1} error {2} - {3}" -f $id, $round, $json.error.code, $json.error.message)
            $results[$id] = @{ Ok = $false; Url = $null; Size = $null; Attempts = $round; Error = ("{0}: {1}" -f $json.error.code, $json.error.message) }
            [void]$next.Add($it)
            continue
        }
        if ($json.data.Count -gt 0 -and $json.data[0].url) {
            $ext = if ($json.data[0].output_format) { $json.data[0].output_format } else { 'jpeg' }
            $results[$id] = @{ Ok = $true; Url = $json.data[0].url; Size = $json.data[0].size; Ext = $ext; Attempts = $round; Error = '' }
            Write-Host ("[{0}] OK {1} ({2}, attempt {3})" -f $id, $json.data[0].size, $ext, $round)
        } else {
            Write-Host ("[{0}] attempt {1} empty data" -f $id, $round)
            $results[$id] = @{ Ok = $false; Url = $null; Size = $null; Attempts = $round; Error = 'empty data' }
            [void]$next.Add($it)
        }
    }
    $pending = @($next)
    if ($pending.Count -gt 0) { Start-Sleep -Seconds (2 * $round) }
}

# 并行下载
$dl = @{}
foreach ($id in @($results.Keys)) {
    if ($results[$id].Ok) {
        $ext = $results[$id].Ext
        $dl[$id] = @{ Task = $client.GetByteArrayAsync($results[$id].Url); File = (Join-Path $OutDir ("{0}.{1}" -f $id, $ext)) }
    }
}
if ($dl.Count -gt 0) {
    [System.Threading.Tasks.Task]::WaitAll(@($dl.Values | ForEach-Object { $_.Task }))
}

$report = New-Object System.Collections.ArrayList
foreach ($it in $items) {
    $id = $it.Id
    $r = $results[$id]
    if ($null -eq $r -or -not $r.Ok) {
        $attempts = if ($r) { $r.Attempts } else { 0 }
        $err      = if ($r) { $r.Error  } else { 'not attempted' }
        [void]$report.Add([pscustomobject]@{ Id = $id; Status = 'FAILED'; Path = ''; Size = ''; Attempts = $attempts; Error = $err })
        continue
    }
    $file = $dl[$id].File
    try {
        [System.IO.File]::WriteAllBytes($file, $dl[$id].Task.Result)
        [void]$report.Add([pscustomobject]@{ Id = $id; Status = 'OK'; Path = $file; Size = $r.Size; Attempts = $r.Attempts; Error = '' })
    } catch {
        [void]$report.Add([pscustomobject]@{ Id = $id; Status = 'DOWNLOAD_FAILED'; Path = $file; Size = $r.Size; Attempts = $r.Attempts; Error = $_.Exception.Message })
    }
}

Write-Host ''
Write-Host '===== REPORT ====='
$report | ForEach-Object { Write-Host ("{0}`t{1}`t{2}`t{3}`t{4}" -f $_.Id, $_.Status, $_.Size, $_.Path, $_.Error) }
$report | ConvertTo-Json -Depth 5 | Set-Content -Path (Join-Path $OutDir 'generate_report.json') -Encoding UTF8

$failedCount = @($report | Where-Object { $_.Status -ne 'OK' }).Count
if ($failedCount -gt 0) { Write-Host ("FAILED: {0}" -f $failedCount); exit 1 }
Write-Host 'ALL DONE'
```


```

---


### 7.2 `scripts/generate_tts_ws.py`

> 路径：`scripts/generate_tts_ws.py`
> 调用：`python scripts/generate_tts_ws.py --book-dir <书目录>`
> 依赖：`scripts/tts_ws_proto/protocols.py`（字节官方 SDK，含二进制帧编解码）

```python
"""
豆包语音 TTS - WebSocket 双向流式 (bidirection) - 全 7 段生成器

路径:
  - URL: wss://openspeech.bytedance.com/api/v3/tts/bidirection
  - Resource-Id: seed-tts-2.0   (账户开通的是 2.0, 不是 1.0)
  - Speaker: zh_male_m191_uranus_bigtts   (云舟 2.0 通用男声, 2.0 兼容)
  - Auth: X-Api-Key

每段独立建一次 WebSocket 连接 (task_request 完成后立即 finish_session).
"""
import argparse
import asyncio
import json
import re
import sys
import time
import uuid
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR / "tts_ws_proto"))

from protocols import (  # noqa: E402
    EventType, MsgType,
    start_connection, start_session, finish_session, finish_connection,
    task_request, receive_message,
)
import websockets  # noqa: E402

API_KEY     = "88e1060b-73c2-42ee-8cf2-a8afb326d4cb"
RESOURCE_ID = "seed-tts-2.0"
SPEAKER     = "zh_male_m191_uranus_bigtts"
WS_URL      = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"
SAMPLE_RATE = 24000

# 通过命令行 --book-dir 传入; 默认与脚本同级的书的结构
DEFAULT_BOOK_DIR = SCRIPT_DIR.parent
LOG_FILE_DEFAULT = SCRIPT_DIR / "logs" / f"tts_ws_{time.strftime('%Y%m%d_%H%M%S')}.log"

# 用 argparse 注入 book-dir 后再赋值全局
_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument("--book-dir", default=str(DEFAULT_BOOK_DIR))
_args, _remaining = _parser.parse_known_args()
ROOT = Path(_args.book_dir)
MD_FILE  = ROOT / "剧本" / "01-标题与旁白文案.md"
AUDIO_DIR = ROOT / "音频"
AUDIO_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_FILE_DEFAULT
LOG_FILE.parent.mkdir(exist_ok=True)
REPORT_FILE = AUDIO_DIR / "tts_report.json"


def log(msg: str):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def speech_rate(speed: float) -> int:
    r = int((speed - 1.0) * 100)
    return max(-50, min(100, r))


def parse_narration(md_text: str):
    """从 01-标题与旁白文案.md 提取 s0|s1|... 的旁白段."""
    code_re = re.compile(r'(?s)```\r?\n(s\d+\|.+\|speed=[\d.]+)\r?\n```')
    m = code_re.search(md_text)
    if not m:
        raise RuntimeError("未在 01-标题与旁白文案.md 中找到 ```s0|...``` 代码块")
    items = []
    for line in m.group(1).splitlines():
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) < 3:
            continue
        sid = parts[0].strip()
        text = parts[1]
        speed = 1.0
        try:
            speed = float(parts[2].strip().split("=")[1])
        except (IndexError, ValueError):
            pass
        items.append({"id": sid, "text": text, "speed": speed})
    return items


async def synth_one(item: dict, retries: int = 2) -> dict:
    sid  = item["id"]
    text = item["text"]
    speed = item["speed"]
    rate = speech_rate(speed)
    out_file = AUDIO_DIR / f"{sid}.mp3"

    sess_payload = json.dumps({
        "user": {"uid": f"u-{uuid.uuid4().hex[:8]}"},
        "req_params": {
            "speaker": SPEAKER,
            "audio_params": {
                "format": "mp3",
                "sample_rate": SAMPLE_RATE,
                "speech_rate": rate,
            },
        },
    }, ensure_ascii=False).encode("utf-8")

    task_payload = json.dumps({
        "user": {"uid": f"u-{uuid.uuid4().hex[:8]}"},
        "event": 200,
        "namespace": "BidirectionalTTS",
        "req_params": {"text": text},
    }, ensure_ascii=False).encode("utf-8")

    last_err = ""
    for attempt in range(1, retries + 2):
        audio = bytearray()
        try:
            headers = [
                ("X-Api-Key", API_KEY),
                ("X-Api-Resource-Id", RESOURCE_ID),
                ("X-Api-Request-Id", str(uuid.uuid4())),
            ]
            log(f"[{sid}] attempt {attempt}: connecting...")
            async with websockets.connect(
                WS_URL,
                additional_headers=headers,
                ping_interval=20,
                max_size=10 * 1024 * 1024,
                close_timeout=10,
            ) as ws:
                await start_connection(ws)
                msg = await receive_message(ws)
                if msg.event != EventType.ConnectionStarted:
                    raise RuntimeError(f"connect event={msg.event} payload={msg.payload!r}")

                session_id = str(uuid.uuid4())
                await start_session(ws, sess_payload, session_id)
                msg = await receive_message(ws)
                if msg.event != EventType.SessionStarted:
                    raise RuntimeError(f"session event={msg.event} payload={msg.payload!r}")

                await task_request(ws, task_payload, session_id)
                await finish_session(ws, session_id)

                while True:
                    msg = await receive_message(ws)
                    if msg.type == MsgType.Error:
                        raise RuntimeError(f"server error code={msg.error_code} payload={msg.payload!r}")
                    if msg.event == EventType.TTSResponse:
                        if msg.payload:
                            audio.extend(msg.payload)
                    elif msg.event == EventType.SessionFinished:
                        break
                    elif msg.event == EventType.SessionFailed:
                        raise RuntimeError(f"session failed: {msg.payload!r}")

                await finish_connection(ws)
                try:
                    while True:
                        msg = await receive_message(ws)
                        if msg.event == EventType.ConnectionFinished:
                            break
                except Exception:
                    pass

            out_file.write_bytes(bytes(audio))
            log(f"[{sid}] OK: {out_file} ({len(audio)} bytes, rate={rate})")
            return {
                "id": sid, "status": "OK", "path": str(out_file), "bytes": len(audio),
                "speed": speed, "speech_rate": rate, "attempts": attempt, "error": "",
            }
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            log(f"[{sid}] attempt {attempt} failed: {last_err}")
            if attempt <= retries:
                wait = 3 * attempt
                log(f"[{sid}] retrying in {wait}s...")
                await asyncio.sleep(wait)

    return {
        "id": sid, "status": "FAILED", "path": "", "bytes": 0,
        "speed": speed, "speech_rate": rate, "attempts": retries + 1, "error": last_err,
    }


async def main():
    md = MD_FILE.read_text(encoding="utf-8")
    items = parse_narration(md)
    log(f"loaded {len(items)} narration lines")

    results = []
    for item in items:
        r = await synth_one(item, retries=2)
        results.append(r)

    REPORT_FILE.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    log("===== REPORT =====")
    for r in results:
        log(f"{r['id']}\t{r['status']}\t{r['bytes']}\t{r['path']}\tattempt={r['attempts']}\trate={r['speech_rate']}\terr={r['error']}")

    failed = sum(1 for r in results if r["status"] != "OK")
    log(f"failed: {failed}/{len(results)}")
    if failed:
        sys.exit(1)
    log("ALL DONE")


if __name__ == "__main__":
    asyncio.run(main())
```

### 7.2.1 协议 SDK: `scripts/tts_ws_proto/protocols.py`

> 字节跳动官方 Python SDK，封装了双向流式协议的二进制帧编解码（version/header_size/msg_type/flags/serialization/compression）和高层函数（`start_connection/start_session/task_request/finish_session/finish_connection`）。
>
> **获取方式**：从字节官方文档下载 `TTS Websocket Bidirection protocols.zip`，解压取 `protocols_.py` 改名为 `protocols.py` 放到 `scripts/tts_ws_proto/`。
>
> SDK 关键定义（无需修改）：`EventType.ConnectionStarted=150`, `SessionStarted=150`, `SessionFinished=152`, `ConnectionFinished=152`, `TTSResponse=352`, `SessionFailed=351`, `MsgType.FullClientRequest=0b0010`, `MsgType.FullServerResponse=0b1001`, `MsgType.Error=0b1011`。
>
> 本技能目录已包含完整副本（559 行），直接复用即可。

---

### 7.3 `scripts/compose_video.py`

> 路径：`scripts/compose_video.py`
> 调用：`python scripts/compose_video.py --book-dir <书目录> --ffmpeg <ffmpeg.exe 路径>`
> 依赖：`图片/sN.jpeg`、`音频/sN.mp3`

```python
"""
合成 7 张图 + 7 段音频 -> 最终视频.mp4

策略:
  1. 测每段 mp3 时长 (ffprobe)
  2. 每张图等比缩放塞进 480x854, 黑边填充, 输出 png
  3. 每段: ffmpeg -loop 1 -i image.png -i audio.mp3 -t <duration> -c:v libx264 -pix_fmt yuv420p -c:a aac -ar 44100 -ac 2 -b:a 192k -r 25 -s 480x854 -> seg_N.mp4
  4. ffmpeg concat demuxer 拼接 -> 最终视频.mp4
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

# ---------------- 配置 ----------------
DEFAULT_FFMPEG = Path(__file__).resolve().parent / 'ffmpeg_bin' / 'ffmpeg.exe'

W, H = 480, 854                    # 9:16, 480p
FPS = 25
AUDIO_BITRATE = '192k'
SAMPLE_RATE = 44100

SEG_IDS = ['s0', 's1', 's2', 's3', 's4', 's5', 's6']


# ---------------- 工具 ----------------
def run(cmd: list[str], log_path: Path = None):
    """运行子进程, 输出写到 log 文件避免中文乱码"""
    print(f'>>> {" ".join(cmd[:6])}...')
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, 'wb') as f:
            r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT)
        if r.returncode != 0:
            print(f'!! exit={r.returncode}, tail of log:')
            with open(log_path, 'rb') as f2:
                data = f2.read()[-2000:]
            print(data.decode('utf-8', errors='replace'))
            sys.exit(1)
    else:
        r = subprocess.run(cmd)
        if r.returncode != 0:
            sys.exit(r.returncode)


def probe_duration_via_json(mp3: Path) -> float:
    """更稳: 让 ffmpeg 输出一行简短的 format 解析"""
    out = subprocess.run(
        [str(FFMPEG), '-hide_banner', '-i', str(mp3), '-f', 'null', '-'],
        capture_output=True,
    )
    import re
    txt = out.stderr.decode('utf-8', errors='replace')
    m = re.search(r'Duration:\s*(\d+):(\d+):(\d+\.\d+)', txt)
    if not m:
        raise RuntimeError(f'Cannot find duration in:\n{txt[-500:]}')
    h, mi, s = m.group(1), m.group(2), m.group(3)
    return int(h) * 3600 + int(mi) * 60 + float(s)


def letterbox_image(src_jpeg: Path, dst_png: Path):
    """等比缩放 src 进 W×H, 黑边填充"""
    from PIL import Image
    img = Image.open(src_jpeg).convert('RGB')
    sw, sh = img.size
    scale = min(W / sw, H / sh)
    nw, nh = int(sw * scale), int(sh * scale)
    img_resized = img.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new('RGB', (W, H), (0, 0, 0))
    canvas.paste(img_resized, ((W - nw) // 2, (H - nh) // 2))
    canvas.save(dst_png, 'PNG', optimize=False)


# ---------------- 主流程 ----------------
def main():
    parser = argparse.ArgumentParser(description='合成 7 图 + 7 音频 → 最终视频.mp4')
    parser.add_argument('--book-dir', required=True, help='书的项目目录（含 图片/、音频/ 子目录）')
    parser.add_argument('--ffmpeg', default=str(DEFAULT_FFMPEG), help='ffmpeg.exe 路径')
    args = parser.parse_args()

    global FFMPEG
    ROOT = Path(args.book_dir)
    FFMPEG = Path(args.ffmpeg)

    IMG_DIR = ROOT / '图片'
    AUD_DIR = ROOT / '音频'
    OUT_DIR = ROOT / '视频'
    WORK_DIR = OUT_DIR / '_work'
    FINAL = OUT_DIR / '最终视频.mp4'

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    print(f'=== BOOK: {ROOT.name} ===')
    print('=== STEP 1: 校验素材 ===')
    durations = {}
    for sid in SEG_IDS:
        img = IMG_DIR / f'{sid}.jpeg'
        aud = AUD_DIR / f'{sid}.mp3'
        if not img.is_file():
            sys.exit(f'!! 缺图片: {img}')
        if not aud.is_file():
            sys.exit(f'!! 缺音频: {aud}')
        d = probe_duration_via_json(aud)
        durations[sid] = d
        print(f'  {sid}: img={img.stat().st_size:>7}B  aud={aud.stat().st_size:>6}B  dur={d:.3f}s')

    print('=== STEP 2: 图片 letterbox ===')
    for sid in SEG_IDS:
        src = IMG_DIR / f'{sid}.jpeg'
        dst = WORK_DIR / f'{sid}.png'
        letterbox_image(src, dst)
        print(f'  {sid}: {W}x{H} -> {dst.name}')

    print('=== STEP 3: 每段合成 seg ===')
    seg_files = []
    for sid in SEG_IDS:
        png = WORK_DIR / f'{sid}.png'
        mp3 = AUD_DIR / f'{sid}.mp3'
        dur = durations[sid]
        seg = WORK_DIR / f'seg_{sid}.mp4'
        log = WORK_DIR / f'seg_{sid}.log'
        cmd = [
            str(FFMPEG), '-y', '-hide_banner', '-loglevel', 'error',
            '-loop', '1', '-framerate', str(FPS), '-i', str(png),
            '-i', str(mp3),
            '-t', f'{dur:.3f}',
            '-c:v', 'libx264', '-preset', 'medium', '-crf', '20',
            '-pix_fmt', 'yuv420p', '-r', str(FPS), '-s', f'{W}x{H}',
            '-c:a', 'aac', '-b:a', AUDIO_BITRATE, '-ar', str(SAMPLE_RATE), '-ac', '2',
            '-shortest',
            '-movflags', '+faststart',
            str(seg),
        ]
        run(cmd, log)
        seg_files.append(seg)
        print(f'  {sid}: {seg.stat().st_size} bytes')

    print('=== STEP 4: concat 拼接 ===')
    list_file = WORK_DIR / 'concat.txt'
    with open(list_file, 'w', encoding='utf-8') as f:
        for s in seg_files:
            f.write(f"file '{s.as_posix()}'\n")
    log = WORK_DIR / 'concat.log'
    cmd = [
        str(FFMPEG), '-y', '-hide_banner', '-loglevel', 'error',
        '-f', 'concat', '-safe', '0', '-i', str(list_file),
        '-c', 'copy',
        str(FINAL),
    ]
    run(cmd, log)
    print(f'  -> {FINAL}  {FINAL.stat().st_size} bytes')

    # 清理 work 目录
    try:
        for f in WORK_DIR.iterdir():
            f.unlink()
        WORK_DIR.rmdir()
    except Exception:
        pass

    print('=== STEP 5: 验证最终视频 ===')
    out = subprocess.run(
        [str(FFMPEG), '-hide_banner', '-i', str(FINAL)],
        capture_output=True,
    )
    txt = out.stderr.decode('utf-8', errors='replace')
    import re
    m = re.search(r'Duration:\s*(\d+):(\d+):(\d+\.\d+)', txt)
    if m:
        h, mi, s = m.group(1), m.group(2), m.group(3)
        total = int(h) * 3600 + int(mi) * 60 + float(s)
        print(f'  total duration: {total:.3f}s')
    else:
        total = sum(durations.values())
        print(f'  (duration parse failed, sum of parts = {total:.3f}s)')

    m2 = re.search(r'Stream #\d+:\d+.*Video.*?(\d+x\d+).*?(\d+\.?\d*)\s*fps', txt)
    if m2:
        print(f'  video: {m2.group(1)} @ {m2.group(2)} fps')
    m3 = re.search(r'Stream #\d+:\d+.*Audio.*?(\d+)\s*Hz', txt)
    if m3:
        print(f'  audio: {m3.group(1)} Hz')

    print()
    print(f'✅ DONE: {FINAL}')
    print(f'   size:  {FINAL.stat().st_size:,} bytes')


if __name__ == '__main__':
    main()
```

---

### 7.4 `scripts/generate_seedance_videos.py`（阶段 4 动态视频）

完整代码见附件 `scripts/generate_seedance_videos.py`（stdlib urllib 实现，无第三方依赖）。关键配置：

```python
API_BASE = "https://ark.cn-beijing.volces.com/api/v3"
MODEL_PRIMARY = "doubao-seedance-1-0-pro-fast-251015"
MODEL_LITE_BACKUP = "doubao-seedance-1-0-pro-250528"
MOTION_SUFFIX = "5 秒时长, 镜头缓慢推进, 主体保持轻微动态, 真实新闻纪录片风格"
WORKER_LIMIT = 4        # 并发任务数
POLL_INTERVAL = 5       # 轮询间隔(秒)
POLL_TIMEOUT = 240      # 单任务最长等待
```

- **鉴权**：`Authorization: Bearer <ARK_API_KEY>`，Key 只从环境变量 `ARK_API_KEY` 或 `--api-key` 读，日志只打印掩码（前8后4）
- **异步任务协议**：`POST /contents/generations/tasks` 提交（响应 JSON 的 `id` 字段是 task_id）→ `GET /contents/generations/tasks/{task_id}` 轮询 `status` → `succeeded` 后从 `content.video_url` 下载
- **请求体**：`content` 数组 = `[{"type":"text","text":提示词}, {"type":"image_url","image_url":{"url":"data:image/jpeg;base64,..."}}]` + `ratio:"9:16"` + `resolution:"480p"` + `duration:5` + `watermark:false`
- **图片输入**：base64 data URL（不走 URL 上传，避免外链可达性问题）
- **提示词来源**：`剧本/分镜/sN.md` 的 `## 画面描述` 章节正文 + 固定 motion 后缀

### 7.5 `scripts/compose_final_video.py`（阶段 5 最终合成）

完整代码见附件 `scripts/compose_final_video.py`。关键配置：

```python
SEG_IDS = [f"s{i}" for i in range(7)]
CRF = "17"; PRESET = "medium"
# 字幕样式: 微软雅黑 16px 白字黑边 底部居中
FORCE_STYLE = "FontName=Microsoft YaHei,FontSize=18,...,Alignment=2,MarginV=70"

# 每段 filter 链 (Ken Burns 方案, 严禁 reverse/乒乓):
vf = ("[0:v]setpts={ratio}*PTS,fps=24,"
      "scale=960:1728:flags=lanczos,"
      "zoompan=z='1+0.0004*on':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=480x864:fps=24,"
      "tpad=stop_mode=clone:stop_duration=0.6,format=yuv420p[v]")
```

- **CLI**：`--book-dir <书目录> --ffmpeg <ffmpeg.exe>` 必填；`--stage all|srt|seg|concat|burn` 分步
- **SRT 对齐**：从 `剧本/分镜/sN.md` 的 `## 字幕文案` 解析，按句拆分（。？！；），段内按字符数加权分配时间，`wrap_line` 每行≤10 字，输出 `_tmp_compose/subs_aligned.srt`（UTF-8-BOM）
- **烧字幕**：`cwd` 切到 srt 所在目录用**相对路径**引用（Windows 盘符冒号在 filter 里转义极易翻车，见 §8.17），同时 `-c:s mov_text` 封装软字幕轨
- **自测三件套**：①逐段 0.2s 步进帧 diff（max/med < 6 = 无突刺）②merged vs final 像素 diff（差异集中在底部字幕区 = 字幕已写入）③ffprobe 查 `Subtitle: mov_text` 流 + 30s 抽帧存 `字幕验证帧_30s.jpg`

---

## 八、避坑经验（重点！每条都踩过坑）


### 8.1 ARK Key 格式

- ✅ 必须是 `ark-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx-xxxxxx` 格式
- ❌ JWT 格式（`xxx.ChB...`）会被拒
- ❌ Key 末尾被截断（如 `ark-1d9db452-0bac-4804-b500-6bac.`）会报 `API key format is incorrect`
- ARK Key **不能**用于豆包语音，反之亦然——两套独立凭据

### 8.2 豆包 TTS：Resource-Id 选择

| 你的账户开通情况 | 用的 Resource-Id | 错误表现（如果不对） |
| --- | --- | --- |
| 开通了 1.0 | `seed-tts-1.0` | 报 `55000000 resource ID is mismatched with speaker related resource`（用了 2.0 专属音色） |
| 开通了 2.0（推荐） | `seed-tts-2.0` | 报 `[resource_id=volc.service_type.10029] requested resource not granted`（如果用 1.0） |
| 都没开 | — | 单向 HTTP 报 `45000030`；双向 WebSocket 报 `403 + service_type 10029 not granted` |

**如何确认你开了哪个**：用 curl HEAD 探针，看握手是 101 还是 403：
```bash
curl -i -H "Connection: Upgrade" -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
  -H "X-Api-Key: <your-key>" -H "X-Api-Resource-Id: seed-tts-2.0" \
  https://openspeech.bytedance.com/api/v3/tts/bidirection
```
- 返回 `HTTP/1.1 101` → 该版本开通了
- 返回 `HTTP/1.1 403 + resource not granted` → 没开通

### 8.3 豆包 TTS：Speaker 必须匹配 Resource-Id

- **`seed-tts-1.0` 用的音色**：BV 系列（如 `BV002_streaming`）或 `*_mars_bigtts`
- **`seed-tts-2.0` 用的音色**：**必须 `*_uranus_bigtts` 结尾**
  - 推荐：`zh_male_m191_uranus_bigtts`（云舟 2.0 通用男声，已验证）
  - 其他：`zh_male_taocheng_uranus_bigtts`（小天 2.0）、`zh_female_xiaohe_uranus_bigtts`（小何 2.0）

### 8.4 WebSocket 双向流协议：协议流程陷阱

**最容易错的两个动作**：

1. **start_session 的 payload 不带 text**。text 必须由 `task_request` 发送。
2. **task_request 之后必须立即 finish_session**。否则服务端不会主动结束事件循环，会一直 hang 住。

完整流程：
```
start_connection → 等 ConnectionStarted (1xx event, type=FullServerResponse)
→ start_session(payload 只设 speaker + audio_params) → 等 SessionStarted (event=150)
→ task_request(payload 设 req_params.text) → 立即 finish_session
→ 循环收消息：TTSResponse (event=352) 累加音频 bytes / MsgType.Error 报错
→ 直到 SessionFinished (event=152) → finish_connection
→ 等 ConnectionFinished (event=152) 收尾
```

### 8.5 WebSocket 连接重试

- 服务端偶发限流时（30 秒内开 7 个连接），某个 segment 会卡死
- 解决：脚本内置 `retries=2`，每次失败 `asyncio.sleep(3 * attempt)` 退避重试
- 7 段都跑通约 25 秒；如果单段超过 60 秒没回，应在脚本里手动中断重跑该段

### 8.6 图片命名冲突

- **复用 `图片/` 目录前必须清空旧文件**，否则新生成的 sN.jpeg 可能与旧文件大小相同被误判为"没新生成"
- 解决：每次开新书就建新子目录（按本技能结构自动隔离）；如果重跑同一本书，先 `rm 图片/s*.jpeg`

### 8.7 音视频时长对齐

**问题**：ffmpeg `-t <duration>` 在某些版本会因为帧率转换误差导致视频时长比音频长 1~2 帧（出现黑屏或静音尾巴）
**解决**：用 `-shortest` 选项（让 ffmpeg 以先结束的流为准）+ `+faststart`（让 mp4 元数据写到头部，便于网页播放）

**校验**：合成完成后用 `ffmpeg -i 最终视频.mp4` 看 `Duration:`，应与各段 mp3 时长之和误差 < 50ms。

### 8.8 PowerShell 中文编码

- PS 5.1 子进程中 `SetConsoleOutputCP(65001)` **无效**（控制台继承父进程编码）
- 不要把中文路径当命令行参数传——会乱码
- 解决：
  - 用 `$PSScriptRoot` 推算脚本所在目录，再相对推书目录
  - 输出到日志时用 `Add-Content -Encoding UTF8` 镜像一份到 UTF-8 文件
  - `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8` + `$OutputEncoding = [System.Text.Encoding]::UTF8` 必须在脚本开头同时设置

### 8.9 ffmpeg 来源

- 系统中可能没装 ffmpeg
- 推荐路径：从 PyPI 拉 `imageio_ffmpeg` wheel（30MB），解 zip 取 `imageio_ffmpeg/binaries/ffmpeg-win-x86_64-vN.N.exe`，改名为 `ffmpeg.exe`
- 完整 wheel 下载地址示例：
  `https://files.pythonhosted.org/packages/2c/c6/fa760e12a2483469e2bf5058c5faff664acf66cadb4df2ad6205b016a73d/imageio_ffmpeg-0.6.0-py3-none-win_amd64.whl`

### 8.10 Python pip 装本地 wheel 失败

- 即使 wheel 文件本身合法，`pip install <本地路径>` 在中文路径下会报 `Invalid wheel filename`
- 解决：把 wheel 复制到无中文路径再装（如 `C:\Users\admin\xxx.whl`），或直接 `zipfile.ZipFile` 解压到 site-packages
- 本技能推荐方案：把 ffmpeg.exe 解出来放在 `scripts/ffmpeg_bin/` 下，调用时显式指定路径

### 8.11 bash 中文路径陷阱

- bash 双引号内嵌套中文 + 反斜杠 + 复杂表达式时，参数会被截断
- 解决方案：用 `python -c "..."` 替代 bash 多行逻辑；或 PowerShell 直接调用（PowerShell 对 UTF-16 处理更稳）

### 8.12 PNG 与 JPEG 转换

- ffmpeg `-loop 1 -i image.jpeg -t ...` 对 JPEG 兼容性差，部分版本会重复编码
- 解决：先用 Pillow 把 JPEG 转 PNG（letterbox 阶段一并完成），再 `-loop 1 -i image.png`

### 8.13 ffmpeg 流复制拼接要求

- 各段 seg_N.mp4 编码参数必须完全一致（分辨率、帧率、profile、level、pixel format）
- 本技能把所有段编码都跑同一个 `ffmpeg` 命令，参数一致 → 用 `-c copy` 拼接 0 误差
- 如果用 `-c:v libx264 -c:a aac` 重编码拼接，会引入 100~500ms 的卡顿和画面突变

### 8.14 各书视觉风格必须重设计

- 不要把《娱乐至死》的"冷色霓虹 + 现代媒介"风格套到《乌合之众》上
- 《乌合之众》用"暖褐复古 + 1895 巴黎 + 油画质感"完全不同
- 提示词必须包含：世界观、色彩基调、明确排除项、固定尾缀 四要素

### 8.15 【核心】TTS 密钥与 ARK 密钥不通用

- ARK Key（`ark-` 开头，方舟控制台）：只能调方舟系 API（Seedream 图片、Seedance 视频）
- 豆包语音 Key（UUID 格式，语音控制台）：只能调 `openspeech.bytedance.com`
- 拿 ARK Key 调 TTS 会报 `45000010 Invalid X-Api-Key`；反之 TTS Key 调方舟会 401
- **脚本里两套 Key 必须分开配置**，TTS 走 `X-Api-Key` 请求头，ARK 走 `Authorization: Bearer`

### 8.16 【核心】TTS 必须走 seed-tts-2.0 WebSocket 双向流

- 大多数账户只开通了 `seed-tts-2.0`（不是 1.0）；单向 HTTP `/api/v3/tts/unidirectional` 走 1.0 通道会报 `45000030`
- 正确路径：`wss://openspeech.bytedance.com/api/v3/tts/bidirection` + `X-Api-Resource-Id: seed-tts-2.0`
- 2.0 音色必须 `*_uranus_bigtts` 结尾（BV 系列会报 `55000000 resource mismatch`）
- 协议关键：`task_request` 后**必须立即** `finish_session`，否则服务端不推结束事件、永久 hang
- 不确定开通情况时，先用 curl 探针看握手 101/403（见 §8.2）

### 8.17 【核心】禁止乒乓倒放凑时长，必须用 zoompan 推近

- 音频 14~22s/段，Seedance 视频只有 5s/段，需要把视频"拉长"
- ❌ **`reverse` / 正放-倒放乒乓循环**：观感是画面"来回鬼畜"，用户明确否决，代码里不得出现
- ❌ **顺序循环 + crossfade**：20s 旁白要循环 4 轮，观众能察觉重复镜头，接缝叠化有重影
- ❌ **纯 setpts 慢放**：2.8~4.3 倍慢放后帧间变化低于肉眼阈值，画面看起来像静态图
- ✅ **正确方案（Ken Burns）**：`setpts 慢放 + zoompan 单向缓慢推近`。2x 预放大（scale=960:1728 lanczos）后再 zoompan 裁回 480x864，消除低分辨率抖动；`z='1+0.0004*on'` 约 19%/20s 的温和放大
- 自测方法：0.2s 步进帧 diff 序列，max/med < 6 无突刺；对比段首/段尾帧确认单向推近

### 8.18 字幕烧录：Windows 路径转义是重灾区

- `subtitles` 滤镜的 filename 在 Windows 下极难转义：盘符冒号、反斜杠、单引号三层转义互相干扰，还可能被"静默忽略"（命令成功但画面无字）
- **稳定做法**：把 SRT 和 ffmpeg 的工作目录放一起（如 `_tmp_compose/`），`subprocess.run(..., cwd=tmp_dir)` 后用**纯相对路径** `subtitles='subs_aligned.srt'`
- 双保险：同一条命令加 `-c:s mov_text -metadata:s:s:0 language=chi` 封装软字幕轨，播放器可选
- **必须客观自测**，不能只看命令退出码：像素 diff（对比烧录前后同时间戳帧，差异应集中在底部字幕区）+ ffprobe 查字幕流 + 抽帧人眼确认

### 8.19 Seedance 能力边界与对齐偏差

- `doubao-seedance-1-0-pro-fast-251015` **不支持 `flf2v` 首尾帧**（服务端报 `the specified task_type flf2v does not support model ...`），只能单图 i2v；不要浪费提交次数去试
- **用量限额**：账户开启"安全体验模式"时，pro-fast 单日生成几条就会报 `SetLimitExceeded`（模型服务暂停）。解法二选一：①控制台模型激活页调整/关闭安全体验模式；②换备选模型 `doubao-seedance-1-0-pro-250528`（已验证可用）。**lite 系列（lite-250428 / lite-i2v-250428）多数账户无权限**，报 `InvalidEndpointOrModel.NotFound`，不要浪费时间
- 脚本支持 `--model` 换模型、`--only s3,s4` 只补跑失败段，报告 `_report.json` 会被最后一次运行覆盖（补跑后注意手工核对 7 段文件是否齐全）
- 返回视频实际分辨率是 **480×864**（1:1.8），不是严格数学 9:16（1:1.778）——服务端四舍五入，合成脚本一律按 864 高度处理，不要写死 854
- `-shortest` 截齐后成品可能比音频总长多 1~2s（逐段累积），对齐精度要求高时以 `-t` 逐段精确截断


---

## 九、执行步骤（端到端运行指南）

### 9.1 准备目录（每本书一次）

```powershell
# 假设工作空间在 C:\Users\admin\WorkBuddy\名著介绍
$book = '《新书名》'
$root = "C:\Users\admin\WorkBuddy\名著介绍\$book"
New-Item -ItemType Directory -Path $root -Force | Out-Null
New-Item -ItemType Directory -Path "$root\剧本" -Force | Out-Null
New-Item -ItemType Directory -Path "$root\剧本\分镜" -Force | Out-Null
New-Item -ItemType Directory -Path "$root\脚本" -Force | Out-Null
```

把 `scripts/` 里的脚本**符号链接**或**复制**到 `$root\脚本\`（推荐用复制，避免路径耦合）。

### 9.2 写 `剧本/01-标题与旁白文案.md`

模板（直接复制修改）：
```markdown
# 《{书名}》讲解视频 · 标题与旁白文案

## 一、视频标题

**《{书名}》——{金句副标题}**

## 二、旁白文案（7 段）

\`\`\`
s0|{引子}|speed=0.9
s1|{报幕}|speed=1.0
s2|{背景}|speed=1.0
s3|{论点一}|speed=1.0
s4|{论点二}|speed=1.0
s5|{论点三}|speed=1.0
s6|{收束}|speed=0.9
\`\`\`
```

### 9.3 写 `剧本/02-画面提示词.md` + `脚本/prompts.txt`

每段画面提示词必须：
- 写清主体、构图、色调、镜头运动
- 控制在 200 字以内
- 以统一的尾缀收尾

### 9.4 准备 ffmpeg.exe

把 ffmpeg.exe 放到 `scripts/ffmpeg_bin/`，或记下绝对路径：
```powershell
# 复制 ffmpeg 到本项目
Copy-Item 'C:\Users\admin\WorkBuddy\名著介绍\《娱乐至死》\脚本\ffmpeg_bin\ffmpeg.exe' "$root\脚本\ffmpeg_bin\ffmpeg.exe"
```

### 9.5 跑图片生成

```powershell
powershell -ExecutionPolicy Bypass -File scripts\generate_images.ps1 `
  -ApiKey '<ark-key>' `
  -BookDir "C:\Users\admin\WorkBuddy\名著介绍\《新书名》"
```

期望输出：
```
===== REPORT =====
s0  OK  720x1280  ...\图片\s0.jpeg
...
ALL DONE
```

### 9.6 跑音频生成

```powershell
python scripts\generate_tts_ws.py --book-dir "C:\Users\admin\WorkBuddy\名著介绍\《新书名》"
```

期望输出：
```
[s0] OK: ...\音频\s0.mp3 (157000 bytes, rate=-9)
...
ALL DONE
```

### 9.7 跑动态视频生成（Seedance）

```powershell
$env:ARK_API_KEY = '<ark-key>'   # 只放环境变量, 不进命令行/日志
python scripts\generate_seedance_videos.py `
  --book-dir "C:\Users\admin\WorkBuddy\名著介绍\《新书名》"
```

期望输出：
```
=== DONE: 7/7 OK ===
  report: ...\视频\动态片段\_report.json
```

### 9.8 跑最终合成（Ken Burns + 硬字幕）

```powershell
python scripts\compose_final_video.py `
  --book-dir "C:\Users\admin\WorkBuddy\名著介绍\《新书名》" `
  --ffmpeg "$root\脚本\ffmpeg_bin\ffmpeg.exe"
```

期望输出：
```
=== DONE ===
  ...\视频\最终动态视频.mp4
  33.6 MB, 132.0s, 480x864, H.264+AAC+mov_text
```

自测三件套会自动执行：逐段动态性/突刺表、像素 diff 验证字幕、ffprobe 字幕流、`字幕验证帧_30s.jpg` 抽帧。

### 9.9 校验产物

- 打开 `视频\最终动态视频.mp4`，确认：时长 ≈ 音频总长（131~150s）、分辨率 480×864、画面持续单向推近无倒放、字幕清晰可读、音频清晰无爆音
- 对照 `音频\tts_report.json`，确认 7 段全 OK
- 对照 `图片\generate_report.json`，确认 7 张全 OK
- 对照 `视频\动态片段\_report.json`，确认 7 段全 OK
- 播放器若支持字幕轨，确认"Chinese"软字幕轨存在（双保险之一）

---

## 十、已验证测试用例

### 10.1 《娱乐至死》（第一本，2026-09-14 跑通）

| 项 | 值 |
| --- | --- |
| 作者 | 尼尔·波兹曼（Neil Postman） |
| 出版年 | 1985 |
| 视觉风格 | 冷色霓虹 + 现代媒介 + 真实新闻纪录片 |
| 图片 | 7/7 OK（476~581KB/张，720×1280） |
| 音频 | 7/7 OK（112~173KB/段，25 秒总耗时） |
| 视频 | 132.01s，5.2MB，480×854@25fps，AAC 44100Hz |

### 10.2 《乌合之众》（2026-09-15 静态图版跑通；2026-09-28 全流程 5 阶段版跑通）

| 项 | 值 |
| --- | --- |
| 作者 | 古斯塔夫·勒庞（Gustave Le Bon） |
| 出版年 | 1895 |
| 视觉风格 | 暖褐复古 + 1895 巴黎 + 油画质感 |
| 图片 | 7/7 OK（400~600KB/张，720×1280，各 1 次成功） |
| 音频 | 7/7 OK（58~139KB/段，TTS 2.0 WebSocket，各 1 次成功） |
| 动态片段 | 7/7 OK（s0~s2 用 pro-fast；触发用量限额后 s3~s6 换 pro-250528 补跑） |
| 最终视频 | **98.62s，27.0MB，480×864，H.264 + AAC + mov_text 字幕轨**，14 条硬字幕，逐段动态性 27%~66%，自测三件套全过 |

测试产物：`C:\Users\admin\WorkBuddy\名著介绍\《乌合之众》\视频\最终动态视频.mp4`

### 10.3 跨书一致性验证

两本书结构、命令、产物完全一致，仅以下 3 个变量不同：
- 子文件夹名（书名）
- `剧本/01-...md`、`02-...md`、`脚本/prompts.txt` 内容
- `脚本/generate_tts_ws.py` 中的 TTS 风格（可保持同 Speaker，也可按书的性别气质切换）

证明技能具备可复用性。

---

## 十一、技能自检清单

> 每次跑新书前，把这份清单过一遍，能避免 90% 的问题。

- [ ] 书目录已建：`C:\...\《书名》\{剧本,剧本\分镜,脚本,图片,音频,视频}\`
- [ ] `剧本/01-标题与旁白文案.md` 写完，含 ```s0|...|speed=...``` 代码块
- [ ] `剧本/分镜/s0.md~s6.md` 写完，每段含 `## 字幕文案` + `## 画面描述`
- [ ] `脚本/prompts.txt` 写完，7 行，每行 `sN|提示词`
- [ ] `脚本/ffmpeg_bin/ffmpeg.exe` 已放好
- [ ] ARK Key 正确（`ark-` 开头）——图片和 Seedance 共用
- [ ] 豆包语音 Key 正确（UUID 格式），且 `seed-tts-2.0` 已开通——与 ARK Key 不通用（§8.15）
- [ ] 跑图片 → 看 `图片/generate_report.json` 7 行全 OK
- [ ] 跑 TTS → 看 `音频/tts_report.json` 7 行全 OK
- [ ] 跑 Seedance → 看 `视频/动态片段/_report.json` 7 段全 OK
- [ ] 跑合成 → 看 `视频/最终动态视频.mp4`、自测三件套全过（动态性 20%+、字幕 diff 集中底部、mov_text 流存在）
- [ ] 抽样播放 `音频/s3.mp3` 听音色是否合适（不合适换 Speaker 重跑 TTS）
- [ ] 重跑同一本书前：先清 `图片/s*.jpeg`、`音频/s*.mp3`、`视频/动态片段/s*.mp4`，避免新旧产物混淆

---

## 十二、已知限制 & 后续可扩展

| 限制 | 影响 | 可扩展方向 |
| --- | --- | --- |
| 固定 7 段结构 | 不适合纯抒情或纯科普型书 | 把 `SEG_IDS` 改成可配置 |
| 单 Speaker | 整本书一个声音，听感单调 | 用 OpenAI / Claude 生成多角色对话 |
| Seedance 仅单图 i2v | 片段之间无连续运镜（非首尾帧） | 换支持 flf2v 的模型（如 seedance pro 非fast版）做 6 组配对过渡 |
| 无背景音乐 | 听感偏单调 | 加一段低音量环境音/钢琴 loop |
| 无封面 | 视频开头没有书名卡 | 加一个 s0 之前的 cover 段（封面 + 书名 + 作者） |
| 全程 AI 文案 | 缺少人工校审 | 在 `剧本/01` 阶段插入"用户审稿 → 修改 → 确认"环节 |

---

## 附录 A：文件清单

技能根目录 `C:\Users\admin\WorkBuddy\名著介绍\名著讲解视频生成Skill\` 应包含：

```
skill.md                       # 本文档
scripts/
├── generate_images.ps1        # 阶段 2 图片生成（ARK Seedream）
├── generate_tts_ws.py         # 阶段 3 TTS 生成（豆包 2.0 WebSocket）
├── generate_seedance_videos.py# 阶段 4 动态视频生成（Seedance i2v）
├── compose_final_video.py     # 阶段 5 最终合成（Ken Burns + 硬字幕）【主用】
├── compose_video.py           # 备选：静态图+音频直接合成（无 Seedance 时）
└── tts_ws_proto/              # 字节官方协议 SDK（必须）
    ├── __init__.py
    └── protocols.py           # 559 行
```

> ffmpeg.exe 不打包进技能目录（每个项目独立放）。

---

**END**