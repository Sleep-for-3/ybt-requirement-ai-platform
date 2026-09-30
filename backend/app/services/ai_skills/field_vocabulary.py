"""Narrow field-name hints; these are recall concepts, not business equivalence."""
from app.services.retrieval.keyword_index import token_matches

VERSION = "field-concepts-1"
# Do not reuse broad banking clusters (for example overdue/nonperforming loans).
# A shared field concept only helps recall; scope, currency, units and rules still
# require human review before selecting a source.
CONCEPTS = {
    "证件类型": ("证件类型", "证件种类", "cert_type", "certificate_type"),
    "证件号码": ("证件号码", "证件号", "cert_no", "certificate_no"),
    "余额": ("余额", "balance"),
    "利率": ("利率", "interest_rate"),
    "借据号": ("借据号", "借据编码", "due_bill_no"),
    "合同号": ("合同号", "合同编号", "contract_no"),
}


def field_concepts(text):
    return {name for name, terms in CONCEPTS.items() if any(token_matches(text or "", term) for term in terms)}
