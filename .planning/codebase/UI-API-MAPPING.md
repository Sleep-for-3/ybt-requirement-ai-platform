# UI → API Mapping

| UI capability | Existing API / entity | Use in rebuild |
|---------------|-----------------------|----------------|
| Current project / institution | `GET /projects`, `Project`, `ProjectContext`, `GET /auth/me` | Top bar and workspace scope |
| Target table | `GET /target-tables?project_id=`, `TargetTable` | Analysis target and document title |
| Target fields | `GET /fields?project_id=&target_table_id=`, `TargetField` | Field navigator and document rows |
| Product scenario | `GET /projects/{id}/scenarios?enabled=true`, `ProductScenario` | Mapping context |
| Business definition | `GET/PUT /target-fields/{field}/scenario-business-mappings`, `ScenarioBusinessMapping` | AI draft vs final business content |
| Technical lineage | `GET/PUT /target-fields/{field}/scenario-technical-lineages`, `ScenarioTechnicalLineage` | Source nodes, processing and final content |
| Source systems | `GET /projects/{id}/business-systems`, `BusinessSystem` | Authorized source scope |
| Datasources/catalog | `GET /projects/{id}/datasources`, catalog APIs | Read-only connection availability and links |
| Regulatory mart | `GET /projects/{id}/mart-tables`, `GET /mart-tables/{id}/mart-fields` | Mart nodes and field labels |
| Source → Mart | `GET /mart-fields/{id}/source-to-mart-mappings`, `SourceToMartMapping` | First mapping layer, kept distinct |
| Mart → YBT | `GET /target-fields/{id}/mart-to-ybt-mappings`, `MartToYbtMapping` | Second mapping layer, kept distinct |
| AI analysis | `POST /projects/{id}/batch/generate-business-drafts`, `...generate-technical-drafts`; `GET /jobs/{id}` | Real job status only |
| Adopt AI draft | `POST /scenario-business-mappings/{id}/adopt-ai-draft`, technical equivalent | Explicit adoption action |
| Evidence | `GET /mappings/{type}/{id}/evidence`, `MappingEvidenceReference` | In-context evidence drawer |
| Pending questions | `GET /projects/{id}/questions`, `PendingQuestion` | Field/table scoped questions |
| Draft/formal delivery | `GET /projects/{id}/deliverables`, `DeliverablePackage` | Latest real version/status and link |
| Excel export | `GET /projects/{id}/export/traceability-workbook` | Real file download |

## Unsupported prototype details

- A persisted free-form “需求背景” document-level entity does not exist. The rebuild uses the current target-field regulatory definition plus existing scenario mapping content; it does not add a fake persistent field.
- The backend does not provide the prototype's seven named AI stages. The UI displays only `BackgroundJob.status`, `current_step` and `progress` when present.
- Connection totals and model identity from the prototype are not authoritative. The UI derives availability from real Datasource/BusinessSystem/Mart records and does not claim a fixed Qwen model.
