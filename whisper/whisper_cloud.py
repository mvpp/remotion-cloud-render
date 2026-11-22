"""Client for the cloud Whisper server (server.py next to this file). Standard library only.

    import whisper_cloud
    res = whisper_cloud.transcribe("take.wav", language="zh", initial_prompt="以下是普通话的句子。")
    # same shape as mlx_whisper.transcribe(..., word_timestamps=True):
    # {"text", "language", "segments": [{"start", "end", "text", "words": [{"word", "start", "end", "probability"}]}]}

`audio` is a file path or a numpy float32 array at 16 kHz. Large inputs are re-encoded to 16 kHz mono FLAC with ffmpeg.

Configuration lives in a JSON file, by default ~/.config/whisper-cloud/config.json (override the path with
WHISPER_CLOUD_CONFIG). Two backends:

    Compute Engine GPU VM, reached through an IAP tunnel (no public port; IAM decides who may connect). The client
    starts the VM when it is stopped; the VM powers itself off after a few idle minutes.
    {"backend": "gce", "project": "my-project", "zone": "us-central1-a", "instance": "whisper-l4", "port": 8080,
     "gcloud": "/path/to/gcloud"}

    Cloud Run service deployed without --allow-unauthenticated (ID token of the gcloud user, needs roles/run.invoker).
    {"backend": "cloudrun", "url": "https://whisper-xxxx.us-central1.run.app", "gcloud": "/path/to/gcloud"}

    Optional "fallback": {...another backend...}, used only when the GPU VM cannot be started (stockout, quota), and
    said out loud; the result's meta.fallback records it. Errors inside a transcription never switch backends.

Errors raise WhisperCloudError with the reason in plain words. This module never falls back to a local model: the
caller decides that, explicitly.
"""
import atexit
import json
import os
import shutil
import socket
import struct
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

UPLOAD_LIMIT = 30 * 1024 * 1024  # Cloud Run's HTTP/1 request limit is 32 MiB; also keeps tunnel uploads small
DEFAULT_CONFIG = Path.home() / ".config" / "whisper-cloud" / "config.json"


class WhisperCloudError(RuntimeError):
    pass


class MachineUnavailable(WhisperCloudError):
    """The GPU VM could not be started (stockout, quota): the only case where a configured fallback is used."""


def config_path():
    return Path(os.environ.get("WHISPER_CLOUD_CONFIG") or DEFAULT_CONFIG).expanduser()


def configured():
    return config_path().exists()


def load_config():
    p = config_path()
    if not p.exists():
        raise WhisperCloudError(f"没有云端 Whisper 配置（{p}）")
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as e:
        raise WhisperCloudError(f"云端 Whisper 配置读不了（{p}：{e}）") from None
    cfg.setdefault("backend", "cloudrun" if cfg.get("url") else "gce")
    need = ["url"] if cfg["backend"] == "cloudrun" else ["project", "zone", "instance"]
    miss = [k for k in need if not cfg.get(k)]
    if miss:
        raise WhisperCloudError(f"云端 Whisper 配置缺 {', '.join(miss)}（{p}）")
    return cfg


def _gcloud(cfg):
    g = cfg.get("gcloud") or shutil.which("gcloud")
    if not g or not Path(g).exists():
        raise WhisperCloudError("找不到 gcloud（配置里写 gcloud 的路径）")
    return g


def _run(cfg, *args, timeout=120):
    r = subprocess.run([_gcloud(cfg), *args, "--quiet"], capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def _why(err):
    lines = [l for l in err.splitlines() if l.strip()]
    text = " ".join(lines)
    if "STOCKOUT" in text or "does not have enough resources" in text:
        return "谷歌云这个区现在没有空闲的 L4 显卡（缺货），过一会儿再试"
    if "auth" in text.lower() and ("login" in text.lower() or "credential" in text.lower()):
        return "gcloud 登录过期，要本人跑 gcloud auth login"
    return (lines[-1] if lines else "没有输出")[:300]


# ------------------------------------------------------------------ Cloud Run backend

_TOKEN = {"value": None, "at": 0.0}


def _token(cfg):
    if _TOKEN["value"] and time.time() - _TOKEN["at"] < 45 * 60:
        return _TOKEN["value"]
    rc, out, err = _run(cfg, "auth", "print-identity-token", timeout=60)
    if rc != 0 or not out:
        raise WhisperCloudError(f"gcloud 拿身份令牌失败（{_why(err)}）")
    _TOKEN.update(value=out, at=time.time())
    return out


# ------------------------------------------------------------------ Compute Engine backend

_TUNNEL = {"proc": None, "port": None}
_LOCK = threading.Lock()


def _vm(cfg, *args, timeout=300):
    return _run(cfg, "compute", "instances", *args, cfg["instance"], "--zone", cfg["zone"], "--project",
                cfg["project"], timeout=timeout)


def _vm_status(cfg):
    rc, out, err = _vm(cfg, "describe", "--format=value(status)", timeout=60)
    if rc != 0:
        raise WhisperCloudError(f"查不到云端 Whisper 机器 {cfg['instance']}（{_why(err)}）")
    return out


def _ensure_vm(cfg, say):
    deadline = time.time() + 300
    while True:
        st = _vm_status(cfg)
        if st == "RUNNING":
            return False
        if st in ("TERMINATED", "STOPPED"):
            say(f"云端 Whisper 机器没开，正在开机（约 1–2 分钟）……")
            rc, _, err = _vm(cfg, "start", timeout=300)
            if rc != 0:
                raise MachineUnavailable(f"云端 Whisper 机器开不了机：{_why(err)}")
            return True
        if st == "SUSPENDED":
            rc, _, err = _vm(cfg, "resume", timeout=300)
            if rc != 0:
                raise MachineUnavailable(f"云端 Whisper 机器恢复不了：{_why(err)}")
            return True
        if time.time() > deadline:  # STOPPING / PROVISIONING / STAGING for too long
            raise WhisperCloudError(f"云端 Whisper 机器卡在 {st} 状态超过 5 分钟")
        time.sleep(5)


def _close_tunnel():
    p = _TUNNEL.get("proc")
    if p and p.poll() is None:
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()
    _TUNNEL.update(proc=None, port=None)


atexit.register(_close_tunnel)


def _tunnel(cfg):
    p = _TUNNEL.get("proc")
    if p and p.poll() is None:
        return _TUNNEL["port"]
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    proc = subprocess.Popen([_gcloud(cfg), "compute", "start-iap-tunnel", cfg["instance"], str(cfg.get("port", 8080)),
                             f"--local-host-port=localhost:{port}", "--zone", cfg["zone"], "--project", cfg["project"]],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    _TUNNEL.update(proc=proc, port=port)
    t = time.time()
    while time.time() - t < 30:  # wait for the local listener
        if proc.poll() is not None:
            err = proc.stderr.read()
            _TUNNEL.update(proc=None, port=None)
            raise WhisperCloudError(f"连不上云端 Whisper 机器的 IAP 隧道：{_why(err)}")
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return port
        except OSError:
            time.sleep(0.5)
    _close_tunnel()
    raise WhisperCloudError("IAP 隧道 30 秒没起来")


def _gce_ready(cfg, say):
    """Start the VM if needed, open the tunnel, wait for /healthz. Returns the base URL."""
    started = _ensure_vm(cfg, say)
    wait = float(cfg.get("boot_wait", 900 if started else 600))
    t = time.time()
    told = False
    while True:
        try:
            port = _tunnel(cfg)
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=10) as r:
                if r.status == 200:
                    return f"http://127.0.0.1:{port}"
        except WhisperCloudError:
            if time.time() - t > wait:
                raise
        except (urllib.error.URLError, OSError, ConnectionError):
            pass
        if time.time() - t > wait:
            raise WhisperCloudError(f"云端 Whisper 机器开了 {int(wait)} 秒还没准备好（看串口日志：gcloud compute instances "
                                    f"get-serial-port-output {cfg['instance']} --zone {cfg['zone']} | grep whisper-run）")
        if not told and time.time() - t > 20:
            say("等云端 Whisper 机器把模型读进显卡……")
            told = True
        if _vm_status(cfg) in ("TERMINATED", "STOPPED", "STOPPING"):  # idle power-off raced us, or preempted
            _close_tunnel()
            started = _ensure_vm(cfg, say) or started
        else:
            _close_tunnel()  # a tunnel opened before the server listened stays broken; open a fresh one
        time.sleep(5)


# ------------------------------------------------------------------ shared

def _ffmpeg(cfg):
    for c in (cfg.get("ffmpeg"), os.environ.get("FFMPEG"), shutil.which("ffmpeg"), "/opt/homebrew/bin/ffmpeg"):
        if c and Path(c).exists():
            return c
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _flac(cfg, src_args, stdin=None):
    ff = _ffmpeg(cfg)
    if not ff:
        raise WhisperCloudError("音频超过 30 MB，要用 ffmpeg 压成 FLAC 才能上传，但这台机器找不到 ffmpeg")
    r = subprocess.run([ff, "-v", "error", *src_args, "-ac", "1", "-ar", "16000", "-c:a", "flac", "-f", "flac", "-"],
                       input=stdin, capture_output=True, timeout=600)
    if r.returncode != 0:
        raise WhisperCloudError(f"ffmpeg 压 FLAC 失败：{r.stderr.decode(errors='replace')[-300:]}")
    return r.stdout


def _payload(cfg, audio):
    """(audio bytes, raw_f32 flag)."""
    if isinstance(audio, (str, os.PathLike)):
        p = Path(audio)
        if not p.exists():
            raise WhisperCloudError(f"音频文件不存在：{p}")
        if p.stat().st_size <= UPLOAD_LIMIT:
            return p.read_bytes(), False
        return _flac(cfg, ["-i", str(p)]), False
    try:
        import numpy as np
    except ImportError:
        raise WhisperCloudError("传进来的不是文件路径，也不是 numpy 数组") from None
    raw = np.ascontiguousarray(audio, dtype="<f4").tobytes()
    if len(raw) <= UPLOAD_LIMIT:
        return raw, True
    return _flac(cfg, ["-f", "f32le", "-ar", "16000", "-ac", "1", "-i", "pipe:0"], stdin=raw), False


def _say(msg):
    import sys
    print(msg, file=sys.stderr, flush=True)


def transcribe(audio, language=None, initial_prompt=None, word_timestamps=True, condition_on_previous_text=True,
               beam_size=1, temperature=None, vad_filter=False, clip_timestamps=None, say=_say, **_ignored):
    """mlx_whisper.transcribe-compatible call against the cloud server. Unknown keyword arguments (e.g.
    path_or_hf_repo) are accepted and ignored so call sites can pass the same arguments as to mlx-whisper."""
    cfg = load_config()
    data, raw = _payload(cfg, audio)
    if len(data) > UPLOAD_LIMIT:
        raise WhisperCloudError(f"音频压完还有 {len(data) / 1e6:.0f} MB，超过单次上传上限，先切成几段再转")
    opt = {"language": language, "initial_prompt": initial_prompt, "word_timestamps": word_timestamps,
           "condition_on_previous_text": condition_on_previous_text, "beam_size": beam_size,
           "vad_filter": vad_filter, "raw_f32": raw}
    if clip_timestamps:
        opt["clip_timestamps"] = [float(x) for x in clip_timestamps]
    if temperature is not None:
        opt["temperature"] = list(temperature) if isinstance(temperature, (list, tuple)) else temperature
    head = json.dumps(opt, ensure_ascii=False).encode()
    body = struct.pack(">I", len(head)) + head + data
    try:
        return _send(cfg, body, say)
    except MachineUnavailable as e:
        fb = cfg.get("fallback")
        if not fb:
            raise
        say(f"⚠ {e}。改用备用的云端 Whisper（{fb.get('label') or fb.get('backend', 'cloudrun')}，比 GPU 慢很多）")
        fcfg = {"gcloud": cfg.get("gcloud"), "ffmpeg": cfg.get("ffmpeg"), **fb}
        fcfg.setdefault("backend", "cloudrun" if fcfg.get("url") else "gce")
        res = _send(fcfg, body, say)
        res.setdefault("meta", {})["fallback"] = {"why": str(e), "used": fcfg.get("label") or fcfg["backend"]}
        return res


def _send(cfg, body, say):
    timeout = float(cfg.get("timeout", 900))
    gce = cfg["backend"] == "gce"
    last = ""
    with _LOCK:
        for attempt in range(1, 6):
            headers = {"Content-Type": "application/octet-stream"}
            if gce:
                base = _gce_ready(cfg, say)
            else:
                base = cfg["url"].rstrip("/")
                headers["Authorization"] = "Bearer " + _token(cfg)
            req = urllib.request.Request(base + "/transcribe", data=body, method="POST", headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", errors="replace")[:300]
                if e.code in (401, 403) and not gce:
                    _TOKEN["value"] = None
                    if attempt == 1:
                        continue
                    raise WhisperCloudError(f"云端 Whisper 拒绝了身份（HTTP {e.code}）：这个 Google 账号要有 Cloud Run "
                                            "调用权限（roles/run.invoker）") from None
                if e.code in (429, 502, 503, 504):  # busy, starting, or recycled mid-request: send again
                    last = f"HTTP {e.code} {detail}"
                    time.sleep(5 * attempt)
                    continue
                raise WhisperCloudError(f"云端 Whisper 出错（HTTP {e.code}）：{detail}") from None
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                # the VM powered off between the health check and the request, was preempted, or the tunnel broke
                last = str(getattr(e, "reason", e))
                if gce:
                    _close_tunnel()
                time.sleep(3 * attempt)
                continue
    raise WhisperCloudError(f"云端 Whisper 试了 5 次都没成（最后一次：{last}）")


def words(res):
    """[(word, start, end)] from a transcribe() result."""
    return [(w["word"], w["start"], w["end"]) for s in res.get("segments", []) for w in s.get("words", [])]


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="转一条音频，打印 JSON（和 mlx-whisper 一样的格式）")
    ap.add_argument("audio", nargs="?")
    ap.add_argument("--language")
    ap.add_argument("--prompt")
    ap.add_argument("--out")
    ap.add_argument("--status", action="store_true", help="只看云端机器状态")
    ap.add_argument("--stop", action="store_true", help="马上关掉云端机器（GCE）")
    a = ap.parse_args()
    if a.status or a.stop:
        c = load_config()
        if c["backend"] != "gce":
            raise SystemExit("Cloud Run 没有机器可看/可关，空闲自动缩到 0")
        if a.stop:
            rc, _, err = _vm(c, "stop", timeout=300)
            print("已关机" if rc == 0 else _why(err))
        print(_vm_status(c))
        raise SystemExit(0)
    if not a.audio:
        ap.error("要给一个音频文件")
    t = time.time()
    res = transcribe(a.audio, language=a.language, initial_prompt=a.prompt)
    res.setdefault("meta", {})["round_trip_seconds"] = round(time.time() - t, 2)
    s = json.dumps(res, ensure_ascii=False, indent=1)
    Path(a.out).write_text(s, encoding="utf-8") if a.out else print(s)
