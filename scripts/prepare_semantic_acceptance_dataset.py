"""Generate a fully synthetic manual acceptance corpus (10 docs / 100 chunks / 20 questions)."""

from __future__ import annotations

import json
from pathlib import Path


OUTPUT = Path(".local-run/semantic-acceptance")
TOPICS = [
    ("loan_balance", "贷款余额", "LOAN_DTL.BALANCE_AMT", "未结清贷款本金余额"),
    ("credit_limit", "授信额度", "CREDIT_LIMIT.TOTAL_AMT", "已审批可使用的总授信额度"),
    ("available_limit", "可用额度", "CREDIT_LIMIT.AVAILABLE_AMT", "总额度扣减已占用额度"),
    ("overdue_days", "逾期天数", "LOAN_DTL.OVERDUE_DAYS", "应还日次日至统计日的自然日"),
    ("customer_level", "客户等级", "CUSTOMER.RISK_LEVEL", "客户风险分层结果"),
    ("account_status", "账户状态", "ACCOUNT.STATUS_CD", "账户当前生命周期状态"),
    ("interest_rate", "执行利率", "LOAN_DTL.EXEC_RATE", "当前实际执行的年化利率"),
    ("repay_amount", "还款金额", "REPAY_TXN.PAID_AMT", "指定期间实际到账金额"),
    ("guarantee_type", "担保方式", "GUARANTEE.TYPE_CD", "合同对应的主要增信方式"),
    ("report_date", "数据日期", "REPORT_HEAD.DATA_DATE", "本批数据反映的业务统计日"),
]


def main() -> None:
    documents = OUTPUT / "documents"
    documents.mkdir(parents=True, exist_ok=True)
    questions = []
    for doc_index, (code, name, field, definition) in enumerate(TOPICS, start=1):
        chunks = [
            f"## {name}规则 {chunk_index}\n"
            f"模拟制度 {doc_index}-{chunk_index}：{name}（简称{code.upper()}）定义为{definition}。"
            f"标准字段为 `{field}`。统计时仅使用合成样例，不代表任何真实机构口径。"
            for chunk_index in range(1, 11)
        ]
        (documents / f"{doc_index:02d}-{code}.md").write_text(
            "\n\n".join(chunks),
            encoding="utf-8",
        )
        questions.extend([
            {
                "case_name": f"{name}-同义表达",
                "query_text": f"{name}现在按什么规则计算？",
                "expected_document": f"{doc_index:02d}-{code}.md",
                "expected_keywords": [name, definition.split("的")[0]],
            },
            {
                "case_name": f"{name}-字段缩写",
                "query_text": f"{field} 对应的业务含义是什么？",
                "expected_document": f"{doc_index:02d}-{code}.md",
                "expected_keywords": [name, field],
            },
        ])
    (OUTPUT / "golden-questions.json").write_text(
        json.dumps(questions, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Prepared {len(TOPICS)} documents, {len(TOPICS) * 10} chunks, {len(questions)} questions in {OUTPUT}")


if __name__ == "__main__":
    main()
