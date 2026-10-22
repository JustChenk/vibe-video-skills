# 质量判据（QA Metrics）

配音版必须过这四条。判据都是**可脚本化**的，别靠耳朵抽样。

---

## 1. 说话人相似度 `spk_cos`

用模型自带的 speaker encoder 把参考音和每句产出都编码成 embedding，算余弦。

```python
tgt = model.model.speaker_encoder_sample_rate        # 24k
wav = librosa.resample(wav, orig_sr=sr, target_sr=tgt)
e  = model.model.extract_speaker_embedding(audio=wav, sr=tgt)
cos = float(ref_e @ e / (np.linalg.norm(ref_e) * np.linalg.norm(e)))
```

| 区间 | 含义 |
|---|---|
| ≥ 0.98 | 极像，肉眼听不出区别 |
| 0.95 ~ 0.98 | 正常合格 |
| 0.90 ~ 0.95 | 可疑，**需要人耳复核** |
| < 0.90 | 明显不是同一人 |

**阈值：≥ 0.95**

> ⚠️ 别把阈值定在 0.90。实测崩坏句能到 0.9202（见 production-notes §2.2），
> 0.90 会直接放行。

---

## 2. 中位基频 `F0`

```python
f0 = librosa.yin(wav16k, fmin=60, fmax=600, sr=16000)
f0 = f0[np.isfinite(f0)]
med = float(np.median(f0))
```

**阈值：`med_f0 ≥ ref_f0 × 0.75`**

**为什么这条最重要**：`spk_cos` 是全局音色距离，
当模型崩成「另一个同性别的声音」时它可能只掉一点；
但**崩成异性/差一个八度时 F0 会腰斩**，一眼可见。

实测对照：

| 句子 | spk_cos | F0 | 判断 |
|---|---|---|---|
| 正常句 | 0.966~0.987 | 316~338 Hz | ✅ |
| 崩坏句 | 0.9202 | **144 Hz** | ❌ |

> 这条几乎零成本（不需要模型，librosa 一算就有），建议每句都跑。

---

## 3. 句首多字

参考音尾音泄漏的专属指标。把每句产出的 ASR 文本和期望文本对齐，
看开头多出几个字。

```python
def prefix_len(expected, got):
    e, g = strip_punct(expected), strip_punct(got)
    for off in range(0, 5):
        if g[off:off+4] == e[:4]:
            return off
    return -1        # 对不上（可能是同音字错误，不算多字）
```

**阈值：`0 / N`（一条都不允许）**

典型泄漏样本：`的是`、`大事`、`得失`、`但是`、`得是`。
修法见 SKILL.md 阶段 3（参考音自然停顿收尾 + 末采样归零）。

---

## 4. 字错率 `CER`

ASR 回环：把合成音频再转写一遍，和原文算编辑距离。

```python
cer = levenshtein(norm(ref), norm(hyp)) / len(norm(ref))
```

归一化：去标点、去空格、转小写（中英混排时尤其重要，`App` vs `APP` 不算错）。

| 模型 | 实测 CER |
|---|---|
| 1.7B-Base | 0.048 |
| 0.6B-Base | 0.053 |

**阈值：≤ 0.10**（超过说明吐字有问题，或混入了幻觉文本）

> CER 也能间接抓重复循环：幻觉出来的「中文字幕志愿者 李宗盛」会把 CER 顶到很高。
> 但它对**音色**问题完全无感——所以不能只靠这一条。

**中文计数字幕稿必须看归一化后的 `adj_cer`**：字幕写「二零零三年」「百分之五十五」「七成七」，
Whisper 回环转写「2003年」「55%」「7成7」，原样算 CER 虚高一个量级
（《以日为鉴》Ep02 原值 0.139 → adj 0.025）。`scripts/qa_report.py` 已内置中文数字归一化
（纯数字串按字符拼接 / 含十百千万按位值 / 百分之X→X% / 两=2），跑批时以它的 adj_cer 为准。
另注意甄别 ASR artifact：繁体输出、数字形态差异都不是 TTS 错（production-notes §5.3）。

---

## 5. 时间对齐

`align_report.json` 逐句给了四个数：

| 字段 | 含义 |
|---|---|
| `win` | 原字幕槽位时长 |
| `tts` | 实测合成时长 |
| `overflow` | `tts - win`，正数=超出槽位 |
| `tempo` | 实际施加的 atempo 倍数 |

**检查点**：

1. `overlaps` 必须为空（有重叠说明两句音频叠在一起了）
2. `overflow` 为正的句子要**逐条过目**——溢出大的通常是崩坏句（异常偏长）
3. 幕拉伸倍数 `scale` 理想在 **1.00~1.15**；超过 1.25 画面会明显变慢

实测参考：172.0s → 178.994s（×1.041），溢出 11/50，最大 +0.81s，无重叠。

---

## 6. 快速验收脚本

```bash
python scripts/eval_voice.py \
  --model 1.7b --qwen-dir ../tts_qwen \
  --ref assets/ref/ref_cand1.wav \
  --batch voicework_qwen/align_report.json \
  --out voicework_qwen/eval.json
```

输出逐句 `spk_cos / F0 / CER`，并在结尾给汇总：

```
[summary] n=50  mean_spk_cos=0.9781  F0=293~352Hz  mean_CER=0.0480
[summary] ✓ 全部通过音色+音高判据
```

出现异常时会点名：

```
[summary] ⚠ 音色/音高异常 2 条：[('021_qwen.wav', 0.9202, 144.4), ('033_qwen.wav', 0.9266, 188.3)]
```

---

## 7. 判据速查表

| # | 指标 | 阈值 | 抓什么 | 成本 |
|---|---|---|---|---|
| 1 | `spk_cos` | ≥ 0.95 | 音色漂移 | 需模型 |
| 2 | `F0` 比值 | ≥ 0.75 | 换性别/换音域 | 极低 |
| 3 | 句首多字 | 0 / N | 参考音尾泄漏 | 需 ASR |
| 4 | `CER` | ≤ 0.10 | 吐字、幻觉 | 需 ASR |
| 5 | `overlaps` | 空 | 音频叠字 | 零成本 |
| 6 | 幕 `scale` | ≤ 1.25 | 画面过慢 | 零成本 |
