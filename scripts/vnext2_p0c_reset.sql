-- P0-C 浏览器闭环演示数据重置（项目 7 / 需求 5）。
--
-- 为什么需要这个脚本：浏览器闭环会真实经过送审、三级审核、正式交付与导出，
-- 因而在 requirement_review_submissions / requirement_formal_deliveries /
-- review_tasks / workflow_instances 留下外键引用。只删除 requirement_revisions
-- 会被外键拒绝（Key (id) is still referenced from requirement_review_submissions），
-- 而 psql 默认继续执行后续语句，结果是「revisions 仍在、requirements.content_version
-- 被改回 1」的半损坏状态。这里按外键依赖顺序清理，并用 psql -v ON_ERROR_STOP=1
-- 保证任一语句失败即中止，不产生半重置状态。
--
-- 用法（宿主 PowerShell）：
--   $sql = Get-Content -Raw ai-platform\scripts\vnext2_p0c_reset.sql
--   $sql | Out-File -Encoding ascii -NoNewline C:\Users\Public\p0c_reset.sql
--   wsl -e sh -lc "docker exec -i ybt-postgres psql -v ON_ERROR_STOP=1 -U ybt_dsh_handoff_v2 -d ybt_dsh_handoff_v2 < /mnt/c/Users/Public/p0c_reset.sql"

BEGIN;

-- 1. 生成候选与输入
DELETE FROM requirement_generation_items
 WHERE input_id IN (SELECT id FROM requirement_generation_inputs WHERE requirement_id = 5);
DELETE FROM requirement_generation_inputs WHERE requirement_id = 5;

-- 2. 正式交付与审核提交（均引用 requirement_revisions）
DELETE FROM requirement_formal_deliveries WHERE requirement_id = 5;
DELETE FROM requirement_review_submissions WHERE requirement_id = 5;

-- 3. 复核 / UAT 关联
DELETE FROM requirement_rechecks WHERE requirement_id = 5;
DELETE FROM requirement_uat_links WHERE requirement_id = 5;

-- 4. 审核工作流（review_decisions → review_tasks → workflow_instances）
DELETE FROM review_decisions
 WHERE review_task_id IN (
   SELECT id FROM review_tasks
    WHERE workflow_instance_id IN (SELECT id FROM workflow_instances WHERE project_id = 7)
 );
DELETE FROM agent_steps
 WHERE review_task_id IN (
   SELECT id FROM review_tasks
    WHERE workflow_instance_id IN (SELECT id FROM workflow_instances WHERE project_id = 7)
 );
DELETE FROM agent_human_decisions
 WHERE review_task_id IN (
   SELECT id FROM review_tasks
    WHERE workflow_instance_id IN (SELECT id FROM workflow_instances WHERE project_id = 7)
 );
DELETE FROM review_tasks
 WHERE workflow_instance_id IN (SELECT id FROM workflow_instances WHERE project_id = 7);
DELETE FROM deliverable_package_versions
 WHERE workflow_instance_id IN (SELECT id FROM workflow_instances WHERE project_id = 7);
DELETE FROM workflow_instances WHERE project_id = 7;

-- 5. 演示需求的历史修订与演示问题
DELETE FROM requirement_revisions WHERE requirement_id = 5 AND content_version > 1;
DELETE FROM pending_questions WHERE project_id = 7 AND question_text LIKE '%浏览器闭环反例%';

-- 6. 回到 v1，供浏览器从「已存在独立内容 v1」开始
UPDATE requirements SET content_version = 1 WHERE id = 5;

COMMIT;

SELECT id, content_version FROM requirements WHERE id = 5;
SELECT count(*) AS revision_count FROM requirement_revisions WHERE requirement_id = 5;
