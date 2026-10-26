import json, time
from app.core.database import SessionLocal
from app.core.settings import get_settings
from app.services.retrieval.hybrid_retriever import HybridRetriever

db = SessionLocal()
r = HybridRetriever(db)
s = get_settings()
for mode in ("keyword_only", "hybrid"):
    for i in range(3):
        t = time.perf_counter()
        log, items = r.search(9, "E010001（产品ID）的监管口径是什么", top_k=10, retrieval_mode=mode, commit=False)
        dt = (time.perf_counter() - t) * 1000
        db.rollback()
        print(mode, i, round(dt), log.query_type, log.retrieval_strategy, len(items), log.latency_ms)
print("kw_top", s.keyword_top_k, "vec_top", s.vector_top_k, "final", s.hybrid_final_top_k)
db.close()
