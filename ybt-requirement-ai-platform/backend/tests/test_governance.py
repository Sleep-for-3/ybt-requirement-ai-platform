from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.core.database import Base, get_db
from app.core.settings import get_settings
from app.services.auth.password import hash_password, verify_password
from app.services.auth.dependencies import Principal
from app.services.auth.permission_service import PermissionService
from app.services.governance.audit import redact_summary
from app.services.task_queue.celery import CeleryTaskQueue
from app.services.task_queue.inline import InlineTaskQueue


def test_password_is_stored_as_a_secure_hash() -> None:
    password = "test-only-" + "governance-password"

    password_hash = hash_password(password)

    assert password not in password_hash
    assert verify_password(password, password_hash)
    assert not verify_password(password + "-wrong", password_hash)


def test_admin_can_bootstrap_login_refresh_and_revoke_session(monkeypatch) -> None:
    with _governance_client(monkeypatch) as client:
        password = "test-only-" + "bootstrap-password"
        bootstrap = client.post(
            "/api/admin/bootstrap",
            json={
                "institution_code": "BANK_A",
                "institution_name": "脱敏示例银行",
                "username": "admin_a",
                "display_name": "测试管理员",
                "email": "admin@example.invalid",
                "password": password,
            },
        )
        assert bootstrap.status_code == 201, bootstrap.text
        assert "password" not in bootstrap.text.lower()

        login = client.post("/api/auth/login", json={"username": "admin_a", "password": password})
        assert login.status_code == 200, login.text
        session = login.json()
        assert session["access_token"] != session["refresh_token"]

        me = client.get("/api/auth/me", headers=_bearer(session["access_token"]))
        assert me.status_code == 200, me.text
        assert me.json()["username"] == "admin_a"

        refreshed = client.post("/api/auth/refresh", json={"refresh_token": session["refresh_token"]})
        assert refreshed.status_code == 200, refreshed.text
        replacement = refreshed.json()
        assert replacement["refresh_token"] != session["refresh_token"]

        logout = client.post("/api/auth/logout", json={"refresh_token": replacement["refresh_token"]})
        assert logout.status_code == 200, logout.text
        rejected = client.post("/api/auth/refresh", json={"refresh_token": replacement["refresh_token"]})
        assert rejected.status_code == 401


def test_project_member_cannot_read_another_institutions_project(monkeypatch) -> None:
    with _governance_client(monkeypatch) as client:
        admin_password = "test-only-" + "platform-admin-password"
        client.post("/api/admin/bootstrap", json={
            "institution_code": "PLATFORM",
            "institution_name": "脱敏平台运营方",
            "institution_type": "platform_operator",
            "username": "platform_admin",
            "display_name": "平台管理员",
            "email": "platform@example.invalid",
            "password": admin_password,
        })
        admin_token = client.post("/api/auth/login", json={"username": "platform_admin", "password": admin_password}).json()["access_token"]
        admin_headers = _bearer(admin_token)
        bank_a = client.post("/api/admin/institutions", headers=admin_headers, json={"institution_code": "BANK_A", "institution_name": "示例甲银行", "institution_type": "bank"}).json()
        bank_b = client.post("/api/admin/institutions", headers=admin_headers, json={"institution_code": "BANK_B", "institution_name": "示例乙银行", "institution_type": "bank"}).json()
        analyst_password = "test-only-" + "analyst-password"
        analyst = client.post("/api/admin/users", headers=admin_headers, json={
            "username": "analyst_a", "display_name": "甲行业务人员", "email": "analyst-a@example.invalid",
            "password": analyst_password, "institution_id": bank_a["id"], "institution_role": "member",
        }).json()
        project_a = client.post("/api/projects", headers=admin_headers, json={"name": "甲行项目", "institution_id": bank_a["id"]}).json()
        project_a_other = client.post("/api/projects", headers=admin_headers, json={"name": "甲行未授权项目", "institution_id": bank_a["id"]}).json()
        project_b = client.post("/api/projects", headers=admin_headers, json={"name": "乙行项目", "institution_id": bank_b["id"]}).json()
        foreign_system = client.post(f"/api/projects/{project_b['id']}/business-systems", headers=admin_headers, json={
            "system_code": "BANK_B_CORE", "system_name": "乙行核心系统",
        }).json()
        target_table = client.post("/api/target-tables", headers=admin_headers, json={
            "project_id": project_b["id"], "table_code": "RPT_SECRET", "table_name": "乙行监管表",
        }).json()
        client.post("/api/fields", headers=admin_headers, json={
            "project_id": project_b["id"], "target_table_id": target_table["id"],
            "field_code": "SECRET_FIELD", "field_name": "乙行字段",
        })
        member = client.post(f"/api/projects/{project_a['id']}/members", headers=admin_headers, json={"user_id": analyst["id"], "project_role": "business_analyst"})
        assert member.status_code == 201, member.text

        analyst_token = client.post("/api/auth/login", json={"username": "analyst_a", "password": analyst_password}).json()["access_token"]
        analyst_headers = _bearer(analyst_token)
        assert client.get(f"/api/projects/{project_a['id']}", headers=analyst_headers).status_code == 200
        assert client.get(f"/api/projects/{project_a_other['id']}", headers=analyst_headers).status_code == 404
        assert client.get(f"/api/projects/{project_b['id']}", headers=analyst_headers).status_code == 404
        assert client.get(f"/api/fields?project_id={project_b['id']}", headers=analyst_headers).status_code == 404
        assert client.get(f"/api/target-tables?project_id={project_b['id']}", headers=analyst_headers).status_code == 404
        assert client.get(f"/api/business-systems/{foreign_system['id']}?project_id={project_a['id']}", headers=analyst_headers).status_code == 404


def test_scenario_review_runs_through_five_separated_roles(monkeypatch) -> None:
    with _governance_client(monkeypatch) as client:
        admin_headers = _bootstrap_platform(client)
        bank = client.post("/api/admin/institutions", headers=admin_headers, json={"institution_code": "BANK_WF", "institution_name": "工作流示例银行", "institution_type": "bank"}).json()
        project = client.post("/api/projects", headers=admin_headers, json={"name": "工作流项目", "institution_id": bank["id"]}).json()
        roles = ["business_analyst", "business_reviewer", "technical_analyst", "technical_reviewer", "final_reviewer"]
        users = {}
        for role in roles:
            password = "test-only-" + role + "-password"
            user = client.post("/api/admin/users", headers=admin_headers, json={
                "username": role, "display_name": role, "email": f"{role}@example.invalid", "password": password,
                "institution_id": bank["id"], "institution_role": "member",
            }).json()
            client.post(f"/api/projects/{project['id']}/members", headers=admin_headers, json={"user_id": user["id"], "project_role": role})
            users[role] = {"id": user["id"], "password": password}

        target_table = client.post("/api/target-tables", headers=admin_headers, json={
            "project_id": project["id"], "table_code": "RPT_CUSTOMER", "table_name": "客户监管表",
        }).json()
        field = client.post("/api/fields", headers=admin_headers, json={
            "project_id": project["id"], "target_table_id": target_table["id"],
            "field_code": "CERT_TYPE", "field_name": "客户证件类型",
        }).json()
        mart_table = client.post(f"/api/projects/{project['id']}/mart-tables", headers=admin_headers, json={
            "table_code": "MART_CUSTOMER", "table_name": "监管客户集市",
        }).json()
        mart_field = client.post(f"/api/mart-tables/{mart_table['id']}/mart-fields", headers=admin_headers, json={
            "field_code": "CERT_TYPE", "field_name": "客户证件类型",
        }).json()
        source_to_mart = client.post(f"/api/mart-fields/{mart_field['id']}/source-to-mart-mappings", headers=admin_headers, json={
            "final_content": "ECIF 证件类型进入监管集市",
        }).json()
        mart_to_ybt = client.post(f"/api/target-fields/{field['id']}/mart-to-ybt-mappings", headers=admin_headers, json={
            "mart_field_id": mart_field["id"], "final_content": "监管集市证件类型进入一表通",
        }).json()
        client.post(f"/api/mappings/source_to_mart/{source_to_mart['id']}/evidence", headers=admin_headers, json={
            "evidence_type": "manual_note", "source_name": "脱敏双层口径证据", "evidence_summary": "来源字段已核验",
        })
        assert client.post(f"/api/source-to-mart-mappings/{source_to_mart['id']}/approve", headers=admin_headers, json={}).status_code == 409
        assert client.post(f"/api/mart-to-ybt-mappings/{mart_to_ybt['id']}/reject", headers=admin_headers, json={}).status_code == 409
        assert client.put(f"/api/source-to-mart-mappings/{source_to_mart['id']}", headers=admin_headers, json={"mapping_status": "approved"}).status_code == 409
        scenario = client.post(f"/api/projects/{project['id']}/scenarios", headers=admin_headers, json={
            "scenario_code": "DEBIT_CARD", "scenario_name": "借记卡",
        }).json()
        business = client.post(
            f"/api/target-fields/{field['id']}/scenarios/{scenario['id']}/business-mapping",
            headers=admin_headers,
            json={"business_definition": "借记卡客户证件类型", "final_content": "按客户主证件类型填报", "open_questions": "境外证件待确认"},
        ).json()
        technical = client.post(
            f"/api/target-fields/{field['id']}/scenarios/{scenario['id']}/technical-lineage",
            headers=admin_headers,
            json={
                "business_mapping_id": business["id"], "source_system_name": "ECIF",
                "source_schema_name": "ODS", "source_table_english_name": "ECIF_CUSTOMER",
                "source_field_english_name": "CERT_TYPE", "processing_logic_type": "direct",
                "processing_logic": "直接取值", "final_content": "ODS.ECIF_CUSTOMER.CERT_TYPE 直接取值",
                "open_questions": "历史客户空值待确认",
            },
        ).json()
        client.post(f"/api/mappings/scenario_business/{business['id']}/evidence", headers=admin_headers, json={
            "evidence_type": "manual_note", "source_name": "脱敏业务访谈", "evidence_summary": "业务证据摘要",
        })
        client.post(f"/api/mappings/scenario_technical/{technical['id']}/evidence", headers=admin_headers, json={
            "evidence_type": "profile_snapshot", "evidence_id": 101, "source_name": "字段探查",
            "evidence_summary": "总量100，空值率1%，distinct 4",
        })

        business_login = client.post("/api/auth/login", json={"username": "business_analyst", "password": users["business_analyst"]["password"]}).json()
        technical_login = client.post("/api/auth/login", json={"username": "technical_analyst", "password": users["technical_analyst"]["password"]}).json()
        assert client.put(
            f"/api/scenario-business-mappings/{business['id']}", headers=_bearer(business_login["access_token"]),
            json={"business_confirm_status": "confirmed"},
        ).status_code == 422
        assert client.put(
            f"/api/scenario-technical-lineages/{technical['id']}", headers=_bearer(technical_login["access_token"]),
            json={"tech_confirm_status": "confirmed"},
        ).status_code == 422

        submitted = client.post(
            f"/api/target-fields/{field['id']}/scenarios/{scenario['id']}/review-package/submit",
            headers=_bearer(business_login["access_token"]),
            json={"assignments": {role: users[role]["id"] for role in roles}},
        )
        assert submitted.status_code == 201, submitted.text
        submitted_package = submitted.json()["scenario_review_package"]
        withdrawn = client.post(
            f"/api/scenario-review-packages/{submitted_package['id']}/withdraw",
            headers=_bearer(business_login["access_token"]), json={},
        )
        assert withdrawn.status_code == 200, withdrawn.text
        assert withdrawn.json()["status"] == "withdrawn"

        created = client.post(f"/api/projects/{project['id']}/tasks/batch-create", headers=admin_headers, json={
            "workflow_key": "scenario_mapping_review",
            "targets": [{"target_field_id": field["id"], "scenario_id": scenario["id"]}],
            "assignments": {role: users[role]["id"] for role in roles},
        })
        assert created.status_code == 201, created.text
        assert created.json()["scenario_review_package_ids"]
        instance_id = created.json()["workflow_instance_ids"][0]
        task_rows = client.get(f"/api/projects/{project['id']}/tasks", headers=admin_headers).json()
        by_step = {row["step_key"]: row for row in task_rows if row["workflow_instance_id"] == instance_id}

        step_roles = [
            ("business_draft", "business_analyst"),
            ("business_review", "business_reviewer"),
            ("technical_draft", "technical_analyst"),
            ("technical_review", "technical_reviewer"),
            ("final_review", "final_reviewer"),
        ]
        draft_login = client.post("/api/auth/login", json={"username": "business_analyst", "password": users["business_analyst"]["password"]}).json()
        assert client.post(f"/api/review-tasks/{by_step['business_draft']['id']}/approve", headers=_bearer(draft_login["access_token"]), json={"comment": "first draft"}).status_code == 200
        reviewer_login = client.post("/api/auth/login", json={"username": "business_reviewer", "password": users["business_reviewer"]["password"]}).json()
        assert client.post(
            f"/api/scenario-business-mappings/{business['id']}/confirm",
            headers=_bearer(reviewer_login["access_token"]), json={},
        ).status_code == 409
        rejected = client.post(
            f"/api/review-tasks/{by_step['business_review']['id']}/reject",
            headers=_bearer(reviewer_login["access_token"]),
            json={"comment": "补充业务边界", "return_to_step": "business_draft"},
        )
        assert rejected.status_code == 200, rejected.text
        returned_tasks = client.get(f"/api/projects/{project['id']}/tasks", headers=admin_headers).json()
        returned_by_step = {row["step_key"]: row for row in returned_tasks if row["workflow_instance_id"] == instance_id}
        assert returned_by_step["business_draft"]["status"] == "returned"
        assert returned_by_step["business_review"]["status"] == "pending"

        for step, role in step_roles[:-1]:
            login = client.post("/api/auth/login", json={"username": role, "password": users[role]["password"]}).json()
            if step == "technical_draft":
                editable = client.put(f"/api/scenario-technical-lineages/{technical['id']}", headers=_bearer(login["access_token"]), json={"remarks": "技术起草阶段可编辑"})
                assert editable.status_code == 200, editable.text
            response = client.post(f"/api/review-tasks/{by_step[step]['id']}/approve", headers=_bearer(login["access_token"]), json={"comment": f"{step} completed"})
            assert response.status_code == 200, response.text
            if step == "business_review":
                assert client.put(f"/api/scenario-business-mappings/{business['id']}", headers=admin_headers, json={"final_content": "未经重新业务审核的替换内容"}).status_code == 409
            if step == "technical_review":
                assert client.put(f"/api/scenario-technical-lineages/{technical['id']}", headers=admin_headers, json={"final_content": "未经最终审核的替换内容"}).status_code == 409

        assert client.get(f"/api/scenario-business-mappings/{business['id']}", headers=admin_headers).json()["business_confirm_status"] != "confirmed"
        assert client.get(f"/api/scenario-technical-lineages/{technical['id']}", headers=admin_headers).json()["tech_confirm_status"] != "confirmed"
        technical_reviewer_login = client.post("/api/auth/login", json={"username": "technical_reviewer", "password": users["technical_reviewer"]["password"]}).json()
        assert client.post(
            f"/api/scenario-technical-lineages/{technical['id']}/confirm",
            headers=_bearer(technical_reviewer_login["access_token"]), json={},
        ).status_code == 409
        assert client.post(
            f"/api/review-tasks/{by_step['final_review']['id']}/approve",
            headers=_bearer(technical_reviewer_login["access_token"]), json={"comment": "attempted skip"},
        ).status_code == 403

        final_login = client.post("/api/auth/login", json={"username": "final_reviewer", "password": users["final_reviewer"]["password"]}).json()
        response = client.post(f"/api/review-tasks/{by_step['final_review']['id']}/approve", headers=_bearer(final_login["access_token"]), json={"comment": "final_review completed"})
        assert response.status_code == 200, response.text

        instance = client.get(f"/api/workflows/{instance_id}", headers=admin_headers)
        assert instance.status_code == 200, instance.text
        assert instance.json()["status"] == "approved"
        decisions = instance.json()["decisions"]
        assert len(decisions) == 7
        assert all(item["content_snapshot_json"] for item in decisions)
        snapshots = {item["step_key"]: item["content_snapshot_json"] for item in decisions if item["decision"] == "approved"}
        assert snapshots["business_draft"]["business_mapping"]["final_content"] == "按客户主证件类型填报"
        assert snapshots["business_review"]["evidence_summary"][0]["evidence_summary"] == "业务证据摘要"
        assert snapshots["technical_draft"]["technical_lineage"]["source_system_name"] == "ECIF"
        assert snapshots["technical_review"]["technical_lineage"]["source_table_english_name"] == "ECIF_CUSTOMER"
        assert snapshots["technical_review"]["technical_lineage"]["source_field_english_name"] == "CERT_TYPE"
        assert snapshots["technical_review"]["profile_evidence_summary"][0]["evidence_summary"].startswith("总量100")
        assert snapshots["final_review"]["business_mapping_id"] == business["id"]
        assert snapshots["final_review"]["technical_lineage_id"] == technical["id"]
        assert snapshots["final_review"]["prior_decisions"]
        assert client.get(f"/api/scenario-business-mappings/{business['id']}", headers=admin_headers).json()["business_confirm_status"] == "confirmed"
        assert client.get(f"/api/scenario-technical-lineages/{technical['id']}", headers=admin_headers).json()["tech_confirm_status"] == "confirmed"
        package = instance.json()["scenario_review_package"]
        assert package["status"] == "approved"
        assert package["current_version_no"] == 2
        assert client.put(f"/api/scenario-business-mappings/{business['id']}", headers=admin_headers, json={"remarks": "审核后修改"}).status_code == 409

        double_created = client.post(f"/api/projects/{project['id']}/tasks/batch-create", headers=admin_headers, json={
            "workflow_key": "double_layer_mapping_review",
            "targets": [{"target_type": "source_to_mart", "target_id": source_to_mart["id"]}],
            "assignments": {
                "technical_reviewer": users["technical_reviewer"]["id"],
                "final_reviewer": users["final_reviewer"]["id"],
            },
        })
        assert double_created.status_code == 201, double_created.text
        double_instance_id = double_created.json()["workflow_instance_ids"][0]
        double_tasks = {
            row["step_key"]: row for row in client.get(f"/api/projects/{project['id']}/tasks", headers=admin_headers).json()
            if row["workflow_instance_id"] == double_instance_id
        }
        assert client.post(f"/api/review-tasks/{double_tasks['technical_review']['id']}/approve", headers=_bearer(technical_reviewer_login["access_token"]), json={"comment": "技术审核通过"}).status_code == 200
        assert client.post(f"/api/review-tasks/{double_tasks['final_review']['id']}/approve", headers=_bearer(final_login["access_token"]), json={"comment": "最终审核通过"}).status_code == 200
        assert client.get(f"/api/source-to-mart-mappings/{source_to_mart['id']}", headers=admin_headers).json()["mapping_status"] == "approved"
        notifications = client.get("/api/me/notifications", headers=_bearer(final_login["access_token"])).json()
        assert any(item["notification_type"] == "task_assigned" for item in notifications)


def test_inline_batch_job_is_queryable_and_idempotent(monkeypatch) -> None:
    with _governance_client(monkeypatch) as client:
        admin_headers = _bootstrap_platform(client)
        bank = client.post("/api/admin/institutions", headers=admin_headers, json={"institution_code": "BANK_JOB", "institution_name": "任务示例银行", "institution_type": "bank"}).json()
        project = client.post("/api/projects", headers=admin_headers, json={"name": "异步任务项目", "institution_id": bank["id"]}).json()
        headers = {**admin_headers, "Idempotency-Key": "business-draft-batch-001"}
        payload = {"field_ids": [], "password": "must-not-enter-job-payload", "knowledge_content": "must-not-enter-job-payload"}

        first = client.post(f"/api/projects/{project['id']}/batch/generate-business-drafts", headers=headers, json=payload)
        second = client.post(f"/api/projects/{project['id']}/batch/generate-business-drafts", headers=headers, json=payload)

        assert first.status_code == 202, first.text
        assert second.status_code == 202, second.text
        assert first.json()["id"] == second.json()["id"]
        job = client.get(f"/api/jobs/{first.json()['id']}", headers=admin_headers)
        assert job.status_code == 200, job.text
        assert job.json()["status"] == "completed"
        assert "must-not-enter-job-payload" not in str(job.json()["payload_summary_json"])


def test_restricted_file_download_is_authorized_and_path_safe(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "storage"))
    with _governance_client(monkeypatch) as client:
        admin_headers = _bootstrap_platform(client)
        bank_a = client.post("/api/admin/institutions", headers=admin_headers, json={"institution_code": "BANK_FILE_A", "institution_name": "文件甲银行", "institution_type": "bank"}).json()
        bank_b = client.post("/api/admin/institutions", headers=admin_headers, json={"institution_code": "BANK_FILE_B", "institution_name": "文件乙银行", "institution_type": "bank"}).json()
        project = client.post("/api/projects", headers=admin_headers, json={"name": "文件安全项目", "institution_id": bank_a["id"]}).json()
        traversal = client.post(f"/api/projects/{project['id']}/files", headers=admin_headers, data={"classification": "restricted"}, files={"file": ("../escape.txt", b"blocked", "text/plain")})
        assert traversal.status_code == 400

        uploaded = client.post(f"/api/projects/{project['id']}/files", headers=admin_headers, data={"classification": "restricted"}, files={"file": ("evidence.txt", b"restricted-test-content", "text/plain")})
        assert uploaded.status_code == 201, uploaded.text
        assert "storage" not in uploaded.text.lower()
        file_id = uploaded.json()["id"]
        downloaded = client.get(f"/api/files/{file_id}/download", headers=admin_headers)
        assert downloaded.status_code == 200
        assert downloaded.content == b"restricted-test-content"
        duplicate = client.post(f"/api/projects/{project['id']}/files", headers=admin_headers, data={"classification": "restricted"}, files={"file": ("evidence-copy.txt", b"restricted-test-content", "text/plain")})
        assert duplicate.status_code == 201, duplicate.text
        assert duplicate.json()["id"] == file_id
        assert client.get(f"/api/files/{file_id}/download", headers=admin_headers).content == b"restricted-test-content"
        stored_paths = [path for path in (tmp_path / "storage").rglob("*") if path.is_file()]
        assert len(stored_paths) == 1
        assert stored_paths[0].read_bytes() == b"restricted-test-content"

        public_first = client.post(f"/api/projects/{project['id']}/files", headers=admin_headers, data={"classification": "public"}, files={"file": ("classification.txt", b"classification-test", "text/plain")})
        restricted_again = client.post(f"/api/projects/{project['id']}/files", headers=admin_headers, data={"classification": "restricted"}, files={"file": ("classification-copy.txt", b"classification-test", "text/plain")})
        assert public_first.status_code == 201 and restricted_again.status_code == 201
        assert public_first.json()["id"] == restricted_again.json()["id"]
        assert restricted_again.json()["classification"] == "restricted"

        other_project = client.post("/api/projects", headers=admin_headers, json={"name": "同机构隔离项目", "institution_id": bank_a["id"]}).json()
        cross_project = client.post(f"/api/projects/{other_project['id']}/files", headers=admin_headers, data={"classification": "restricted"}, files={"file": ("evidence.txt", b"restricted-test-content", "text/plain")})
        assert cross_project.status_code == 201, cross_project.text
        assert cross_project.json()["id"] != file_id
        assert client.get(f"/api/files/{file_id}/download", headers=admin_headers).content == b"restricted-test-content"

        outsider_password = "test-only-outsider-password"
        outsider = client.post("/api/admin/users", headers=admin_headers, json={"username": "outsider", "display_name": "乙行用户", "email": "outsider@example.invalid", "password": outsider_password, "institution_id": bank_b["id"], "institution_role": "member"}).json()
        outsider_token = client.post("/api/auth/login", json={"username": "outsider", "password": outsider_password}).json()["access_token"]
        assert client.get(f"/api/files/{file_id}/download", headers=_bearer(outsider_token)).status_code == 404


def test_login_failures_are_generic_and_temporarily_lock_account(monkeypatch) -> None:
    with _governance_client(monkeypatch) as client:
        headers = _bootstrap_platform(client)
        for _ in range(5):
            failed = client.post("/api/auth/login", json={"username": "platform_admin", "password": "wrong-password-value"})
            assert failed.status_code == 401
            assert failed.json()["detail"] == "Invalid username or password"
        locked = client.post("/api/auth/login", json={"username": "platform_admin", "password": "test-only-platform-bootstrap-password"})
        assert locked.status_code == 401


def test_task_queues_retry_cancel_and_celery_payload_safety(db_session) -> None:
    from app.models import BackgroundJob

    inline = InlineTaskQueue()
    attempts = {"count": 0}

    def flaky(db, job):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("temporary worker failure")
        return {"success_count": 1, "failed_count": 0}

    failed = inline.enqueue(db_session, job_type="project_backup", institution_id=None, project_id=None, created_by=1, idempotency_key="retryable", payload_summary={}, handler=flaky)
    assert failed.status == "failed"
    retried = inline.retry(db_session, failed)
    assert retried.status == "completed"
    assert retried.retry_count == 1

    queued = BackgroundJob(institution_id=None, project_id=None, idempotency_key="cancel-me", job_type="project_backup", status="queued", progress=0, payload_summary_json={}, result_summary_json={}, created_by=1)
    db_session.add(queued); db_session.commit(); db_session.refresh(queued)
    assert inline.cancel(db_session, queued).status == "cancelled"

    class FakeCelery:
        class Result:
            def __init__(self, task_id): self.id = task_id
        class Control:
            def __init__(self): self.revocations = []
            def revoke(self, task_id, terminate=False): self.revocations.append((task_id, terminate))
        def __init__(self): self.calls = []; self.control = self.Control()
        def send_task(self, name, args):
            self.calls.append((name, args))
            return self.Result(f"celery-{len(self.calls)}")

    fake = FakeCelery(); celery = CeleryTaskQueue(fake)
    remote = celery.enqueue(db_session, job_type="metadata_sync", institution_id=1, project_id=1, created_by=1, idempotency_key="celery-safe", payload_summary={"password": "do-not-send", "knowledge_content": "do-not-send"})
    assert fake.calls == [("app.workers.execute_background_job", [remote.id])]
    assert remote.celery_task_id == "celery-1"
    assert "do-not-send" not in str(remote.payload_summary_json)
    cancelled = celery.cancel(db_session, remote)
    assert cancelled.status == "cancelled"
    assert fake.control.revocations == [("celery-1", False)]
    retried_remote = celery.retry(db_session, cancelled)
    assert retried_remote.status == "queued"
    assert retried_remote.celery_task_id == "celery-2"
    with pytest.raises(ValueError, match="Only failed"):
        celery.retry(db_session, retried_remote)


def test_running_batch_stops_before_next_item_when_cancelled(db_session) -> None:
    from app.api.jobs import _draft_handler
    from app.models import BackgroundJob, ScenarioBusinessMapping

    job = BackgroundJob(
        institution_id=None, project_id=77, idempotency_key="cancel-running-batch",
        job_type="batch_ai_generation_business", status="running", progress=1,
        payload_summary_json={}, result_summary_json={}, created_by=1,
    )
    rows = [
        ScenarioBusinessMapping(project_id=77, target_field_id=index, scenario_id=index, business_definition=f"row-{index}")
        for index in (1, 2)
    ]
    db_session.add_all([job, *rows]); db_session.commit(); db_session.refresh(job)
    processed = []

    async def cancel_after_first(db, mapping_id):
        processed.append(mapping_id)
        current = db.get(BackgroundJob, job.id)
        current.status = "cancelled"
        db.commit()

    result = _draft_handler(db_session, job, ScenarioBusinessMapping, cancel_after_first)

    assert len(processed) == 1
    assert result["success_count"] == 1
    assert db_session.get(BackgroundJob, job.id).status == "cancelled"


def test_s3_storage_save_is_idempotent() -> None:
    from app.services.storage.s3 import S3CompatibleStorageService

    class FakeS3:
        def __init__(self): self.objects = {}; self.put_calls = 0
        def head_object(self, *, Bucket, Key):
            if Key not in self.objects: raise KeyError(Key)
            return {}
        def put_object(self, *, Bucket, Key, Body, ServerSideEncryption):
            self.put_calls += 1; self.objects[Key] = Body

    client = FakeS3()
    service = S3CompatibleStorageService(client, "test-bucket")
    first = service.save(b"same-content", file_name="evidence.txt", project_id=9)
    second = service.save(b"same-content", file_name="evidence.txt", project_id=9)

    assert first.storage_key == second.storage_key
    assert client.put_calls == 1
    assert client.objects[first.storage_key] == b"same-content"


def test_audit_redaction_removes_credentials_and_sensitive_values() -> None:
    sensitive = "138" + "0013" + "8000"
    summary = redact_summary({"password": "plain", "token": "bearer", "note": f"联系电话{sensitive}"})
    assert "password" not in summary
    assert "token" not in summary
    assert sensitive not in summary["note"]


def test_health_metrics_dashboard_and_audit_are_available(monkeypatch) -> None:
    with _governance_client(monkeypatch) as client:
        admin_headers = _bootstrap_platform(client)
        bank = client.post("/api/admin/institutions", headers=admin_headers, json={"institution_code": "BANK_DASH", "institution_name": "看板银行", "institution_type": "bank"}).json()
        project = client.post("/api/projects", headers=admin_headers, json={"name": "看板项目", "institution_id": bank["id"]}).json()
        live = client.get("/api/health/live")
        ready = client.get("/api/health/ready")
        metrics = client.get("/api/metrics")
        dashboard = client.get(f"/api/projects/{project['id']}/dashboard", headers=admin_headers)
        audit = client.get(f"/api/audit?project_id={project['id']}", headers=admin_headers)
        assert live.status_code == 200
        assert ready.status_code == 200, ready.text
        assert "ybt_http_requests_total" in metrics.text
        assert dashboard.status_code == 200, dashboard.text
        assert dashboard.json()["field_count"] == 0
        assert audit.status_code == 200


@pytest.mark.parametrize("role,allowed,denied", [
    ("business_analyst", "business.edit", "business.review"),
    ("technical_analyst", "technical.edit", "technical.review"),
    ("business_reviewer", "business.review", "technical.edit"),
    ("technical_reviewer", "technical.review", "business.edit"),
    ("final_reviewer", "final.review", "technical.edit"),
    ("knowledge_manager", "knowledge.manage", "catalog.manage"),
    ("data_catalog_manager", "catalog.manage", "knowledge.manage"),
    ("viewer", "project.view", "business.edit"),
])
def test_project_role_permission_matrix(db_session, role, allowed, denied) -> None:
    from app.models import Institution, InstitutionMembership, Project, ProjectMembership, User
    user = User(username=f"matrix_{role}", display_name=role, email=f"{role}@matrix.invalid", password_hash=hash_password("test-only-matrix-password"), status="active")
    institution = Institution(institution_code=f"I_{role}", institution_name=role, institution_type="bank", status="active")
    db_session.add_all([user, institution]);db_session.flush()
    db_session.add(InstitutionMembership(institution_id=institution.id,user_id=user.id,role="member",status="active",created_by=user.id));db_session.flush()
    project=Project(name=f"P_{role}",institution_id=institution.id,project_owner_id=user.id,project_status="active",confidentiality_level="internal");db_session.add(project);db_session.flush()
    db_session.add(ProjectMembership(project_id=project.id,user_id=user.id,project_role=role,status="active",created_by=user.id));db_session.commit()
    permissions=PermissionService(db_session,Principal(user.id,user.username,user.display_name))
    assert permissions.require_project_permission(project.id,allowed).id==project.id
    with pytest.raises(HTTPException) as error: permissions.require_project_permission(project.id,denied)
    assert error.value.status_code==403


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _bootstrap_platform(client: TestClient) -> dict[str, str]:
    password = "test-only-platform-bootstrap-password"
    response = client.post("/api/admin/bootstrap", json={
        "institution_code": "PLATFORM", "institution_name": "脱敏平台运营方", "institution_type": "platform_operator",
        "username": "platform_admin", "display_name": "平台管理员", "email": "platform@example.invalid", "password": password,
    })
    assert response.status_code == 201, response.text
    login = client.post("/api/auth/login", json={"username": "platform_admin", "password": password})
    assert login.status_code == 200, login.text
    return _bearer(login.json()["access_token"])


@contextmanager
def _governance_client(monkeypatch) -> Iterator[TestClient]:
    monkeypatch.setenv("AUTH_MODE", "required")
    monkeypatch.setenv("JWT_SECRET_KEY", "tests-generate-this-non-production-secret")
    get_settings.cache_clear()
    from app.services.storage.factory import get_storage_service
    from app.services.task_queue.factory import get_task_queue
    get_storage_service.cache_clear()
    get_task_queue.cache_clear()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    def override_get_db() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    from app.main import app

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        get_storage_service.cache_clear()
        get_task_queue.cache_clear()
        get_settings.cache_clear()
