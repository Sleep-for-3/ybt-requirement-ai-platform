"""Banking and regulatory domain vocabulary, synonyms, and acronyms for semantic query expansion.

Completely local and offline: no external network or API dependencies.
"""
from typing import Dict, Set

# Bidirectional / directional banking synonym clusters
BANKING_SYNONYM_GROUPS = [
    # Loan domain
    {"房贷", "个人住房贷款", "按揭贷款", "个人住房按揭贷款", "住房贷款"},
    {"车贷", "个人汽车贷款", "消费贷款"},
    {"经营贷", "个人经营性贷款", "普惠贷款", "小微贷款", "小微企业贷款"},
    {"公积金贷", "公积金贷款", "个人住房公积金贷款"},
    {"借据", "贷款借据", "借据号", "借据编码", "due_bill"},
    {"合同", "贷款合同", "授信合同", "contract"},
    # Deposit & Account domain
    {"活期", "活期存款", "活期储蓄", "单位活期存款", "个人活期存款"},
    {"定期", "定期存款", "定期储蓄", "单位定期存款"},
    {"结算账户", "银行账户", "基本存款账户", "一般存款账户"},
    # Customer & Entity domain
    {"ecif", "客户系统", "客户信息系统", "统一客户系统"},
    {"对公", "公司客户", "企业客户", "机构客户", "对公业务"},
    {"零售", "个人客户", "零售客户", "零售业务"},
    # Regulatory & Risk domain
    {"一表通", "监管一表通", "ybt", "1104", "east"},
    {"逾期", "逾期贷款", "不良贷款", "违约", "风险资产"},
    {"五级分类", "风险分类", "资产质量分类", "资产分类"},
    # Common Field Concepts
    {"证件类型", "证件种类", "客户证件类型", "cert_type", "certificate_type"},
    {"证件号码", "证件号", "身份证号", "cert_no", "id_no"},
    {"余额", "本金余额", "借据余额", "账户余额", "balance"},
    {"利率", "执行利率", "合同利率", "浮动利率", "interest_rate"},
    {"利息", "应收利息", "计息", "结息", "accrued_interest"},
]

# Build fast lookup map
_SYNONYM_MAP: Dict[str, Set[str]] = {}
for group in BANKING_SYNONYM_GROUPS:
    for term in group:
        lower_term = term.lower()
        if lower_term not in _SYNONYM_MAP:
            _SYNONYM_MAP[lower_term] = set()
        _SYNONYM_MAP[lower_term].update(other.lower() for other in group if other.lower() != lower_term)


def get_banking_synonyms(term: str) -> Set[str]:
    """Retrieve all banking domain synonyms for a given term."""
    return _SYNONYM_MAP.get(term.lower(), set())


def expand_tokens_with_banking_domain(tokens: list[str]) -> dict[str, float]:
    """Expand token list with domain synonyms and assigned weights.
    
    Original tokens get weight 1.0.
    Expanded domain synonyms get weight 0.85.
    """
    weights: dict[str, float] = {}
    for token in tokens:
        weights[token] = 1.0
        # Check synonyms
        synonyms = get_banking_synonyms(token)
        for syn in synonyms:
            if syn not in weights:
                weights[syn] = 0.85
    return weights
