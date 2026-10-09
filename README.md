# Fusion360 MCP 参数化 CAD 建模 Skill

把「Fusion360 MCP + 多模态视觉校验」的 CAD 建模规则封装为**可直接导入的 Skill**：强制单特征分步建模，每个特征完成后用测量数据 + 视口截图做闭环校验。适用于机械零件、3D 打印件等参数化实体建模场景。

## 交付物

| 路径 | 说明 |
|---|---|
| `fusion360-mcp-cad.zip` | 可直接导入的 Skill 包 |
| `fusion360-mcp-cad/` | Skill 源目录（修改后重新打包用） |
| `Fusion360 MCP + DeepSeek V4.1 Flash 多模态CAD建模规则封装成 Skill.md` | 原始规则草稿（历史参考） |

## 快速开始

1. **导入 Skill**：直接导入 `fusion360-mcp-cad.zip`；或把 `fusion360-mcp-cad/` 目录复制到 `~/.codebuddy/skills/`（个人级）或项目下 `.codebuddy/skills/`（项目级）。
2. **启动 Fusion 360 并加载 MCP 插件**，确认服务在线：

   ```bash
   python fusion360-mcp-cad/scripts/check_mcp_server.py --tools
   ```

3. **描述零件需求**，Skill 会自动进入「参数规划 → 分步建模 → 测量 + 截图自检」流程。

## 适配器版本与 Schema 核对（重要）

`fusion360-mcp-cad/references/mcp-tools.md` 中记录的是 **MCP Server Adapter 1.0.0** 的实际工具定义（最近核对：2026-10-09，Fusion 360 更新后重新拉取）：

- 端点：`http://127.0.0.1:27182/mcp`（协议版本 `2025-03-26`）
- 工具：`fusion_mcp_read`、`fusion_mcp_execute`、`fusion_mcp_update`、`fusion_mcp_electronics_read`
- 资源：51 个（`resource://mcp.electronics_entity_types` + 50 个 `resource://mcp.electronics_schema_<snake_case 类名>`）
- 实体建模统一通过 `fusion_mcp_execute` + `featureType: "script"` 执行 Python 脚本完成

**2026-10-09 核对结果**：工具名称、必填参数与全部枚举无变化；新增 3 个可选 `object` 字段——`userMessageSummary`（所有非建模 featureType 通用）、`title`（`previewImage` 预览标题）、`extensionName`（`purchase` + 扩展）；另补充了 `previewImage` / `purchase` / `editImage` 的行为细节与资源命名规则（已同步至 `references/mcp-tools.md`）。

**适配器升级后，工具名称、参数与枚举值都可能变化。** 升级后请用以下命令拉取最新 schema，与 `references/mcp-tools.md` 逐项核对：

```bash
# 概览：工具名 + 描述 + 参数列表
python fusion360-mcp-cad/scripts/check_mcp_server.py --tools --detail

# 完整 schema：机器可读 JSON，含每个工具的 inputSchema
python fusion360-mcp-cad/scripts/check_mcp_server.py --tools --json
```

**核对要点**：

1. 工具名称与数量（当前为 4 个）；
2. `fusion_mcp_read` 的 `queryType` 枚举（当前：`apiDocumentation` / `licensing` / `screenshot` / `document` / `projects` / `activeCommand`）；
3. `fusion_mcp_execute` 的 `featureType` 枚举（当前：`script` / `document` / `purchase` / `editImage` / `generatePowerpoint` / `previewImage`）、`object` 子字段清单（当前 16 个，其中 `userMessageSummary` / `title` / `extensionName` 为 2026-10 新增）与脚本约定（`def run(_context: str):`、`print` 作为输出、不捕获异常、只读脚本用 `readOnly: true`）；
4. `screenshot` 查询的 `direction` 枚举（校验用 `iso-top-left`）与 `width` / `height` 取值范围（32–4096）；
5. `fusion_mcp_update` 的 `featureType`（`undo` / `redo`）；
6. `fusion_mcp_electronics_read` 的 `entity_type` 枚举（当前 50 个）与 `resources/list` 的 51 个资源项（类 schema 资源名使用 snake_case）。

> 注意：`serverInfo` 版本号可能不变，但工具定义会扩展（历史示例：2026-09 新增 `readOnly`、`licensing` 与多个 `featureType`；2026-10 新增 `object.userMessageSummary` 等 3 个可选字段）。**核对时以 schema 内容为准，不要只看版本号。**

发现差异时：同步更新 `fusion360-mcp-cad/references/mcp-tools.md` 及受影响的 `SKILL.md` / references 文件，然后重新打包 zip（保持 `fusion360-mcp-cad/SKILL.md` 的目录结构）。

## 目录结构

```
fusion360-mcp-cad/
├── SKILL.md                       主流程：建模铁律 / 三阶段流程 / 输出格式 / 工具约束
├── references/
│   ├── mcp-tools.md               MCP 真实工具定义、参数约定与推荐调用序列
│   ├── visual-verification.md     视觉校验清单、自检报告模板、无视觉降级方案
│   ├── error-recovery.md          9 类错误分类与修复策略
│   └── 3d-print-rules.md          3D 打印专项规则（壁厚/支撑/拔模/公差/凸雕文字）
└── scripts/
    ├── check_mcp_server.py        探测 MCP 端点，列出工具、参数与完整 schema
    └── validate_part_params.py    参数 JSON 结构校验 + 可制造性静态检查
```

## 模型兼容性

Skill 不绑定特定模型：

- **视觉多模态模型**：测量数值 + 截图图像双通道自检，自动输出视觉结论；
- **纯文本 / 仅工具调用模型**：降级为脚本测量数值校验，截图仍会捕获并交由用户人工确认。

两种模式的建模流程完全一致，仅图像分析环节按能力降级。
