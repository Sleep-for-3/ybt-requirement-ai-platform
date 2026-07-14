"use client";

import { useEffect, useState } from "react";
import { DatabaseZap, Download, Search } from "lucide-react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { CatalogColumn, CatalogSchema, CatalogSearchItem, CatalogTable, DataSource, apiGet, apiPost } from "@/lib/api";

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

  const displayedColumns: CatalogSearchItem[] = results.length ? results : columns.map((column) => ({
    catalog_column_id: column.id, datasource_id: column.datasource_id, datasource_name: "", schema_name: column.schema_name,
    table_name: column.table_name, column_name: column.column_name, column_comment: column.column_comment,
    data_type: column.data_type, nullable: column.nullable, is_primary_key: column.is_primary_key, score: 0, match_reasons: [],
  }));

  return <main>
    <WorkspaceHeader title="项目数据目录" meta={`${schemas.length} 个 schema / ${tableTotal} 张目录表`} />
    <div className="mx-auto max-w-[1600px] space-y-5 p-6">
      <section className="panel flex flex-wrap gap-2 p-4">
        <select className="control" onChange={(event) => { setDatasourceId(event.target.value); setSchemaName(""); setTablePage(1); }} value={datasourceId}><option value="">全部数据源</option>{datasources.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
        <input className="control min-w-64 flex-1" onChange={(event) => setQuery(event.target.value)} placeholder="搜索表名、字段名或中文注释" value={query} />
        <button className="button-primary" onClick={search}><Search size={16} />搜索目录</button>
      </section>
      {message ? <p className="text-sm text-slate-600">{message}</p> : null}
      <div className="grid gap-5 xl:grid-cols-[220px_380px_1fr]">
        <section className="panel p-3"><h2 className="font-semibold">Schema 树</h2><button className={`mt-2 block text-sm ${!schemaName ? "font-semibold" : ""}`} onClick={() => { setSchemaName(""); setTablePage(1); }}>全部 schema</button>{schemas.map((schema) => <button className={`mt-2 block text-left text-sm ${schemaName === schema.schema_name ? "font-semibold" : ""}`} key={schema.id} onClick={() => { setSchemaName(schema.schema_name); setTablePage(1); }}>{schema.schema_name}</button>)}</section>
        <section className="panel overflow-hidden"><div className="border-b p-3 font-semibold">表列表</div>{tables.map((table) => <button className={`block w-full border-b p-3 text-left text-sm ${selectedTable === table.id ? "bg-slate-100" : ""}`} key={table.id} onClick={() => openTable(table.id)}><strong>{table.schema_name}.{table.table_name}</strong><div className="text-xs text-slate-500">{table.table_comment || table.table_type}</div></button>)}<Pagination page={tablePage} pageSize={TABLE_PAGE_SIZE} total={tableTotal} onPage={(page) => setTablePage(page)} /></section>
        <section className="panel overflow-hidden"><div className="border-b p-3 font-semibold">字段（按表懒加载）</div>{displayedColumns.map((column) => <div className="border-b p-3 text-sm" key={column.catalog_column_id}><div className="flex items-start justify-between gap-3"><div><strong>{column.table_name}.{column.column_name}</strong><div className="mt-1 text-slate-500">{column.column_comment || "无注释"} / {column.data_type || "类型未知"} / {column.nullable ? "可空" : "非空"}{column.is_primary_key ? " / 主键" : ""}</div>{column.match_reasons.length ? <div className="mt-1 text-xs text-slate-500">评分 {Math.round(column.score * 100)}% · {column.match_reasons.join("、")}</div> : null}</div><div className="flex gap-2"><button className="button-secondary" onClick={() => importColumn(column.catalog_column_id, "source")}><Download size={14} />来源层</button><button className="button-secondary" onClick={() => importColumn(column.catalog_column_id, "mart")}><DatabaseZap size={14} />集市层</button></div></div></div>)}{selectedTable && !results.length ? <Pagination page={columnPage} pageSize={COLUMN_PAGE_SIZE} total={columnTotal} onPage={(page) => openTable(selectedTable, page)} /> : null}</section>
      </div>
    </div>
  </main>;
}

function Pagination({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return <div className="flex items-center justify-between p-3 text-xs text-slate-500"><button className="button-secondary" disabled={page <= 1} onClick={() => onPage(page - 1)}>上一页</button><span>{page} / {pages}（{total}）</span><button className="button-secondary" disabled={page >= pages} onClick={() => onPage(page + 1)}>下一页</button></div>;
}
