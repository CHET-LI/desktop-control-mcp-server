"""screen_capture 新能力测试：全屏带指针标记 / cursor 中心模式 / 返回坐标。

用法: .venv\\Scripts\\python.exe test_capture.py
截出的图会画上红圈指针标记，可用 view_image 人工 / 模型核对。
"""
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = SERVER_DIR + r"\.venv\Scripts\python.exe"


async def call(session, name, args):
    result = await session.call_tool(name, args)
    return result.content[0].text if result.content else str(result)


async def main() -> None:
    server_params = StdioServerParameters(command=PYTHON, args=["server.py"], cwd=SERVER_DIR)
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print("[1] 工具列表:", names)

            # 1) 全屏 + 画指针（默认）：先移动鼠标到 (1280, 600) 便于观察
            print("[2] mouse_move ->", await call(session, "mouse_move", {"x": 1280, "y": 600}))
            r = json.loads(await call(session, "screen_capture", {"region": "full"}))
            print("[3] 全屏截图:", {k: r[k] for k in ("width", "height", "scale")})
            print("    cursor:", r["cursor"])
            assert r["cursor"]["on_screenshot"] is not None, "全屏下指针应在图内"
            assert r["width"] <= 1440, "默认应缩到 <=1440 宽"
            print("[3] OK 全屏指针已标记，输出宽 =", r["width"])

            # 2) cursor 模式：以指针为中心
            r2 = json.loads(await call(session, "screen_capture", {"region": "cursor"}))
            print("[4] cursor模式截图:", r2["width"], "x", r2["height"], "cursor.on_screenshot =", r2["cursor"]["on_screenshot"])
            assert r2["cursor"]["on_screenshot"] is not None, "cursor模式指针应在图内"
            w, h = r2["width"], r2["height"]
            ox, oy = r2["cursor"]["on_screenshot"]
            assert abs(ox - w/2) < 40 and abs(oy - h/2) < 40, "cursor模式指针应接近图片中心"
            print("[4] OK 指针接近图中心:", (ox, oy), "图尺寸", (w, h))

            # 3) 局部截图 + 指针不在区域内
            r3 = json.loads(await call(session, "screen_capture", {"region": "0,0,200,120"}))
            print("[5] 局部小图:", r3["width"], "x", r3["height"], "cursor.on_screenshot =", r3["cursor"]["on_screenshot"])
            # 指针在 (1280,600) 不在 0,0,200,120 内 → 应为 None，且图未被缩放
            assert r3["width"] <= 200, "局部小图不应被放大"
            print("[5] OK 局部小图未放大")

            # 4) 自定义 max_width 更糊
            r4 = json.loads(await call(session, "screen_capture", {"region": "full", "max_width": 800}))
            print("[6] max_width=800 截图宽 =", r4["width"], " 指针 on_screenshot =", r4["cursor"]["on_screenshot"])
            assert r4["width"] == 800

            print("\n全部通过 ✅")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())