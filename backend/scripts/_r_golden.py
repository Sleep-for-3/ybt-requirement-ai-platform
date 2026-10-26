import json
from sqlalchemy import select, func
from app.core.database import SessionLocal
from app.models import KnowledgeUnit
from scripts.retrieval_eval import resolve_golden

db = SessionLocal()
print("p9 units", db.scalar(select(func.count()).select_from(KnowledgeUnit).where(KnowledgeUnit.project_id == 9)))
for predicate in (
    {"values": ["LOAN_BAL", "贷款余额"]},
    {"values": ["LOAN_STATUS", "贷款状态"]},
    {"values": ["E010001", "产品ID"]},
    {"values": ["客户统一标识"]},
):
    ids = resolve_golden(db, predicate)
    titles = list(db.scalars(select(KnowledgeUnit.title).where(KnowledgeUnit.id.in_(ids))).all()) if ids else []
    print(json.dumps({"predicate": predicate, "ids": ids[:10], "count": len(ids), "titles": titles[:6]}, ensure_ascii=False))
import app.services.retrieval.hybrid_retriever as h
print("has preds", hasattr(h, "governed_unit_predicates"))
db.close()
