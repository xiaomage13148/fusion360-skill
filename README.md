# Fusion 360 参数化建模 Skill

为支持 Skill 指令与工具调用的 AI 客户端提供一份共享建模流程，通过可用的 Fusion 360 连接能力创建、修改、检查参数化实体，并按需求交付模型文件。适用于机械零件、外壳、支架和打印件，不绑定 CodeBuddy 或特定模型。

本仓库提供 Skill 与辅助脚本，Fusion 360 MCP 插件需另行安装。Skill 安装和 MCP 连接是两个独立步骤；接入目标与验证范围见 [客户端指南](docs/clients.md)。

## 快速开始

1. 将 [fusion360-mcp-cad](fusion360-mcp-cad/SKILL.md) 所在的完整目录放入客户端支持的 Skill 目录，或在支持导入的客户端导入 [发布包](fusion360-mcp-cad.zip)。不要只复制 SKILL.md，参考文件也需要保留。
2. 启动 Fusion 360 和对应 MCP 插件，在 AI 客户端中连接它。优先使用客户端已连接的工具；具体地址、传输和认证由所用服务决定。
3. 显式选择或调用 `fusion360-mcp-cad`，描述任务。客户端没有原生 Skill 加载能力时，可明确要求读取该 SKILL.md，并在需要时读取其相对引用。

示例请求：

> 使用 fusion360-mcp-cad，在 Fusion 360 创建 40 × 20 × 5 mm 的底板，两个直径 3.2 mm 的通孔，孔中心分别距短边 5 mm、位于宽度中线。关键尺寸设为可编辑参数，完成后检查尺寸。

> 将当前指定底板的长度改为 50 mm，保持两孔分别距两端 5 mm。检查修改后的孔距和特征健康状态。

> 先给参数与建模方案，不修改模型。

## 执行与验证

- **自主执行（默认）**：在用户授权范围内小步修改、独立校验、连续完成，关键阶段汇报。
- **逐步确认**：用户要求教学或逐步控制时，按约定停下。
- **仅规划/检查**：按任务范围工作，检查任务不修改几何。

采用显式单位转换，保留现有模型的组件、坐标与参数依赖。失败或超时后先检查实际状态，不无条件 undo 或重发操作。

检查报告区分“通过、不通过、未验证、不适用”。截图辅助外观检查，不能代替几何测量；包围盒不能证明实体干涉或全局最小壁厚。缺少截图/视觉能力时继续可完成的数值检查。仅打印任务加载打印建议，不默认套用 FDM。

工具名称和参数以**当前连接的 MCP schema** 为准。[适配注意事项](fusion360-mcp-cad/references/mcp-tools.md) 只补充执行与恢复限制，不再复制完整接口定义。脚本中的 Fusion API 仍按需查询。

## 可选辅助工具

Python 3.10+，仅使用标准库。在仓库根目录运行：

```bash
# 仅当需要独立诊断 HTTP 服务时使用；默认示例地址不是所有适配器的固定端点
python fusion360-mcp-cad/scripts/check_mcp_server.py --endpoint http://127.0.0.1:27182/mcp --tools --detail

# 输出实际 schema，作为维护资料，不要求加载进建模上下文
python fusion360-mcp-cad/scripts/check_mcp_server.py --tools --json

# 校验参数文件；也可用 - 从 stdin 读取
python fusion360-mcp-cad/scripts/validate_part_params.py params.json --json
```

HTTP 诊断区分初始化与工具发现；使用 `--tools` 时工具发现失败也返回退出码 1。支持 JSON/SSE POST 响应、工具分页与协商版本头；仅支持脚本列出的协议子集，不支持 stdio、旧式双端点 SSE、OAuth 或服务端 RPC。需要 bearer token 时用 `--token-env 环境变量名`，不要把凭据写进端点。

参数检查支持 mm/cm/m/in、显式类型和合法步骤依赖，默认无制造工艺。详见 [参数格式与报告范围](fusion360-mcp-cad/references/parameter-format.md)。静态参数 PASS 不表示模型或制造验收通过。

## 目录

```text
fusion360-mcp-cad/
├── SKILL.md
├── references/
│   ├── modeling-and-units.md       参数、单位、实体引用与交付
│   ├── parameter-format.md         可选参数 JSON 契约
│   ├── mcp-tools.md                当前适配器的补充约定
│   ├── visual-verification.md      几何证据与图像检查
│   ├── error-recovery.md           失败/结果未知时的恢复
│   └── 3d-print-rules.md            按需加载的打印建议
└── scripts/
    ├── check_mcp_server.py
    └── validate_part_params.py
scripts/build_skill.py              从唯一源码生成/检查发布包
tests/                             离线回归测试
docs/                              接入指南、优化方案与历史草稿
```

## 开发与发布

```bash
python -m unittest discover -s tests -v
python scripts/build_skill.py
python scripts/build_skill.py --check
```

源码目录是唯一维护来源，zip 由脚本生成并逐文件核对；不包含缓存、测试或客户端安装副本。更新客户端时重新复制完整 Skill 目录或导入新包，避免旧安装副本继续生效。历史 DeepSeek 草稿保留在 docs 中并标为历史资料，不作为运行规则。

## 当前验证范围

离线测试覆盖参数错误、单位/工艺处理、HTTP JSON/SSE、分页、错误传播、超时和发布包一致性。客户端与真实 Fusion 的检查结果记录在 [客户端指南](docs/clients.md)。工具可发现或 API 文档查询成功，不等于完成真实建模验收。

[优化方案与实施状态](docs/通用化评估与优化方案.md) 保留设计依据和剩余验证项目。
