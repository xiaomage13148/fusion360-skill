# 客户端接入与验证记录

核对日期：2026-10-30。各客户端复用同一份 `fusion360-mcp-cad/`，不复制维护建模规则。先安装 Skill，再配置 Fusion MCP；原生 Skill、MCP、图片传递和本地脚本是不同能力。

## 接入方式

| 客户端 | Skill 加载 | Fusion MCP | 本仓库验证状态 |
|---|---|---|---|
| CodeBuddy | 原仓库安装位置为个人 `~/.codebuddy/skills/` 或项目 `.codebuddy/skills/`，升级时核对客户端当前约定 | 在客户端配置实际服务 | 有历史安装副本；本轮未做完整建模验收 |
| Codex | 当前官方文档列出项目 `.agents/skills/`；将整个 Skill 目录放入其中，加载后显式选择或用 `$fusion360-mcp-cad` 调用 | 通过当前客户端的 MCP 配置连接服务，CLI 可用 `codex mcp` 管理 | 已完成手机支架创建、参数修改重建、几何测量和真实截图；详见 [实测记录](phone-stand-test.md)。失败恢复与文件交付尚未验收 |
| Claude Code | 本轮未取得官方页面内容，按当前产品文档确认 Skill 目录和调用方式 | 按当前客户端文档配置 | 尚未实测，不据此宣称兼容 |
| Cursor / 其他 MCP 客户端 | 先确认是否支持该 Skill 形式；否则明确让代理读取源码目录的 SKILL.md 和按需参考 | 使用原生 MCP 连接能力 | 尚未实测，不保证自动触发 |

Codex 资料：[Skills](https://developers.openai.com/codex/skills/)、[MCP](https://developers.openai.com/codex/mcp/)，本轮已读取。Claude Code 的 [Skills](https://code.claude.com/docs/en/skills) / [MCP](https://code.claude.com/docs/en/mcp) 页面本轮返回 HTTP 403，因此没有据此填写未经核对的配置。以上说明不自动修改任何客户端的本机配置。

## 通用检查

1. 确认客户端能读到 SKILL.md，且相对引用的 references/scripts 完整。
2. 确认 Fusion 已运行、插件已加载，宿主能看到当前工具 schema；不要照抄旧参数表。
3. 做当前任务所需的只读查询；脚本执行入口、只读限制、返回输出按实际说明确认。
4. 分别验证截图能否获取、客户端能否传递图像、模型能否理解。任一环节缺失时标记外观未验证。
5. 用户授权建模后，用简单模型检查单位、参数依赖、几何健康与恢复方式。远端代理的 localhost 是远端自身，需要可达的连接路径。

无本地 Python 环境不妨碍使用已连接的 MCP 工具；辅助脚本只用于需要它们的诊断和参数检查。

## 真实建模验收清单

至少在两个实际客户端中记录以下结果，再把对应组合标为已验证：

- 客户端版本、Fusion 版本、服务版本与 schema 来源。
- 40 × 20 × 5 mm 带孔板：实际尺寸、孔径和孔位测量。
- 参数修改：外宽变化后孔仍距边 5 mm，且没有重复实体。
- 多实体选择正确，文档切换后重新定位目标。
- 修改前失败、部分修改、响应超时与用户介入时不会误撤销或重复创建。
- 图片链路，以及保存/导出文件的真实格式、路径和单位。

初始 UnitsManager 查询确认了 API 内部长度 cm、角度 rad、体积 cm³ 的约定。后续 [手机支架实测](phone-stand-test.md) 验证了几何创建、单位、参数重建和图像链路；执行工具事务边界及保存/导出仍需独立验证。

本地 HTTP 实测：`http://127.0.0.1:27182/mcp`，`MCP Server Adapter 1.0.0`，协商协议 `2025-03-26`。发现 4 个工具；此条记录只证明该环境的初始化和发现链路。
