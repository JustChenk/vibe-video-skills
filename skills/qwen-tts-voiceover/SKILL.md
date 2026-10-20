---
name: qwen-tts-voiceover

description: "用本地 Qwen3-TTS（1.7B/0.6B Base）克隆指定音色，给 SRT 字幕稿逐句配音，并让字幕/画面/音频三者严格同步（三级对齐 + 时间轴重映射 + 重渲染）。当用户要求'用某个人的声音配音''克隆这个音色''给视频加配音''把音频抽出来仿这个说话人''SRT 转配音版视频'时使用。关键词：音色克隆、Qwen3-TTS、本地 TTS 配音、配音版、音画同步、字幕对齐、voice clone、音色替换"

version: "1.0.0"

author: "CodeBuddy AI"

created: "2026-10-20"

changelog: "1.0.0 首版。沉淀自《AI 逆向一切》配音版实战（REA 视频 172s→179s 配音重建）与 tts_qwen 本地部署。核心内容：①Qwen3-TTS Base 的 ICL 音色克隆用法（参考音 + ref_text 双输入）；②参考音**干净收尾**铁律（末采样≈0，否则每句开头多出半个字，如「的是」）；③逐句合成的三道采样防线（token 封顶 / 截断判定 / **音色+F0 双校验**）；④SRT→voice.wav 的三级对齐（L1 句内变速 / L2 吞 gap / L3 幕级重排）与 voice_timeline.js 时间轴重映射；⑤全流程质量门禁与验收指标。重点 bug 记录见 references/production-notes.md §2.2（第 21 条英文专名句采样崩成男声：F0 320Hz→144Hz、cos 0.9202、并出现幻觉文本「中文字幕志愿者 李宗盛」的重复循环症状，而旧阈值 0.90 把它放行了）。"
---

# Qwen3-TTS 音色克隆配音 · 音画同步 SOP

> **Goal**：给定「一段参考音频 + 一份 SRT 字幕稿 + 一个已渲染的动画工程」，
> 产出**音色克隆自参考音频、且字幕/画面/音频三者严格同步**的配音版成片。

本 skill 解决两个独立但必须串起来的问题：

1. **音色从哪来** —— 本地 Qwen3-TTS Base 模型做零样本音色克隆（3~10s 参考音即可）；
2. **时间和画面对不上怎么办** —— 配音时长和原字幕槽位天然不等，必须做**三级对齐**并重映射画面时间轴。

> ⚠️ 第 2 点是本 skill 最容易低估的部分：换配音**不是**换一条音轨，
> 而是整条时间轴重建 + 画面重渲染。

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

## 二、流水线总览

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

---

## 三、分步执行

### 阶段 1 · 抽音轨

```bash
ffmpeg -y -i ref.mp4 -vn -c:a pcm_s16le -ar 48000 -ac 2 ref_full_48k.wav
ffmpeg -y -i ref.mp4 -vn -c:a pcm_s16le -ar 24000 -ac 1 ref_full_24k.wav
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

### 阶段 4 · 逐句克隆 + 三级对齐

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

### 阶段 5 · 重渲染（帧数会变，必须整体重渲）

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

### 阶段 6 · 合成成片

```bash
python scripts/build_dub_video.py ./frames_voice ./voicework/voice.wav ./配音版.mp4 --fps 24
```

### 阶段 7 · 验收

```bash
python scripts/eval_voice.py --model 1.7b --qwen-dir <tts_qwen> \
  --ref <ref.wav> --batch ./voicework/align_report.json --out ./eval.json
```

---

## 四、质量门禁（四条，缺一不可）

| # | 指标 | 阈值 | 抓什么 |
|---|---|---|---|
| 1 | `spk_cos` 说话人余弦 | **≥ 0.95** | 音色漂移 |
| 2 | `F0` 中位基频 | **≥ 参考音 × 0.75** | **换成了另一个性别/音域的人** |
| 3 | 句首多字 | **0 / N** | 参考音尾音泄漏 |
| 4 | `CER` ASR 回环 | ≤ 0.10（参考值） | 吐字错误、幻觉文本 |

> **第 2 条不是可选项。** 实测中 0.6B/1.7B 都可能把某句崩成男声，
> 而 `spk_cos` 仍能到 0.92（过不了 0.95 但也能骗过 0.90 的旧阈值），
> **F0 会直接腰斩到 45%**，是最灵敏的单一判据。

---

## 五、硬性纪律

1. **参考音末采样必须 ≈ 0**，否则每句开头多半个字。见阶段 3。
2. **必须做音色 + F0 双校验**，不能只看时长。阈值别低于 0.95（详见 production-notes §2.2）。
3. **`max_new_tokens` 必须按句子长度封顶**（约 12.5 token/秒）。
   默认 `generation_config` 是 8192 ≈ 655 秒音频，采样进重复循环会「卡死」几分钟。
4. **`voice_timeline.js` 是单文件覆盖**：换引擎重配音必然覆盖上一版时间轴。
   换之前先备份 `voice_timeline.<旧引擎>_backup.js`。
5. **8GB 显存档位**：TTS 模型（3.9GB）和 Whisper（3GB）不能同时驻留。
   验收脚本已按「先算 embedding → 释放模型 → 再跑 ASR」分段。
6. **换配音必须整体重渲染**，不能只换音轨。

---

## 六、目录结构

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

---

## 七、与合集其它 skill 的边界

| Skill | 关系 |
|---|---|
| `handdrawn-explainer-video` / `dark-field-explainer-video` | 上游：产出无声成片 + `framework.js`（含 SCENES）+ `video_voice.html`。本 skill 消费它的工程与时间轴 |
| `bgm-beat-align` | 下游：配音版出来后再叠 BGM 卡点 |
| `douyin-cover-generator` | 无关，封面独立 |

**前置条件**：动画工程必须支持时间轴注入（`window.__SCENES` / `window.__CAPTIONS_LIST` /
`window.__TIME_REMAP` 三个注入点）。手绘与暗场两套模板都已内置。

---

## 八、实测数据（RTX 4060 Laptop 8GB）

| 项目 | 1.7B-Base | 0.6B-Base |
|---|---|---|
| 显存占用 | ≈ 3.9 GB | ≈ 2.0 GB |
| 生成速度 | 3s 音频约 5~7s（RTF ≈ 0.5×） | 同量级 |
| 50 句整篇（179s） | 约 12 分钟 | 约 11 分钟 |
| 音色相似度 | 0.9756~0.9867 | 0.9660~0.9834 |
| CER | 0.048 | 0.053 |

**推荐 1.7B**：错字明显更少，显存也够用。0.6B 适合批量草稿。
