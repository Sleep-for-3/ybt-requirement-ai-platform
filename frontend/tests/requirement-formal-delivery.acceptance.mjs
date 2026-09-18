#!/usr/bin/env node
/**
 * Requirement formal delivery acceptance: submit → review → finalize → download.
 * Tests the complete 3-stage review workflow and formal delivery.
 */

import { chromium } from "playwright";
import { spawn } from "child_process";
import { setTimeout } from "timers/promises";

const DIST_DIR = process.env.NEXT_DIST_DIR || ".next-formal-delivery-acceptance";
const TEST_PORT = 13406;
const ACCEPTANCE_DIR = "docs/ux/acceptance";

const mockData = {
  projectId: 1,
  requirementId: 1,
  userId: 1,
  reviewerId: 2,
  finalReviewerId: 3,
  fieldId: 1,
};

function startDevServer() {
  return new Promise((resolve, reject) => {
    const env = { ...process.env, NEXT_DIST_DIR: DIST_DIR, PORT: String(TEST_PORT) };
    const proc = spawn("npm", ["run", "dev"], { env, shell: true, stdio: ["ignore", "pipe", "pipe"] });
    let started = false;
    const timeout = setTimeout(() => {
      if (!started) {
        proc.kill();
        reject(new Error("Dev server startup timeout"));
      }
    }, 60000);

    proc.stdout.on("data", (chunk) => {
      const line = String(chunk);
      console.log("[dev]", line.trim());
      if (!started && /ready|started|listening/i.test(line)) {
        started = true;
        clearTimeout(timeout);
        resolve(proc);
      }
    });

    proc.stderr.on("data", (chunk) => console.error("[dev:err]", String(chunk).trim()));
    proc.on("error", reject);
    proc.on("exit", (code) => !started && reject(new Error(`Server exited with ${code}`)));
  });
}

async function interceptAPIs(page) {
  const { projectId, requirementId, userId, reviewerId, finalReviewerId, fieldId } = mockData;

  // Mock auth
  await page.route("**/auth/me", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      user_id: userId,
      effective_project_permissions: {
        [projectId]: ["project.view", "business.edit", "technical.edit", "deliverable.manage", "deliverable.view", "deliverable.review", "deliverable.export", "lineage.view"]
      }
    })
  }));

  // Mock requirement
  await page.route(`**/projects/${projectId}/requirements/${requirementId}`, (route) => {
    if (route.request().method() === "GET") {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: requirementId,
          project_id: projectId,
          name: "测试正式交付需求",
          version: 1,
          content_version: 1,
          scope_json: {
            target_table_id: 1,
            scenario_id: 1,
            field_ids: [fieldId],
            background: "正式交付端到端验收测试",
          }
        })
      });
    } else {
      route.continue();
    }
  });

  // Mock review readiness - initially eligible
  let readinessVersion = 1;
  await page.route(`**/projects/${projectId}/requirements/${requirementId}/review-readiness*`, (route) => {
    const eligible = readinessVersion === 1;
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        eligible,
        content_version: readinessVersion,
        content_hash: "abc123",
        revision_status: "draft",
        blocking_count: eligible ? 0 : 1,
        reasons: eligible ? [] : [{ code: "lineage_missing", message: "缺少血缘快照" }]
      })
    });
  });

  // Mock review submissions
  let submissionId = null;
  let submissionStatus = null;
  let workflowTasks = [];

  await page.route(`**/projects/${projectId}/requirements/${requirementId}/review-submissions`, (route) => {
    if (route.request().method() === "POST") {
      submissionId = 1;
      submissionStatus = "pending_review";
      workflowTasks = [
        { id: 101, step_key: "business_review", status: "pending", assignee_role: "business_reviewer" },
        { id: 102, step_key: "technical_review", status: "pending", assignee_role: "technical_reviewer" },
        { id: 103, step_key: "final_review", status: "pending", assignee_role: "final_reviewer" }
      ];
      route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          id: submissionId,
          content_version: 1,
          status: submissionStatus,
          submitted_at: new Date().toISOString()
        })
      });
    } else {
      const submissions = submissionId ? [{
        id: submissionId,
        content_version: 1,
        status: submissionStatus,
        submitted_at: new Date().toISOString(),
        reviewed_at: submissionStatus === "approved" ? new Date().toISOString() : null,
        workflow: { id: 1, status: submissionStatus, current_step: workflowTasks.find(t => t.status === "pending")?.step_key || null },
        tasks: workflowTasks
      }] : [];
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(submissions)
      });
    }
  });

  // Mock review finalize
  let formalDeliveryId = null;
  await page.route(`**/projects/${projectId}/requirements/${requirementId}/review-submissions/${submissionId}/finalize`, (route) => {
    if (submissionStatus === "approved") {
      formalDeliveryId = 1;
      route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          id: formalDeliveryId,
          version_no: 1,
          content_version: 1,
          approved_at: new Date().toISOString()
        })
      });
    } else {
      route.fulfill({ status: 409, body: "审核未通过" });
    }
  });

  // Mock formal deliveries
  await page.route(`**/projects/${projectId}/requirements/${requirementId}/formal-deliveries`, (route) => {
    const deliveries = formalDeliveryId ? [{
      id: formalDeliveryId,
      version_no: 1,
      content_version: 1,
      status: "formal",
      approved_at: new Date().toISOString()
    }] : [];
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(deliveries)
    });
  });

  // Mock formal delivery download
  await page.route(`**/projects/${projectId}/requirements/${requirementId}/formal-deliveries/${formalDeliveryId}/export`, (route) => {
    // Return a minimal Excel file mock
    route.fulfill({
      status: 200,
      headers: {
        "content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "content-disposition": `attachment; filename="formal-delivery-v1.xlsx"`
      },
      body: Buffer.from("PK") // Minimal ZIP signature for Excel
    });
  });

  // Mock review task
  await page.route(`**/review-tasks/*`, (route) => {
    const taskId = parseInt(route.request().url().split("/").pop());
    const task = workflowTasks.find(t => t.id === taskId);
    if (task) {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: taskId,
          workflow_instance_id: 1,
          step_key: task.step_key,
          status: task.status,
          assignee_role: task.assignee_role,
          context: {
            requirement_id: requirementId,
            project_id: projectId,
            content_version: 1
          }
        })
      });
    } else {
      route.continue();
    }
  });

  // Mock task approval
  await page.route(`**/review-tasks/*/approve`, (route) => {
    const taskId = parseInt(route.request().url().split("/")[route.request().url().split("/").length - 2]);
    const task = workflowTasks.find(t => t.id === taskId);
    if (task) {
      task.status = "approved";
      // Move to next step
      const currentIndex = workflowTasks.indexOf(task);
      if (currentIndex < workflowTasks.length - 1) {
        workflowTasks[currentIndex + 1].status = "pending";
      } else {
        // All approved
        submissionStatus = "approved";
      }
      route.fulfill({ status: 200, body: JSON.stringify({ status: "approved" }) });
    } else {
      route.continue();
    }
  });

  return {
    approveTask: (taskId) => {
      const task = workflowTasks.find(t => t.id === taskId);
      if (task) {
        task.status = "approved";
        const currentIndex = workflowTasks.indexOf(task);
        if (currentIndex < workflowTasks.length - 1) {
          workflowTasks[currentIndex + 1].status = "pending";
        } else {
          submissionStatus = "approved";
        }
      }
    }
  };
}

async function run() {
  console.log("Starting formal delivery acceptance test...");
  const server = await startDevServer();
  console.log(`Dev server started on port ${TEST_PORT}`);

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 1024 } });
  const page = await context.newPage();

  const mockAPI = await interceptAPIs(page);

  const results = {
    timestamp: new Date().toISOString(),
    tests: [],
    passed: 0,
    failed: 0
  };

  function assert(condition, name) {
    const passed = Boolean(condition);
    results.tests.push({ name, passed });
    if (passed) {
      results.passed++;
      console.log(`✓ ${name}`);
    } else {
      results.failed++;
      console.error(`✗ ${name}`);
    }
    return passed;
  }

  try {
    // Navigate to workspace (mock will handle the requirement load)
    await page.goto(`http://localhost:${TEST_PORT}/workspace?projectId=${mockData.projectId}&requirementId=${mockData.requirementId}`, { waitUntil: "networkidle" });
    await setTimeout(1000);

    // Check if delivery panel is visible
    const deliveryPanel = await page.locator('#requirement-delivery').count();
    assert(deliveryPanel > 0, "Delivery panel is visible");

    // Check readiness badge
    const readyBadge = await page.locator('.badge-success:has-text("可送审")').count();
    assert(readyBadge > 0, "Shows eligible for submission");

    // Find and click submit button
    const submitButton = await page.locator('button:has-text("提交内容")').first();
    assert(await submitButton.count() > 0, "Submit button is present");

    await submitButton.click();
    await setTimeout(1500);

    // Check submission confirmation
    const confirmMessage = await page.locator('text=/已提交三阶段审核/').count();
    assert(confirmMessage > 0, "Submission confirmation appears");

    // Check review tasks appear
    const businessTask = await page.locator('text=/业务审核/').count();
    const techTask = await page.locator('text=/技术审核/').count();
    const finalTask = await page.locator('text=/终审/').count();
    assert(businessTask > 0 && techTask > 0 && finalTask > 0, "Three review tasks are listed");

    // Approve all tasks programmatically
    mockAPI.approveTask(101);
    mockAPI.approveTask(102);
    mockAPI.approveTask(103);

    await page.reload({ waitUntil: "networkidle" });
    await setTimeout(1000);

    // Check for finalize button
    const finalizeButton = await page.locator('button:has-text("固定正式交付")').first();
    assert(await finalizeButton.count() > 0, "Finalize button appears after approval");

    await finalizeButton.click();
    await setTimeout(1500);

    // Check finalize confirmation
    const finalizeMessage = await page.locator('text=/正式交付版本已固定/').count();
    assert(finalizeMessage > 0, "Finalize confirmation appears");

    // Check formal delivery appears in history
    const formalDelivery = await page.locator('text=/正式 v1/').count();
    assert(formalDelivery > 0, "Formal delivery v1 appears in history");

    // Check download button
    const downloadButton = await page.locator('button:has-text("下载")').first();
    assert(await downloadButton.count() > 0, "Download button is present");

    // Screenshot final state
    await page.screenshot({ path: `${ACCEPTANCE_DIR}/requirement-formal-delivery.png`, fullPage: true });
    console.log(`Screenshot saved to ${ACCEPTANCE_DIR}/requirement-formal-delivery.png`);

    // Save results
    const fs = await import("fs/promises");
    await fs.mkdir(ACCEPTANCE_DIR, { recursive: true });
    await fs.writeFile(
      `${ACCEPTANCE_DIR}/requirement-formal-delivery.json`,
      JSON.stringify(results, null, 2)
    );

  } catch (error) {
    console.error("Test error:", error);
    results.tests.push({ name: "Test execution", passed: false, error: error.message });
    results.failed++;
  } finally {
    await browser.close();
    server.kill();
    console.log(`\nResults: ${results.passed} passed, ${results.failed} failed`);
    process.exit(results.failed > 0 ? 1 : 0);
  }
}

run().catch((error) => {
  console.error("Fatal error:", error);
  process.exit(1);
});
