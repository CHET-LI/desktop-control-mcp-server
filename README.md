# Desktop Control MCP Server（系统级键鼠）

给 QwenPaw 任意 agent（default 等）提供**真实系统级键鼠操控**能力，Computer Agent 风格：
**看屏（view_image）→ 思考 → 真实操控鼠标键盘**。

## 核心能力

### v0.4 · OCR 语义点击：模型再也不用算坐标

**背景（用户痛点）**：agent 即使配了 `normalized=True`，仍要**目测截图里的坐标**并换算成
[0,1]/[0,999]，缩放/DPI/小字时容易点偏（用户反馈"点的，不准确"）。

**方案**：采用业界 CUA（Computer-Use Agent）的 Grounding 思路——模型（Worker）**只描述语义动作**
（"点那个'发送'按钮"），Grounding 阶段用 **OCR** 找出文字位置自动换算坐标——**模型从头到尾不碰像素**。

新增 3 个 OCR 语义工具（旧 13 个 100% 兼容）：

| 工具 | 说明 |
|------|------|
| `ocr_all(min_conf=0.3)` | OCR 扫描全屏，返回所有文字及坐标（text / raw 物理像素 / norm 归一化 / conf / bbox）——摸清界面 |
| `find_text(text)` | 找包含该文字的所有位置（不点击），返回同上结构 |
| `click_text(text, index=0)` | 【语义点击】直接按文字点击，**完全不用算坐标**——找不到返回 not_found 不点 |

**推荐用法（覆盖之前的"看图标→估算坐标"流程）**：
1. 知道要点什么文字 → 直接 `click_text("发送")` / `click_text("确认")`（首选，最准）
2. 想先摸清界面 → `ocr_all()` 看全部文字+坐标 → 再 `click_text(...)`
3. 多个同名匹配 → `find_text("保存")` 看 count → `click_text("保存", index=1)` 选第二个
4. 只有图标/图形无文字时，才退回截图目测 + `mouse_click(normalized=True)`

**技术细节**：
- easyocr 中英双语（`~/.EasyOCR/model` 已缓存 craft_mlt_25k + zh_sim_g2）
- reader **主线程预热**（`__main__` 里 prewarm）——torch/easyocr 首次初始化在 MCP worker 线程会卡死（实测）
- readtext 输入必须 `np.array(img)`（easyocr 不支持直接传 PIL Image）

### v0.3 · 截图提速：小图 + JPEG

**背景（用户痛点）**：default 每次截图后"空窗 20 多秒"。实测 MCP server 端本身极快
（热调用 <0.05s），瓶颈在**喂给视觉模型的图太重**：旧默认 1440×900 **PNG 370KB/张**，
视觉模型编码推理时间 ≈ 图片 token 数，PNG 大图让模型明显更慢。

业界常用口径：截图统一缩到 ~720p 高 + JPEG q80。`screen_capture` 新增（旧调用 100% 兼容）：
1. **默认输出 JPEG**（`image_format="jpeg"`，q80）—— 同尺寸下 370KB PNG → 116KB JPEG（-69%），视觉编码更快
2. **`max_height` 限高**：设 `720` 即极速口径（2560 屏 → 1152×720，84KB，比旧 default 小 77%），
   视觉 token 最少、响应最快
3. 返回 JSON 增加 `format` 字段（"jpg" / "png"）
4. 想保留旧行为可显式传 `image_format="png"`

**实测体积对比（2560×1600 屏）**：

| 档位 | 输出 | 体积 |
|------|------|------|
| 旧默认（v0.2） | 1440×900 PNG | 370KB |
| 新默认 `jpeg` | 1440×900 JPEG q80 | 116KB |
| 极速 `jpeg + max_height=720` | 1152×720 JPEG q80 | 84KB |

**推荐用法**：日常操控用默认 `screen_capture()`（jpeg 116KB）即可；
要最快反馈（连点、验证按钮）用 `screen_capture(max_height=720)`；
只有需要看清小字（图标名/代码）时才 `image_format="png"` 或放大 max_width。

### v0.2 · 坐标抽象与安全

1. **Windows DPI 感知**：高分屏（125%/150% 缩放）下 pyautogui 坐标不再错位
2. **坐标归一化抽象层**：所有鼠标工具新增 `normalized` 参数——
   `normalized=True` 时 x/y 接受视觉模型习惯的抽象坐标 **[0,999] 整数 或 [0,1] 浮点**，
   由 server 自动投影到物理像素，模型不用知道屏幕分辨率
3. **边缘内缩 4px**：归一化坐标自动避开屏幕热角 / FAILSAFE 触发区
4. **easeOutQuad 缓动**平滑移动 + 点击前先平滑到位（模拟人手）
5. **全局串行锁**：多 agent 并发调键鼠时排队，避免互相抢鼠标

## 与 screen-control skill 的关系

- 底层完全复用已验证的 `pyautogui`（真实输入注入，非浏览器 CDP 模拟）
- 之前 agent 走「读 SKILL.md → 拼命令 → execute_shell_command」链条太长、易迷路
- 现在封装成 **MCP 原生工具**：agent 直接调用，不用拼命令，不会陷入自我增强循环

## 注册信息（default workspace drivers/mcp/desktop_control.yaml）

- 命令: `<workspace>\desktop-mcp-server\.venv\Scripts\python.exe server.py`（本机路径按实际替换）
- 传输: stdio，enabled=true，policy: allow
- 变更生效: 改 server.py 后 **touch drivers/mcp/desktop_control.yaml**（watcher 捡到卡片变化会刷新 driver）+ `qwenpaw daemon reload-config`；**新会话才带新工具签名**

## 工具列表（16 个）

| 工具 | 说明 |
|------|------|
| `screen_capture` | 截屏（全屏/区域/cursor 中心），**默认 JPEG** 返回图片路径 → view_image 看图 |
| `screen_size` | 屏幕分辨率 |
| `mouse_position` | 当前鼠标坐标 |
| `mouse_move` | 平滑移动鼠标（支持 normalized） |
| `mouse_click` / `mouse_double_click` / `mouse_right_click` | 左/双击/右键（支持 normalized） |
| `mouse_drag` | 拖拽（选字/移动，支持 normalized） |
| `mouse_scroll` | 滚动（支持 normalized） |
| `keyboard_write` | 键入 ASCII 文本 |
| `key_paste` | 粘贴任意文本（**支持中文**，剪贴板方案） |
| `key_press` | 单键（enter/tab/esc/方向键…） |
| `press_hotkey` | 组合键（ctrl+c / alt+tab…） |
| `ocr_all`（v0.4） | OCR 扫描全屏文字+坐标（不点击） |
| `find_text`（v0.4） | 找包含指定文字的位置（不点击） |
| `click_text`（v0.4） | **按文字语义点击**，不用算坐标 |

> `normalized=True` 用法示例：`mouse_click(500, 500, normalized=True)` 会点击屏幕中心
> （因为 (500,500) 在 [0,999] 坐标系下即中心）。绝对像素用法不变：`mouse_click(1281, 800)`。

## 安全规约

- `pyautogui.FAILSAFE` 开启：鼠标甩到左上角 (0,0) 可紧急中止
- 所有坐标做屏幕边界夹取，越界拒绝；归一化坐标额外做 4px 边缘内缩
- 破坏性操作（关机/关闭应用等）仍需用户确认

## 端到端测试

```bash
python test_client.py       # 基础：工具列表 / screen_size / mouse_position / screen_capture
python test_capture.py      # screen_capture 全屏指针标记 / cursor 模式 / 局部不放大 / max_width
python bench_v03.py         # v0.3 体积三档对比（PNG vs JPEG vs JPEG-720p）
python test_ocr_semantic.py # v0.4 OCR 工具（ocr_all / find_text / click_text not_found 分支）
```

## 文件

- `server.py` — MCP server 本体（v0.4：OCR 语义点击 + reader 主线程预热）
- `test_client.py` / `test_capture.py` / `test_ocr_semantic.py` — 端到端测试
- `bench_v03.py` / `bench_call.py` — 性能对比脚本
- `.venv/` — 隔离 venv（mcp==1.29.0 + easyocr + 系统 pyautogui 0.9.54）
- `shots/` — 截屏输出目录
