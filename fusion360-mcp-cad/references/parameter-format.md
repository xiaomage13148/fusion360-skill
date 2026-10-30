# 离线参数 JSON 格式

仅在需要机器检查参数时使用；不要求每次建模先生成 JSON。运行 `scripts/validate_part_params.py <文件> --json`，也可用 `-` 从 stdin 读取。Python 3.10+，仅标准库。

## 示例

```json
{
  "schema_version": 1,
  "part_name": "plate",
  "units": "mm",
  "features": [
    {"step": 1, "type": "sketch", "params": {"width_mm": 40, "height_mm": 20}},
    {"step": 2, "type": "extrude", "depends_on": [1], "params": {"depth_mm": 5}},
    {"step": 3, "type": "hole", "depends_on": [2], "params": {
      "hole_dia_mm": 3.2, "count": 2, "x_mm": -5,
      "edge_allowance": {"kind": "clearance", "value": 5, "unit": "mm"}
    }}
  ]
}
```

这是参数计划，不是自动执行的 CAD 程序。示例未包含足够的几何约束来自动生成完整零件，仍需结合设计意图和实际 Fusion 上下文。

## 契约

- `part_name`：非空字符串，兼容旧字段 `name`；`schema_version` 可省略，提供时必须为整数 1。
- `units`：默认长度单位，支持 `mm`、`cm`、`m`、`in`（兼容 `millimeter`、`millimetre`、`inch`）。不会改写原始值。
- `process`：可省略或 null；`--process` 覆盖它。仅 FDM/SLA/DLP 有粗略打印提醒，其他工艺保留原名称并标记未覆盖，绝不回退到 FDM。
- `features`：非空数组，`step` 必须与数组位置一致，从 1 开始；`type` 为非空字符串，未知类型提示未覆盖；`depends_on` 可选，只能引用之前的有效步骤。
- `params`：非空对象。支持常用字段简写或显式 `{kind, value, unit}`。不执行字符串表达式；带单位输入可用显式对象，不能把任意表达式字符串视为已验证数值。

| kind | 数值约束 | 单位 |
|---|---|---|
| length / diameter / wall / radius | 有限数且 > 0 | 长度单位，缺省用顶层 units |
| count | 严格正整数，拒绝布尔与小数 | 无 |
| angle | 有限数，可为零或负值 | 必须显式 deg / rad |
| coordinate / offset | 有限数，可为零或负值 | 长度单位 |
| clearance | 有限数且 ≥ 0 | 长度单位；过盈另行明确建模 |
| scalar | 任意有限数 | 无 |

简写用下划线分词推断：`width_mm`、`depth_in` 是长度，`hole_dia_mm` 是直径，`wall_mm` 是壁厚，`fillet_radius_mm` 是半径，`x_mm` 是坐标，`offset_mm` 是偏移，`angle_deg` 是角度，`count` / `hole_count` 是数量。显式 kind、单位与已识别名称冲突时报错，避免绕过约束；自定义参数名优先声明 kind。

未知字段/参数被保留并产生 warning，不能算已验证。顶层元数据、材料、字符串表达式、孔位关系等尚无通用语义检查；需要实际模型与专项检查。此格式不限制模型中的用户参数表达式，只限制这个离线检查器能证明的范围。

## 报告

JSON 始终包含 `verdict`、`errors`、`warnings`、`infos` 和 `scope: static-parameters-only`。输入读取/解析失败也返回 JSON 错误。退出码 1 表示非法输入，0 表示无 error（可能有 warning）；自动调用应同时读取 warning 与 scope。

PASS 仅表示已覆盖的静态参数检查通过，不表示 CAD 几何、配合、全局壁厚或制造通过。打印提醒先转换到 mm 再比较，经验阈值见 [打印建议](3d-print-rules.md)。
