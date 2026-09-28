"""compose_final_video.py — 最终合成：音画对齐(Ken Burns推近) + 硬字幕烧录 + 无损拼接

流程:
  1. 探测 7 段音频/动态视频实际时长
  2. 按音频时长重新生成对齐 SRT (按句拆分 + 字符数加权, 每行<=10字)
  3. 每段: setpts 慢放对齐音频 + zoompan 单向缓慢推近 (Ken Burns) + tpad 尾帧定格 + AAC
     ⚠ 禁止使用 reverse / 乒乓循环凑时长 —— 观感是"正放-倒放来回", 必须用 zoompan
  4. concat demuxer 流拷贝无损拼接
  5. subtitles 滤镜烧录硬字幕 + mov_text 软字幕轨双保险 -> 最终动态视频.mp4
  6. 自测: 像素diff验证字幕 / ffprobe字幕流 / 抽30秒帧

用法:
  python compose_final_video.py --book-dir "C:\\...\\《书名》" --ffmpeg "C:\\...\\ffmpeg.exe"
  可用 --stage srt|seg|concat|burn 分步执行
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

FONT = r"C:\Windows\Fonts\msyh.ttc"
SEG_IDS = [f"s{i}" for i in range(7)]
CRF = "17"
PRESET = "medium"

# 字幕样式 (ASS force_style): 白字黑边, 底部居中
FORCE_STYLE = (
    "FontName=Microsoft YaHei,FontSize=18,Bold=1,"
    "PrimaryColour=&H00FFFFFF,OutlineColour=&H96000000,"
    "BorderStyle=1,Outline=2,Shadow=0,"
    "Alignment=2,MarginV=70,Spacing=0.5"
)


def run(cmd, desc, timeout=600, cwd=None):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                       encoding="utf-8", errors="replace", cwd=cwd)
    if r.returncode != 0:
        print(f"!! FAIL [{desc}]")
        print("\n".join(r.stderr.splitlines()[-15:]))
        sys.exit(1)
    return r


def probe_duration(ffmpeg, path: Path) -> float:
    r = subprocess.run([ffmpeg, "-i", str(path)], capture_output=True, text=True,
                       timeout=15, encoding="utf-8", errors="replace")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", r.stderr)
    if not m:
        raise RuntimeError(f"no duration: {path}")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def extract_gray_frame(ffmpeg, video: Path, ts: float):
    """提取单帧原始灰度数据 (480*864=414720 字节), 失败返回 None。"""
    r = subprocess.run(
        [ffmpeg, "-ss", f"{ts:.3f}", "-i", str(video),
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True, timeout=30,
    )
    data = r.stdout
    if len(data) < 400000:
        return None
    return data[:414720]


def motion_stats(ffmpeg, path: Path, dur: float, step: float = 0.2, thresh: int = 12):
    """step 秒步进相邻帧 diff 序列 -> (中位数%, 最大值%, max/med)。
    max/med 过大 = 存在跳帧或接缝突刺。"""
    samples = []
    prev = extract_gray_frame(ffmpeg, path, 0.5)
    t = 0.5 + step
    while t < dur - 0.2:
        cur = extract_gray_frame(ffmpeg, path, t)
        if prev and cur:
            diff = sum(1 for x, y in zip(prev, cur) if abs(x - y) > thresh) / 414720 * 100
            samples.append(diff)
        prev = cur
        t += step
    if not samples:
        return None
    ss = sorted(samples)
    med = ss[len(ss) // 2]
    mx = max(samples)
    return med, mx, (mx / med if med > 0.001 else 99.0)


# ---------- 字幕文案: 分句 + 断行 ----------
def extract_caption(md_text: str) -> str:
    m = re.search(r"^##\s+字幕文案.*?\n(.+?)(?=\n##\s|\Z)", md_text, flags=re.MULTILINE | re.DOTALL)
    if not m:
        raise KeyError("未找到字幕文案章节")
    return m.group(1).strip()


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。？！；])", text)
    return [p.strip() for p in parts if p.strip()]


def wrap_line(sentence: str, max_chars: int = 10) -> str:
    if len(sentence) <= max_chars:
        return sentence
    chunks = re.split(r"(?<=[，、：])", sentence)
    lines, cur = [], ""
    for ch in chunks:
        if len(cur) + len(ch) <= max_chars:
            cur += ch
        else:
            if cur:
                lines.append(cur)
            while len(ch) > max_chars:
                lines.append(ch[:max_chars])
                ch = ch[max_chars:]
            cur = ch
    if cur:
        lines.append(cur)
    return "\n".join(lines)


def fmt_srt_ts(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_aligned_srt(book: Path, durations: dict, tmp: Path) -> Path:
    blocks = []
    idx = 1
    cursor = 0.0
    for sid in SEG_IDS:
        md = (book / "剧本" / "分镜" / f"{sid}.md").read_text(encoding="utf-8")
        caption = extract_caption(md)
        sentences = split_sentences(caption)
        seg_dur = durations[sid]
        weights = [len(s) for s in sentences]
        total_w = sum(weights)
        acc = 0
        for sent, w in zip(sentences, weights):
            start = cursor + seg_dur * acc / total_w
            acc += w
            end = cursor + seg_dur * acc / total_w
            blocks.append(f"{idx}\n{fmt_srt_ts(start)} --> {fmt_srt_ts(end)}\n{wrap_line(sent)}\n")
            idx += 1
        cursor += seg_dur
    srt_path = tmp / "subs_aligned.srt"
    srt_path.write_text("\n".join(blocks), encoding="utf-8-sig")
    return srt_path


def main():
    ap = argparse.ArgumentParser(description="音画对齐(Ken Burns) + 硬字幕烧录 + 拼接")
    ap.add_argument("--book-dir", required=True, help="书的项目目录（含 音频/、视频/动态片段/、剧本/分镜/）")
    ap.add_argument("--ffmpeg", required=True, help="ffmpeg.exe 绝对路径")
    ap.add_argument("--stage", choices=["all", "srt", "seg", "concat", "burn"], default="all")
    args = ap.parse_args()

    FFMPEG = args.ffmpeg
    book = Path(args.book_dir)
    audio_dir = book / "音频"
    video_dir = book / "视频" / "动态片段"
    out_dir = book / "视频"
    tmp = out_dir / "_tmp_compose"
    final = out_dir / "最终动态视频.mp4"
    tmp.mkdir(parents=True, exist_ok=True)

    # 1. 探测时长
    print("=== [1/5] 探测时长 ===")
    a_dur, v_dur = {}, {}
    for sid in SEG_IDS:
        a_dur[sid] = probe_duration(FFMPEG, audio_dir / f"{sid}.mp3")
        v_dur[sid] = probe_duration(FFMPEG, video_dir / f"{sid}.mp4")
        print(f"  {sid}: audio={a_dur[sid]:.2f}s video={v_dur[sid]:.2f}s ratio={a_dur[sid]/v_dur[sid]:.2f}x")

    # 2. 对齐 SRT
    if args.stage in ("all", "srt"):
        print("=== [2/5] 生成对齐 SRT ===")
        srt_path = build_aligned_srt(book, a_dur, tmp)
        n_blocks = srt_path.read_text(encoding="utf-8-sig").count("\n\n") + 1
        print(f"  -> {srt_path.name} ({n_blocks} 条字幕)")
    srt_path = tmp / "subs_aligned.srt"
    if not srt_path.exists():
        print("!! 对齐 SRT 不存在, 请先跑 --stage srt")
        sys.exit(1)

    # 3. 逐段: setpts 慢放 + zoompan 单向推近 (禁止 reverse/乒乓!)
    seg_files = []
    if args.stage in ("all", "seg"):
        print("=== [3/5] 逐段对齐 (慢放 + zoompan 推近 + AAC) ===")
        for sid in SEG_IDS:
            ratio = a_dur[sid] / v_dur[sid]
            pad = 0.6
            out_seg = tmp / f"seg_{sid}.mp4"
            # 2x 预放大再 zoompan 裁回原尺寸: 减轻低分辨率抖动
            # z 增速 0.0004/帧: 20s 段约放大 19%, 温和单向推近
            vf = (
                f"[0:v]setpts={ratio:.6f}*PTS,fps=24,"
                f"scale=960:1728:flags=lanczos,"
                f"zoompan=z='1+0.0004*on':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=480x864:fps=24,"
                f"tpad=stop_mode=clone:stop_duration={pad},format=yuv420p[v]"
            )
            cmd = [
                FFMPEG, "-y",
                "-i", str(video_dir / f"{sid}.mp4"),
                "-i", str(audio_dir / f"{sid}.mp3"),
                "-filter_complex", vf,
                "-map", "[v]", "-map", "1:a",
                "-c:v", "libx264", "-crf", CRF, "-preset", PRESET,
                "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
                "-shortest",
                str(out_seg),
            ]
            run(cmd, f"seg {sid}")
            d = probe_duration(FFMPEG, out_seg)
            print(f"  {sid}: ratio={ratio:.2f}x -> seg_{sid}.mp4 ({d:.2f}s)")
            seg_files.append(out_seg)

        # 逐段自测: 动态性 + 跳帧突刺检测
        print("  --- 逐段自测 (相邻0.2s帧diff序列) ---")
        print("  片段   动态性(1s)   diff中位   diff最大   max/med   判定")
        for f_seg in seg_files:
            d = probe_duration(FFMPEG, f_seg)
            a1 = extract_gray_frame(FFMPEG, f_seg, d / 2)
            a2 = extract_gray_frame(FFMPEG, f_seg, d / 2 + 1.0)
            dyn = sum(1 for x, y in zip(a1, a2) if abs(x - y) > 12) / 414720 * 100 if a1 and a2 else 0
            st = motion_stats(FFMPEG, f_seg, d)
            if st is None:
                print(f"  {f_seg.stem}: 采样失败")
                continue
            med, mx, rr = st
            verdict = "平稳" if rr < 6 else "疑似突刺!"
            print(f"  {f_seg.stem[-2:]}   {dyn:6.1f}%     {med:6.2f}%    {mx:6.2f}%   {rr:5.1f}x   {verdict}")
    else:
        seg_files = [tmp / f"seg_{sid}.mp4" for sid in SEG_IDS]

    # 4. 无损拼接
    merged = tmp / "merged.mp4"
    if args.stage in ("all", "seg", "concat"):
        print("=== [4/5] 无损拼接 ===")
        list_file = tmp / "concat.txt"
        list_file.write_text("\n".join(f"file '{f}'" for f in seg_files), encoding="utf-8")
        run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
             "-c", "copy", str(merged)], "concat")
        print(f"  -> merged.mp4 ({probe_duration(FFMPEG, merged):.2f}s)")
    elif not merged.exists():
        print("!! merged.mp4 不存在, 请先跑 --stage seg 或 concat")
        sys.exit(1)

    # 5. 烧录硬字幕 (cwd 切到 srt 目录用相对路径, 避开 Windows 盘符转义坑)
    #    同时封装 mov_text 软字幕轨双保险
    if args.stage in ("all", "burn"):
        print("=== [5/5] 烧录硬字幕 + 封装软字幕轨 ===")
        vf = "subtitles='subs_aligned.srt':force_style='FontName=Microsoft YaHei,FontSize=16'"
        cmd = [
            FFMPEG, "-y",
            "-i", str(merged),
            "-i", "subs_aligned.srt",
            "-vf", vf,
            "-c:v", "libx264", "-crf", CRF, "-preset", PRESET,
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            "-c:s", "mov_text",
            "-metadata:s:s:0", "language=chi",
            "-metadata:s:s:0", "title=Chinese",
            "-movflags", "+faststart",
            str(final),
        ]
        run(cmd, "burn subs", cwd=str(tmp))
        print(f"  -> {final.name} ({probe_duration(FFMPEG, final):.2f}s)")

        # 6. 自测: 像素 diff + ffprobe 字幕流 + 30s 抽帧
        print("=== [6/6] 自测 ===")
        for ts in (10.0, 45.0, 90.0):
            f1 = extract_gray_frame(FFMPEG, merged, ts)
            f2 = extract_gray_frame(FFMPEG, final, ts)
            if f1 is None or f2 is None:
                print(f"  t={ts}: 提取失败")
                continue
            n = len(f1)
            diff = sum(1 for a, b in zip(f1, f2) if abs(a - b) > 30)
            bot_start = int(n * 2 / 3)
            bot_diff = sum(1 for a, b in zip(f1[bot_start:], f2[bot_start:]) if abs(a - b) > 30)
            print(f"  t={ts}s: 总差异 {diff:,} ({diff/n*100:.1f}%), 底部字幕区 {bot_diff:,}")
        r = subprocess.run([FFMPEG, "-i", str(final)], capture_output=True,
                           text=True, timeout=30, encoding="utf-8", errors="replace")
        sub_line = next((l.strip() for l in r.stderr.splitlines() if "Subtitle:" in l), "(none)")
        print(f"  字幕流: {'✓' if 'Subtitle:' in r.stderr else '✗ 缺失'}  {sub_line}")
        frame_out = out_dir / "字幕验证帧_30s.jpg"
        run([FFMPEG, "-y", "-ss", "30", "-i", str(final),
             "-vframes", "1", "-q:v", "2", str(frame_out)], "extract frame 30s")
        print(f"  30s 帧: {frame_out}")

    if final.exists():
        size_mb = final.stat().st_size / 1024 / 1024
        print(f"\n=== DONE ===")
        print(f"  {final}")
        print(f"  {size_mb:.1f} MB, {probe_duration(FFMPEG, final):.1f}s, 480x864, H.264+AAC+mov_text")


if __name__ == "__main__":
    main()
