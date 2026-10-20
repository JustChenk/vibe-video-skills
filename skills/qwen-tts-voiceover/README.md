# qwen-tts-voiceover

用**本地 Qwen3-TTS** 克隆指定音色，给 SRT 字幕稿逐句配音，
并让**字幕 / 画面 / 音频三者严格同步**——包括时间轴重建与画面重渲染。

> 纯本地推理，零 API 依赖。RTX 4060 Laptop 8GB 即可跑 1.7B。

---

## 它解决什么问题

给一个已经做好的无声动画视频配「某个人的声音」，有两个独立难点：

| 难点 | 本 skill 的做法 |
|---|---|
| **音色从哪来** | Qwen3-TTS Base 零样本克隆，3~10s 参考音即可 |
| **时间怎么对齐** | 三级对齐（L1 句内变速 / L2 吞 gap / L3 幕级重排）+ 时间轴重映射 |

> 换配音**不是**换一条音轨。配音时长和原字幕槽位天然不等，
> 整条时间轴会变，画面必须重渲染。

---

## 快速开始

```bash
# 1. 参考视频 → 干净人声
ffmpeg -y -i ref.mp4 -vn -c:a pcm_s16le -ar 48000 -ac 2 ref_48k.wav
audio-separator ref_48k.wav --model_filename melband_roformer_inst_v2.ckpt \
  --output_dir sep --single_stem vocals --sample_rate 48000

# 2. 切参考音（关键：自然停顿处收尾 + 补静音）
python scripts/pick_ref.py sep/vocals.wav assets/ref

# 3. 逐句克隆 + 三级对齐
python scripts/tts_voiceover.py 字幕.srt voicework --project ./工程 \
  --engine qwen --qwen-model 1.7b --qwen-dir ../tts_qwen \
  --ref-audio assets/ref/ref_cand1.wav

# 4. 关键帧审查 → 重渲染
node keyframes.js video_voice.html ./keyframes_voice --approve "逐张看过"
node render.js video_voice.html ./frames_voice --fps 24 --dur <新时长> \
  --clean --review-dir ./keyframes_voice

# 5. 合成 + 验收
python scripts/build_dub_video.py ./frames_voice voicework/voice.wav 配音版.mp4
python scripts/eval_voice.py --model 1.7b --qwen-dir ../tts_qwen \
  --ref assets/ref/ref_cand1.wav --batch voicework/align_report.json
```

---

## 四条质量门禁

| 指标 | 阈值 | 抓什么 |
|---|---|---|
| `spk_cos` 说话人余弦 | ≥ 0.95 | 音色漂移 |
| `F0` 中位基频 | ≥ 参考音 × 0.75 | **换性别/换音域** |
| 句首多字 | 0 / N | 参考音尾音泄漏 |
| `CER` ASR 回环 | ≤ 0.10 | 吐字、幻觉文本 |

---

## 三个必须知道的坑

1. **参考音末采样必须 ≈ 0**
   字中间硬切会让**每句开头多出半个字**（「的是」「大事」）。
   判据：`abs(w[-1]) < 0.01` 且末尾 200ms 峰值 ≈ 0。ASR 会漏判，必须测波形。

2. **音色校验阈值别低于 0.95**
   实测崩坏句 `spk_cos = 0.9202` 但 `F0` 从 320Hz 掉到 144Hz。
   0.90 的阈值会把男声放行——**F0 是唯一立刻暴露的判据**。

3. **`max_new_tokens` 必须按句子封顶**
   默认 8192 ≈ 655 秒音频，采样进重复循环会「卡死」几分钟，
   且症状很像死锁（GPU 50%、CPU 持续涨）。

详细复盘见 [references/production-notes.md](references/production-notes.md)。

---

## 文档

| 文件 | 内容 |
|---|---|
| [SKILL.md](SKILL.md) | 完整 SOP：七阶段流程、门禁、纪律 |
| [references/environment-setup.md](references/environment-setup.md) | 环境搭建（含 CUDA 轮子踩坑） |
| [references/production-notes.md](references/production-notes.md) | **踩坑台账**（含音色突变 bug 完整复盘） |
| [references/qa-metrics.md](references/qa-metrics.md) | 判据定义与阈值依据 |

---

## 脚本

| 脚本 | 作用 |
|---|---|
| `scripts/tts_voiceover.py` | 主流程：逐句合成 + 三级对齐 + 时间轴注入 |
| `scripts/pick_ref.py` | 参考音挑选：词边界滑窗 + 干净收尾 + 精确 ref_text |
| `scripts/eval_voice.py` | 验收：cos / F0 / CER 逐句体检 |
| `scripts/build_dub_video.py` | 帧序列 + 音轨 → 最终 MP4 |

---

## 实测性能（RTX 4060 Laptop 8GB）

| 项目 | 1.7B-Base | 0.6B-Base |
|---|---|---|
| 显存 | ≈ 3.9 GB | ≈ 2.0 GB |
| 生成速度 | RTF ≈ 0.5× | RTF ≈ 0.5× |
| 50 句整篇（179s） | 12 min | 11 min |
| 音色相似度 | 0.9756~0.9867 | 0.9660~0.9834 |
| CER | 0.042 | 0.053 |

**推荐 1.7B**：错字约为 0.6B 的一半。

---

## 相关 skill

| Skill | 关系 |
|---|---|
| `handdrawn-explainer-video` / `dark-field-explainer-video` | 上游：产出无声成片 + 可注入时间轴的工程 |
| `bgm-beat-align` | 下游：配音版再叠 BGM 卡点 |
