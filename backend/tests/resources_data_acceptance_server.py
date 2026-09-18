"""Loopback full application with in-memory synthetic resources, no environment file."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import settings as settings_module

settings = settings_module.Settings(_env_file=None, database_url="sqlite://", environment="test",
    auth_mode="required", llm_provider="mock", embedding_provider="mock", vector_store_provider="mock",
    cors_origins="*", app_secret_key="synthetic-acceptance-only-not-a-secret", jwt_secret_key="synthetic-acceptance-only-not-a-secret")
settings_module.get_settings = lambda: settings

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool
from app.core.database import Base, get_db
from app.main import app
from app.models import ProjectMembership, User
from app.services.auth.dependencies import Principal, get_current_principal
from app.services.rag import document_preview_service, grounded_answer_service, data_field_answer_service
from app.api import templates as templates_api
from app.services.llm import prompt_runtime
from app.services.llm.base import ModelCallMetadata
from resources_data_fixtures import seed_resources

engine = create_engine("sqlite:///file:resources_acceptance?mode=memory&cache=shared&uri=true",
    connect_args={"check_same_thread":False,"timeout":30}, poolclass=QueuePool)
Base.metadata.create_all(engine)
with Session(engine) as db:
    data=seed_resources(db)
    user=User(username="resource-acceptance",display_name="隔离验收用户")
    db.add(user);db.flush()
    db.add(ProjectMembership(project_id=data.project.id,user_id=user.id,project_role="project_manager",status="active"))
    db.commit()
    principal=Principal(user.id,user.username,user.display_name)
    files=dict(data.files)

document_preview_service.get_storage_service=lambda:SimpleNamespace(read=lambda key:files[key])
templates_api.get_storage_service=lambda:SimpleNamespace(read=lambda key:files[key])

class SyntheticProvider:
    last_call=ModelCallMetadata(provider="mock",model="synthetic-extractive-acceptance")
    async def chat_structured(self, system_prompt, user_prompt, response_schema):
        if response_schema is data_field_answer_service.DataFieldOutput:
            evidence=json.loads(user_prompt)["evidence"]
            return response_schema.model_validate({"claims":[{"citation_id":evidence[0]["citation_id"],"text":evidence[0]["quoted_content"]}]})
        return response_schema.model_validate({"answer":"合成验收依据：客户证件类型用于客户识别，适用范围须结合原文确认。","confidence_level":"low","open_questions":["请核验制度适用范围。"]})

prompt_runtime.get_runtime_llm_service=lambda *args,**kwargs:SyntheticProvider()
# The real retriever still runs, using only persisted keyword indexes; no model network.
original_search=grounded_answer_service.HybridRetriever.search
def keyword_search(self,*args,**kwargs):
    kwargs["retrieval_mode"]="keyword_only"
    return original_search(self,*args,**kwargs)
grounded_answer_service.HybridRetriever.search=keyword_search

def isolated_db():
    with Session(engine) as db:
        yield db
app.dependency_overrides[get_db]=isolated_db
app.dependency_overrides[get_current_principal]=lambda:principal

if __name__=="__main__":
    import uvicorn
    uvicorn.run(app,host="127.0.0.1",port=int(sys.argv[1]),lifespan="off",access_log=False)
