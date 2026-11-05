"""DDL 建表语句导入：多文件/多语句、忽略库名、导入时选择层级。"""
import pytest
from sqlalchemy import select

from app.models import CatalogTable, DataSource, Project
from app.models.data_architecture import CatalogClassification
from app.services import data_architecture
from app.services.metadata import batch_import as service
from app.services.metadata.batch_parser import parse_file

from tests.test_resource_batch_import import MemoryStorage, apply_batch, make_batch, sample  # noqa: F401


HIVE_DDL = """CREATE EXTERNAL TABLE `dm_bappdb_tcyl`.`hyf_contract` (
  `branch_no` STRING COMMENT '机构编号',
  `objectno` STRING COMMENT '合同号',
  `amt` DECIMAL(18,2) COMMENT '金额'
)
COMMENT '合同信息'
PARTITIONED BY (`data_dt` STRING)
STORED AS PARQUET;

CREATE TABLE `dm_bappdb_tcyl`.`hyf_customer` (
  `cust_no` STRING COMMENT '客户号'
)
COMMENT '客户信息';
"""


def layers_of(db, project):
    row = data_architecture.get_architecture(db, project_id=project.id)
    return row.definition_json["layers"] if row else []


def test_hive_ddl_txt_is_detected_and_parses_multiple_statements():
    kind, parsed = parse_file(HIVE_DDL.encode("utf-8"), "监管集市ddl.txt", "auto", "")
    assert kind == "ddl", "Hive 方言的 .txt 建表语句应按 DDL 解析"
    assert [table["table_name"] for table in parsed["tables"]] == ["hyf_contract", "hyf_customer"]
    assert parsed["tables"][0]["schema_name"] == "dm_bappdb_tcyl"
    assert parsed["tables"][0]["table_comment"] == "合同信息"
    assert parsed["tables"][0]["columns"][0]["column_comment"] == "机构编号"
    assert parsed["complete"] is True


def test_ddl_with_statement_without_columns_still_imports_the_rest():
    data = (HIVE_DDL + "\nCREATE TABLE `dm_bappdb_tcyl`.`hyf_copy` LIKE `dm_bappdb_tcyl`.`hyf_customer`;\n").encode()
    kind, parsed = parse_file(data, "混合语句.txt", "auto", "")
    assert kind == "ddl"
    assert len(parsed["tables"]) == 2, "没有字段清单的语句不应让整份 DDL 解析失败"
    assert parsed["warnings"], "被跳过的语句需要留下可核验提示"


def test_ignore_database_uses_selected_layer_as_data_source_and_autocreates_layer(sample):
    db, project, _, _ = sample
    batch = make_batch(sample, [("监管集市ddl.txt", HIVE_DDL.encode("utf-8"))],
                       {"ignore_database": True, "defaults": {"layer_name": "监管集市"}})
    layers = layers_of(db, project)
    assert [layer["name"] for layer in layers] == ["监管集市"]
    layer_key = layers[0]["key"]

    tables = batch.preview_json["items"][0]["tables"]
    assert len(tables) == 2
    metadata = tables[0]["metadata"]
    assert metadata["database_name"] == "监管集市", "忽略了 DDL 库名后用层级作为离线数据源"
    assert metadata["schema_name"] == "main"
    assert metadata["source_database_name"] == "dm_bappdb_tcyl"
    assert tables[0]["layer_key"] == layer_key

    result, _ = apply_batch(sample, batch)
    assert result["success_count"] == 1 and not result["failed_count"]
    stored = list(db.scalars(select(CatalogTable).order_by(CatalogTable.table_name)))
    assert [(x.database_name, x.schema_name, x.table_name) for x in stored] == [
        ("监管集市", "main", "hyf_contract"), ("监管集市", "main", "hyf_customer")]
    source = db.get(DataSource, stored[0].datasource_id)
    assert source.db_type == "offline" and source.display_name == "离线文件：监管集市"
    binding = db.scalar(select(CatalogClassification).where(CatalogClassification.catalog_table_id == stored[0].id))
    assert binding.assignment_json["layer_key"] == layer_key


def test_without_ignore_database_the_ddl_namespace_is_preserved(sample):
    db, _, _, _ = sample
    batch = make_batch(sample, [("plain.ddl", b"CREATE TABLE bank.ods.t1 (id BIGINT);")],
                       {"defaults": {"layer_name": "监管集市"}})
    metadata = batch.preview_json["items"][0]["tables"][0]["metadata"]
    assert metadata["database_name"] == "bank" and metadata["schema_name"] == "ods"


def test_multiple_files_and_multiple_layers_do_not_collide(sample):
    db, project, _, _ = sample
    market = "CREATE TABLE `dm`.`same_tbl` (`id` STRING COMMENT '市场');".encode()
    manual = "CREATE TABLE `ODS_YBT`.`same_tbl` (`id` STRING COMMENT '补录');".encode()
    batch = make_batch(sample, [("监管集市ddl.txt", market), ("补录表ddl.txt", manual)], {
        "ignore_database": True,
        "defaults": {"layer_name": "监管集市"},
        "file_options": {"补录表ddl.txt": {"layer_name": "补录系统"}},
    })
    assert [layer["name"] for layer in layers_of(db, project)] == ["监管集市", "补录系统"]
    result, _ = apply_batch(sample, batch)
    assert result["success_count"] == 2 and not result["failed_count"]
    stored = list(db.scalars(select(CatalogTable).order_by(CatalogTable.id)))
    assert [(x.database_name, x.table_name) for x in stored] == [
        ("监管集市", "same_tbl"), ("补录系统", "same_tbl")]
    sources = {db.get(DataSource, table.datasource_id).display_name for table in stored}
    assert sources == {"离线文件：监管集市", "离线文件：补录系统"}


def test_existing_disabled_layer_with_same_name_is_reactivated_not_duplicated(sample):
    db, project, _, _ = sample
    data_architecture.save_architecture(db, {"layers": [
        {"key": "layer_0", "name": "监管集市", "active": False},
        {"key": "layer_1", "name": "业务系统", "active": True},
    ], "relations": []}, 0, project_id=project.id)
    make_batch(sample, [("监管集市ddl.txt", HIVE_DDL.encode("utf-8"))],
               {"ignore_database": True, "defaults": {"layer_name": "监管集市"}})
    layers = layers_of(db, project)
    assert [(x["key"], x["name"], x["active"]) for x in layers] == [
        ("layer_0", "监管集市", True), ("layer_1", "业务系统", True)]


def test_unknown_layer_name_is_rejected_instead_of_silently_dropped(sample):
    from fastapi import HTTPException
    db, project, user, storage = sample
    # 直接构造一个绕过上传期补建的批次（例如旧批次或人工改库）。
    batch = service.create_batch(db, project, user.id, "stale", [("a.ddl", b"CREATE TABLE a.s.t (id BIGINT);")],
                                 {"ignore_database": True, "defaults": {"layer_name": "监管集市"}}, storage)
    batch.options_json = {**batch.options_json, "defaults": {"layer_name": "不存在的层级"}}
    db.flush()
    with pytest.raises(HTTPException) as error:
        service.preview(db, batch)
    assert error.value.status_code == 422


def test_http_upload_accepts_txt_ddl_ignore_database_and_layer_names(monkeypatch):
    """前端实际提交的载荷：多文件 + .txt 建表语句 + ignore_database + 层级名。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    from app.api import batch_imports
    from app.core.database import Base, get_db
    from app.models import Institution, ProjectMembership, User
    from app.services.auth.dependencies import Principal, get_current_principal
    from app.services.task_queue.inline import InlineTaskQueue

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = Session(engine, expire_on_commit=False)
    bank = Institution(institution_code="ddl-http-bank", institution_name="DDL HTTP 银行")
    db.add(bank)
    db.flush()
    project = Project(name="DDL HTTP", institution_id=bank.id)
    user = User(username="ddl-http-user")
    db.add_all([project, user])
    db.flush()
    db.add(ProjectMembership(project_id=project.id, user_id=user.id, project_role="project_manager"))
    db.commit()
    storage = MemoryStorage()
    monkeypatch.setattr(service, "get_storage_service", lambda: storage)
    monkeypatch.setattr(batch_imports, "get_task_queue", lambda: InlineTaskQueue())
    app = FastAPI()
    app.include_router(batch_imports.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_principal] = lambda: Principal(user.id, user.username, None)
    client = TestClient(app)
    root = f"/api/projects/{project.id}/resource-imports"
    import json as jsonlib
    options = {"ignore_database": True, "defaults": {"layer_name": "监管集市"},
               "file_options": {"补录表ddl.txt": {"layer_name": "补录系统"}}}
    try:
        response = client.post(root, data={"idempotency_key": "ddl-http", "options": jsonlib.dumps(options)},
            files=[("files", ("监管集市ddl.txt", HIVE_DDL.encode(), "text/plain")),
                   ("files", ("补录表ddl.txt", "CREATE TABLE `ODS_YBT`.`ods_t` (`id` STRING COMMENT '编号');".encode(), "text/plain"))])
        assert response.status_code == 201, response.text
        batch_id = response.json()["id"]
        detail = client.get(f"{root}/{batch_id}").json()
        assert detail["options"]["ignore_database"] is True
        items = {item["path"]: item for item in detail["preview"]["items"]}
        assert items["监管集市ddl.txt"]["kind"] == "ddl"
        first = items["监管集市ddl.txt"]["tables"][0]["metadata"]
        assert (first["database_name"], first["schema_name"], first["source_database_name"]) == ("监管集市", "main", "dm_bappdb_tcyl")
        assert items["补录表ddl.txt"]["tables"][0]["metadata"]["database_name"] == "补录系统"

        # 预览里改层级：仍可用"层级名"提交，服务端自动补建 业务系统。
        updated_options = {**options, "file_options": {"补录表ddl.txt": {"layer_name": "业务系统"}}}
        updated = client.put(f"{root}/{batch_id}/preview",
                             json={"expected_version": detail["version"], "options": updated_options})
        assert updated.status_code == 200, updated.text
        assert updated.json()["preview"]["items"][1]["tables"][0]["layer_key"] == "layer_2"

        applied = client.post(f"{root}/{batch_id}/apply", json={"expected_version": updated.json()["version"]})
        assert applied.status_code == 200, applied.text
        assert applied.json()["status"] == "completed", applied.text
        stored = list(db.scalars(select(CatalogTable).order_by(CatalogTable.id)))
        assert len(stored) == 3
        assert sorted(x.database_name for x in stored) == ["业务系统", "监管集市", "监管集市"]
    finally:
        db.close()
        engine.dispose()
