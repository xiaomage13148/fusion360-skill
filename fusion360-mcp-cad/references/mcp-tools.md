# Fusion360 MCP 工具参考

> 本文件基于对**实际运行中的 MCP 服务**调用 `tools/list` / `resources/list` 返回的真实定义整理（最近核对：2026-10-09，Fusion 360 更新后重新拉取）。
> 服务信息：`http://127.0.0.1:27182/mcp`，serverInfo = **MCP Server Adapter 1.0.0**，协议版本 `2025-03-26`。
> 服务升级后工具与参数可能变化（注意：serverInfo 版本号可能不变但定义已扩展）。用 `scripts/check_mcp_server.py --tools --detail` 查看概览，或用 `--tools --json` 获取完整 schema 后核对本文件。
>
> **2026-10-09 核对结论**：4 个工具的名称、必填参数与全部枚举均**无变化**（`queryType`、`featureType`、`direction`、`apiCategory`、`operation`、`undo`/`redo`），electronics 的 50 个 `entity_type` 与 51 个资源无增删。本次变化集中在 `fusion_mcp_execute` 的 `object` 可选字段：新增 `userMessageSummary`、`title`、`extensionName`（详见 §2「其他 featureType」），并补充了 `previewImage` / `purchase` / `editImage` 的行为细节。

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
| `licensing` | 查询当前用户的许可与权益状态 | 无 | 许可摘要、服务、已激活/可购买扩展、Flex 令牌余额 |
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

### licensing（许可与权益，Fusion 更新后新增）

- 无参数，返回 `{success, queryType:"licensing", licenseTypeSummary, summary, services, activeExtensions, purchasableExtensions, flexTokens}`。
- `summary` 含许可类型判定标志：`isHobbyist`（个人版）、`isStudent`（教育版）、`isCommercial`（商业版）。
- `activeExtensions`：用户已拥有的扩展（不要建议再次购买或重复启用）；`purchasableExtensions`：商业用户可购买、教育用户可免费启用的扩展。
- `flexTokens`：Flex 令牌余额、账户、`isFlexAvailable`、`isTFlexContract` 等字段。
- 用途：涉及许可、购买、扩展能力咨询时先查此项；本 skill 的几何建模流程通常不需要。

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

`object` 参数：

| 参数 | 必填 | 说明 |
|---|---|---|
| `script` | 是 | Python 脚本源码 |
| `readOnly` | 否 | `true` 表示脚本只读，默认 `false` |

服务端强制要求：

- 脚本必须定义入口函数 `def run(_context: str):`，执行时被调用。
- 使用 Fusion API（`adsk.core`、`adsk.fusion` 等）。
- 脚本内 `print()` 的内容作为工具输出返回——**尺寸测量结果靠 print 输出**。
- **不要用 try/except 捕获异常**：异常信息是判断失败原因的关键，捕获后无法定位问题。
- 建议流程：先查 API 文档 → 写脚本 → 执行 → 用读取/截图确认结果。

返回结构（实测）：`result.content[0].text` 为 JSON 字符串，`message` 字段承载脚本 `print()` 的全部输出（如 `"bodies=0\ntimeline features=0\n"`），`success` 标识执行是否成功——**测量结果从 `message` 中读取**。

**readOnly 规则（Fusion 更新后新增，对校验闭环很关键）**：

- 普通脚本**不能**在命令对话框打开时运行（例如用户正处于草图或拉伸命令中），会直接返回错误。
- 纯检查、纯测量的脚本应设 `readOnly: true`：这类脚本**允许在命令对话框打开时运行**，是命令进行中读取模型状态的唯一方式。
- 该声明会被**强制执行**：只读脚本一旦尝试修改设计，立即报错 `Cannot modify the design from a read-only context`。
- 只读脚本还必须避免 `Application.executeTextCommand`（不受该机制覆盖）。
- 需要修改设计时：省略 `readOnly`，并先请用户关闭当前对话框。

### featureType = "document"

| operation | 必填参数 | 说明 |
|---|---|---|
| `open` | `object.fileId` | 打开文档；fileId 由 read 的 `document` 查询（`search`）获得 |
| `close` | `userConfirmedSaveAndClose` **或** `userConfirmedCloseWithoutSave` | 有未保存改动时必须先征询用户，二选一 |
| `save` | 无 | **除用户明确要求保存外，不要调用** |

### 其他 featureType（非建模用途）

以下能力与本 skill 的实体建模流程无关，仅在用户明确提出对应需求时使用；**不得用于替代几何校验**。

| featureType | 用途 | 必填 object 字段 | 可选 object 字段 |
|---|---|---|---|
| `purchase` | 打开应用内 Purchase Manager（订阅、席位、扩展、Flex 令牌） | `purchaseInterest`（`fusion_subscription`/`extension`/`flex`）、`userConfirmedOpenPurchaseManager`（**必须用户明确同意后**才设 true） | `extensionName`（`purchaseInterest: "extension"` 时：扩展 ID 或显示名，优先取 `licensing` 的 `purchasableExtensions` 标题）、`userMessageSummary` |
| `editImage` | 用自然语言提示编辑模型截图（换材质、放入场景渲染） | `image_url`（签名 URL）、`s3_url`、`prompt`（**逐字传递用户提示，不要改写**） | `userMessageSummary` |
| `generatePowerpoint` | 按 JSON 定义生成 PPT | `slides_json`；**调用前必须先读 `resource://mcp.generate_powerpoint_schema` 并向用户确认大纲** | `userMessageSummary` |
| `previewImage` | 预览 / 打开 / 下载生成的文件（图片、pptx） | `image_url`、`s3_url`（单文件传字符串，多文件传等长数组） | `action`：`preview`（默认，仅图片）/`external`/`download`；`title`（`action: "preview"` 时的预览对话框标题）；`userMessageSummary` |

要点：

- `userMessageSummary`（2026-10 核对新增）：所有非建模 featureType 通用的可选字段，携带用户请求的简短转述，仅作上下文提示，不参与执行逻辑；建模流程不需要。
- `purchase`：调用前先查 `licensing`；不同许可类型（个人 / 教育 / 商业）的可用选项与话术不同，教育用户不得使用 `fusion_subscription` 与 `flex`；Purchase Manager 已打开时该调用是**切换到目标标签页**，不要描述成新开对话框。
- `editImage`：每次调用消耗一次 AI 媒体生成配额，配额耗尽会返回错误与提示语（原样转达用户）；用户要求重试时必须**重新调用**，不要沿用上次的错误结论；返回结构化 attachments，不要把原始 JSON 展示给用户。
- `generatePowerpoint`：服务端生成可能需要数分钟；占位符结构为 `{idx, accepts, value}`，`accepts` 取值 `text`/`image`/`any`；图片占位符只能使用 s3:// URL（不要用 thumbnail_url）。注意：当前 adapter 实例**未暴露** `resource://mcp.generate_powerpoint_schema`（见 §4 末注），调用前需确认该资源可读。
- `previewImage`：多文件（数组）时强制 `action: "download"` 并打包为 ZIP；`preview` 仅支持图片（pptx 自动转 `external`）；`image_url` 过期时服务会用 `s3_url` 自动刷新，两数组长度必须一致。
- 建模与校验流程中默认不调用以上 4 种。

## 3. fusion_mcp_update（撤销 / 重做）

`featureType`：`undo` 或 `redo`。

- 成功：`{"success": true, "message": "...", "canUndo": bool, "canRedo": bool}`
- 失败：`{"success": false, "error": "Nothing to undo"}`；交互式/预览状态下不可撤销（优雅失败）
- 撤销对象是**最近一次已提交事务**（创建特征、删除、编辑等）。
- **这是失败恢复的核心工具**：几何报错时只对当前这一步执行 `undo`，之前已完成并确认的特征全部保留。

## 4. fusion_mcp_electronics_read（电子设计数据）

仅在存在活动 Electronics 文档时可用，用于读取原理图 / PCB / 库数据。

- `entity_type`（必填）：`electronics.<Class>`，共 50 种（Fusion 更新后新增 `PortNetMappingEntry`），覆盖：
  - 原理图类：`Schematic`、`Sheet`、`Net`、`Bus`、`Wire`、`Segment`、`Junction`、`Label`、`Part`、`Instance`、`Gate`、`Pin`、`PinRef`、`Port`、`PortRef`、`PortNetMappingEntry`、`Module`、`ModuleInstance`、`Symbol`、`Variant`、`VariantDef`、`Technology`
  - PCB 类：`Board`、`Signal`、`Layer`、`Pad`、`Smd`、`Via`、`Hole`、`PolyPour`、`PolyShape`、`PolyCutout`、`Spline`、`Dimension`、`Element`、`Error`、`NetClass`、`Package`、`Package3D`、`Contact`、`ContactRef`
  - 通用类：`Attribute`、`Library`、`Device`、`DeviceSet`、`Frame`、`Grid`、`Circle`、`Rectangle`、`Text`
- `object`（可选）：
  - `fields`：要返回的列名，省略则返回全部列
  - `filters`：`[{"property": "...", "op": "eq", "value": ...}]`，字符串属性只能用 `eq`；整数/数值属性可用 `lt`/`gt`，但需该属性在 schema 资源中声明支持
  - `pagination`：`{"limit": 100, "offset": 0}`，limit 默认 100、上限 1000；响应中 `hasMore` 为 true 时用 `nextOffset` 取下一页
- 发现资源：`resource://mcp.electronics_entity_types`（全部类型）、`resource://mcp.electronics_schema_<snake_case 类名>`（该类的属性与过滤操作符）。实测资源名使用 snake_case 转换（如 `electronics.PortNetMappingEntry` → `resource://mcp.electronics_schema_port_net_mapping_entry`），当前共 51 个资源（1 个类型清单 + 50 个类 schema）；`resources/templates/list` 与 `prompts/list` 未实现（返回 `-32601`）。
- `resources/read` 返回内容为 JSON 字符串：`contents[0].text` 形如 `{"entity_type": "electronics.Wire", "properties": [{"name": "object_id", "type": "integer", "filterable": true, "operators": ["eq"]}, ...]}`——写入 `filters` 前查此资源确认属性可过滤性与支持的运算符。
- 注意：当前 adapter 实例**未暴露** `resource://mcp.generate_powerpoint_schema`（`resources/list` 不含该项，直接读取返回 `Resource not found`），仅在调用 `generatePowerpoint` 时需留意；与本 skill 的建模流程无关。

## 典型调用序列

### 单特征闭环（核心流程）

```
1) 查 API     fusion_mcp_read    { "queryType": "apiDocumentation", "searchPattern": "Extrude",
                                   "apiCategory": "class", "filter": "adsk.fusion" }
2) 建特征     fusion_mcp_execute { "featureType": "script",
                                   "object": { "script": "<只创建 1 个特征的脚本>" } }
3) 读尺寸     fusion_mcp_execute { "featureType": "script",
                                   "object": { "readOnly": true,
                                               "script": "<print 包围盒/体积/关键尺寸的脚本>" } }
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
7. 测量/检查脚本设 `readOnly: true`（命令对话框打开时也可运行）；建模脚本不设，执行前先请用户关闭对话框。非建模类 featureType（`purchase` / `editImage` / `generatePowerpoint` / `previewImage`）不得用于几何校验。
