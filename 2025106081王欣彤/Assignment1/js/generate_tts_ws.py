"""
豆包语音 TTS - WebSocket 双向流式 (bidirection) - 全 7 段生成器

路径:
  - URL: wss://openspeech.bytedance.com/api/v3/tts/bidirection
  - Resource-Id: seed-tts-2.0   (你账户开通的是 2.0, 不是 1.0)
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

# Key 优先从环境变量 DOUYIN_TTS_KEY 读取（避免硬编码泄露），缺省回落到本地默认值
import os as _os
API_KEY     = _os.environ.get("DOUYIN_TTS_KEY", "88e1060b-73c2-42ee-8cf2-a8afb326d4cb")
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