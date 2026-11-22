"""Whisper on a Cloud Run L4: faster-whisper with word timestamps, answering in mlx-whisper's JSON shape.

POST /transcribe  body = 4-byte big-endian length + options JSON + audio file bytes (any format PyAV/ffmpeg reads,
                  or raw little-endian float32 16 kHz mono when options.raw_f32 is true)
                  options: language, initial_prompt, word_timestamps (default true), condition_on_previous_text
                  (default true), clip_timestamps, beam_size (default 1, greedy like mlx-whisper), temperature (default 0), vad_filter (default false)
GET  /healthz     model, device, uptime

Cloud Run IAM does the authentication (the service is deployed without --allow-unauthenticated); this process
never sees a token. A GPU instance is billed for its whole life, idle included, and Cloud Run may keep an idle
instance for up to 15 minutes, so the process exits after IDLE_EXIT_SECONDS without a request (0 = never).
"""
import io
import json
import os
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
from faster_whisper import WhisperModel, decode_audio

MODEL_DIR = os.environ.get("WHISPER_MODEL_DIR", "/models/large-v3-turbo")
MODEL_NAME = os.environ.get("WHISPER_MODEL_NAME", "large-v3-turbo")
DEVICE = os.environ.get("WHISPER_DEVICE", "cuda")
COMPUTE = os.environ.get("WHISPER_COMPUTE", "float16")
IDLE_EXIT = float(os.environ.get("IDLE_EXIT_SECONDS", "180"))
PORT = int(os.environ.get("PORT", "8080"))

T0 = time.time()
model = WhisperModel(MODEL_DIR if os.path.isdir(MODEL_DIR) else MODEL_NAME, device=DEVICE, compute_type=COMPUTE)
LOAD_SECONDS = round(time.time() - T0, 2)
print(json.dumps({"event": "model_loaded", "seconds": LOAD_SECONDS, "device": DEVICE, "compute": COMPUTE}), flush=True)

GPU = threading.Lock()
state = {"last": time.time(), "busy": 0}
state_lock = threading.Lock()


def idle_watch():
    while IDLE_EXIT > 0:
        time.sleep(5)
        with state_lock:
            idle = state["busy"] == 0 and time.time() - state["last"] > IDLE_EXIT
        if idle:
            print(json.dumps({"event": "idle_exit", "after_seconds": IDLE_EXIT}), flush=True)
            os._exit(0)


def transcribe(audio_bytes, opt):
    if opt.get("raw_f32"):
        audio = np.frombuffer(audio_bytes, dtype="<f4").astype(np.float32)
    else:
        audio = decode_audio(io.BytesIO(audio_bytes), sampling_rate=16000)
    kw = dict(
        language=opt.get("language"),
        initial_prompt=opt.get("initial_prompt") or None,
        word_timestamps=bool(opt.get("word_timestamps", True)),
        condition_on_previous_text=bool(opt.get("condition_on_previous_text", True)),
        beam_size=int(opt.get("beam_size", 1)),  # 1 = greedy, like mlx-whisper: same words, same times
        temperature=opt.get("temperature", [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]),
        vad_filter=bool(opt.get("vad_filter", False)),
    )
    if opt.get("clip_timestamps"):  # [start, end, start, end, ...] seconds, as in mlx-whisper
        kw["clip_timestamps"] = [float(x) for x in opt["clip_timestamps"]]
    t = time.time()
    with GPU:
        segs, info = model.transcribe(audio, **kw)
        out = []
        for s in segs:  # the generator decodes lazily: consume it inside the lock
            out.append({
                "id": s.id, "seek": s.seek, "start": s.start, "end": s.end, "text": s.text, "tokens": list(s.tokens),
                "temperature": s.temperature, "avg_logprob": s.avg_logprob,
                "compression_ratio": s.compression_ratio, "no_speech_prob": s.no_speech_prob,
                "words": [{"word": w.word, "start": w.start, "end": w.end, "probability": w.probability}
                          for w in (s.words or [])],
            })
    return {
        "text": "".join(s["text"] for s in out),
        "segments": out,
        "language": info.language,
        "meta": {"engine": "faster-whisper", "model": MODEL_NAME, "device": DEVICE, "compute": COMPUTE,
                 "audio_seconds": round(len(audio) / 16000, 3), "seconds": round(time.time() - t, 3),
                 "uptime": round(time.time() - T0, 1), "load_seconds": LOAD_SECONDS},
    }


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/healthz"):
            return self.send(200, {"ok": True, "model": MODEL_NAME, "device": DEVICE,
                                   "uptime": round(time.time() - T0, 1), "load_seconds": LOAD_SECONDS})
        self.send(404, {"error": "not found"})

    def do_POST(self):
        if not self.path.startswith("/transcribe"):
            return self.send(404, {"error": "not found"})
        with state_lock:
            state["busy"] += 1
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n)
            if len(body) < 4:
                return self.send(400, {"error": "empty body"})
            k = struct.unpack(">I", body[:4])[0]
            opt = json.loads(body[4:4 + k] or b"{}")
            audio = body[4 + k:]
            if not audio:
                return self.send(400, {"error": "no audio"})
            self.send(200, transcribe(audio, opt))
        except Exception as e:  # report the cause to the caller; the client turns it into a clear error
            print(json.dumps({"event": "error", "error": repr(e)[:500]}), file=sys.stderr, flush=True)
            self.send(500, {"error": f"{type(e).__name__}: {e}"[:500]})
        finally:
            with state_lock:
                state["busy"] -= 1
                state["last"] = time.time()

    def log_message(self, fmt, *args):
        print(json.dumps({"event": "http", "line": fmt % args}), flush=True)


if __name__ == "__main__":
    threading.Thread(target=idle_watch, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
