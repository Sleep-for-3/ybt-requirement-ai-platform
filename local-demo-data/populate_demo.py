import json
import subprocess


BASE_URL = "http://localhost:18000/api"
PROJECT_ID = 1


def request(method: str, path: str, payload: dict | None = None):
    command = [
        "curl.exe",
        "--noproxy",
        "*",
        "--fail",
        "--silent",
        "--show-error",
        "--max-time",
        "15",
        "-X",
        method,
        f"{BASE_URL}{path}",
    ]
    if payload is not None:
        command.extend(
            [
                "-H",
                "Content-Type: application/json; charset=utf-8",
                "--data-binary",
                json.dumps(payload, ensure_ascii=False),
            ]
        )
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False)
    if completed.returncode:
        raise RuntimeError(f"{method} {path} failed: {completed.stderr.strip()}")
    return json.loads(completed.stdout)


tables = request("GET", f"/target-tables?project_id={PROJECT_ID}")
table = next((item for item in tables if item["table_code"] == "YBT_T_DEMO_ACCOUNT"), None)
if table is None:
    table = request(
        "POST",
        "/target-tables",
        {
            "project_id": PROJECT_ID,
            "table_code": "YBT_T_DEMO_ACCOUNT",
            "table_name": "模拟账户信息表",
            "description": "完全合成的一表通目标表，仅用于本地技术验证。",
        },
    )

field_specs = [
    ("CUSTOMER_NO", "客户编号", "VARCHAR(64)", "虚构客户的唯一标识", "仅用于本地模拟，不得关联真实客户"),
    ("ACCOUNT_NO", "账户编号", "VARCHAR(64)", "虚构账户的唯一标识", "仅用于本地模拟，不得关联真实账户"),
    ("ACCOUNT_NAME", "账户名称", "VARCHAR(200)", "虚构账户展示名称", "不得填入真实姓名或账户名"),
    ("PRODUCT_CODE", "产品代码", "VARCHAR(32)", "模拟产品分类代码", "使用合成产品代码"),
    ("CURRENCY_CODE", "币种代码", "VARCHAR(3)", "账户币种代码", "使用标准币种字符代码"),
    ("BALANCE", "账户余额", "DECIMAL(18,2)", "报送日终模拟余额", "取模拟报送日日终余额"),
    ("OPEN_DATE", "开户日期", "DATE", "模拟账户开户日期", "日期格式 YYYY-MM-DD"),
    ("STATUS_CODE", "账户状态", "VARCHAR(1)", "模拟账户状态代码", "仅允许 A、F、C 三种模拟状态"),
    ("BRANCH_CODE", "机构代码", "VARCHAR(32)", "虚构机构代码", "不得使用真实机构号"),
    ("REPORT_DATE", "报送日期", "DATE", "模拟监管报送日期", "作为数据快照日期"),
]
existing_fields = request("GET", f"/fields?project_id={PROJECT_ID}&target_table_id={table['id']}")
existing_field_codes = {item["field_code"] for item in existing_fields}
for code, name, field_type, definition, regulatory in field_specs:
    if code in existing_field_codes:
        continue
    request(
        "POST",
        "/fields",
        {
            "project_id": PROJECT_ID,
            "target_table_id": table["id"],
            "field_code": code,
            "field_name": name,
            "field_type": field_type,
            "required_flag": code != "ACCOUNT_NAME",
            "field_definition": definition,
            "regulatory_description": regulatory,
        },
    )

scenario_specs = [
    ("PERSONAL_DEMAND", "个人活期存款", "deposit", 10),
    ("PERSONAL_TIME", "个人定期存款", "deposit", 20),
    ("MANUAL_ENTRY", "手工补录", "manual", 30),
]
existing_scenarios = request("GET", f"/projects/{PROJECT_ID}/scenarios")
existing_scenario_codes = {item["scenario_code"] for item in existing_scenarios}
for code, name, scenario_type, sort_order in scenario_specs:
    if code in existing_scenario_codes:
        continue
    request(
        "POST",
        f"/projects/{PROJECT_ID}/scenarios",
        {
            "scenario_code": code,
            "scenario_name": name,
            "scenario_type": scenario_type,
            "description": "完全合成的本地验收业务场景。",
            "enabled": True,
            "sort_order": sort_order,
        },
    )

final_fields = request("GET", f"/fields?project_id={PROJECT_ID}&target_table_id={table['id']}")
final_scenarios = request("GET", f"/projects/{PROJECT_ID}/scenarios")
print(
    json.dumps(
        {
            "project_id": PROJECT_ID,
            "target_table_id": table["id"],
            "target_table_code": table["table_code"],
            "field_count": len(final_fields),
            "scenario_count": len(final_scenarios),
        },
        ensure_ascii=False,
    )
)
