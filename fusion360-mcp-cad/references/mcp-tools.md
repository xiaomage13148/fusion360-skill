# Fusion360 MCP 工具参考

> 本文件基于对**实际运行中的 MCP 服务**调用 `tools/list` 返回的真实定义整理。
> 服务信息：`http://127.0.0.1:27182/mcp`，serverInfo = **MCP Server Adapter 1.0.0**。
> 适配器升级后工具可能变化。用 `scripts/check_mcp_server.py --tools --detail` 查看概览，或用 `--tools --json` 获取完整 schema 后核对本文件。

## 服务配置

| 项 | 值 |
|---|---|
| 服务名 | Fusion360 MCP Server（MCP Server Adapter） |
| 端点 | `http://127.0.0.1:27182/mcp` |
| 传输 | HTTP（Streamable HTTP / JSON-RPC 2.0） |
| 实测 serverInfo | `MCP Server Adapter 1.0.0` |
| 前置条件 | Fusion 360 已启动且 MCP 插件已加载 |

## 架构要点（必读）

该服务**不提供** `fusion_extrude`、`fusion_hole`、`fusion_measure` 这类单一建模工具，只暴露 4 个通用工具：

| 工具 | 用途 | 必填参数 |
|---|---|---|
| `fusion_mcp_read` | 只读查询：API 文档 / 视口截图 / 文档 / 项目 / 活动命令 | `queryType` |
| `fusion_mcp_execute` | 执行 Python 脚本，或打开/关闭/保存文档 | `featureType`、`object` |
| `fusion_mcp_update` | 撤销 / 重做最近一次操作 | `featureType` |
| `fusion_mcp_electronics_read` | 读取原理图 / PCB / 库数据（需活动 Electronics 文档） | `entity_type` |

**所有实体建模都通过 `fusion_mcp_execute` + `featureType: "script"` 执行 Python 脚本完成**（Fusion API：`adsk.core`、`adsk.fusion`）。由此得出三条硬规则：

1. 「一次调用执行一个特征」= 一段脚本里**只创建一个 Fusion 特征**。
2. 写任何建模脚本前，先用 `apiDocumentation` 查询查清目标 API 的类、方法与属性。
3. 只读校验（尺寸读取、截图、文档查询）不属于建模特征，可在任意时刻单独执行。

## 1. fusion_mcp_read（只读查询）

`queryType` 为必填参数，取值如下：

| queryType | 用途 | 主要附加参数 | 返回 |
|---|---|---|---|
| `apiDocumentation` | 查询 Fusion API 类 / 成员文档 | `searchPattern`（正则）、`apiCategory`、`filter` | classes（含成员概览）、members（完整描述） |
| `screenshot` | 捕获活动视口 PNG | `direction`、`width`、`height`、`antiAliasing`、`transparentBackground` | `{"type":"image","mimeType":"image/png","base64Data":"..."}` |
| `document` | 文档查询 | `operation`：`search`/`open`/`recent`，`name`，`project` | results 列表（名称、id 与状态字段） |
| `projects` | 列出当前 hub 全部项目 | 无 | projects 列表（name、id） |
| `activeCommand` | 读取当前命令对话框的输入值 | 无 | activeCommand 对象，无命令时为 null |

### screenshot（视觉校验主通道）

- `direction` 枚举：`current`、`front`、`back`、`top`、`bottom`、`left`、`right`、`iso-top-left`、`iso-top-right`、`iso-bottom-left`、`iso-bottom-right`。
- **正交等轴测校验视图使用 `iso-top-left`（或 `iso-top-right`）**；需要保持当前视角时用 `current`。
- `width` / `height`：32–4096 px，默认取画布尺寸。
- `antiAliasing` 默认 `true`；`transparentBackground` 默认 `true`（校验截图建议设为 `false`，便于观察轮廓）。
- 返回 base64 编码 PNG。视觉模型直接分析图像；非视觉模型将图像交付用户人工确认。

### apiDocumentation（写脚本前必查）

- `searchPattern`：正则表达式，匹配 API 类名或成员名（如 `"Extrude"`、`"createSketch"`）。
- `apiCategory`：`class`（查类名）、`member`（查属性/函数/枚举值名）、`description`（搜索描述文本）、`all`。
- `filter`：点分命名空间限定，如 `adsk.fusion`（整个命名空间）或 `adsk.fusion.Extrude`（单个类）。
- 返回中 classes 给出属性/函数清单与简短说明，members 给出完整描述；先用 class 概览定位，再查具体成员。

### document

- `operation: "search"`：按 `name` 模糊匹配（不区分大小写），`project` 可选（省略则搜索全部项目）；返回 `{"results": [{"name": ..., "id": ...}]}`。
- `operation: "open"`：列出当前已打开文档，实测返回字段：`id`、`name`、`isActive`、`isModified`、`isReadOnly`、`isSaved`、`parentFolder`、`parentProject`、`parentProjectId`。
- `operation: "recent"`：列出最近文档。
- 查到的 `id` 可直接作为 `fusion_mcp_execute` 的 `object.fileId` 使用。
- 实测响应结构（MCP 标准）：`result.content[0].type = "text"`，`.text` 为 JSON 字符串（如 `{"success": true, "projects": [...]}`）。

### activeCommand

- 返回当前命令对话框的 id、name、tooltip 及全部可见输入值：`value`/`angle`（含 expression）、`checkbox`、`dropdown`、`selection`（含 selectionCount 与 selectionPoint）、`string`、`table`、`other`。
- `isDefaultCommand: true` 表示当前是会话默认命令（无交互对话框）。
- 用途：在交互式命令进行中读取用户当前参数状态，避免与用户手工操作冲突。

> 注：`searchPattern` 的字段描述中提到了 `materialLibraries` 查询，但该值未出现在 `queryType` 枚举中。以服务实际响应为准。

## 2. fusion_mcp_execute（执行）

`featureType` 为必填参数：`script` 或 `document`。

### featureType = "script"（建模主通道）

```json
{
  "featureType": "script",
  "object": { "script": "import adsk.core, adsk.fusion\n\ndef run(_context: str):\n    ..." }
}
```

服务端强制要求：

- 脚本必须定义入口函数 `def run(_context: str):`，执行时被调用。
- 使用 Fusion API（`adsk.core`、`adsk.fusion` 等）。
- 脚本内 `print()` 的内容作为工具输出返回——**尺寸测量结果靠 print 输出**。
- **不要用 try/except 捕获异常**：异常信息是判断失败原因的关键，捕获后无法定位问题。
- 建议流程：先查 API 文档 → 写脚本 → 执行 → 用读取/截图确认结果。

### featureType = "document"

| operation | 必填参数 | 说明 |
|---|---|---|
| `open` | `object.fileId` | 打开文档；fileId 由 read 的 `document` 查询（`search`）获得 |
| `close` | `userConfirmedSaveAndClose` **或** `userConfirmedCloseWithoutSave` | 有未保存改动时必须先征询用户，二选一 |
| `save` | 无 | **除用户明确要求保存外，不要调用** |

## 3. fusion_mcp_update（撤销 / 重做）

`featureType`：`undo` 或 `redo`。

- 成功：`{"success": true, "message": "...", "canUndo": bool, "canRedo": bool}`
- 失败：`{"success": false, "error": "Nothing to undo"}`；交互式/预览状态下不可撤销（优雅失败）
- 撤销对象是**最近一次已提交事务**（创建特征、删除、编辑等）。
- **这是失败恢复的核心工具**：几何报错时只对当前这一步执行 `undo`，之前已完成并确认的特征全部保留。

## 4. fusion_mcp_electronics_read（电子设计数据）

仅在存在活动 Electronics 文档时可用，用于读取原理图 / PCB / 库数据。

- `entity_type`（必填）：`electronics.<Class>`，共 49 种，覆盖：
  - 原理图类：`Schematic`、`Sheet`、`Net`、`Bus`、`Wire`、`Segment`、`Junction`、`Label`、`Part`、`Instance`、`Gate`、`Pin`、`PinRef`、`Port`、`PortRef`、`Module`、`ModuleInstance`、`Symbol`、`Variant`、`VariantDef`、`Technology`
  - PCB 类：`Board`、`Signal`、`Layer`、`Pad`、`Smd`、`Via`、`Hole`、`PolyPour`、`PolyShape`、`PolyCutout`、`Spline`、`Dimension`、`Element`、`Error`、`NetClass`、`Package`、`Package3D`、`Contact`、`ContactRef`
  - 通用类：`Attribute`、`Library`、`Device`、`DeviceSet`、`Frame`、`Grid`、`Circle`、`Rectangle`、`Text`
- `object`（可选）：
  - `fields`：要返回的列名，省略则返回全部列
  - `filters`：`[{"property": "...", "op": "eq", "value": ...}]`，字符串属性只能用 `eq`；整数/数值属性可用 `lt`/`gt`，但需该属性在 schema 资源中声明支持
  - `pagination`：`{"limit": 100, "offset": 0}`，limit 默认 100、上限 1000；响应中 `hasMore` 为 true 时用 `nextOffset` 取下一页
- 发现资源：`resource://mcp.electronics_entity_types`（全部类型）、`resource://mcp.electronics_schema_<class>`（该类的属性与过滤操作符）

## 典型调用序列

### 单特征闭环（核心流程）

```
1) 查 API     fusion_mcp_read    { "queryType": "apiDocumentation", "searchPattern": "Extrude",
                                   "apiCategory": "class", "filter": "adsk.fusion" }
2) 建特征     fusion_mcp_execute { "featureType": "script",
                                   "object": { "script": "<只创建 1 个特征的脚本>" } }
3) 读尺寸     fusion_mcp_execute { "featureType": "script",
                                   "object": { "script": "<print 包围盒/体积/关键尺寸的脚本>" } }
4) 截图       fusion_mcp_read    { "queryType": "screenshot", "direction": "iso-top-left" }
5) 失败回退   fusion_mcp_update  { "featureType": "undo" }
```

### 会话准备与收尾

```
fusion_mcp_read     { "queryType": "projects" }                          # 连通性与项目确认
fusion_mcp_read     { "queryType": "document", "operation": "open" }     # 查看已打开文档
fusion_mcp_execute  { "featureType": "document",
                      "object": { "operation": "open", "fileId": "..." } } # 打开目标文档
```

### 建模脚本骨架（示意，API 以 apiDocumentation 查询结果为准）

```python
import adsk.core
import adsk.fusion

def run(_context: str):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent

    # 一次脚本只创建一个特征：草图与拉伸算两个特征，需分两次调用
    sketch = root.sketches.add(root.xYConstructionPlane)
    # ... 绘制轮廓（完全约束、以原点定位）...

    print("feature created: sketch name=%s" % sketch.name)
```

> 骨架仅示范 `run` 结构与输出方式；具体 API 名称、参数、枚举值必须通过 `apiDocumentation` 查询确认，不要凭记忆编写。

## 调用纪律

1. 一次 `execute/script` 只创建 **1 个**特征；禁止在一段脚本里批量创建草图、拉伸、布尔、圆角。
2. 写脚本前先查 `apiDocumentation`；API 名称、方法签名、枚举值以查询结果为准。
3. 特征创建后必须单独发起校验调用（尺寸脚本 + 截图），确认后再进入下一步，两类任务不混在同一次调用中。
4. 脚本不写 try/except；失败后用 `fusion_mcp_update` + `undo` 只回退当前这一步。
5. 除用户明确要求外，不执行 `document: save`；关闭有改动文档前必须先取得用户确认。
6. MCP 日志不要整段回灌上下文，只保留关键结果行与错误行。
