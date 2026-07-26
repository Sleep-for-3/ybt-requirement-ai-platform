"use client";

import { BrainCircuit, GitBranch, Landmark, LogIn, PackageCheck, ShieldAlert } from "lucide-react";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { apiPost, saveSession } from "@/lib/api";

const HIGHLIGHTS = [
  { icon: BrainCircuit, title: "AI 口径起草", text: "结合知识库与元数据，自动生成字段级业务口径草稿" },
  { icon: GitBranch, title: "双层血缘追溯", text: "业务系统到集市、集市到一表通的映射全程留痕" },
  { icon: PackageCheck, title: "一键交付导出", text: "口径与技术溯源 Excel 按模板校验后正式交付" }
];

export default function LoginPage() {
  const router = useRouter();
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setMessage("");
    try {
      const session = await apiPost<{ access_token: string; refresh_token: string }>("/auth/login", {
        username: form.get("username"),
        password: form.get("password")
      });
      saveSession(session.access_token, session.refresh_token);
      router.replace("/projects");
    } catch {
      setMessage("用户名或密码错误");
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-screen bg-mist">
      <aside className="relative hidden w-[46%] flex-col justify-between overflow-hidden bg-gradient-to-br from-[#0f2620] via-[#113129] to-[#0a1b16] p-10 text-white lg:flex">
        <div aria-hidden className="pointer-events-none absolute -right-32 -top-32 h-96 w-96 rounded-full bg-pine-500/20 blur-3xl" />
        <div aria-hidden className="pointer-events-none absolute -bottom-40 -left-24 h-96 w-96 rounded-full bg-pine-400/10 blur-3xl" />

        <div className="relative flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-pine-500 shadow-lg shadow-pine-950/50">
            <Landmark size={20} />
          </span>
          <div>
            <div className="text-sm font-semibold">一表通口径平台</div>
            <div className="text-xs text-emerald-100/60">YBT Requirement AI Platform</div>
          </div>
        </div>

        <div className="relative">
          <h1 className="max-w-md text-3xl font-semibold leading-snug tracking-tight">
            银行一表通字段级口径
            <br />
            智能辅助平台
          </h1>
          <p className="mt-4 max-w-md text-sm leading-relaxed text-emerald-100/70">
            围绕监管报送的字段口径协作：从需求模板、数据资产到口径生成、评审与交付，一站式完成。
          </p>
          <ul className="mt-8 space-y-4">
            {HIGHLIGHTS.map((item) => (
              <li className="flex items-start gap-3" key={item.title}>
                <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white/10">
                  <item.icon size={16} className="text-pine-300" />
                </span>
                <div>
                  <div className="text-sm font-medium">{item.title}</div>
                  <div className="mt-0.5 text-xs leading-relaxed text-emerald-100/60">{item.text}</div>
                </div>
              </li>
            ))}
          </ul>
        </div>

        <div className="relative flex items-center gap-2 text-xs text-emerald-100/45">
          <ShieldAlert size={14} />
          仅限脱敏模拟数据环境，禁止录入真实银行数据
        </div>
      </aside>

      <section className="flex flex-1 items-center justify-center p-6">
        <form className="w-full max-w-sm" onSubmit={login}>
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-pine text-white shadow-md">
              <Landmark size={20} />
            </span>
            <div>
              <div className="text-sm font-semibold text-ink">一表通口径平台</div>
              <div className="text-xs text-slate-500">YBT Requirement AI Platform</div>
            </div>
          </div>

          <h2 className="text-2xl font-semibold tracking-tight text-ink">登录协作工作台</h2>
          <p className="mt-2 text-sm text-slate-500">使用机构管理员分配的本地账号登录</p>

          <div className="mt-8 space-y-4">
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-ink">用户名</span>
              <input autoComplete="username" className="control" name="username" placeholder="请输入用户名" required />
            </label>
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-ink">密码</span>
              <input autoComplete="current-password" className="control" name="password" placeholder="请输入密码" required type="password" />
            </label>
            <button className="button-primary h-10 w-full" disabled={busy} type="submit">
              <LogIn size={16} />
              {busy ? "登录中…" : "登录"}
            </button>
          </div>

          {message ? (
            <p className="mt-4 rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-sm text-coral-700">{message}</p>
          ) : null}

          <p className="mt-8 text-center text-xs text-slate-400">默认使用 Mock LLM，无需真实模型密钥</p>
        </form>
      </section>
    </main>
  );
}
