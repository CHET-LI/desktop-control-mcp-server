"""desktop-mcp-server 端到端测试：启动 server → 列工具 → 真实调用无副作用工具。"""
import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = SERVER_DIR + r"\.venv\Scripts\python.exe"


async def main() -> None:
    server_params = StdioServerParameters(
        command=PYTHON,
        args=["server.py"],
        cwd=SERVER_DIR,
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print("[1] 工具列表:", names)

            for name, args in [("screen_size", {}), ("mouse_position", {})]:
                result = await session.call_tool(name, args)
                text = result.content[0].text if result.content else str(result)
                print(f"[2] {name}() 返回: {text}")

            # 截一小块图（左上角 200x120），验证 screen_capture 真实可用
            result = await session.call_tool("screen_capture", {"x": 0, "y": 0, "width": 200, "height": 120})
            text = result.content[0].text if result.content else str(result)
            print(f"[3] screen_capture(0,0,200,120) 返回: {text}")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())
