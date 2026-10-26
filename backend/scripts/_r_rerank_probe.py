"""一次性探针：验证 cross-encoder 精排能否真实加载并拉开排序（M2）。

下载走 HF 镜像（HF_ENDPOINT=https://hf-mirror.com）；失败只打印降级原因，不抛错。
"""

from __future__ import annotations

import os
import time

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

from app.core.settings import get_settings  # noqa: E402
from app.services.retrieval.reranker import rerank_items  # noqa: E402

QUERY = "机构ID 按既定规则生成的唯一编码，前11位与金融许可证号相同"

ITEMS = [
    {"knowledge_unit_id": 1, "authority_rank": 6, "title": "产品业务基本信息", "content": "产品ID取自 HYF_PD_BIC_INFO_EXT_YBT.PRD_ID，按采集日期取当日有效记录。"},
    {"knowledge_unit_id": 2, "authority_rank": 6, "title": "机构ID监管口径", "content": "机构ID按照既定规则生成分配给实际业务经办最小单位机构的唯一编码，前11位与金融许可证号前11位相同，后13位使用内部机构号。"},
    {"knowledge_unit_id": 3, "authority_rank": 6, "title": "贷款余额口径", "content": "贷款余额仅报送正常类贷款，按五级分类统计，不含表外业务。"},
    {"knowledge_unit_id": 4, "authority_rank": 6, "title": "产品名称", "content": "产品名称取自产品基本信息的 PROD_NAM 字段，长度不超过100字符。"},
    {"knowledge_unit_id": 5, "authority_rank": 6, "title": "机构ID字段画像", "content": "E010002 机构ID，数据格式 varchar(24)，用于标识业务经办机构。"},
    {"knowledge_unit_id": 6, "authority_rank": 5, "title": "客户统一标识", "content": "客户统一标识用于跨系统识别同一客户，由 ECIF 分配。"},
]


def main() -> None:
    settings = get_settings()
    settings.reranker_enabled = True
    started = time.time()
    outcome = rerank_items(ITEMS, QUERY, settings)
    elapsed = round(time.time() - started, 1)
    print("diagnostics", outcome.diagnostics(), "elapsed_s", elapsed)
    for item in outcome.items:
        print(item["knowledge_unit_id"], item.get("rerank_score"), item["title"])


if __name__ == "__main__":
    main()
