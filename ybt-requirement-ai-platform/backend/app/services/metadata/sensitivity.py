import re

HIGHLY_SENSITIVE = {"密码","密钥","password","secret","身份证号","证件号","id_no","cert_no","账号","卡号","account_no","card_no"}
SENSITIVE = {"客户姓名","姓名","手机号","电话号码","地址","customer_name","cust_name","mobile","phone","address"}

def classify_column_sensitivity(name: str, comment: str | None = None) -> str:
    text = re.sub(r"[\s_]+", "", f"{name} {comment or ''}".lower())
    if any(re.sub(r"[\s_]+", "", item.lower()) in text for item in HIGHLY_SENSITIVE): return "highly_sensitive"
    if any(re.sub(r"[\s_]+", "", item.lower()) in text for item in SENSITIVE): return "sensitive"
    return "normal" if text else "unknown"
