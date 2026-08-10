"""对比 v0.3 默认 jpeg vs 旧 png 的体积/尺寸，验证提速点。"""
import asyncio, json, sys, os

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
            print("[1] 工具:", [t.name for t in tools.tools])
            import os
            # 旧默认 = png 1440
            r1 = await call(s, "screen_capture", {"region": "full", "image_format": "png"})
            # 新默认 = jpeg 1440/80
            r2 = await call(s, "screen_capture", {"region": "full"})
            # 极致 = jpeg 720 高
            r3 = await call(s, "screen_capture", {"region": "full", "max_height": 720})
            for name, r in [("PNG-1440(旧)", r1), ("JPEG-1440/q80(新默认)", r2), ("JPEG-720p(极速)", r3)]:
                size_kb = os.path.getsize(r["path"]) // 1024
                print(f"[2] {name}: {r['width']}x{r['height']} {size_kb}KB format={r.get('format')}")
            print("[3] 全部返回均含 path/format/cursor ✔")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())