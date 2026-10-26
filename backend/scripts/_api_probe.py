"""一次性探针：登录 + 调用平台接口并把响应存到 out/probe/。

用法（在 backend 目录下）：
  .venv\\Scripts\\python.exe scripts/_api_probe.py GET  /health/ready
  .venv\\Scripts\\python.exe scripts/_api_probe.py POST /projects/9/requirements/script-preview --json '{"script_version_ids":[1]}'
  .venv\\Scripts\\python.exe scripts/_api_probe.py POST /projects/9/... --form a=1 --file x.xlsx=path
可选：--save name 把响应体存成 out/probe/name.json；--raw 存二进制到 out/probe/name.bin。
不写入仓库数据（除 out/probe）。
"""
import argparse
import json
import os
import sys
from pathlib import Path

import requests

BASE = os.environ.get("PROBE_BASE", "http://127.0.0.1:8011/api")
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out" / "probe"
TOKEN_FILE = OUT / "token.txt"


def login():
    OUT.mkdir(parents=True, exist_ok=True)
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    r = requests.post(f"{BASE}/auth/login", json={"username": "ybt-lead", "password": "Ybt#20261024lead"}, timeout=30)
    r.raise_for_status()
    token = r.json()["access_token"]
    TOKEN_FILE.write_text(token)
    return token


def headers():
    return {"Authorization": f"Bearer {login()}"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("method")
    ap.add_argument("path")
    ap.add_argument("--json", default=None)
    ap.add_argument("--form", action="append", default=[])
    ap.add_argument("--file", action="append", default=[])
    ap.add_argument("--save", default=None)
    ap.add_argument("--raw", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    url = f"{BASE}{args.path}"
    kw = {"headers": headers(), "timeout": 1800}
    if args.json:
        kw["json"] = json.loads(args.json)
    if args.form or args.file:
        data = {}
        files = {}
        for item in args.form:
            k, v = item.split("=", 1)
            data[k] = v
        for item in args.file:
            k, v = item.split("=", 1)
            files[k] = open(v, "rb")
        kw["data"] = data
        kw["files"] = files
    r = requests.request(args.method.upper(), url, **kw)
    print(f"HTTP {r.status_code}")
    ctype = r.headers.get("content-type", "")
    interesting = {k.lower(): v for k, v in r.headers.items() if k.lower().startswith("x-requirement")}
    if interesting:
        print("HEADERS " + json.dumps(interesting, ensure_ascii=False))
    name = args.out or args.save
    if args.raw or "spreadsheet" in ctype or "wordprocessing" in ctype or "octet-stream" in ctype or "zip" in ctype:
        OUT.mkdir(parents=True, exist_ok=True)
        dest = OUT / (name or "download.bin")
        dest.write_bytes(r.content)
        print(f"BINARY {len(r.content)} bytes -> {dest}")
        return
    try:
        body = r.json()
    except Exception:
        print(r.text[:4000])
        return
    text = json.dumps(body, ensure_ascii=False, indent=1)
    if name:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"{name}.json").write_text(text, encoding="utf-8")
        print(f"SAVED -> {OUT / f'{name}.json'}")
    print(text[:12000])


if __name__ == "__main__":
    main()
