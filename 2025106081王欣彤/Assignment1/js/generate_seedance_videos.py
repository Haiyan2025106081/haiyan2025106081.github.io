"""Seedance 视频批量生成 (stdlib urllib)

由于 doubao-seedance-1-0-pro-fast-251015 不支持首尾帧 flf2v (服务端报错),
回退到单图 i2v 模式: 7 张图片各生成一段 5 秒 480p 9:16 动态视频.

提示词 = s{0..6}.md 的 "## 画面描述" 段 + 一句固定 motion 后缀 (5 秒内镜头推进/主体轻微动).
"""
import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

API_BASE = "https://ark.cn-beijing.volces.com/api/v3"
MODEL_PRIMARY = "doubao-seedance-1-0-pro-fast-251015"
MODEL_LITE_BACKUP = "doubao-seedance-1-0-pro-250528"   # pro-fast 触发用量限额时的可用备选（lite 系列多数账户无权限）

# 7 段固定 motion 后缀 (与 03-图生视频提示词.md 的节奏一致)
MOTION_SUFFIX = "5 秒时长, 镜头缓慢推进, 主体保持轻微动态, 真实新闻纪录片风格"

WORKER_LIMIT = 4          # 并发任务数
POLL_INTERVAL = 5         # 秒
POLL_TIMEOUT = 240        # 单任务最长等待
DOWNLOAD_TIMEOUT = 120    # 下载最长等待

SEG_IDS = [f"s{i}" for i in range(7)]


def mask_key(k: str) -> str:
    if not k:
        return "(empty)"
    return k[:8] + "..." + k[-4:]


def to_data_url(image_path: Path) -> str:
    data = image_path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def http_post_json(path: str, body: dict, api_key: str, timeout: int = 60) -> tuple[int, str]:
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:
        return 0, f"EXC: {type(e).__name__}: {e}"


def http_get_json(path: str, api_key: str, timeout: int = 30) -> tuple[int, str]:
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:
        return 0, f"EXC: {type(e).__name__}: {e}"


def http_download(url: str, dest: Path, timeout: int = DOWNLOAD_TIMEOUT) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            dest.write_bytes(r.read())
        return True, f"{dest.stat().st_size:,} bytes"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def extract_paint_desc(md_text: str) -> str:
    """提取 "## 画面描述..." 章节后的正文, 直到下一个 ## 或文件结尾。"""
    m = re.search(r"^##\s+画面描述.*?\n(.+?)(?=\n##\s|\Z)",
                  md_text, flags=re.MULTILINE | re.DOTALL)
    if not m:
        raise KeyError("未找到画面描述章节")
    text = m.group(1).strip()
    # 去掉 list 标记 (- 开头的列表项) 和连续空行
    text = re.sub(r"^-\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def build_body(model: str, prompt: str, data_url: str) -> dict:
    return {
        "model": model,
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": data_url}},
        ],
        "ratio": "9:16",
        "resolution": "480p",
        "duration": 5,
        "watermark": False,
    }


def submit_one(api_key: str, model: str, prompt: str, data_url: str) -> dict:
    body = build_body(model, prompt, data_url)
    code, text = http_post_json("/contents/generations/tasks", body, api_key)
    if code != 200:
        return {"ok": False, "error": f"HTTP {code}: {text[:200]}"}
    try:
        tid = json.loads(text)["id"]
    except Exception:
        return {"ok": False, "error": f"bad response: {text[:200]}"}
    return {"ok": True, "task_id": tid}


def poll_one(api_key: str, task_id: str, log_prefix: str = "") -> dict:
    deadline = time.time() + POLL_TIMEOUT
    last_status = "?"
    while time.time() < deadline:
        code, text = http_get_json(f"/contents/generations/tasks/{task_id}", api_key)
        try:
            data = json.loads(text)
        except Exception:
            data = {"raw": text}
        status = data.get("status", "?")
        if status != last_status:
            print(f"  {log_prefix}poll: {status}", flush=True)
            last_status = status
        if status == "succeeded":
            return {"ok": True, "data": data}
        if status in ("failed", "cancelled"):
            return {"ok": False, "error": f"{status}: {data.get('error', {})}", "data": data}
        time.sleep(POLL_INTERVAL)
    return {"ok": False, "error": "timeout"}


def process_one(api_key: str, model: str, sid: str,
                img_path: Path, prompt: str, out_path: Path) -> dict:
    log = f"[{sid}] "
    t0 = time.time()
    # 1. submit
    sub = submit_one(api_key, model, prompt, to_data_url(img_path))
    if not sub["ok"]:
        print(f"  {log}SUBMIT FAIL: {sub['error']}", flush=True)
        return {"sid": sid, "ok": False, "stage": "submit", "error": sub["error"]}
    tid = sub["task_id"]
    print(f"  {log}submit ok task_id={tid}", flush=True)

    # 2. poll
    pol = poll_one(api_key, tid, log_prefix=log)
    if not pol["ok"]:
        print(f"  {log}POLL FAIL: {pol['error']}", flush=True)
        return {"sid": sid, "ok": False, "stage": "poll", "task_id": tid, "error": pol["error"]}

    vu = pol["data"].get("content", {}).get("video_url", "")
    if not vu:
        return {"sid": sid, "ok": False, "stage": "poll",
                "task_id": tid, "error": "no video_url in response"}

    # 3. download
    ok, info = http_download(vu, out_path)
    elapsed = round(time.time() - t0, 1)
    if not ok:
        print(f"  {log}DOWNLOAD FAIL: {info}", flush=True)
        return {"sid": sid, "ok": False, "stage": "download",
                "task_id": tid, "video_url": vu, "error": info}
    print(f"  {log}OK -> {out_path.name} {info} ({elapsed}s)", flush=True)
    return {"sid": sid, "ok": True, "task_id": tid,
            "video_url": vu, "path": str(out_path), "elapsed_sec": elapsed,
            "size_bytes": out_path.stat().st_size}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-key", default=os.environ.get("ARK_API_KEY", ""))
    ap.add_argument("--book-dir", default=r"C:\Users\admin\WorkBuddy\名著介绍\《娱乐至死》")
    ap.add_argument("--model", default=MODEL_PRIMARY)
    ap.add_argument("--only", default="",
                    help="只跑指定段, 逗号分隔 (如 s3,s4,s5,s6); 留空跑全部")
    args = ap.parse_args()

    if not args.api_key:
        print("!! 没拿到 ARK_API_KEY (环境变量或 --api-key)")
        sys.exit(1)

    print(f"api_key={mask_key(args.api_key)} (len={len(args.api_key)})")
    print(f"model: {args.model}")
    print(f"work_dir: {args.book_dir}")

    book_dir = Path(args.book_dir)
    img_dir = book_dir / "图片"
    out_dir = book_dir / "视频" / "动态片段"
    out_dir.mkdir(parents=True, exist_ok=True)

    seg_ids = SEG_IDS
    if args.only:
        seg_ids = [s.strip() for s in args.only.split(",") if s.strip()]
        bad = [s for s in seg_ids if s not in SEG_IDS]
        if bad:
            print(f"!! invalid seg ids: {bad}")
            sys.exit(1)
        print(f"only running: {seg_ids}")

    # 1. 校验图片
    missing = [sid for sid in seg_ids if not (img_dir / f"{sid}.jpeg").exists()]
    if missing:
        print(f"!! missing images: {missing}")
        sys.exit(1)

    # 2. 提取画面描述 + 加 motion 后缀
    prompts: dict[str, str] = {}
    for sid in seg_ids:
        md = (img_dir.parent / "剧本" / "分镜" / f"{sid}.md").read_text(encoding="utf-8")
        base = extract_paint_desc(md)
        prompts[sid] = f"{base} {MOTION_SUFFIX}"
        print(f"  prompt[{sid}]: {len(prompts[sid])} chars")

    # 3. 并发提交 + 轮询 + 下载
    print(f"\n=== START (workers={WORKER_LIMIT}) ===")
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=WORKER_LIMIT) as ex:
        futs = {
            ex.submit(
                process_one, args.api_key, args.model, sid,
                img_dir / f"{sid}.jpeg", prompts[sid],
                out_dir / f"{sid}.mp4"
            ): sid for sid in seg_ids
        }
        for fut in as_completed(futs):
            res = fut.result()
            results.append(res)

    # 4. 按 sid 排序 + 写报告
    results.sort(key=lambda r: r["sid"])
    report = {
        "model": args.model,
        "mode": "single_image_i2v",
        "ratio": "9:16",
        "resolution": "480p",
        "duration_sec": 5,
        "watermark": False,
        "n_total": len(results),
        "n_ok": sum(1 for r in results if r["ok"]),
        "n_fail": sum(1 for r in results if not r["ok"]),
        "results": results,
    }
    report_path = out_dir / "_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n=== DONE: {report['n_ok']}/{report['n_total']} OK ===")
    print(f"  report: {report_path}")
    print(f"  videos: {out_dir}")
    for r in results:
        flag = "✓" if r["ok"] else "✗"
        sz = f"{r.get('size_bytes', 0):>9,}B" if r["ok"] else "FAIL"
        tid = r.get("task_id", "-")
        print(f"    {flag} {r['sid']}.mp4  {sz}  task={tid}")


if __name__ == "__main__":
    main()