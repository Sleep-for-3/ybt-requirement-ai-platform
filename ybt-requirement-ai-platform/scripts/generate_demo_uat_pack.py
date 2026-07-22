from __future__ import annotations

import argparse
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import re
import zipfile

from openpyxl import Workbook


FIXED_ZIP_TIME = (2026, 7, 22, 0, 0, 0)


def generate_demo_pack(output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "一表通目标字段模板.xlsx": _workbook_bytes("目标字段", [["表代码", "字段代码", "字段名称"], ["DEMO_CUSTOMER", "DEMO_CUSTOMER_TYPE", "示例客户类型"]]),
        "银行正式交付模板.xlsx": _workbook_bytes("业务口径及技术溯源表", [["字段代码", "字段名称", "示例口径"], ["DEMO_CUSTOMER_TYPE", "示例客户类型", "仅用于公开模拟 UAT"]]),
        "历史业务口径.xlsx": _workbook_bytes("历史业务口径", [["字段代码", "场景", "业务口径"], ["DEMO_CUSTOMER_TYPE", "DEMO_SCENE", "示例历史建议，不覆盖正式内容"]]),
        "历史技术溯源.xlsx": _workbook_bytes("历史技术溯源", [["字段代码", "来源系统", "来源字段"], ["DEMO_CUSTOMER_TYPE", "SAMPLE_SYSTEM", "TEST_SOURCE.DEMO_TYPE"]]),
        "监管答疑.xlsx": _workbook_bytes("监管答疑", [["问题", "回答"], ["示例客户类型如何填报？", "仅使用虚构枚举 DEMO_A/DEMO_B"]]),
        "数据字典.xlsx": _workbook_bytes("数据字典", [["schema", "table", "column", "type"], ["SAMPLE", "TEST_CUSTOMER", "DEMO_TYPE", "VARCHAR"]]),
        "load_customer_v1.sql": b"-- DEMO ONLY; never execute uploaded SQL\nSELECT DEMO_TYPE FROM SAMPLE.TEST_CUSTOMER;\n",
        "load_customer_v2.sql": b"-- DEMO ONLY; never execute uploaded SQL\nSELECT COALESCE(DEMO_TYPE, 'DEMO_UNKNOWN') AS DEMO_TYPE FROM SAMPLE.TEST_CUSTOMER;\n",
        "run_customer.sh": b"#!/bin/sh\n# DEMO ONLY; uploaded Shell is evidence and must never execute\necho 'DEMO UAT'\n",
        "README.md": "# 公开模拟 UAT 材料\n\n全部内容属于示例银行、示例客户与 DEMO/TEST/SAMPLE 命名，不对应任何真实机构。\n".encode("utf-8"),
    }
    for name, content in files.items():
        (output_dir / name).write_bytes(content)
    manifest = {
        "pack_type": "public_sanitized_demo",
        "file_count": len(files),
        "files": [{"name": name, "sha256": sha256(content).hexdigest(), "byte_size": len(content)} for name, content in sorted(files.items())],
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    (output_dir / "expected_manifest.json").write_bytes(manifest_bytes)
    return {**manifest, "output_dir": str(output_dir.resolve()), "manifest_sha256": sha256(manifest_bytes).hexdigest()}


def _workbook_bytes(title: str, rows: list[list[str]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = title
    for row in rows:
        sheet.append(row)
    sheet.freeze_panes = "A2"
    workbook.properties.creator = "YBT DEMO UAT"
    workbook.properties.created = "2026-07-22T00:00:00Z"
    workbook.properties.modified = "2026-07-22T00:00:00Z"
    raw = BytesIO(); workbook.save(raw)
    source = zipfile.ZipFile(BytesIO(raw.getvalue()))
    stable = BytesIO()
    with zipfile.ZipFile(stable, "w", zipfile.ZIP_DEFLATED) as target:
        for name in sorted(source.namelist()):
            info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIME); info.compress_type = zipfile.ZIP_DEFLATED
            content = source.read(name)
            if name == "docProps/core.xml":
                content = re.sub(rb"(<dcterms:created[^>]*>)[^<]*(</dcterms:created>)", rb"\g<1>2026-07-22T00:00:00Z\g<2>", content)
                content = re.sub(rb"(<dcterms:modified[^>]*>)[^<]*(</dcterms:modified>)", rb"\g<1>2026-07-22T00:00:00Z\g<2>", content)
            target.writestr(info, content)
    return stable.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a deterministic public sanitized UAT material pack")
    parser.add_argument("--output", type=Path, default=Path(os.getenv("UAT_LOCAL_PACK_DIR", "uat_local_packs")) / "demo")
    args = parser.parse_args()
    print(json.dumps(generate_demo_pack(args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
