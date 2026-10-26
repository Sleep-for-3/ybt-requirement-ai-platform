"""一次性只读勘察：把 T_5_1 需求正文的字段/集市映射/脚本血缘压缩成一份概览。"""
import json
from pathlib import Path

import requests

BASE = "http://127.0.0.1:8011/api"
OUT = Path("scripts/out/probe")
TOKEN = (OUT / "token.txt").read_text().strip()
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def main() -> None:
    document = requests.get(
        f"{BASE}/projects/9/requirements/30/document", headers=HEADERS, timeout=60
    ).json()
    fields = []
    for record in document["fields"]:
        field = record["field"]
        fields.append(
            {
                "id": field["id"],
                "code": field["field_code"],
                "name": field["field_name"],
                "maps": [
                    [
                        mapping.get("mart_table_summary"),
                        mapping.get("mart_field_summary"),
                        mapping.get("business_rule"),
                    ]
                    for mapping in (record.get("mart_mappings") or [])
                ],
                "business": bool((record.get("business") or {}).get("business_definition")),
                "script": [
                    [rule.get("target"), rule.get("source"), rule.get("transformation_expression")]
                    for rule in (document.get("script_basis") or {}).get("rules") or []
                    if (rule.get("target") or {}).get("column_name") == field["field_code"]
                ][:4],
            }
        )
    (OUT / "t51_fields.json").write_text(
        json.dumps(fields, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print("fields", len(fields))
    for item in fields:
        sources = sorted(
            {
                f"{(rule[1] or {}).get('table_name')}.{(rule[1] or {}).get('column_name')}"
                for rule in item["script"]
            }
        )
        print(
            item["code"],
            item["name"],
            "| maps",
            len(item["maps"]),
            [m[0] for m in item["maps"]][:2],
            "| script",
            sources[:3],
        )


if __name__ == "__main__":
    main()
