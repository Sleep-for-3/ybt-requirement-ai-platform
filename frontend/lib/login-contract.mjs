export function loginErrorMessage(error) {
  if (error?.status === 401) return "用户名或密码错误";
  if (error?.status === 0) return "无法连接登录服务，请检查连接后重试。";
  if (error?.status === 429) return "登录请求过于频繁，请稍后重试。";
  return "登录服务暂不可用，请稍后重试。";
}
