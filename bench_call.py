"""测量完整 MCP stdio 调用链:进程启动+初始化+单次 screen_capture。"""
import asyncio, os, sys, time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = os.path.join(_DIR, ".venv", "Scripts", "python.exe")
SERVER = os.path.join(_DIR, "server.py")

async def main() -> None:
    t0 = time.perf_counter()
    params = StdioServerParameters(command=PYTHON, args=[SERVER])
    async with stdio_client(params) as (read, write):
        t1 = time.perf_counter()
        async with ClientSession(read, write) as session:
            await session.initialize()
            t2 = time.perf_counter()
            # 第一发（冷）
            r = await session.call_tool("screen_capture", {"x": 0, "y": 0, "width": 300, "height": 200})
            t3 = time.perf_counter()
            # 第二发（热，同会话）
            r2 = await session.call_tool("screen_capture", {"x": 0, "y": 0, "width": 300, "height": 200})
            t4 = time.perf_counter()
            print("stdio 连接:%.3fs init:%.3fs 冷调用:%.3fs 热调用:%.3fs" % (t1-t0, t2-t1, t3-t2, t4-t3))
            print("返回:", str(r.content[0].text)[:120])

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())