"""Office 文件的确定性字节化（docx/xlsx 共用）。

正式文件审计要求"同一冻结内容 = 同一文件"。但 python-docx / openpyxl 默认会把
**当前时间**写进 ``docProps/core.xml`` 的 ``dcterms:created`` / ``dcterms:modified``，
并把生成时间写进 zip 条目头；于是同一份内容隔一秒导出就会得到不同 sha256。

真实事故（2026-10-24 一表通导出）：同一冻结快照连续三次导出 xlsx，file_sha256
分别是 ``3dbef3c1…``、``4c6a3570…``、``dbc3a675…`` —— 内容与版式完全相同，
差异只来自时间戳。这类差异会让"按内容身份复用产物"失去意义，也让审计无法用
文件 hash 证明"交付的就是当时冻结的那份"。

处理办法与 docx 侧一致：删掉 core.xml 里的时间元素，重排 zip 条目并把条目时间
固定为 2000-01-01，正文、样式、公式都不动。
"""

from __future__ import annotations

import re
import zipfile
from io import BytesIO

CORE_TIME_PATTERN = re.compile(
    rb"<dcterms:(?:created|modified|lastPrinted)[^>]*/>"
    rb"|<dcterms:(?:created|modified|lastPrinted)[^>]*>.*?</dcterms:(?:created|modified|lastPrinted)>",
    re.DOTALL,
)
FIXED_DATE_TIME = (2000, 1, 1, 0, 0, 0)


def strip_core_timestamps(data: bytes) -> bytes:
    """删除 ``docProps/core.xml`` 中的创建/修改/打印时间元素。"""

    source = zipfile.ZipFile(BytesIO(data))
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
        for name in source.namelist():
            payload = source.read(name)
            if name == "docProps/core.xml":
                payload = CORE_TIME_PATTERN.sub(b"", payload)
            target.writestr(_fixed_info(name), payload)
    source.close()
    return buffer.getvalue()


def deterministic_package(data: bytes) -> bytes:
    """重排 zip：固定条目时间戳与属性，其余字节原样保留。"""

    source = zipfile.ZipFile(BytesIO(data))
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
        for name in source.namelist():
            target.writestr(_fixed_info(name), source.read(name))
    source.close()
    return buffer.getvalue()


def normalize_office_bytes(data: bytes) -> bytes:
    """一步到位：先去时间元数据，再固定 zip 条目属性。"""

    return deterministic_package(strip_core_timestamps(data))


def _fixed_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=FIXED_DATE_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o600 << 16
    return info
