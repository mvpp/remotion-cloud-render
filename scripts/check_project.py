#!/usr/bin/env python3
"""上云前体检：查出云端渲染会出问题的地方。

用法: python3 check_project.py <工程目录>
退出码: 0 = 没有阻断问题（可能有提醒）, 1 = 有必须先改的问题。

查这几样：
  软链接            云端只拿到上传的真文件，软链接会断（cloud_render.sh 打包时会自动解开，这里只提醒）
  本机绝对路径      /Users/...、/home/...、C:\\...、file:// 在云上都不存在
  WebGPU            云上没有显卡，navigator.gpu 不可用
  没打包的字体      font-family 用了工程里没有 @font-face 的字体，云上的 Linux 会换成别的字
  外链资源          渲染时从网上拉的图、字体、脚本，可能慢、可能失败、可能每次不一样
"""
import os
import re
import sys

TEXT_EXT = {".html", ".htm", ".css", ".js", ".mjs", ".json", ".svg"}
SKIP_DIRS = {"node_modules", ".git", ".hyperframes", "out", "renders", ".cache", "dist"}
GENERIC_FONTS = {
    "serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui",
    "ui-sans-serif", "ui-serif", "ui-monospace", "emoji", "math", "inherit",
    "initial", "unset", "revert", "var",
}

ABS_PATH = re.compile(r"""(file://|["'(\s]/Users/|["'(\s]/home/|["'(\s][A-Za-z]:\\\\)""")
WEBGPU = re.compile(r"navigator\.gpu|requestAdapter\(|\bwebgpu\b", re.I)
FONT_FACE = re.compile(r"@font-face\s*{[^}]*?font-family\s*:\s*([^;}]+)", re.I | re.S)
FONT_FAMILY = re.compile(r"font-family\s*:\s*([^;}\"]+|\"[^\"]*\"[^;}]*)", re.I)
FONT_ATTR = re.compile(r"fontFamily\s*[:=]\s*['\"`]([^'\"`]+)['\"`]")
REMOTE = re.compile(r"""(?:src|href)\s*=\s*["'](https?://[^"']+)|url\(\s*["']?(https?://[^"')]+)""", re.I)


def names(value):
    out = []
    for part in value.split(","):
        n = part.strip().strip("'\"").strip()
        if n and not n.lower().startswith("var(") and n.lower() not in GENERIC_FONTS and "!important" not in n:
            out.append(n)
    return out


def main():
    if len(sys.argv) != 2 or not os.path.isdir(sys.argv[1]):
        sys.exit(__doc__)
    root = os.path.abspath(sys.argv[1])
    links, abs_hits, gpu_hits, remote_hits = [], [], [], []
    declared, used = set(), {}
    total = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for d in list(dirnames):
            if os.path.islink(os.path.join(dirpath, d)):
                links.append(os.path.relpath(os.path.join(dirpath, d), root))
        for f in filenames:
            p = os.path.join(dirpath, f)
            rel = os.path.relpath(p, root)
            if os.path.islink(p):
                links.append(rel)
                continue
            try:
                total += os.path.getsize(p)
            except OSError:
                pass
            if os.path.splitext(f)[1].lower() not in TEXT_EXT:
                continue
            try:
                text = open(p, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            is_vendor = "vendor" in rel.split(os.sep) or f.endswith(".min.js")
            for i, line in enumerate(text.splitlines(), 1):
                if ABS_PATH.search(line):
                    abs_hits.append(f"{rel}:{i}: {line.strip()[:120]}")
                if not is_vendor and WEBGPU.search(line):
                    gpu_hits.append(f"{rel}:{i}: {line.strip()[:120]}")
            for m in REMOTE.finditer(text):
                url = m.group(1) or m.group(2)
                if "w3.org" not in url:
                    remote_hits.append(f"{rel}: {url[:120]}")
            for m in FONT_FACE.finditer(text):
                declared.update(n.lower() for n in names(m.group(1)))
            if not is_vendor:
                for m in list(FONT_FAMILY.finditer(text)) + list(FONT_ATTR.finditer(text)):
                    for n in names(m.group(1)):
                        used.setdefault(n.lower(), (n, rel))

    blocking = False
    print(f"工程 {root}，约 {total / 1e6:.1f} MB")
    if total > 500e6:
        print("  提醒：工程超过 500 MB，每次上传都慢。大视频素材可以先压一下。")
    if links:
        print(f"\n软链接 {len(links)} 个（cloud_render.sh 打包时会解开；自己调 cloudrun render 要先 cp -RL）：")
        for x in links[:20]:
            print("  ", x)
    if abs_hits:
        blocking = True
        print(f"\n[必须改] 本机绝对路径 {len(abs_hits)} 处，云上找不到，改成工程内相对路径：")
        for x in abs_hits[:20]:
            print("  ", x)
    if gpu_hits:
        blocking = True
        print(f"\n[必须改] 用到 WebGPU {len(gpu_hits)} 处，云上没有显卡，换成 WebGL、Canvas2D 或 CSS/SVG：")
        for x in gpu_hits[:20]:
            print("  ", x)
    missing = [v for k, v in used.items() if k not in declared]
    if missing:
        print(f"\n[建议改] 这些字体没有在工程里用 @font-face 打包，云上会被换成别的字，文字宽度和换行可能变：")
        for n, rel in missing[:30]:
            print(f"   {n}（首次出现在 {rel}）")
    if remote_hits:
        print(f"\n[提醒] 渲染时要联网拉的资源 {len(remote_hits)} 个，建议下载进工程：")
        for x in sorted(set(remote_hits))[:20]:
            print("  ", x)
    print("\n结论：" + ("有必须先改的问题。" if blocking else "可以上云。"))
    sys.exit(1 if blocking else 0)


if __name__ == "__main__":
    main()
