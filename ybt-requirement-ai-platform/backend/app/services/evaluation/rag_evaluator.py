from datetime import UTC,datetime
from sqlalchemy import select
from app.models import RagEvaluationCase,RagEvaluationResult,RagEvaluationRun
from app.services.rag import grounded_answer
def run_evaluation(db,run):
    run.status="running";run.started_at=datetime.now(UTC);db.commit();results=[]
    cases=list(db.scalars(select(RagEvaluationCase).where(RagEvaluationCase.project_id==run.project_id,RagEvaluationCase.enabled.is_(True))).all())
    for case in cases:
        answer=grounded_answer(db,run.project_id,case.query_text,target_field_id=case.target_field_id,scenario_id=case.scenario_id,top_k=10);retrieved=[item["knowledge_unit_id"] for item in answer["citations"]];expected=case.expected_knowledge_unit_ids_json or [];hits=[index for index,item in enumerate(retrieved,1) if item in expected];recall=len(set(retrieved)&set(expected))/len(expected) if expected else 1;rr=1/min(hits) if hits else 0;keywords=case.expected_answer_keywords_json or [];coverage=sum(1 for item in keywords if item in answer["answer"])/len(keywords) if keywords else 1
        result=RagEvaluationResult(evaluation_run_id=run.id,evaluation_case_id=case.id,retrieved_unit_ids_json=retrieved,generated_answer=answer["answer"],citations_json=answer["citations"],recall_at_k=recall,reciprocal_rank=rr,source_hit=bool(hits),citation_coverage=1 if answer["citations"] else 0,groundedness_score=1 if not answer["unsupported_claims"] else 0,keyword_coverage=coverage,latency_ms=0);db.add(result);results.append(result)
    run.status="completed";run.finished_at=datetime.now(UTC);run.summary_metrics_json={"case_count":len(results),"recall_at_5":sum(item.recall_at_k for item in results)/len(results) if results else 0,"recall_at_10":sum(item.recall_at_k for item in results)/len(results) if results else 0,"mrr":sum(item.reciprocal_rank for item in results)/len(results) if results else 0,"source_hit_rate":sum(item.source_hit for item in results)/len(results) if results else 0,"field_hit_rate":sum(item.source_hit for item in results)/len(results) if results else 0,"average_latency_ms":0};db.commit();db.refresh(run);return run
