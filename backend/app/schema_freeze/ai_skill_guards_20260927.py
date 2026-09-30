"""Frozen DDL for Skill history guards (202609270044); never change in place."""
from sqlalchemy import inspect

VERSION_FIELDS = ("definition_id", "version_no", "content_json", "content_hash", "release_dependency_hash",
                  "scope_type", "scope_key", "institution_id", "project_id", "invocation_key", "created_by",
                  "edited_by", "approved_by", "published_at", "restored_from_version_id", "test_epoch")
PROMPT_FIELDS = ("prompt_key", "version_no", "system_prompt", "user_prompt_template", "output_schema_json", "skill_version_id")


def install(connection):
    tables = set(inspect(connection).get_table_names())
    for table, prefix, predicate, fields in (
        ("ai_skill_versions", "skill_version_history", "OLD.published_at IS NOT NULL", VERSION_FIELDS),
        ("prompt_template_versions", "skill_prompt_history", "OLD.skill_version_id IS NOT NULL", PROMPT_FIELDS),
    ):
        if table not in tables or (table == "prompt_template_versions" and "skill_version_id" not in {c["name"] for c in inspect(connection).get_columns(table)}):
            continue
        if connection.dialect.name == "sqlite":
            comparison = " OR ".join(f"NEW.{field} IS NOT OLD.{field}" for field in fields)
            connection.exec_driver_sql(f"CREATE TRIGGER IF NOT EXISTS {prefix}_update BEFORE UPDATE ON {table} WHEN {predicate} AND ({comparison}) BEGIN SELECT RAISE(ABORT, 'immutable Skill history'); END")
            connection.exec_driver_sql(f"CREATE TRIGGER IF NOT EXISTS {prefix}_delete BEFORE DELETE ON {table} WHEN {predicate} BEGIN SELECT RAISE(ABORT, 'immutable Skill history'); END")
        elif connection.dialect.name == "postgresql":
            comparison = " OR ".join(f"NEW.{field}::text IS DISTINCT FROM OLD.{field}::text" for field in fields)
            connection.exec_driver_sql(f"""CREATE OR REPLACE FUNCTION {prefix}_guard() RETURNS trigger AS $$
                BEGIN
                    IF {predicate} THEN
                        IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'immutable Skill history'; END IF;
                        IF {comparison} THEN RAISE EXCEPTION 'immutable Skill history'; END IF;
                    END IF;
                    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
                    RETURN NEW;
                END; $$ LANGUAGE plpgsql""")
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {prefix} ON {table}")
            connection.exec_driver_sql(f"CREATE TRIGGER {prefix} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION {prefix}_guard()")


def uninstall(connection):
    for table, prefix in (("ai_skill_versions", "skill_version_history"), ("prompt_template_versions", "skill_prompt_history")):
        if connection.dialect.name == "sqlite":
            for action in ("update", "delete"):
                connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {prefix}_{action}")
        elif connection.dialect.name == "postgresql":
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {prefix} ON {table}")
            connection.exec_driver_sql(f"DROP FUNCTION IF EXISTS {prefix}_guard()")
