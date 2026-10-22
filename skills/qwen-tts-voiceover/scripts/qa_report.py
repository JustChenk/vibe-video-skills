"""qa_report.py —— 汇总单集合成质量：manifest 指标 + eval 异常清单。

用法：
  python qa_report.py <配音目录>   # 读 manifest.json / eval.json
判定口径（qwen-tts-voiceover 质量门禁）：
  spk_cos >= 0.95 ｜ f0_ratio >= 0.75 ｜ CER <= 0.10 ｜ 句首多字 = 0（ASR 头部多字人工确认）

⚠ 以日为鉴的字幕稿用中文计数（"二零零三年"/"百分之五十五"/"七成七"），
Whisper 回环常转写成阿拉伯数字（"2003年"/"55%"），原样算 CER 会虚高。
本脚本在原始 CER 之外另算一份 **adj_cer**：先把中文数字归一成阿拉伯数字再算。
"""
import json
import re
import sys
from pathlib import Path

_DIGIT = {"零": "0", "一": "1", "二": "2", "两": "2", "三": "3", "四": "4",
          "五": "5", "六": "6", "七": "7", "八": "8", "九": "9"}
_UNIT = {"十": 10, "百": 100, "千": 1000}


def _run_to_num(s: str) -> str:
    """把一段中文数字 run 转成阿拉伯数字串。
    纯数字串（二零零三 / 九二）按字符拼接 → 2003 / 92（年份口癖）；
    含十百千万的按位值解析 → 四十七=47、五百万=500000。
    """
    if not s:
        return s
    if "点" in s:  # 小数：三点五 / 零点七三
        a, _, b = s.partition("点")
        ia = _int_cn(a) if a else 0
        frac = "".join(_DIGIT.get(c, "") for c in b)
        return f"{ia}.{frac}" if frac else str(ia)
    if any(c in _UNIT or c == "万" for c in s):
        return str(_int_cn(s))
    return "".join(_DIGIT.get(c, c) for c in s)


def _int_cn(s: str) -> int:
    total, section, number = 0, 0, 0
    for c in s:
        if c in _DIGIT:
            number = int(_DIGIT[c])
        elif c in _UNIT:
            unit = _UNIT[c]
            if number == 0:
                number = 1
            section += number * unit
            number = 0
        elif c == "万":
            section = (section + number) if number else section or 1
            total += section * 10000
            section, number = 0, 0
        else:
            return 0
    return total + section + number


def cn_norm(s: str) -> str:
    """中文计数 → 阿拉伯数字，便于与 Whisper 回环做公平 CER 比较。"""
    # 百分之X → X%（X 可含小数：零点九 → 0.9）
    s = re.sub(r"百分之([零一二三四五六七八九十百千点]+)",
               lambda m: _run_to_num(m.group(1)) + "%", s)
    # 其余中文数字 run → 阿拉伯数字
    s = re.sub(r"[零一二三四五六七八九十百千点]+",
               lambda m: _run_to_num(m.group(0)), s)
    return s


def cer(ref: str, hyp: str) -> float:
    if not ref:
        return 1.0
    prev = list(range(len(hyp) + 1))
    for i, rc in enumerate(ref, 1):
        cur = [i]
        for j, hc in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc)))
        prev = cur
    return prev[-1] / len(ref)


def norm_cn(s: str) -> str:
    s = re.sub(r"[，。！？、；：\u201c\u201d\u2018\u2019（）《》…—,.\!?;:\"'()\[\]{}<>\s\-]", "", s)
    return s.lower()


def main():
    d = Path(sys.argv[1])
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    print(f"== {d.name} ==")
    print(f"cue_count={man['cue_count']} voice_end={man.get('voice_end_sec')}s "
          f"track={man['duration_sec']}s speech={man['speech_sec']}s avg_cps={man['avg_cps']}")
    print(f"speedup={man['speedup_count']} trim={man['trim_count']} "
          f"over_slot(>0.05s)={man.get('over_slot_count')} wall={man['wall_sec']}s")

    flagged = [it for it in man["items"]
               if it.get("note") or it.get("over_slot", 0) > 0.05]
    if flagged:
        print("-- 变速/裁切/超槽 清单 --")
        for it in flagged:
            print(f"  #{it['idx']:>2} slot={it['slot']:.2f} nat={it['natural']:.2f} "
                  f"fin={it['final']:.2f} over={it['over_slot']:+.2f} [{it['note']}] {it['text'][:26]}")
    else:
        print("变速/裁切/超槽：无")

    ev = d / "eval.json"
    if not ev.exists():
        print("eval.json：缺失（未跑验收）")
        return
    rows = json.loads(ev.read_text(encoding="utf-8"))
    if isinstance(rows, dict):
        rows = rows.get("items", [])
    for r in rows:  # 补一列数字归一化后的 CER
        r["adj_cer"] = round(cer(norm_cn(cn_norm(r.get("text", ""))),
                                 norm_cn(cn_norm(r.get("asr", "")))), 4)
    n = len(rows)
    bad = [r for r in rows
           if (r.get("spk_cos") is not None and r["spk_cos"] < 0.95)
           or (r.get("f0_ratio") is not None and r["f0_ratio"] < 0.75)
           or (r.get("adj_cer") is not None and r["adj_cer"] > 0.10)]
    mn_cos = min((r["spk_cos"] for r in rows if r.get("spk_cos")), default=None)
    mn_f0 = min((r["f0_ratio"] for r in rows if r.get("f0_ratio")), default=None)
    mx_cer = max((r["cer"] for r in rows if r.get("cer") is not None), default=None)
    mean_adj = sum(r["adj_cer"] for r in rows) / max(1, n)
    print(f"-- eval {n} 条：min_cos={mn_cos} min_f0_ratio={mn_f0} "
          f"max_cer(原)={mx_cer} mean_adj_cer={mean_adj:.4f} 异常={len(bad)} --")
    for r in bad:
        print(f"  ⚠ {r['file']} cos={r.get('spk_cos')} f0x={r.get('f0_ratio')} "
              f"cer={r.get('cer')} adj={r.get('adj_cer')}")
        print(f"     原文: {r.get('text', '')[:40]}")
        print(f"     ASR : {r.get('asr', '')[:40]}")


if __name__ == "__main__":
    main()
