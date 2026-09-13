r"""用本地 Chrome（CDP）登录平台并批量截图，供系统使用文档引用。

前置：
    1) 本地能连到站点。若 DNS 被代理劫持，用 SSH 本地转发：
       ssh -N -L 127.0.0.1:18080:127.0.0.1:80 -p 42438 root@<服务器>
    2) 启动 Chrome：
       chrome.exe --headless=new --remote-debugging-port=9333 \
         --user-data-dir=%TEMP%\ybt-guide-profile --no-proxy-server \
         --host-resolver-rules="MAP <域名> 127.0.0.1:18080" --window-size=1440,900

用法：
    GUIDE_USER=xxx GUIDE_PASSWORD=yyy python scripts/docs/capture_system_guide.py
"""

from __future__ import annotations

import asyncio
import base64
import itertools
import json
import os
import pathlib
import sys
import urllib.request

import websockets

CDP_PORT = int(os.getenv("CDP_PORT", "9333"))
BASE_URL = os.getenv("GUIDE_BASE_URL", "http://57008897.xyz").rstrip("/")
USERNAME = os.environ["GUIDE_USER"]
PASSWORD = os.environ["GUIDE_PASSWORD"]
OUT_DIR = pathlib.Path(os.getenv("GUIDE_OUT", "docs/assets/system-guide")).resolve()
PROJECT_ID = os.getenv("GUIDE_PROJECT_ID", "10")

PAGES: list[tuple[str, str, str]] = [
    ("01-login", "/login", "登录页"),
    ("02-workspace", "/workspace", "工作台总览"),
    ("03-projects", "/projects", "项目列表"),
    ("04-cockpit", "/cockpit", "驾驶舱"),
    ("05-work", "/work", "需求工作台"),
    ("06-fields", "/fields", "业务字段"),
    ("07-knowledge", "/knowledge", "知识库总览"),
    ("08-knowledge-documents", "/knowledge/documents", "知识文档与解析"),
    ("09-knowledge-search", "/knowledge/search", "混合检索"),
    ("10-knowledge-ask", "/knowledge/ask", "知识问答"),
    ("11-datasources", "/datasources", "数据源"),
    ("12-catalog", "/catalog", "元数据目录"),
    ("13-lineage", "/lineage", "血缘"),
    ("14-review-tasks", "/review-tasks", "审核任务"),
    ("15-deliverables", "/deliverables", "交付包"),
    ("16-uat", "/uat", "UAT 验收"),
    ("17-jobs", "/jobs", "后台任务"),
    ("18-admin-users", "/admin/users", "机构与用户管理"),
    ("19-admin-health", "/admin/system-health", "系统健康"),
    ("20-model-profiles", "/model-profiles", "模型档案"),
]

# 需要先做一次交互再截图才有内容的页面：(placeholder, 输入内容, 按钮文案)
PAGE_ACTIONS: dict[str, tuple[str, str, str]] = {
    "09-knowledge-search": ("输入字段、口径或监管问题关键词", "借记卡客户证件类型 CERT_TYPE", "检索"),
    "10-knowledge-ask": ("例如：客户证件类型取哪个字段？", "借记卡客户证件类型取哪个字段", "提问"),
}


class Page:
    def __init__(self, ws, session_id: str, pending: dict[int, asyncio.Future], ids: itertools.count) -> None:
        self._ws = ws
        self._session = session_id
        self._pending = pending
        self._ids = ids

    async def call(self, method: str, params: dict | None = None) -> dict:
        message_id = next(self._ids)
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[message_id] = future
        await self._ws.send(json.dumps({
            "id": message_id, "method": method, "params": params or {}, "sessionId": self._session,
        }))
        response = await asyncio.wait_for(future, timeout=90)
        if "error" in response:
            raise RuntimeError(json.dumps(response["error"]))
        return response.get("result", {})

    async def evaluate(self, expression: str):
        result = await self.call("Runtime.evaluate", {
            "expression": expression, "awaitPromise": True, "returnByValue": True,
        })
        return result.get("result", {}).get("value")

    async def goto(self, path: str, settle: float = 3.0) -> None:
        await self.call("Page.navigate", {"url": f"{BASE_URL}{path}"})
        for _ in range(60):
            await asyncio.sleep(0.5)
            state = await self.evaluate("document.readyState")
            if state == "complete":
                break
        await asyncio.sleep(settle)

    async def screenshot(self, name: str, max_height: int = 2600) -> pathlib.Path:
        metrics = await self.call("Page.getLayoutMetrics")
        size = metrics.get("cssContentSize") or metrics.get("contentSize") or {}
        width = int(size.get("width") or 1440)
        height = min(int(size.get("height") or 900), max_height)
        data = await self.call("Page.captureScreenshot", {
            "format": "png",
            "captureBeyondViewport": True,
            "clip": {"x": 0, "y": 0, "width": width, "height": height, "scale": 1},
        })
        target = OUT_DIR / f"{name}.png"
        target.write_bytes(base64.b64decode(data["data"]))
        return target


async def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    version = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/version").read())
    async with websockets.connect(version["webSocketDebuggerUrl"], max_size=200 * 1024 * 1024) as ws:
        ids = itertools.count(1)
        pending: dict[int, asyncio.Future] = {}

        async def pump() -> None:
            async for raw in ws:
                message = json.loads(raw)
                future = pending.pop(message.get("id"), None)
                if future is not None:
                    future.set_result(message)

        pump_task = asyncio.create_task(pump())

        async def browser_call(method: str, params: dict | None = None) -> dict:
            message_id = next(ids)
            future: asyncio.Future = asyncio.get_running_loop().create_future()
            pending[message_id] = future
            await ws.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
            response = await asyncio.wait_for(future, timeout=90)
            if "error" in response:
                raise RuntimeError(response["error"])
            return response.get("result", {})

        target = await browser_call("Target.createTarget", {"url": "about:blank"})
        attached = await browser_call("Target.attachToTarget", {"targetId": target["targetId"], "flatten": True})
        page = Page(ws, attached["sessionId"], pending, ids)
        await page.call("Page.enable")
        await page.call("Runtime.enable")
        await page.call("Emulation.setDeviceMetricsOverride", {
            "width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False,
        })

        # 1) 登录页
        await page.goto("/login", settle=2.5)
        login_shot = await page.screenshot("01-login")
        print(f"captured {login_shot.name}")

        # 2) 登录（用原生 setter 触发 React 受控输入）
        await page.evaluate(
            """(() => {
                const setValue = (el, value) => {
                    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                    setter.call(el, value);
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                };
                const inputs = [...document.querySelectorAll('input')];
                setValue(inputs[0], %s);
                setValue(inputs[1], %s);
                const button = [...document.querySelectorAll('button')].find((b) => b.textContent.includes('登录'));
                if (button) button.click();
                return inputs.length;
            })()""" % (json.dumps(USERNAME), json.dumps(PASSWORD))
        )
        for _ in range(40):
            await asyncio.sleep(0.5)
            if "/login" not in await page.evaluate("location.pathname"):
                break
        await asyncio.sleep(3)
        print("after login:", await page.evaluate("location.pathname"))

        # 3) 逐页截图（带 projectId，保证页面有真实数据）
        only = {item for item in os.getenv("GUIDE_ONLY", "").split(",") if item}
        for name, path, _title in PAGES:
            if only and name not in only:
                continue
            separator = "&" if "?" in path else "?"
            await page.goto(f"{path}{separator}projectId={PROJECT_ID}", settle=3.5)
            action = PAGE_ACTIONS.get(name)
            if action:
                placeholder, value, label = action
                await page.evaluate(
                    """(() => {
                        const setValue = (el, v) => {
                            const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                            setter.call(el, v);
                            el.dispatchEvent(new Event('input', { bubbles: true }));
                        };
                        const input = [...document.querySelectorAll('input')].find((i) => i.placeholder === %s);
                        if (!input) return 'no-input';
                        setValue(input, %s);
                        const button = [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === %s);
                        if (!button) return 'no-button';
                        button.click();
                        return 'clicked';
                    })()""" % (json.dumps(placeholder), json.dumps(value), json.dumps(label))
                )
                await asyncio.sleep(float(os.getenv("GUIDE_ACTION_WAIT", "9")))
            shot = await page.screenshot(name)
            print(f"captured {shot.name} ({shot.stat().st_size // 1024} KB)")

        pump_task.cancel()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
