import { ArrowRight, Cpu, FileText, FlaskConical, GitBranch, MessagesSquare, Search } from "lucide-react";
import Link from "next/link";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";

const SECTIONS = [
  { icon: FileText, title: "文档管理", href: "/knowledge/documents", text: "阅读原文，维护知识资料与版本" },
  { icon: Search, title: "混合检索", href: "/knowledge/search", text: "根据关键词与业务含义查找证据" },
  { icon: MessagesSquare, title: "监管知识问答", href: "/knowledge/ask?mode=regulatory", text: "根据制度、答疑和已沉淀业务知识回答" },
  { icon: GitBranch, title: "数据字段与血缘问答", href: "/knowledge/ask?mode=data_field", text: "查找真实来源字段、关联与加工规则" }
];

export default function Page() {
  return (
    <main>
      <WorkspaceHeader title="知识与证据" meta="查找知识、阅读原文、核验回答依据" />
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
