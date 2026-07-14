import re
PATTERNS=[(re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),"[手机号]"),(re.compile(r"(?<!\d)\d{17}[\dXx](?!\w)"),"[证件号]"),(re.compile(r"(?<!\d)\d{12,19}(?!\d)"),"[账号]"),(re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),"[邮件]"),(re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),"[IP]"),(re.compile(r"(?:postgresql|mysql|oracle|sqlite)\+?[^\s:]*://\S+",re.I),"[数据库连接串]"),(re.compile(r"(password|passwd|pwd|secret|密钥|密码)\s*[:=]\s*\S+",re.I),"[密钥]")]
def redact_content(text:str)->str:
    for pattern,replacement in PATTERNS:text=pattern.sub(replacement,text)
    return text
def ensure_external_allowed(level:str,local_only:bool)->None:
    if level=="restricted" and not local_only:raise ValueError("restricted 内容只允许本地模型")
    if level=="confidential" and not local_only:raise ValueError("confidential 内容默认只允许 local_only 模型")
