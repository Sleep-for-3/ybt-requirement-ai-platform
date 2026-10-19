# P1-B 交付说明：条款粒度与实现对照的「未对照」态

- 日期：2026-10-18
- 范围：`.planning/_prompts.md:285-322`「四　P1-B　条款定位剩余缺口：粒度与实现对照」
- 仓库：`ai-platform`（branch `dsh/banking-semantic-agent-v2`，HEAD `e8ce8af`）
- 状态：代码 + 回归 + 全量回归完成；**未提交 git**（工作区保持可 review 状态）

---

## 0　结论摘要

定位器本身上一轮已收紧，本轮不再动它（`_prompts.md` 明确「不要放宽 inscribed_clause_locator 的接受范围」）。本轮补的是它下面两件结构性的事，都按「记录事实，不猜事实」落地：

| 缺口 | 改动前 | 改动后 |
| --- | --- | --- |
| 条款粒度 | `parsers.py` 把每个段落切成一个 `policy_clause` unit，标题与正文同为 unit，条款与章节的从属关系不落库 | docx 解析时记录 `chapter_no` / `chapter_heading` / `clause_no` 进 `metadata_json`（再镜像进 `locator`），标题不再产出 unit |
| 实现对照 | `missing_implementation` 一态两用：「没跑过对照」与「对照过发现缺实现」混在一个计数里 | 新增 `not_compared` 态与 `policy_not_compared` gap；没跑过的对照不再计入 `missing_implementation` |

关键数字（只读探针实测，见 §4.4）：

```
活库 policy_clause units                      : 13（project 1 两条、project 12 十一条）
旧定位器判为「无可引用条款」                 : 13 / 13
新定位器仍判为「无可引用条款」               : 6 / 13   → 7 条由 unit 自述条款号救回
活库 compare_policy 步骤历史 missing_implementation gap : 7 次（全部是「未匹配到实现证据」）
24 份 gap_report 的 missing_implementation_count        : 全部 0
```

第 7 条同时说明：那个 7 不是「发现缺实现」的结论，正是本轮要改名的东西。

---

## 1　人拍板的那一个岔路口

`_prompts.md` 只要求「优先用已存在的 metadata_json 承载，不要新增表，除非证明 metadata 装不下」，没有要求先拍板。本轮按此执行：**没有新增表、没有新增列、没有迁移**。

但有一个必须写明的取舍：

- `metadata_json` 是 `KnowledgeUnit` 的既有列，写入不改变 `content_hash`（`ingestion_service.py` 的 hash 不含 metadata），因此**不会让既有 unit 重新 dedup 或漂移**。
- 章节字段同时被镜像进 `locator`（`parsers.py:24-28` 的 `locator.setdefault`），因为检索命中把 `locator` 原样交给 `evidence.py`，不镜像的话引用侧读不到。
- **没有**把 `chapter_no` 加进 `unit_locator()` 白名单（`knowledge_evidence.py`）：那会改变新建 basis 的 `basis_hash`，让既有已确认的需求快照作废。章节只走 agent 侧的 `policy_clause` 证据，不进冻结快照。这条是**有意保留**，见 §5。

---

## 2　变更文件清单

后端（`git diff --numstat`）：

> 说明：工作区还带着**本会话更早阶段**（P0 系列、检索/治理/任务队列、P1-A 等）的改动，`git status` 共 40 余个 M 文件。下表只列 P1-B 自己触及的文件；其余不属于本次交付，复核时请勿归到 P1-B 名下。

| 文件 | +/- | 作用 |
| --- | --- | --- |
| `backend/app/services/knowledge_ingestion/parsers.py` | +118/-8 | docx 章节/条款从属落 metadata 与 locator；标题不再产出 `policy_clause` unit |
| `backend/app/services/agent/tools/evidence.py` | +86/-3 | `clause_parentage()` 与 `inscribed_clause_locator()`；证据携带章节三元组 |
| `backend/app/services/agent/tools/builtin.py` | +10/-3 | `not_compared` 进对照统计；没匹配到实现事实改为 `policy_not_compared` gap |
| `backend/app/services/requirement_policy_comparison.py` | +15/-3 | status 增加 `not_compared`；`comparison_issues` 的「未对照」独立编码；确认时禁止未对照关联实现 |
| `backend/tests/test_requirement_policy_comparison.py` | +65/-2 | 4 条「未对照」回归 |
| `backend/tests/test_agent_acceptance.py` | +6/-1 | 断言新增两个 count 键，且 `missing_implementation_count == 0` |

新增文件（未跟踪 → 待 add）：

| 文件 | 行数 | 作用 |
| --- | --- | --- |
| `backend/tests/test_agent_clause_parentage.py` | 158 | 15 条：引用侧章节回溯 + docx 切分端到端 |

无前端改动、无迁移、无配置项改动。

---

## 3　实现要点

### 3.1　粒度：章节从属在切分时记录，不在引用时猜测

`backend/app/services/knowledge_ingestion/parsers.py`：

- `CHAPTER_NUMBER_PATTERN`（:13）只认标题开头的 `第N章`；`CLAUSE_NUMBER_PATTERN`（:12）与引用侧 `INSCRIBED_CLAUSE_PATTERN` 逐字一致——两侧同一个正则，避免「切分记了、引用不认」的漂移。
- `_docx()`（:94）：遇到 heading 时
  - 有章号 → `chapter = 第N章`；
  - **无章号（`附录`、`总则`）→ `chapter = None`**。这一条是补 `缺` 之后才发现的：最初写成 `if chapter_match: chapter = ...`，结果「附录」下面没有编号的段落继承了上一章的 `第三章`，正是我同时要求在引用侧禁止的「靠邻接获得章号」。首跑就是被新回归 `test_a_clause_outside_a_numbered_chapter_reports_no_chapter` 抓住的。
  - 标题本身 `continue`，不再产出 unit。原实现让每个章标题都成为一个无法被引用的 `policy_clause`，等于给自己制造 `clause_locator_missing`。
- 正文段落写入 `metadata = {"paragraph", "clause_no", "chapter_no", "chapter_heading"}`；`parse_document()`（:22-29）把它镜像进 `locator` 的 `chapter_no` / `clause_no`。

### 3.2　引用：条款号可由 unit 自述，章节只能来自记录

`backend/app/services/agent/tools/evidence.py`：

- `clause_parentage(hit)`（:91）：从 `locator` 读三元组，`chapter_heading` 缺省回落到 `source_heading`；`chapter_no` 缺失时**返回 None 而不是拿邻近标题补**。
- `inscribed_clause_locator(hit)`（:112）：只在「unit 自己拥有的文本」（`source_heading` / `title` / 正文前 12 行）里匹配 `第N条` 或 `N.N`，且必须在行首。容器定位（`A2:J2`、`xxx.xlsx`）不会被当成条款。
- `policy_clause_evidence()`（:146）：容器定位不合格时先试 `inscribed_clause_locator`；救不回来才发 `clause_locator_missing`。**并且**：若最终 locator 既不是记录的 `clause_no`、也不是完整匹配 `CLAUSE_LOCATOR_PATTERN`，则把章节三元组清空——文件名永远不会因为旁边放着 `chapter_no` 就获得章节。
- 证据 `value` 增加 `chapter_no` / `chapter_heading` / `clause_no` 三个键；未加进 `unit_locator()` 白名单（见 §1）。

### 3.3　对照：「未对照」不再是「缺实现」

- `requirement_policy_comparison.py:21` 的 `status` Literal 增加 `not_compared`，理由是注释里写的：没有对照过的人，与断言「实现不存在」的人，不能共用一个计数器。
- `comparison_issues()`（:62）：无人工决策的 unit 改用固定编码 `not_compared`（此前是 `unit:{id}`，导致「尚未人工对照」与「确认依据不完整」共用一个前缀）；`labels` 增加 `未对照` 文案。
- `confirm_comparison()`（:128）：`not_compared` 不允许同时关联实现规则（422），与既有 `missing_implementation` 不许关联实现的规则对称——未对照是空白，不是结论。
- `builtin.py:504`：`_create_gap_report` 新增 `not_compared_count`；`_task_gaps`（:487）把 `not_compared` 并入需要人类看的对照集合。
- `builtin.py:662`：确定性对照阶段没找到可关联实现事实时，gap 从 `missing_implementation` 改名为 `policy_not_compared`，文案从「未找到与监管条款 X 对应的实现证据」改为「未完成实现对照（未定位到可关联的实现证据）」。**这是本轮唯一改变既有 gap 语义的地方**，见 §5 第 3 条。

---

## 4　验收证据

### 4.1　目标测试集

```
pytest tests/test_agent_clause_parentage.py \
       tests/test_agent_policy_clause_locator.py \
       tests/test_requirement_policy_comparison.py \
       tests/test_agent_acceptance.py -q
→ 42 passed
```

拆分：`test_agent_clause_parentage.py` 15、`test_agent_policy_clause_locator.py` 6（既有，未改）、`test_requirement_policy_comparison.py` 22、`test_agent_acceptance.py` 3。

`test_agent_clause_parentage.py` 的 15 条分两组：

引用侧（12 条，纯函数）：
1. `test_clause_parentage_reads_chapter_recorded_at_ingestion`
2. `test_clause_parentage_never_invents_a_chapter_for_a_unit_that_has_none`
3. `test_clause_parentage_falls_back_to_the_recorded_heading_for_the_chapter_title`
4. `test_clause_parentage_ignores_non_text_locator_values`（5 个参数）
5. `test_evidence_carries_chapter_parentage_onto_the_cited_clause`
6. `test_a_file_name_citation_never_acquires_a_chapter_by_adjacency`
7. `test_an_inscribed_clause_number_keeps_its_recorded_chapter`
8. `test_a_clause_without_recorded_parentage_reports_blank_not_guessed`

切分侧（3 条，真 docx）：
9. `test_ingestion_records_the_chapter_a_clause_belongs_to` —— 两个编号章各带条款，断言 `第五条`/`第六条` → `第二章`、`第七条` → `第三章`，读的是 `metadata["locator"]["chapter_no"]` 而不是解析器的内存草稿。
10. `test_a_heading_without_a_chapter_number_is_not_a_citable_clause` —— 章标题不产出 unit。
11. `test_a_clause_outside_a_numbered_chapter_reports_no_chapter` —— 「附录」下的段落 `chapter_no is None`。

`test_requirement_policy_comparison.py` 新增 4 条：

12. `test_a_unit_never_compared_is_reported_apart_from_missing_implementation` —— 恰好 1 条 `not_compared`，且 message 带上 unit id。
13. `test_not_compared_keeps_the_review_unfinished_without_claiming_a_missing_implementation` —— 未对照不产出 `missing_implementation`。
14. `test_not_compared_cannot_cite_an_implementation_rule` —— 422。
15. `test_not_compared_renders_as_its_own_label_in_the_scope_export` —— 导出里状态原样是 `not_compared`。

### 4.2　既有语义不变的证据

- `test_missing_implementation_and_partial_rule_coverage_remain_blocking`（既有，未改）仍然通过：`missing_implementation` 依旧阻塞。
- `test_agent_policy_clause_locator.py` 6 条边界**一行未改**仍全绿：证明没有放宽上一轮特意收紧的接受范围。

### 4.3　全量 backend 回归

```
环境：ENVIRONMENT=test AUTH_MODE=optional DATABASE_URL=sqlite:///./.ci.db
      STORAGE_PROVIDER=local TASK_QUEUE_PROVIDER=inline VECTOR_STORE_PROVIDER=mock
      LLM_PROVIDER=mock EMBEDDING_PROVIDER=mock LINEAGE_GIT_ENABLED=false
pytest -q  →  1715 passed / 1 skipped, 12 warnings  (26m42s, exit 0)  [P1-B 交付时点]。
```
基线（P1-A 交付时记录）：1689 passed / 1 skipped。P1-B 交付时点跑出 1715（+26），全部收口后同一套件最终为 **1725 passed / 1 skipped**（exit 0）。

| 阶段 | passed | 增量来源 |
| --- | --- | --- |
| P1-A 交付时基线 | 1689 | — |
| P1-B 交付时点 | 1715 | P1-B 新增 19 条（`test_agent_clause_parentage.py` 15 + `test_requirement_policy_comparison.py` 4）+ 并行落地的 P2-A/P2-B 回归 7 条 |
| 最终（全部收口后） | **1725** | 1715 → 1725 的 +10 差在本单外（P2-A 补投递失败用例、P2-B 补候选收敛用例）；本单未再动测试文件 |

P1-B 自身的贡献应当看「19 条新增 + 既有测试零改动通过」，不应把 1689→1725 的全部差值记在本单头上。


1 skipped 是既有项（`test_version_consistency.py:136`，需 `PHASE4_VERIFY_DATABASE_URL` 指向一次性 PostgreSQL），与本轮无关。

### 4.4　前后对比（只读探针，活库实测）

探针只做 SELECT，脚本跑完即删（`backend/.probe_live_gaps.py`，未留在工作区）。

条款定位接受率——把活库 13 个 `policy_clause` unit 按检索命中结构喂给前后两版定位逻辑：

| 指标 | 改动前 | 改动后 |
| --- | --- | --- |
| 判为「无可引用条款」（`clause_locator_missing`） | 13 / 13 | **6 / 13** |
| 由 unit 自述条款号救回 | — | **7** |
| 记录到章节号的 unit | 0（当时未落库） | 0（存量数据不回溯，见 §5） |

救回的 7 条全部是 `第N条` 开头的正文段落（project 12：「第一条 …」「第二条 …」「第三条 …」「第四条 …」等），旧逻辑因为 `locator` 里只有 `paragraph_index` 而判为不可引用。

实现对照——活库 43 个 `compare_policy` 步骤：

| 指标 | 数值 |
| --- | --- |
| 历史 `missing_implementation` gap | 7 次（步骤 475/502/528×2/537/564/620，涉及 task 26/27/30×2/31/32/35） |
| 这 7 次的成因 | 全部是「未找到与 knowledge:34:unit:6899 对应的实现证据」 |
| 24 份 `gap_report` 的 `missing_implementation_count` | 全部为 0 |

逐条核对了 7 次的 message：它们全部是「没匹配到实现事实」，没有一条是人工确认过「实现确实缺失」。这正是本轮改名的对象——改后这 7 次会记为 `policy_not_compared`，`missing_implementation_count` 仍为 0（因为 `gap_report` 的口径只数 `policy_comparisons[].status`，而这 7 次没有产出 comparison）。**注意：改名不会让这 7 条既有记录消失**，它们是历史行，存量数据不回溯。

---

## 5　残余、边界与需要后续跟进的事

1. **存量 unit 没有回溯补章节**。`metadata_json` 里没有 `chapter_no` 的既有 unit 依旧报 `None`，不会显示章节。补章节需要重新解析原文件（`storage_path` 里的 docx）再写回，属于一次数据作业，不在本轮范围；本轮保证的是「重新入库的文档会带上章节」。这也是为什么第 3 条说「改后活库仍会看到 6/13 的 clause_locator_missing」——那 6 条是图片/表格类 unit，与章节无关。

2. **`chapter_no` 没有进 `unit_locator()` 白名单**。进了会改 `basis_hash`，使既有已确认的需求快照失效。章节目前只出现在 agent 侧的 `policy_clause` 证据 `value` 里，供 prompt 与人工查看；需求快照的冻结证据不含章节。若将来需要「basis 里也带章节」，需要一次性 basis 版本升级，属产品决策。

3. **`missing_implementation` → `policy_not_compared` 的改名改变了既有 gap 语义**。影响面：`gap_codes_json` 的下游消费者（前端缺口面板、导出）会看到新码；旧码不再由确定性对照路径产生（人工确认路径仍用 `missing_implementation`，语义不变）。这是一次「把真实状态说准」的改动，但也意味着按旧码统计的历史看板会出现断层。若需要平滑，应在前端做一次映射，本轮未做。

4. **`not_compared` 只加在 requirement 对照的 status 上，没加进前端表单**。前端 `policy_comparisons` 的确认表单目前只能选 matched / conflict / missing_implementation / pending；`not_compared` 是「还没选」的隐式状态，服务端会拒绝对它关联实现。如果要在 UI 上显式提供这个选项，需要前端改动，本轮未做。

5. **docx 的章节识别只认 `第N章`**。`一、`、`（一）`、`1.` 这类标题样式不产生 `chapter_no`；`第N节` 也没有。这是有意的窄口径：宁可报 `None`，也不要造出错误层级。要扩，必须先有真实的层级样例。

6. **表格行不带 `clause_no`**。表格行只继承了 `chapter_no`，因为表格里没有「第N条」这种自述条款号；它们的定位仍是 `table:1:row:2`。

7. **验收跑与活库探针都只读、都没改数据**。活库探针只做 SELECT；`gap_report` 的统计口径说明见 §4.4。

8. **未提交 git**。工作区非提交态，变更以上表文件清单为准。
