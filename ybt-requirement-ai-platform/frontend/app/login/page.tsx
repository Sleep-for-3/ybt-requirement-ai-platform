"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { apiPost, saveSession } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter(); const [message, setMessage] = useState("");
  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget);
    try {
      const session = await apiPost<{access_token:string;refresh_token:string}>("/auth/login", { username: form.get("username"), password: form.get("password") });
      saveSession(session.access_token, session.refresh_token); router.replace("/projects");
    } catch { setMessage("用户名或密码错误"); }
  }
  return <main className="flex min-h-screen items-center justify-center bg-slate-950 p-6"><form className="w-full max-w-md rounded-xl bg-white p-8 shadow-2xl" onSubmit={login}><div className="text-sm font-semibold text-pine">银行一表通治理平台</div><h1 className="mt-2 text-2xl font-semibold">登录协作工作台</h1><p className="mt-2 text-sm text-slate-500">使用机构管理员分配的本地账号登录</p><div className="mt-6 space-y-3"><input className="control" name="username" placeholder="用户名" autoComplete="username" required /><input className="control" type="password" name="password" placeholder="密码" autoComplete="current-password" required /><button className="button-primary w-full">登录</button></div>{message ? <p className="mt-3 text-sm text-coral">{message}</p> : null}</form></main>;
}
