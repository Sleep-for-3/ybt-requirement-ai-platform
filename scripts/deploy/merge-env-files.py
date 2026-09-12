#!/usr/bin/env python3
"""把多个 env 片段合并成一份 compose 可以直接使用的 .env。

背景：老部署把「编排变量」放在仓库根 .env，把「运行变量」放在 backend/.env，
而 `docker-compose.yml` 只读取根 .env（backend/.env 不再被容器加载）。
本脚本把两份文件合并成单一来源，避免同一个键出现两个不同取值。

用法（在源码目录执行）：

    python3 scripts/deploy/merge-env-files.py \
        --base backend/.env --override .env \
        --set YBT_RELEASE_TAG=20260913-abcdef0 \
        --output .env.new

规则：
  * --base 提供默认值，--override 优先；
  * 输出保留 --override 的原注释与顺序，只在末尾追加 base 独有的键；
  * 任何键都只出现一次；不会打印任何值到终端，避免密钥进入日志。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

KEY_ALLOWED = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


def parse_env(path: Path) -> tuple[dict[str, str], list[str]]:
    values: dict[str, str] = {}
    lines: list[str] = []
    if not path.exists():
        return values, lines
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip("\n")
        lines.append(line)
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not key or not set(key) <= KEY_ALLOWED or key[0].isdigit():
            continue
        values[key] = value
    return values, lines


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True, help="提供默认值的 env 片段（优先级低）")
    parser.add_argument("--override", required=True, help="优先的 env 片段（注释与顺序会被保留）")
    parser.add_argument("--set", action="append", default=[], help="追加/覆盖的 KEY=VALUE，可重复")
    parser.add_argument("--output", required=True, help="输出文件；已存在时会被覆盖")
    args = parser.parse_args()

    base_values, _ = parse_env(Path(args.base))
    override_values, override_lines = parse_env(Path(args.override))
    forced: dict[str, str] = {}
    for item in args.set:
        if "=" not in item:
            print(f"--set 需要 KEY=VALUE 形式: {item}", file=sys.stderr)
            return 2
        key, value = item.split("=", 1)
        forced[key.strip()] = value

    effective = dict(base_values)
    effective.update(override_values)
    effective.update(forced)

    output: list[str] = list(override_lines)
    if output and output[-1].strip():
        output.append("")

    forced_lines = [f"{key}={value}" for key, value in forced.items() if key not in override_values]
    if forced_lines:
        output.append("# ---- 由 scripts/deploy/merge-env-files.py --set 注入 ----")
        output.extend(forced_lines)
        output.append("")

    base_only = {key: value for key, value in base_values.items() if key not in override_values and key not in forced}
    if base_only:
        output.append("# ---- 从 base 片段（backend/.env）合并进来的运行变量 ----")
        output.extend(f"{key}={value}" for key, value in base_only.items())
        output.append("")

    Path(args.output).write_text("\n".join(output).rstrip("\n") + "\n", encoding="utf-8")
    summary = ", ".join(sorted(effective))
    print(f"已写入 {args.output}：{len(effective)} 个键")
    print(f"键清单：{summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
