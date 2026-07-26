import { ArrowRight, Cpu, FileText, FlaskConical, GitBranch, MessagesSquare, Search } from "lucide-react";
import Link from "next/link";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";

const SECTIONS = [
  { icon: FileText, title: "文档管理", href: "/knowledge/documents", text: "上传监管制度与答疑文档，管理版本、去重与解析状态" },
  { icon: Search, title: "混合检索", href: "/knowledge/search", text: "结构化过滤、关键词与向量得分融合，规则重排定位证据" },
  { icon: MessagesSquare, title: "有证据问答", href: "/knowledge/ask", text: "无证据不下确定结论，引用必须对应真实知识单元" },
  { icon: Cpu, title: "模型配置", href: "/model-profiles", text: "管理模型档位、调用参数与脱敏约束" },
  { icon: GitBranch, title: "Prompt 版本", href: "/prompt-versions", text: "Prompt 模板的版本管理、发布与回滚" },
  { icon: FlaskConical, title: "RAG 评测", href: "/evaluations", text: "批量评测检索与问答质量，沉淀评测用例" }
];

export default function Page() {
  return (
    <main>
      <WorkspaceHeader title="企业监管知识库" meta="结构化知识、混合 RAG 与可验证引用" />
      <div className="mx-auto grid max-w-5xl gap-4 p-4 md:grid-cols-3 lg:p-6">
        {SECTIONS.map((item) => (
          <Link className="panel group flex flex-col p-5 transition hover:shadow-pop" href={item.href} key={item.href}>
            <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-pine-50 text-pine-600">
              <item.icon size={18} />
            </span>
            <h2 className="mt-3 text-[15px] font-semibold text-ink">{item.title}</h2>
            <p className="mt-1 flex-1 text-sm leading-relaxed text-slate-500">{item.text}</p>
            <span className="mt-4 inline-flex items-center gap-1 border-t border-line pt-3 text-sm font-medium text-pine-600 transition group-hover:text-pine-700">
              进入
              <ArrowRight size={15} />
            </span>
          </Link>
        ))}
      </div>
    </main>
  );
}
