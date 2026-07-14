import sqlite3
from io import BytesIO
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from openpyxl import Workbook
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from app.core.database import Base, get_db
from app.main import app
from app.models import CatalogColumn, DataSource, Project
from app.services.metadata.base import ColumnMetadata, SchemaMetadata, TableMetadata
from app.services.metadata.sync_service import synchronize_metadata
import app.services.metadata.sync_service as sync_service
from app.services.metadata.mysql_compatible_adapter import MySQLCompatibleMetadataAdapter
from app.services.metadata.postgresql_adapter import PostgreSQLMetadataAdapter
import app.services.metadata.generic_adapter as generic_adapter

def test_sqlite_metadata_sync_search_pagination_and_import(tmp_path: Path) -> None:
    source_db=tmp_path/"ecif_catalog.db"
    with sqlite3.connect(source_db) as connection:
        connection.execute("create table ecif_customer (customer_id integer primary key, cert_type text, customer_name text)")
        connection.executemany("insert into ecif_customer values (?,?,?)",[(1,"01","张三"),(2,"01","李四"),(3,"02","王五"),(4,None,"赵六")])
    with _client() as client:
        project=_post(client,"/api/projects",{"name":"元数据目录项目"})
        datasource=_post(client,f"/api/projects/{project['id']}/datasources",{"name":"ecif_catalog","db_type":"sqlite","database_name":str(source_db),"readonly_flag":True})
        task=_post(client,f"/api/datasources/{datasource['id']}/metadata-sync",{"sync_mode":"full","schema_names":[],"include_views":True})
        assert task["status"]=="completed"; assert task["table_count"]==1; assert task["column_count"]==3
        tables=_get(client,f"/api/projects/{project['id']}/catalog/tables?page=1&page_size=1")
        assert tables["total"]==1; table=tables["items"][0]; assert table["table_name"]=="ecif_customer"; assert table["primary_key_columns_json"]==["customer_id"]
        columns=_get(client,f"/api/catalog/tables/{table['id']}/columns?page=1&page_size=2")
        assert columns["total"]==3; assert len(columns["items"])==2
        same=_post(client,f"/api/datasources/{datasource['id']}/metadata-sync",{"sync_mode":"incremental"});assert same["status"]=="completed";assert _get(client,f"/api/catalog/tables/{table['id']}")["metadata_hash"]==table["metadata_hash"]
        with sqlite3.connect(source_db) as connection:connection.execute("alter table ecif_customer drop column customer_name")
        _post(client,f"/api/datasources/{datasource['id']}/metadata-sync",{"sync_mode":"full"});all_columns=_get(client,f"/api/catalog/tables/{table['id']}/columns?include_disabled=true");assert next(item for item in all_columns["items"] if item["column_name"]=="customer_name")["enabled"] is False
        search=_post(client,f"/api/projects/{project['id']}/catalog/search",{"query":"cert_type","top_k":10})
        candidate=search["items"][0]; assert candidate["column_name"]=="cert_type"; assert candidate["match_reasons"]
        nl=_post(client,"/api/nl-tasks",{"project_id":project["id"],"text":"使用 ecif_catalog 帮我查找与 cert_type 相关的候选字段"});assert nl["intent"]=="catalog_search";nl_result=_post(client,f"/api/nl-tasks/{nl['task_id']}/run",{});assert nl_result["generated_sql_json"]==[];assert nl_result["result_summary_json"]["items"]
        imported=_post(client,f"/api/catalog/columns/{candidate['catalog_column_id']}/import-as-source-field",{"system_code":"ECIF","system_name":"客户信息系统"})
        repeated=_post(client,f"/api/catalog/columns/{candidate['catalog_column_id']}/import-as-source-field",{"system_code":"ECIF","system_name":"客户信息系统"})
        assert imported["source_field_id"]==repeated["source_field_id"]
        mart=_post(client,f"/api/catalog/columns/{candidate['catalog_column_id']}/import-as-mart-field",{})
        assert mart["mart_field_id"]
        target_table=_post(client,"/api/target-tables",{"project_id":project["id"],"table_code":"YBT_CUSTOMER","table_name":"客户信息"})
        target=_post(client,"/api/fields",{"project_id":project["id"],"target_table_id":target_table["id"],"field_code":"CERT_TYPE","field_name":"客户证件类型","field_definition":"客户证件类型代码"})
        scenario=_post(client,f"/api/projects/{project['id']}/scenarios",{"scenario_code":"DEBIT_CARD","scenario_name":"借记卡"})
        recommendations=_post(client,f"/api/target-fields/{target['id']}/scenarios/{scenario['id']}/recommend-sources",{})["recommendations"]
        catalog_rec=next(item for item in recommendations if item["catalog_column_id"]==candidate["catalog_column_id"])
        assert catalog_rec["data_type"].lower()=="text"; assert catalog_rec["profile_status"]=="not_profiled"
        assert _get(client,f"/api/catalog/columns/{candidate['catalog_column_id']}/profiles")==[]
        selected=_post(client,f"/api/source-recommendations/{catalog_rec['id']}/select",{})
        assert selected["lineage"]["source_field_english_name"] is None
        profile=_post(client,f"/api/catalog/columns/{candidate['catalog_column_id']}/profile",{"target_field_id":target["id"],"scenario_id":scenario["id"],"source_recommendation_id":catalog_rec["id"],"metrics":["null_rate","distinct_count","top_values","min_max","length_distribution"]})
        assert profile["status"]=="completed"; assert profile["profile_result_json"]["null_rate"]==0.25; assert profile["profile_result_json"]["distinct_count"]==2; assert profile["profile_result_json"]["top_values"]
        snapshots=_get(client,f"/api/catalog/columns/{candidate['catalog_column_id']}/profiles"); assert snapshots[0]["total_count"]==4
        evidence=_get(client,f"/api/mappings/scenario_technical/{selected['lineage']['id']}/evidence"); assert any(item["evidence_type"]=="column_profile" for item in evidence)
        draft=_post(client,f"/api/scenario-technical-lineages/{selected['lineage']['id']}/generate-draft",{});assert "安全探查摘要" in draft["ai_generated_content"];assert "distinct=2" in draft["ai_generated_content"]
        adopted=_post(client,f"/api/source-recommendations/{catalog_rec['id']}/adopt",{});assert adopted["lineage"]["source_field_english_name"]=="cert_type"
        next_scenario=_post(client,f"/api/projects/{project['id']}/scenarios",{"scenario_code":"CREDIT_CARD","scenario_name":"信用卡"})
        next_recommendations=_post(client,f"/api/target-fields/{target['id']}/scenarios/{next_scenario['id']}/recommend-sources",{})["recommendations"]
        next_catalog=next(item for item in next_recommendations if item["catalog_column_id"]==candidate["catalog_column_id"])
        assert "历史技术溯源匹配" in next_catalog["recommend_reason"]
        assert "已导入来源字段" in next_catalog["recommend_reason"]

def test_profile_requires_selection_and_protects_sensitive_values(tmp_path:Path)->None:
    source_db=tmp_path/"sensitive.db"
    with sqlite3.connect(source_db) as connection:
        connection.execute("create table customer (customer_name text, label text)");connection.executemany("insert into customer values (?,?)",[("张三","13800138000"),("李四","13900139000")])
    with _client() as client:
        project=_post(client,"/api/projects",{"name":"敏感探查"});ds=_post(client,f"/api/projects/{project['id']}/datasources",{"name":"sensitive_db","db_type":"sqlite","database_name":str(source_db)})
        _post(client,f"/api/datasources/{ds['id']}/metadata-sync",{"sync_mode":"full"});catalog=_post(client,f"/api/projects/{project['id']}/catalog/search",{"query":"customer_name"})["items"][0]
        table=_post(client,"/api/target-tables",{"project_id":project["id"],"table_code":"CUSTOMER","table_name":"客户"});field=_post(client,"/api/fields",{"project_id":project["id"],"target_table_id":table["id"],"field_code":"CUSTOMER_NAME","field_name":"客户姓名"});scenario=_post(client,f"/api/projects/{project['id']}/scenarios",{"scenario_code":"CUSTOMER","scenario_name":"客户"})
        rec=next(item for item in _post(client,f"/api/target-fields/{field['id']}/scenarios/{scenario['id']}/recommend-sources",{})["recommendations"] if item["catalog_column_id"]==catalog["catalog_column_id"])
        rejected=client.post(f"/api/catalog/columns/{catalog['catalog_column_id']}/profile",json={"target_field_id":field["id"],"scenario_id":scenario["id"],"source_recommendation_id":rec["id"],"metrics":["top_values","min_max","distinct_count"]});assert rejected.status_code==400
        _post(client,f"/api/source-recommendations/{rec['id']}/select",{});profile=_post(client,f"/api/catalog/columns/{catalog['catalog_column_id']}/profile",{"target_field_id":field["id"],"scenario_id":scenario["id"],"source_recommendation_id":rec["id"],"metrics":["top_values","min_max","distinct_count"]})
        assert "top_values" not in profile["profile_result_json"];assert profile["profile_result_json"]["sensitivity_level"]=="sensitive"

        disguised=_post(client,f"/api/projects/{project['id']}/catalog/search",{"query":"label"})["items"][0]
        disguised_field=_post(client,"/api/fields",{"project_id":project["id"],"target_table_id":table["id"],"field_code":"LABEL","field_name":"状态标签"})
        disguised_rec=next(item for item in _post(client,f"/api/target-fields/{disguised_field['id']}/scenarios/{scenario['id']}/recommend-sources",{})["recommendations"] if item["catalog_column_id"]==disguised["catalog_column_id"])
        _post(client,f"/api/source-recommendations/{disguised_rec['id']}/select",{})
        disguised_profile=_post(client,f"/api/catalog/columns/{disguised['catalog_column_id']}/profile",{"target_field_id":disguised_field["id"],"scenario_id":scenario["id"],"source_recommendation_id":disguised_rec["id"],"metrics":["top_values","min_max","distinct_count"]})
        result=disguised_profile["profile_result_json"]
        assert result["sensitivity_level"]=="normal"
        assert "top_values" not in result
        assert "min_value" not in result and "max_value" not in result
        assert "13800138000" not in str(disguised_profile)
        snapshots=_get(client,f"/api/catalog/columns/{disguised['catalog_column_id']}/profiles")
        assert snapshots[0]["top_values_json"]==[]
        assert snapshots[0]["min_value_text"] is None and snapshots[0]["max_value_text"] is None

def test_metadata_excel_preview_and_repeated_apply_are_idempotent()->None:
    workbook=Workbook();sheet=workbook.active;sheet.title="数据字典";sheet.append(["schema","表英文名","表中文名","字段英文名","字段中文名","字段类型","是否可空","主键","字段顺序","系统名称","数据源名称"]);sheet.append(["ODS","ECIF_CUSTOMER","客户基本信息表","CERT_TYPE","客户证件类型","VARCHAR(20)","是","否",2,"ECIF","excel_catalog"]);sheet.append(["DWD","ECIF_CUSTOMER","客户主题表","CERT_TYPE","客户证件类型","VARCHAR(20)","是","否",2,"ECIF","excel_catalog"]);stream=BytesIO();workbook.save(stream)
    with _client() as client:
        project=_post(client,"/api/projects",{"name":"Excel 元数据"});ds=_post(client,f"/api/projects/{project['id']}/datasources",{"name":"excel_catalog","db_type":"sqlite","database_name":":memory:"})
        response=client.post(f"/api/datasources/{ds['id']}/metadata-import/upload",files={"file":("脱敏数据字典.xlsx",stream.getvalue(),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")});assert response.status_code==200,response.text;document=response.json();assert document["parse_summary_json"]["row_count"]==2;assert document["parsed_rows_json"][0]["source_cells"]["column_name"].endswith("D2");assert document["parsed_rows_json"][0]["system_name"]=="ECIF";assert document["parsed_rows_json"][0]["datasource_name"]=="excel_catalog"
        first=_post(client,f"/api/metadata-imports/{document['id']}/apply",{});second=_post(client,f"/api/metadata-imports/{document['id']}/apply",{});assert first["columns"]==2;assert second["columns"]==0
        tables=_get(client,f"/api/projects/{project['id']}/catalog/tables");assert tables["total"]==2
        nl=_post(client,"/api/nl-tasks",{"project_id":project["id"],"text":"使用 excel_catalog 帮我查找与客户证件类型相关的候选字段"});nl_result=_post(client,f"/api/nl-tasks/{nl['task_id']}/run",{});assert nl_result["generated_sql_json"]==[];assert nl_result["result_summary_json"]["items"]
        candidates=_post(client,f"/api/projects/{project['id']}/catalog/search",{"query":"CERT_TYPE"})["items"]
        source_imports=[_post(client,f"/api/catalog/columns/{item['catalog_column_id']}/import-as-source-field",{"system_code":"ECIF","system_name":"客户信息系统"}) for item in candidates]
        mart_imports=[_post(client,f"/api/catalog/columns/{item['catalog_column_id']}/import-as-mart-field",{}) for item in candidates]
        assert len({item["source_table_id"] for item in source_imports})==2
        assert len({item["mart_table_id"] for item in mart_imports})==2

def test_postgresql_and_mysql_adapters_exclude_system_schemas(monkeypatch)->None:
    class Inspector:
        def get_schema_names(self):return ["public","information_schema","pg_catalog","mysql","sys"]
        def get_table_names(self,schema=None):return ["customer"]
        def get_view_names(self,schema=None):return []
        def get_table_comment(self,name,schema=None):return {"text":"客户表"}
        def get_pk_constraint(self,name,schema=None):return {"constrained_columns":["id"]}
        def get_columns(self,name,schema=None):return [{"name":"id","type":"INTEGER","nullable":False,"comment":"主键"}]
    monkeypatch.setattr(generic_adapter,"inspect",lambda engine:Inspector())
    pg=PostgreSQLMetadataAdapter(DataSource(id=1,project_id=1,name="pg_db",db_type="postgresql"));pg._engine=lambda:object()
    mysql=MySQLCompatibleMetadataAdapter(DataSource(id=2,project_id=1,name="mysql_db",db_type="mysql"));mysql._engine=lambda:object()
    assert [item.schema_name for item in pg.list_schemas()]==["public","mysql","sys"]
    assert [item.schema_name for item in mysql.list_schemas()]==["public","pg_catalog"]
    assert pg.list_tables(["public"])[0].primary_key_columns==["id"]
    assert mysql.list_columns("public","customer")[0].column_comment=="主键"

def test_full_sync_preserves_a_failed_tables_existing_columns(db_session,monkeypatch)->None:
    project=Project(name="失败隔离同步");db_session.add(project);db_session.flush();datasource=DataSource(project_id=project.id,name="sync_isolation",db_type="sqlite",database_name=":memory:");db_session.add(datasource);db_session.commit()
    class Adapter:
        fail=False
        def list_schemas(self):return [SchemaMetadata("main")]
        def list_tables(self,schema_names=None,include_views=True):return [TableMetadata("main","healthy"),TableMetadata("main","fragile")]
        def list_columns(self,schema_name,table_name):
            if table_name=="fragile" and self.fail:raise RuntimeError("catalog permission denied")
            names=["kept"] if table_name=="fragile" else (["current"] if self.fail else ["current","removed"])
            return [ColumnMetadata("main",table_name,name,data_type="TEXT",ordinal_position=index) for index,name in enumerate(names,start=1)]
    adapter=Adapter();monkeypatch.setattr(sync_service,"create_metadata_adapter",lambda datasource:adapter)
    assert synchronize_metadata(db_session,datasource).status=="completed"
    adapter.fail=True;task=synchronize_metadata(db_session,datasource)
    assert task.status=="partially_completed";assert "fragile" in str(task.warnings_json)
    columns={f"{item.table_name}.{item.column_name}":item.enabled for item in db_session.query(CatalogColumn).all()}
    assert columns["healthy.current"] is True
    assert columns["healthy.removed"] is False
    assert columns["fragile.kept"] is True

@contextmanager
def _client()->Iterator[TestClient]:
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool);Base.metadata.create_all(engine);factory=sessionmaker(bind=engine,autoflush=False)
    def override()->Iterator[Session]:
        session=factory()
        try:yield session
        finally:session.close()
    app.dependency_overrides[get_db]=override
    try:
        with TestClient(app) as client:yield client
    finally:app.dependency_overrides.clear();Base.metadata.drop_all(engine)

def _post(client,path,payload):
    response=client.post(path,json=payload);assert response.status_code==200,response.text;return response.json()
def _get(client,path):
    response=client.get(path);assert response.status_code==200,response.text;return response.json()
