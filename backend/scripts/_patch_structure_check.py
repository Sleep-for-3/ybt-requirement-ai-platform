"""一次性补丁：结构自检支持 v10 的"场景分组"（业务口径/溯源按位置成对，不再要求同名）。"""
from pathlib import Path

TARGET = Path("app/services/requirement_survey_structure_check.py")


def main() -> None:
    text = TARGET.read_bytes().decode("utf-8").replace("\r\n", "\n")

    old_contract = '''    return {
        "version": STRUCTURE_CONTRACT_VERSION,
        "generation": generation,
        "renderer_version": value,
        "label": spec["label"],
        "required_keys": list(spec["required_keys"]),
    }
'''
    new_contract = '''    return {
        "version": STRUCTURE_CONTRACT_VERSION,
        "generation": generation,
        "renderer_version": value,
        "label": spec["label"],
        "required_keys": list(spec["required_keys"]),
        # v10 起列组按场景分列：业务口径-借记卡 与 溯源-借记卡系统 是成对的两组，
        # 组名本来就不相同，只能按位置配对判定，不能再要求去掉前缀后同名。
        "pair_by_position": generation >= 10,
    }
'''
    if old_contract not in text:
        raise SystemExit("contract anchor missing")
    text = text.replace(old_contract, new_contract, 1)

    old_groups = '''    groups_ok = (
        title_row is not None
        and _BASE_TITLE in group_titles
        and _EAST_TITLE in group_titles
        and business_groups == source_groups
        and len(business_groups) >= 1
    )
    add(
        "groups",
        "按来源系统分组（业务口径/溯源成对）",
        groups_ok,
        f"第 {title_row or '?'} 行；业务口径组={business_groups}；溯源组={source_groups}",
    )
'''
    new_groups = '''    paired = business_groups == source_groups
    if contract.get("pair_by_position"):
        paired = len(business_groups) == len(source_groups)
    groups_ok = (
        title_row is not None
        and _BASE_TITLE in group_titles
        and _EAST_TITLE in group_titles
        and paired
        and len(business_groups) >= 1
    )
    add(
        "groups",
        "列组分组（业务口径/溯源成对）",
        groups_ok,
        f"第 {title_row or '?'} 行；业务口径组={business_groups}；溯源组={source_groups}",
    )
'''
    if old_groups not in text:
        raise SystemExit("groups anchor missing")
    text = text.replace(old_groups, new_groups, 1)

    TARGET.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    print("patched", TARGET)


if __name__ == "__main__":
    main()
