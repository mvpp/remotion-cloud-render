#!/usr/bin/env python3
"""Pre-flight check for rendering a Remotion project on Cloud Run Jobs.

Usage: python3 check_project.py <project dir>
Exit: 0 = nothing blocking (warnings may print), 1 = fix something first.

Checks:
  absolute paths   /Users/..., /home/..., C:\\..., file:// do not exist in the cloud           [blocking]
  version pin      remotion / @remotion/* must be one exact version (the job image is per version)
  GL renderer      remotion.config.ts 'angle'/'egl'/'vulkan' need a GPU; cloud tasks use 'swangle'
  system fonts     font-family names never loaded by the project fall back to the image's fonts
                   (Noto, Noto CJK, Noto Color Emoji, Liberation), so widths and line breaks can change
  WebGL / 3D       three.js / WebGL scenes run on a software renderer in the cloud: slow, costly
  remote assets    fetched at render time: slower, can fail, can change between renders
  public/ size     uploaded inside the bundle on every render
"""
import json
import os
import re
import sys

SRC_EXT = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".css", ".json"}
SKIP_DIRS = {"node_modules", ".git", "out", "build", "dist", ".cache", "public"}
IMAGE_FONTS = {"noto sans", "noto serif", "noto sans cjk sc", "noto sans cjk tc", "noto sans cjk jp",
               "noto sans cjk kr", "noto color emoji", "liberation sans", "liberation serif", "liberation mono",
               "noto sans mono", "noto sans sc"}
GENERIC = {"serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui", "ui-sans-serif", "ui-serif",
           "ui-monospace", "emoji", "math", "inherit", "initial", "unset", "revert"}

ABS_PATH = re.compile(r"""(file://|["'`(]\s*/Users/|["'`(]\s*/home/|["'`(]\s*[A-Za-z]:\\\\)""")
FONT_LITERAL = re.compile(r"""(?:fontFamily|font-family)\s*[:=]\s*['"`]([^'"`]+)['"`]""")
FONT_LOADED = re.compile(r"""new FontFace\(\s*['"`]([^'"`]+)|@font-face\s*{[^}]*font-family\s*:\s*['"]?([^;'"}]+)|google-fonts/([A-Za-z0-9]+)""", re.S)
GL_CONFIG = re.compile(r"setChromiumOpenGlRenderer\(\s*['\"](\w+)['\"]")
WEBGL = re.compile(r"""from ['"](three|@react-three/fiber|@remotion/three)['"]|getContext\(\s*['"]webgl""")
REMOTE = re.compile(r"""['"`](https?://[^'"`\s]+)""")


def walk(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in filenames:
            if os.path.splitext(f)[1] in SRC_EXT and f not in ("package-lock.json",):
                yield os.path.join(dirpath, f)


def dir_size(path):
    return sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(path) for f in fs)


def split_names(value):
    names = []
    for part in value.split(","):
        n = part.strip().strip("'\"").strip()
        if n and not n.startswith("${") and not n.lower().startswith("var(") and n.lower() not in GENERIC:
            names.append(n)
    return names


def main():
    if len(sys.argv) != 2 or not os.path.isdir(sys.argv[1]):
        sys.exit(__doc__)
    root = os.path.abspath(sys.argv[1])
    blocking, notes = [], []

    pkg = json.load(open(os.path.join(root, "package.json")))
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    versions = {k: v for k, v in deps.items() if k == "remotion" or k.startswith("@remotion/")}
    if any(not re.fullmatch(r"\d+\.\d+\.\d+", v) for v in versions.values()) or len(set(versions.values())) > 1:
        notes.append(f"pin remotion and every @remotion/* to one exact version (now {versions}); the job image is built per version")

    used, loaded, abs_hits, gl_hits, webgl_hits, remote_hits = {}, set(), [], [], [], set()
    for path in walk(root):
        rel = os.path.relpath(path, root)
        text = open(path, encoding="utf-8", errors="ignore").read()
        for i, line in enumerate(text.splitlines(), 1):
            if ABS_PATH.search(line):
                abs_hits.append(f"{rel}:{i}: {line.strip()[:110]}")
        for m in FONT_LOADED.finditer(text):
            loaded.add((m.group(1) or m.group(2) or re.sub(r"(?<!^)(?=[A-Z])", " ", m.group(3) or "")).strip().lower())
        for m in FONT_LITERAL.finditer(text):
            for n in split_names(m.group(1)):
                used.setdefault(n.lower(), (n, rel))
        gl_hits += [f"{rel}: '{g}'" for g in GL_CONFIG.findall(text) if g not in ("swangle", "swiftshader")]
        webgl_hits += [rel] if WEBGL.search(text) else []
        remote_hits |= {u for u in REMOTE.findall(text) if "w3.org" not in u and "remotion.dev" not in u}

    if abs_hits:
        blocking.append("local absolute paths (use staticFile() and public/):\n    " + "\n    ".join(abs_hits[:15]))
    if gl_hits:
        notes.append(f"GL renderer {', '.join(gl_hits)} needs a GPU; cloud tasks render with 'swangle' (same pixels, CPU only)")
    missing = [(n, rel) for k, (n, rel) in used.items() if k not in loaded and k not in IMAGE_FONTS]
    if missing:
        notes.append("fonts named but never loaded by the project and not in the image — the cloud substitutes another font:\n    "
                     + "\n    ".join(f"{n} (first in {rel})" for n, rel in missing[:20]))
    if webgl_hits:
        notes.append(f"WebGL/3D in {', '.join(sorted(set(webgl_hits))[:5])}: software-rendered in the cloud, expect slow tasks")
    if remote_hits:
        notes.append(f"{len(remote_hits)} remote URL(s) fetched at render time, e.g. " + ", ".join(sorted(remote_hits)[:4]))
    pub = os.path.join(root, "public")
    if os.path.isdir(pub) and dir_size(pub) > 300e6:
        notes.append(f"public/ is {dir_size(pub) / 1e6:.0f} MB and is uploaded on every render; trim unused files")

    print(f"check {root}")
    for n in notes:
        print(f"  note: {n}")
    for b in blocking:
        print(f"  BLOCKING: {b}")
    print("  result: " + ("fix the blocking items first" if blocking else "ok for the cloud"))
    sys.exit(1 if blocking else 0)


if __name__ == "__main__":
    main()
