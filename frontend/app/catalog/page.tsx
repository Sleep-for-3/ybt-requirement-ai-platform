"use client";

import { useEffect, useState } from "react";
import { Clock3, Columns3, DatabaseZap, Download, Search, Table2 } from "lucide-react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { CatalogColumn, CatalogSchema, CatalogSearchItem, CatalogTable, ColumnProfileSnapshot, DataSource, apiGet, apiPost } from "@/lib/api";

const TABLE_PAGE_SIZE = 50;
const COLUMN_PAGE_SIZE = 100;

export default function CatalogPage() {
  const { projectId } = useProjectWorkspace();
  const [datasources, setDatasources] = useState<DataSource[]>([]);
  const [schemas, setSchemas] = useState<CatalogSchema[]>([]);
  const [tables, setTables] = useState<CatalogTable[]>([]);
  const [tableTotal, setTableTotal] = useState(0);
  const [tablePage, setTablePage] = useState(1);
  const [columns, setColumns] = useState<CatalogColumn[]>([]);
  const [columnTotal, setColumnTotal] = useState(0);
  const [columnPage, setColumnPage] = useState(1);
  const [selectedTable, setSelectedTable] = useState<number | null>(null);
  const [datasourceId, setDatasourceId] = useState("");
  const [schemaName, setSchemaName] = useState("");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<CatalogSearchItem[]>([]);
  const [profileHistory, setProfileHistory] = useState<{ columnId: number; items: ColumnProfileSnapshot[] } | null>(null);
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!projectId) return;
    void Promise.all([
      apiGet<DataSource[]>(`/projects/${projectId}/datasources`),
      apiGet<CatalogSchema[]>(`/projects/${projectId}/catalog/schemas${datasourceId ? `?datasource_id=${datasourceId}` : ""}`),
    ]).then(([sourceItems, schemaItems]) => { setDatasources(sourceItems); setSchemas(schemaItems); });
  }, [projectId, datasourceId]);

  useEffect(() => {
    if (!projectId) return;
    const params = new URLSearchParams({ page: String(tablePage), page_size: String(TABLE_PAGE_SIZE) });
    if (datasourceId) params.set("datasource_id", datasourceId);
    if (schemaName) params.set("schema_name", schemaName);
    void apiGet<{ items: CatalogTable[]; total: number }>(`/projects/${projectId}/catalog/tables?${params}`).then((response) => {
      setTables(response.items); setTableTotal(response.total);
    });
  }, [projectId, datasourceId, schemaName, tablePage]);

  async function openTable(id: number, page = 1) {
    const response = await apiGet<{ items: CatalogColumn[]; total: number }>(`/catalog/tables/${id}/columns?page=${page}&page_size=${COLUMN_PAGE_SIZE}`);
    setSelectedTable(id); setColumnPage(page); setColumns(response.items); setColumnTotal(response.total); setResults([]);
  }

  async function search() {
    if (!projectId) return;
    const response = await apiPost<{ items: CatalogSearchItem[] }>(`/projects/${projectId}/catalog/search`, {
      query, datasource_ids: datasourceId ? [Number(datasourceId)] : [], schema_names: schemaName ? [schemaName] : [], top_k: 50,
    });
    setResults(response.items); setMessage(`找到 ${response.items.length} 个目录字段`);
  }

  async function importColumn(id: number, type: "source" | "mart") {
    await apiPost(`/catalog/columns/${id}/import-as-${type}-field`, {});
    setMessage(type === "source" ? "已导入来源层" : "已导入监管集市层");
    if (results.length) await search();
  }

  async function showProfileHistory(columnId: number) {
    const items = await apiGet<ColumnProfileSnapshot[]>(`/catalog/columns/${columnId}/profiles`);
    setProfileHistory({ columnId, items });
  }

  const displayedColumns: CatalogSearchItem[] = results.length ? results : columns.map((column) => ({
    catalog_column_id: column.id, datasource_id: column.datasource_id, datasource_name: "", schema_name: column.schema_name,
    table_name: column.table_name, column_name: column.column_name, column_comment: column.column_comment,
    data_type: column.data_type, nullable: column.nullable, is_primary_key: column.is_primary_key, score: 0, match_reasons: [],
  }));

  return (
    <main>
      <WorkspaceHeader title="项目数据目录" meta={`${schemas.length} 个 schema / ${tableTotal} 张目录表`} />
      <div className="mx-auto max-w-[1600px] space-y-5 p-4 lg:p-6">
        <section className="panel flex flex-wrap items-center gap-2 p-4">
          <select
            className="control max-w-56"
            onChange={(event) => { setDatasourceId(event.target.value); setSchemaName(""); setTablePage(1); }}
            value={datasourceId}
          >
            <option value="">全部数据源</option>
            {datasources.map((item) => (
              <option key={item.id} value={item.id}>{item.name}</option>
            ))}
          </select>
          <input
            className="control min-w-64 flex-1"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索表名、字段名或中文注释"
            value={query}
          />
          <button className="button-primary" onClick={search}>
            <Search size={16} />
            搜索目录
          </button>
        </section>

        {message ? (
          <p className="rounded-lg border border-line bg-white px-3 py-2 text-sm text-slate-600">{message}</p>
        ) : null}

        <div className="grid gap-5 xl:grid-cols-[220px_380px_1fr]">
          <section className="panel h-fit overflow-hidden">
            <div className="panel-header">
              <h2 className="text-[15px] font-semibold text-ink">Schema 树</h2>
            </div>
            <div className="space-y-1.5 p-3">
              <button
                className={`block w-full rounded-lg border px-3 py-2 text-left text-sm transition ${!schemaName ? "border-pine bg-pine-50 text-pine-700" : "border-line bg-white hover:bg-mist"}`}
                onClick={() => { setSchemaName(""); setTablePage(1); }}
              >
                全部 schema
              </button>
              {schemas.map((schema) => (
                <button
                  className={`block w-full rounded-lg border px-3 py-2 text-left text-sm transition ${schemaName === schema.schema_name ? "border-pine bg-pine-50 text-pine-700" : "border-line bg-white hover:bg-mist"}`}
                  key={schema.id}
                  onClick={() => { setSchemaName(schema.schema_name); setTablePage(1); }}
                >
                  {schema.schema_name}
                </button>
              ))}
            </div>
          </section>

          <section className="panel h-fit overflow-hidden">
            <div className="panel-header">
              <h2 className="text-[15px] font-semibold text-ink">表列表</h2>
            </div>
            {tables.length ? (
              <div className="space-y-1.5 p-3">
                {tables.map((table) => (
                  <button
                    className={`block w-full rounded-lg border px-3 py-2 text-left text-sm transition ${selectedTable === table.id ? "border-pine bg-pine-50 text-pine-700" : "border-line bg-white hover:bg-mist"}`}
                    key={table.id}
                    onClick={() => openTable(table.id)}
                  >
                    <strong>{table.schema_name}.{table.table_name}</strong>
                    <div className="text-xs text-slate-500">{table.table_comment || table.table_type}</div>
                  </button>
                ))}
              </div>
            ) : (
              <div className="empty-state m-3">
                <Table2 className="text-slate-300" size={28} />
                <p>当前筛选下暂无目录表，试试切换数据源或 schema</p>
              </div>
            )}
            <Pagination page={tablePage} pageSize={TABLE_PAGE_SIZE} total={tableTotal} onPage={(page) => setTablePage(page)} />
          </section>

          <section className="panel h-fit overflow-hidden">
            <div className="panel-header">
              <h2 className="text-[15px] font-semibold text-ink">字段（按表懒加载）</h2>
            </div>
            {displayedColumns.length ? (
              displayedColumns.map((column) => (
                <div className="border-b border-line p-4 text-sm last:border-0" key={column.catalog_column_id}>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <strong>{column.table_name}.{column.column_name}</strong>
                      <div className="mt-1 text-slate-500">
                        {column.column_comment || "无注释"} / {column.data_type || "类型未知"} / {column.nullable ? "可空" : "非空"}
                        {column.is_primary_key ? " / 主键" : ""}
                      </div>
                      {column.match_reasons.length ? (
                        <div className="mt-1 text-xs text-slate-500">
                          评分 {Math.round(column.score * 100)}% · {column.match_reasons.join("、")}
                        </div>
                      ) : null}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <button className="button-secondary" onClick={() => showProfileHistory(column.catalog_column_id)}>
                        <Clock3 size={14} />
                        探查历史
                      </button>
                      <button className="button-secondary" onClick={() => importColumn(column.catalog_column_id, "source")}>
                        <Download size={14} />
                        来源层
                      </button>
                      <button className="button-secondary" onClick={() => importColumn(column.catalog_column_id, "mart")}>
                        <DatabaseZap size={14} />
                        集市层
                      </button>
                    </div>
                  </div>
                  {profileHistory?.columnId === column.catalog_column_id ? <ProfileHistory items={profileHistory.items} /> : null}
                </div>
              ))
            ) : (
              <div className="empty-state m-3">
                <Columns3 className="text-slate-300" size={28} />
                <p>选择左侧的表，或搜索表名、字段名后在这里查看目录字段</p>
              </div>
            )}
            {selectedTable && !results.length ? (
              <Pagination page={columnPage} pageSize={COLUMN_PAGE_SIZE} total={columnTotal} onPage={(page) => openTable(selectedTable, page)} />
            ) : null}
          </section>
        </div>
      </div>
    </main>
  );
}

function Pagination({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="flex items-center justify-between border-t border-line p-3 text-xs text-slate-500">
      <button className="button-secondary" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        上一页
      </button>
      <span>{page} / {pages}（{total}）</span>
      <button className="button-secondary" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        下一页
      </button>
    </div>
  );
}

function ProfileHistory({ items }: { items: ColumnProfileSnapshot[] }) {
  if (!items.length) {
    return <p className="mt-3 rounded-lg border border-line bg-white px-3 py-2 text-sm text-slate-600">暂无探查历史</p>;
  }
  return (
    <div className="mt-3 space-y-2 rounded-lg border border-line bg-mist/60 p-3 text-xs text-slate-600">
      {items.map((item) => (
        <div key={item.id}>
          <strong>{new Date(item.profile_date).toLocaleString()}</strong> · total {item.total_count ?? "-"} · null rate {item.null_rate ?? "-"} · distinct {item.distinct_count ?? "-"}
        </div>
      ))}
    </div>
  );
}
