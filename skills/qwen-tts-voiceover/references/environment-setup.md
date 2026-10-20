# 环境搭建（Environment Setup）

本 skill 需要一份 **`tts_qwen` 运行时工程**：模型权重 + 隔离的 Python 环境。
建议放在项目根下，例如 `<项目根>/tts_qwen/`。

## 1. 目录布局

```
tts_qwen/
├── models/
│   ├── Qwen3-TTS-12Hz-1.7B-Base/     # 4.23 GB
│   │   ├── model.safetensors
│   │   ├── config.json / generation_config.json
│   │   ├── vocab.json / merges.txt / tokenizer_config.json
│   │   └── speech_tokenizer/         # 650 MB，内置，无需单独下载
│   ├── Qwen3-TTS-12Hz-0.6B-Base/     # 2.34 GB
│   └── audio-separator/              # 人声分离模型缓存
├── assets/ref/                       # 参考音片段
└── .venv/                            # Python 3.12
```

## 2. 创建环境

```powershell
cd tts_qwen
uv venv --python 3.12 --seed .venv
```

## 3. 装 PyTorch（必须锁 CUDA 直链）

> ⚠️ **最容易翻车的一步**：`--index-url .../cu128` 在最新版缺失时会**静默回退到 CPU 轮子**。
> 必须用直链，并在装完后立刻验证。

```powershell
uv pip install --python .venv\Scripts\python.exe --no-deps `
  "https://download.pytorch.org/whl/cu128/torch-2.9.1%2Bcu128-cp312-cp312-win_amd64.whl" `
  "https://download.pytorch.org/whl/cu128/torchaudio-2.9.1%2Bcu128-cp312-cp312-win_amd64.whl"

# 验证（不通过就别往下走）
.\.venv\Scripts\python.exe -c "import torch; print(torch.__version__, torch.cuda.is_available())"
# 期望：2.9.1+cu128 True
```

Linux/macOS 把 `win_amd64` 换成对应平台标签（`manylinux_x86_64` / `macosx_*`）。

## 4. 装推理与工具链

```powershell
uv pip install --python .venv\Scripts\python.exe `
  numpy qwen-tts huggingface_hub `
  audio-separator audioread faster-whisper
```

关键版本（qwen-tts 0.1.1 锁死了 transformers）：

| 包 | 版本 | 说明 |
|---|---|---|
| `qwen-tts` | 0.1.1 | 官方推理包 |
| `transformers` | 4.57.3 | 被 qwen-tts 锁定，**不要手动升** |
| `accelerate` | 1.12.0 | 同上 |

## 5. 下载模型

```powershell
$env:HF_HOME = "$PWD\models\hf_home"     # 避免用户缓存目录权限问题
.\.venv\Scripts\hf.exe download Qwen/Qwen3-TTS-12Hz-1.7B-Base `
    --local-dir models\Qwen3-TTS-12Hz-1.7B-Base --exclude "README.md" ".gitattributes"
.\.venv\Scripts\hf.exe download Qwen/Qwen3-TTS-12Hz-0.6B-Base `
    --local-dir models\Qwen3-TTS-12Hz-0.6B-Base --exclude "README.md" ".gitattributes"
```

`speech_tokenizer/` 是模型目录的子目录，**随主模型一起下载**，不需要单独的
`Qwen3-TTS-Tokenizer-12Hz` 仓库。

国内网络可用 ModelScope 镜像：

```bash
modelscope download --model Qwen/Qwen3-TTS-12Hz-1.7B-Base --local_dir ./Qwen3-TTS-12Hz-1.7B-Base
```

## 6. ffmpeg

`tts_voiceover.py` 与 `build_dub_video.py` 都依赖 ffmpeg/ffprobe。
脚本会按 **`--ffmpeg` 参数 → `FFMPEG` 环境变量 → `tools/ffmpeg.exe` → PATH** 顺序查找。

```powershell
$env:PATH = "<项目根>\tools;$env:PATH"
ffmpeg -version | Select-Object -First 1
```

## 7. Whisper（参考音转写与验收用）

Whisper 用于两次：`pick_ref.py` 拿词级时间戳、`eval_voice.py` 算 CER。

离线部署时把模型指到本地快照，避免每次联网校验：

```powershell
$env:WHISPER_DIR = "<tts_qwen>\models\hf_home\hub\models--Systran--faster-whisper-large-v3\snapshots\<hash>"
$env:HF_HUB_OFFLINE = "1"
```

不给 `WHISPER_DIR` 时回退到模型名 `large-v3`（需联网或已有 HF 缓存）。

> **PyAV 兼容性坑**：faster-whisper 1.2.1 的 `decode_audio` 会调
> `av.open(..., metadata_errors="ignore")`，而 PyAV 19 没有这个参数；
> 降级 `av<15` 在 Windows 上又没有预编译轮子。
> **解法：自己用 `soundfile` + `soxr` 读成 numpy 数组再传给 `transcribe()`**，
> 完全绕开 PyAV 解码路径。`pick_ref.py` / `eval_voice.py` 已内置此写法。

## 8. 人声分离模型

```powershell
$env:AUDIO_SEPARATOR_MODEL_DIR = "<tts_qwen>\models\audio-separator"
audio-separator -l     # 首次会拉取模型清单
```

推荐 `melband_roformer_inst_v2.ckpt`（SDR 16.1）。首次运行自动下载权重（约 1 GB）。

## 9. 自检清单

装完跑一遍，全过再开工：

```powershell
$py = "tts_qwen\.venv\Scripts\python.exe"

& $py -c "import torch; assert torch.cuda.is_available(); print('CUDA OK', torch.cuda.get_device_name(0))"
& $py -c "import torch; assert torch.cuda.get_device_capability(0) >= (8,0); print('bf16 OK')"
& $py -c "import transformers; print('transformers', transformers.__version__)"   # 4.57.3
& $py -c "from qwen_tts import Qwen3TTSModel; print('qwen_tts OK')"
& $py -c "from faster_whisper import WhisperModel; print('faster_whisper OK')"
& $py -c "from audio_separator.separator import Separator; print('audio_separator OK')"
```

## 10. 显存档位

| 模型 | 显存 | 8GB 卡能否与 Whisper 共存 |
|---|---|---|
| 1.7B-Base | 3.9 GB | ❌ 需分段（先 embedding 后 ASR） |
| 0.6B-Base | 2.0 GB | ⚠️ 勉强，建议仍分段 |
| Whisper large-v3 | ≈ 3 GB | — |

脚本已按分段实现，正常使用无需手工干预。
