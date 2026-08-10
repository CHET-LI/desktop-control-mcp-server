"""OCR 语义工具端到端测试（v0.4）：find_text / ocr_all / click_text(not_found 分支)。"""
import asyncio, json, os, sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = os.path.join(_DIR, ".venv", "Scripts", "python.exe")
SERVER = os.path.join(_DIR, "server.py")


async def call(session, name, args):
    res = await session.call_tool(name, args)
    return json.loads(res.content[0].text)


async def main() -> None:
    params = StdioServerParameters(command=PYTHON, args=[SERVER])
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = await s.list_tools()
            names = [t.name for t in tools.tools]
            print("[1] 工具数:", len(names))
            assert "find_text" in names and "ocr_all" in names and "click_text" in names, names
            print("    OCR 三工具已注册 ✔")

            # 第一次 OCR 会加载 easyocr 模型（~1-3s），之后快
            print("[2] ocr_all 扫描全屏（首次加载模型，稍等）...")
            r = await call(s, "ocr_all", {"min_conf": 0.3})
            print("    识别文字数:", r["count"])
            if r["items"]:
                for it in r["items"][:3]:
                    print("     ", it["text"], "->", it["norm"])

            print("[3] find_text 找 QQ（可能 0 个，验证返回结构）...")
            r2 = await call(s, "find_text", {"text": "QQ"})
            print("     matches:", r2["count"])

            print("[4] click_text 找不到时安全返回 not_found（不点）...")
            r3 = await call(s, "click_text", {"text": "完全不存在的文字_QA_测试_9182"})
            print("     ", r3)
            assert r3["clicked"] is False

            print("PASS ✅")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())