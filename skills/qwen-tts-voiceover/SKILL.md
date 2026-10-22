---
name: qwen-tts-voiceover

description: "用本地 Qwen3-TTS（1.7B/0.6B Base）克隆指定音色，给 SRT 字幕稿逐句配音，产出音画同步的配音版成片。按动画工程能力二选一：路线 A 时间轴重映射 + 重渲染（语音优先，工程需支持 __SCENES/__CAPTIONS_LIST/__TIME_REMAP 注入）；路线 B fit-to-slot 零重渲染（画面优先，配音适配现有槽位与空档、直接并轨进无声母版，仅片尾语音溢出才延长视频）。当用户要求'用某个人的声音配音''克隆这个音色''给视频加配音''把音频抽出来仿这个说话人''SRT 转配音版视频''给无声成片加配音但别动画面'时使用。关键词：音色克隆、Qwen3-TTS、本地 TTS 配音、配音版、音画同步、字幕对齐、voice clone、音色替换、零重渲染"

version: "1.1.0"

author: "CodeBuddy AI"

created: "2026-10-20"

changelog: "1.1.0 新增路线 B「fit-to-slot 零重渲染」并落盘三个脚本：synthesize_srt_fitnext.py（fit-next 合成驱动）、merge_dub.py（并轨 + 仅 speech 冲片尾才 tpad 延长）、qa_report.py（manifest 汇总 + 中文计数归一化 adj_cer）。沉淀自《以日为鉴》17 集批量配音实战（2026-10-22/23）：用户拍板'配音保持自然速度优先、不硬塞槽位，视频多放几秒只适用于片尾'；新增路线选择决策表与预演法（按 6.62 字/s 估超槽/撞句）；修正'换配音必须整体重渲染'为路线 A 专属纪律；新增 adj_cer 判据（中文计数稿原 CER 虚高一个量级）、ASR artifact 甄别（繁体输出/数字形态差异非 TTS 错）、uv venv trampoline 损坏绕法、tpad 0.3s 垫尾误触发教训。 1.0.1 补两条实战教训：①`eval_voice.py` 支持直接读 align_report.json；②§3.5「被 Whisper 幻觉误导」+ §2.9 三实例对照。 1.0.0 首版。沉淀自《AI 逆向一切》配音版实战（REA 172s→179s）与 tts_qwen 本地部署：①ICL 音色克隆；②参考音干净收尾铁律；③三道采样防线（token 封顶/截断判定/音色+F0 双校验）；④三级对齐与 voice_timeline.js；⑤质量门禁。重点 bug 见 production-notes §2.2。"
---

# Qwen3-TTS 音色克隆配音 · 音画同步 SOP

> **Goal**：给定「一段参考音频 + 一份 SRT 字幕稿 + 一个已渲染的动画工程」，
> 产出**音色克隆自参考音频、且字幕/画面/音频三者严格同步**的配音版成片。

本 skill 解决两个独立但必须串起来的问题：

1. **音色从哪来** —— 本地 Qwen3-TTS Base 模型做零样本音色克隆（3~10s 参考音即可）；
2. **时间和画面对不上怎么办** —— 配音时长和原字幕槽位天然不等，按工程能力二选一：

| | **路线 A · 时间轴重映射 + 重渲染** | **路线 B · fit-to-slot 零重渲染** |
|---|---|---|
| 优先让谁 | **语音**：按语音重建时间轴，画面跟随 | **画面**：配音适配现有槽位/空档，视频一帧不改 |
| 工程要求 | 支持时间轴注入（`__SCENES`/`__CAPTIONS_LIST`/`__TIME_REMAP`） | **不需要注入点**（这正是它存在的意义） |
| 成本 | 逐集重渲染 + 关键帧签收（小时级） | 并轨（分钟级） |
| 适用 | handdrawn/dark-field 模板工程、语音显著长于槽位 | 无注入点的工程、已冻结系列、批量补水 |

> ⚠️ 路线 A 最容易低估的部分：换配音**不是**换一条音轨，
> 而是整条时间轴重建 + 画面重渲染。
> 路线 B 反过来：配音给画面让路，只在「会撞下一句」时提速，视频时间轴不动。

---

## 一、安装

本 skill 是 [vibe-video-skills](https://github.com/JustChenk/vibe-video-skills) 合集里的标准 Agent Skill 包，
位于仓库 `skills/qwen-tts-voiceover/`。

```bash
git clone https://github.com/JustChenk/vibe-video-skills.git ~/vibe-video-skills

# 项目级（Windows 用 junction，无需管理员）
mklink /J "<项目根>\.workbuddy\skills\qwen-tts-voiceover" "%USERPROFILE%\vibe-video-skills\skills\qwen-tts-voiceover"
# Linux/macOS
ln -s ~/vibe-video-skills/skills/qwen-tts-voiceover <项目根>/.workbuddy/skills/qwen-tts-voiceover
```

同时需要一份 **`tts_qwen` 运行时工程**（模型权重 + Python 环境），结构见
[references/environment-setup.md](references/environment-setup.md)。

---

## 二、路线选择（动手前先定）

两条路线共享阶段 1–3（参考音）与阶段 7（验收），区别只在「语音怎么落到时间轴上」。
**先做预演再选路线**，预演同时回答「这批字幕配得上配音吗」：

```python
# 按参考音实测语速估算（REA 实测 6.62 字/秒；不确定时先跑一小段manifest 取 avg_cps）
CPS = 6.62
for cue in cues:
    nat = len(去标点(cue.text)) / CPS
    slot = cue.end - cue.start
    nxt = 下一句.start（末条为 inf）
    超槽 += nat > slot
    撞句 += cue.start + nat > nxt - 0.05     # 会压到下一句 = 真问题
```

| 预演结果 | 选择 |
|---|---|
| 撞句 = 0，超槽为个位数 | **路线 B**（语音自然溢进空档，零重渲染） |
| 撞句成规模 / 语音显著长于槽位 | **路线 A**（重建时间轴 + 重渲染） |
| 工程无注入点 | **只能路线 B**（并接受中段溢出的听感取舍） |

路线 B 还有一道**前置门禁**：项目的字幕时间轴一致性检查必须 PASS
（scenes.js 的字幕窗 vs SRT 绝对时间逐条比对——这种错位肉眼看画面发现不了，
**配音一上就全片报废**）。旧写法工程检查输出 N/A 是「工具查不了」不是「没过检」，
人工抽 3 帧核对画面字幕与 SRT 再放行。

---

## 三、流水线总览

**路线 A（语音优先，时间轴重建）**：

```
参考视频/音频
   │ ① ffmpeg 抽音轨（48k 立体声备份 + 24k 单声道）
   ▼
BGM 混在一起的原声
   │ ② 人声分离（MelBand-RoFormer，去 BGM/音效）
   ▼
干净人声
   │ ③ pick_ref.py：词边界滑窗切 9~12s + **自然停顿处收尾** + 重新 ASR 得 ref_text
   ▼
参考音 ref.wav + ref.txt
   │ ④ tts_voiceover.py --engine qwen：逐句克隆 + 三级对齐
   ▼
voice.wav + voice_new.srt + align_report.json + voice_timeline.js
   │ ⑤ 关键帧审查签收 → 全量重渲染（帧数变了！）
   ▼
新 frames/
   │ ⑥ build_dub_video.py：帧 + 音轨 → 配音版成片
   ▼
配音版.mp4
   │ ⑦ eval_voice.py 验收（cos / F0 / CER / 句首多字）
   ▼
交付
```

**路线 B（画面优先，零重渲染）**：

```
参考音 ref.wav + ref.txt（同阶段 1–3，通常已存在，直接复用）
   │ ④-B 预演（撞句计数）+ 字幕时间轴门禁 PASS
   ▼
   │ ⑤-B synthesize_srt_fitnext.py --fit-next：逐句克隆，语音在
   │     「下一句起点-0.10s」与「槽位+1.5s」之间自然走，只在会撞下一句时提速
   ▼
voice.wav（按 SRT 绝对时间落位）+ manifest.json + cue_NNN.wav
   │ ⑥-B merge_dub.py --voice-end：视频流直拷 + aac 并轨；
   │     仅真实语音冲片尾才 tpad 克隆末帧延长
   ▼
<原名>_配音版.mp4（原无声母版不动）
   │ ⑦ eval_voice.py + qa_report.py 验收
   ▼
交付
```

---

## 四、分步执行

### 阶段 1 · 抽音轨

```bash
ffmpeg -y -i ref.mp4 -vn -c:a pcm_s16le -ar 48000 -ac 2 ref_full_48k.wav
ffmpeg -y -i ref_full_48k.wav -vn -c:a pcm_s16le -ar 24000 -ac 1 ref_full_24k.wav
```

> 24k 单声道是 Qwen3-TTS 的原生采样率，作为参考音输入最省心。

### 阶段 2 · 人声分离

```bash
export AUDIO_SEPARATOR_MODEL_DIR=<工程>/models/audio-separator
audio-separator ref_full_48k.wav \
  --model_filename melband_roformer_inst_v2.ckpt \
  --output_dir sep --output_format WAV --single_stem vocals --sample_rate 48000
```

`melband_roformer_inst_v2`（SDR 16.1）用于去伴奏。**不要跳过这步**：
参考音带着 BGM 一起喂给模型，克隆会把噪声特征也学进去。

### 阶段 3 · 选参考音（本 skill 最关键的一步）

```bash
python scripts/pick_ref.py assets/sep/vocals.wav assets/ref
```

脚本做四件事：词级时间戳 → 找停顿收尾点 → 切 9~12s → **对裁剪片段重新 ASR** 得到 `ref_text`。

**三条硬要求（缺一条就会出问题）**：

| 要求 | 判据 | 违反的后果 |
|---|---|---|
| 在**语音自然停顿处**收尾 | 见下方末采样判据 | 每句开头多出半个字（「的是」「大事」「得失」） |
| 尾部淡出 + 补 250ms 数字静音 | 末尾 200ms 峰值 ≈ 0 | 同上，且会带出咔哒声 |
| `ref_text` 必须对**裁剪后那段**重新 ASR | — | 文本与音频错位，克隆跑偏、吐字含糊 |

**末采样判据（最可靠的单一检查）**：

```python
w, sr = sf.read("ref.wav")
print(abs(w[-1]))                              # 应 < 0.01
print(np.max(np.abs(w[-200ms:])))              # 应 ≈ 0
```

对照实测：

| 参考音 | 末采样 | 最后 50ms 峰值 | 克隆句首 |
|---|---|---|---|
| 官方示例 `clone.wav` | **0.0000** | **0%** | `刷到一个App…` ✅ |
| 字中间硬切 | **0.331** | **75%** | `的是，刷到一个App…` ❌ |

> 为什么难以自查：ASR 有时会把开头那段杂音吞掉，只看转写文本会漏判。
> **一定要直接测波形末采样**。

> 同系列多集配音**复用同一条参考音**（如 `ref_cand1.wav`），跨集音色才一致；
> 换参考音 = 换音色，已配的集全部作废。

### 阶段 4A · 路线 A：逐句克隆 + 三级对齐

```bash
python scripts/tts_voiceover.py <字幕.srt> <voicework目录> \
  --project <动画工程目录> \
  --engine qwen --qwen-model 1.7b \
  --qwen-dir <tts_qwen 工程根> \
  --ref-audio <ref.wav> \
  --min-gap 0.12 --tail 0.5
```

产出：

| 文件 | 内容 |
|---|---|
| `voice.wav` | 整轨配音（44.1k 单声道 s16），已是最终时间轴 |
| `voice_new.srt` | 新时间轴字幕 |
| `align_report.json` | 逐句对账：`win`（原槽位）/ `tts`（实测）/ `new_start` / `overflow` / `tempo` |
| `voice_timeline.js` | 动画工程的时间轴注入段 |
| `take/NNN_qwen.wav` | 逐句音档，**可单句重做** |

**三级对齐逻辑**：

- **L1 句内变速**（可选 `--auto-tempo`）：只在句长严重超出槽位时压回，上限 `--max-tempo`
- **L2 吞并间隙**：句子起点 = `max(原起点, 前句结束 + min-gap)`，把所有留白借出来
- **L3 幕级重排**：幕**只增不减**（`max(原dur, 语音需求 + tail)`），画面靠 `__TIME_REMAP` 拉伸

> 为什么让幕只增不减：画面压缩会破坏动画的节奏感与可读性（贴纸墙读不完）。
> 宁可整体变长、画面变慢，也不要压短。

### 阶段 5A · 路线 A：重渲染（帧数会变，必须整体重渲）

`voice.wav` 时长变了 → 总帧数变了 → **旧的 frames/ 全部作废**。

```bash
# 1) 关键帧审查（多数工程有门禁，不能跳）
node <skill>/scripts/keyframes.js <video_voice.html> ./keyframes_voice
# 2) 逐张看联系表后签收
node <skill>/scripts/keyframes.js <video_voice.html> ./keyframes_voice --approve "逐张看过，无错位"
# 3) 全量渲染，--dur 用新时长
node <skill>/scripts/render.js <video_voice.html> ./frames_voice \
  --fps 24 --dur <新时长> --clean --review-dir ./keyframes_voice
```

**常见坑**：`render.js` 的 `--review-dir` 默认是 `./keyframes`，
签收目录另起名字时必须显式传，否则会报「没有有效签收」。

### 阶段 6A · 路线 A：合成成片

```bash
python scripts/build_dub_video.py ./frames_voice ./voicework/voice.wav ./配音版.mp4 --fps 24
```

### 阶段 4B · 路线 B：预演 + 拷字幕

跑第二节的预演脚本 + 项目字幕时间轴门禁（PASS 或旧写法人工抽帧核对）。
通过后**二进制拷贝**字幕到工作区：

```bash
cp <集目录>/字幕.srt assets/srt/epXX.srt     # 必须 cp，禁止用编辑工具碰 SRT
```

> 编辑工具（Write/Edit）落盘 SRT 会**吞全角标点**（`，：？` 变半角），
> 表现为质检时「全部条数文案不一致」。拷完用 `cmp` 验一致。

### 阶段 5B · 路线 B：fit-next 逐句合成

```bash
# 路线 B 三个脚本定位 tts_qwen 工程（模型权重 + tts_cli + venv）靠 TTS_QWEN_DIR；
# ffmpeg 不在 PATH 时设 VIBE_FFMPEG/VIBE_FFPROBE
export TTS_QWEN_DIR=<tts_qwen 工程根>
python scripts/synthesize_srt_fitnext.py --model 1.7b \
  --ref-audio assets/ref/ref_cand1.wav \
  --ref-text "$(cat assets/ref/ref_cand1.txt)" \
  --srt assets/srt/epXX.srt \
  --out-dir output/epXX \
  --seed 20261019
```

**fit-next 口径（2026-10-22 用户拍板）**：

- 可用窗口 = `min(下一句起点 - 0.10s, 槽位 + 1.5s)`——**配音保持自然速度优先**，
  不硬塞槽位，允许自然溢进那句字幕前的空档；
- 只在**会撞下一句**时才 `atempo` 提速（≤1.18x，保音高）；仍超才硬裁并记 `+trim` 待人工复核；
- 明显偏短（< 槽位 × 0.82）按槽放慢填充（≤1.10x）——字幕停之前声音别断；
- **末条不受下一句限制**：片尾溢出由并轨时视频延长消化；
- 中段溢出**不延时视频**：会把后续所有幕拖后、级联成整集重渲染，为零点几秒不值得。

产出（`out-dir` 内）：

| 文件 | 内容 |
|---|---|
| `full_raw.wav` | 整轨配音，长度 = max(末条 end, 语音实际结束) + 0.3s |
| `manifest.json` | 逐条 `start/slot/window/natural/final/over_slot/note/text` + 汇总计数 |
| `cue_NNN.wav` | 逐条音档，**可单句重做** |

### 阶段 6B · 路线 B：并轨（视频流直拷）

```bash
python scripts/merge_dub.py <无声母版.mp4> output/epXX/full_raw.wav \
  <集目录>/<原名>_配音版.mp4 \
  --voice-end <manifest.json 的 voice_end_sec>
```

- `--voice-end` **必须传 manifest 的 `voice_end_sec`**（真实语音结束点）。
  音轨全长含 0.3s 静音垫尾，用它判断片尾溢出会被垫尾误触发、白重编码一次（生产笔记 §5.4）；
- 延长分支（`voice_end` > 视频长）：`tpad=stop_mode=clone` 克隆末帧 + libx264 重编码，
  码率对齐原片（`--vb`，如 4.5M）——静态画面延长零成本，正是「视频多放几秒」的正确用法；
- 输出时长 = `max(视频长, voice_end)`；音频 aac 192k / 44.1k / 单声道；
- **原无声母版永不改动**；输出已存在则拒绝覆盖，先删再跑。

### 阶段 7 · 验收（两条路线共同）

```bash
# 逐句体检：音色余弦 / F0 / ASR 回环 CER（先算 embedding，释放模型再跑 ASR）
python scripts/eval_voice.py --model 1.7b --qwen-dir <tts_qwen> \
  --ref <ref.wav> --batch output/epXX/manifest.json --out output/epXX/eval.json

# 汇总：manifest 指标 + 变速/裁切/超槽清单 + adj_cer
python scripts/qa_report.py <配音目录>
```

- Pilot 集 **eval 全量**；批量可抽样：首/尾 2 条 + 全部变速/裁切条 + 每 10 条抽 1；
- **CER 看 `adj_cer` 不看原值**：字幕稿用中文计数（「二零零三年」「百分之五十五」「七成七」）时，
  Whisper 回环转写阿拉伯数字，原 CER 虚高一个量级（实测 0.139 → adj 0.025）。
  `qa_report.py` 已内置中文数字归一化；
- **ASR artifact 甄别**（别误判为 TTS 错、别去改没问题的字幕稿）：
  ① 繁体输出（「驚的是開局…」）是 Whisper 抽风；② 数字形态差异（2003 vs 二零零三）不是错；
  ③ CER 接近 1.0 先查音频是否采样崩坏（production-notes §3.5）；
- 残留的单字误读有基线：约 5/37 条、集中在不常见词（平账→屏障、派遣→派全、文部省→文布…）。
  是否定点重配由用户试听裁定——重配入口是 `cue_NNN.wav` 单句重做 + 重跑并轨。

---

## 五、质量门禁（四条，缺一不可）

| # | 指标 | 阈值 | 抓什么 |
|---|---|---|---|
| 1 | `spk_cos` 说话人余弦 | **≥ 0.95** | 音色漂移 |
| 2 | `F0` 中位基频 | **≥ 参考音 × 0.75** | **换成了另一个性别/音域的人** |
| 3 | 句首多字 | **0 / N** | 参考音尾音泄漏 |
| 4 | `CER` ASR 回环 | ≤ 0.10（**中文计数稿看 adj_cer**） | 吐字错误、幻觉文本 |

> **第 2 条不是可选项。** 实测中 0.6B/1.7B 都可能把某句崩成男声，
> 而 `spk_cos` 仍能到 0.92（过不了 0.95 但也能骗过 0.90 的旧阈值），
> **F0 会直接腰斩到 45%**，是最灵敏的单一判据。

---

## 六、硬性纪律

1. **参考音末采样必须 ≈ 0**，否则每句开头多半个字。见阶段 3。
2. **必须做音色 + F0 双校验**，不能只看时长。阈值别低于 0.95（详见 production-notes §2.2）。
3. **`max_new_tokens` 必须按句子长度封顶**（约 12.5 token/秒）。
   默认 `generation_config` 是 8192 ≈ 655 秒音频，采样进重复循环会「卡死」几分钟。
4. **`voice_timeline.js` 是单文件覆盖**：换引擎重配音必然覆盖上一版时间轴。
   换之前先备份 `voice_timeline.<旧引擎>_backup.js`。（仅路线 A）
5. **8GB 显存档位**：TTS 模型（3.9GB）和 Whisper（3GB）不能同时驻留。
   验收脚本已按「先算 embedding → 释放模型 → 再跑 ASR」分段。
6. **路线 A：换配音必须整体重渲染**，不能只换音轨。路线 B 反过来：
   视频一帧不动，只换/并音轨；只有 speech 冲片尾才 tpad 延长。
7. **路线 B 并轨必须传 `--voice-end`**（manifest 的 `voice_end_sec`）。
   0.3s 静音垫尾不是溢出，用音轨全长判断会误触发延长分支。
8. **SRT 只读**：拷贝使用，编辑工具会吞全角标点（阶段 4B）。
9. **同系列复用同一参考音**，换参考音 = 全系列重配（阶段 3）。

---

## 七、目录结构

**路线 A**：

```
<项目>/
├── assets/
│   ├── video/ref_full_48k.wav       # 抽出的原始音轨
│   ├── sep/vocals.wav               # 分离出的人声
│   └── ref/ref_cand1.wav + .txt     # 参考音 + 精确文本
├── voicework_qwen/
│   ├── voice.wav                    # 整轨配音（最终时间轴）
│   ├── voice_new.srt
│   ├── align_report.json
│   └── take/NNN_qwen.wav            # 逐句可重做
├── frames_voice_qwen/               # 重渲染的帧序列
├── keyframes_voice_qwen/            # 关键帧审查 + 签收
├── voice_timeline.js                # 注入段（现用）
├── voice_timeline_yunxi_backup.js   # 旧版备份
└── 配音版_Qwen.mp4
```

**路线 B**（以日为鉴实战布局）：

```
<集目录>/
├── <原名>.mp4                       # 无声母版（永不改动）
├── <原名>_配音版.mp4                # 交付：母版 + 配音并轨
├── 字幕.srt                         # 只读，禁编辑工具碰
└── 配音/
    ├── voice.wav                    # 整轨配音（从 full_raw.wav 拷贝）
    ├── manifest.json                # 逐条对账 + voice_end_sec
    ├── eval.json                    # eval_voice.py 验收明细
    └── qa_report.txt                # qa_report.py 汇总
```

tts_qwen 侧工作区：`assets/srt/epXX.srt`（拷入的字幕）、`output/epXX/`（合成产物 + 日志）。

---

## 八、与合集其它 skill 的边界

| Skill | 关系 |
|---|---|
| `handdrawn-explainer-video` / `dark-field-explainer-video` | 上游：产出无声成片 + `framework.js`（含 SCENES）+ `video_voice.html`。本 skill 消费它的工程与时间轴 |
| `bgm-beat-align` | 下游：配音版出来后再叠 BGM 卡点 |
| `douyin-cover-generator` | 无关，封面独立 |

**前置条件**：路线 A 要求动画工程支持时间轴注入（`window.__SCENES` / `window.__CAPTIONS_LIST` /
`window.__TIME_REMAP` 三个注入点），手绘与暗场两套模板已内置；
路线 B **不要求注入点**，但要求字幕时间轴与画面一致（项目侧 timeline 检查 PASS 或人工抽帧核对）。

---

## 九、实测数据（RTX 4060 Laptop 8GB）

| 项目 | 1.7B-Base | 0.6B-Base |
|---|---|---|
| 显存占用 | ≈ 3.9 GB | ≈ 2.0 GB |
| 生成速度 | 3s 音频约 5~7s（RTF ≈ 0.5×） | 同量级 |
| 50 句整篇（179s，路线 A） | 约 12 分钟 | 约 11 分钟 |
| 37 句整篇（165s，路线 B） | 约 5 分钟 | — |
| 音色相似度 | 0.9756~0.9867（A）｜0.9667~0.9846（B） | 0.9660~0.9834 |
| CER | 0.048（A）｜adj_cer 0.025~0.048（B，中文计数稿） | 0.053 |

**推荐 1.7B**：错字明显更少，显存也够用。0.6B 适合批量草稿。
