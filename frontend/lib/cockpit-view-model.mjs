export function cockpitErrorState(error) {
  const status = Number(error?.status || 0);
  if (status === 401) return { kind: "forbidden", title: "登录已失效", description: "请重新登录后查看监管驾驶舱。" };
  if (status === 403) return { kind: "forbidden", title: "没有机构驾驶舱权限", description: "当前账号未获得机构驾驶舱查看能力。" };
  if (status === 0 || error?.errorCode === "network_error") return { kind: "error", title: "无法连接服务", description: "暂时无法连接后端服务，请稍后重试。" };
  if (status === 500) return { kind: "error", title: "驾驶舱数据计算失败", description: "服务端未能完成机构数据聚合，请携带追踪编号联系平台管理员。" };
  if (status === 404) return { kind: "error", title: "驾驶舱服务不可用", description: "当前运行的后端版本未提供驾驶舱接口，请检查发布版本。" };
  return { kind: "error", title: "驾驶舱加载失败", description: error?.message || "暂时无法读取机构驾驶舱。" };
}
