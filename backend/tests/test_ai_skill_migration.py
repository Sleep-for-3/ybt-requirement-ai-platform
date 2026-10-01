"""Verify historical migration isolation and forward/backward compatibility."""
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.core.settings import get_settings
from app.models import AISkillDefinition, AISkillVersion, AISkillScopeBinding, AISkillReleaseEvent, AISkillTestCase, AISkillTestRun, AISkillTestResult


def test_skill_migration_roundtrip_preserves_legacy_rows(tmp_path, monkeypatch):
    url = "sqlite:///" + (tmp_path / "skill-migration.db").as_posix()
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    cfg = Config("alembic.ini")
    engine = create_engine(url)
    try:
        command.upgrade(cfg, "202609200041")
        assert "ai_skill_versions" not in inspect(engine).get_table_names()
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO prompt_template_versions (prompt_key,version_no,system_prompt,user_prompt_template,output_schema_json,enabled) VALUES ('legacy_demo',1,'old system','old user','{}',true)"))
        command.upgrade(cfg, "head")
        for model in (AISkillDefinition, AISkillVersion, AISkillScopeBinding, AISkillReleaseEvent, AISkillTestCase, AISkillTestRun, AISkillTestResult):
            actual = {c["name"] for c in inspect(engine).get_columns(model.__tablename__)}
            assert actual == set(model.__table__.columns.keys())
        for target in ("202609200041", "head"):
            (command.downgrade if target != "head" else command.upgrade)(cfg, target)
            with engine.connect() as conn:
                assert conn.execute(text("SELECT system_prompt FROM prompt_template_versions WHERE prompt_key='legacy_demo'")).scalar_one() == "old system"
        with engine.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "202609270044"
            assert conn.execute(text("SELECT skill_version_id FROM prompt_template_versions WHERE prompt_key='legacy_demo'")).scalar_one() is None
    finally:
        engine.dispose()
        get_settings.cache_clear()
