"""Fix: KnowledgeUnit has scenario_id (not scenario_name). Patch the G2 block. CRLF safe."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(r"C:\Users\李儒伟\Desktop\ai-platform-dsh-20260930-150943 (2)\ai-platform\backend")
PATH = ROOT / "app" / "services" / "retrieval" / "hybrid_retriever.py"

OLD = """        scenario_names: set[str] = set()
        if expansion_enabled:
            scenario_names = matched_scenarios(
                query,
                list(
                    self.db.scalars(
                        select(ProductScenario.scenario_name).where(
                            ProductScenario.project_id == project_id,
                            ProductScenario.enabled.is_(True),
                        )
                    ).all()
                ),
            )
"""

NEW = """        scenario_names: set[str] = set()
        scenario_ids_by_name: dict[str, int] = {}
        if expansion_enabled:
            # KnowledgeUnit 只存 scenario_id，名称要现查；按名称命中后再换成 id 集合。
            rows = self.db.execute(
                select(ProductScenario.id, ProductScenario.scenario_name).where(
                    ProductScenario.project_id == project_id,
                    ProductScenario.enabled.is_(True),
                )
            ).all()
            scenario_ids_by_name = {name: sid for sid, name in rows if name}
            scenario_names = matched_scenarios(query, list(scenario_ids_by_name))
        scenario_ids = {scenario_ids_by_name[name] for name in scenario_names}
"""

OLD_HIT = """            scenario_hit = bool(scenario_names) and unit.scenario_name in scenario_names
"""

NEW_HIT = """            scenario_hit = bool(scenario_ids) and unit.scenario_id in scenario_ids
"""


def main() -> int:
    raw = PATH.read_bytes().decode("utf-8")
    text = raw.replace("\r\n", "\n")
    for old, new, label in ((OLD, NEW, "scenario-ids"), (OLD_HIT, NEW_HIT, "scenario-hit")):
        count = text.count(old)
        if count == 0 and new in text:
            print(f"skip {label}")
            continue
        if count != 1:
            print(f"FAIL {label}: count={count}")
            return 1
        text = text.replace(old, new, 1)
        print(f"ok {label}")
    PATH.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
