<div align="center">

# EvoGroup

### 面向共享上下文群体智能体的自演化记忆 Harness

**交互 · 分析 · 演化**

<a href="docs/paper.md"><img alt="论文" src="https://img.shields.io/badge/Paper-Manuscript-b31b1b?style=flat"></a>
<a href="LICENSE"><img alt="许可" src="https://img.shields.io/badge/License-MIT-22c55e?style=flat"></a>
<img alt="Python" src="https://img.shields.io/badge/Python-3.11%2B-3b82f6?style=flat&logo=python&logoColor=white">
<img alt="版本" src="https://img.shields.io/badge/Version-0.1.0-a855f7?style=flat">
<img alt="使用方式" src="https://img.shields.io/badge/Interface-CLI-0891b2?style=flat">

[论文](docs/paper.md) · [概述](#概述) · [方法](#方法) · [实验结果](#实验结果) · [快速开始](#快速开始) · [English](README.md)

</div>

---

## 概述

**EvoGroup（EvoG）** 是面向共享上下文群体智能体的自演化记忆 Harness。
它帮助群助手在长期多人对话中保留发言归属、讨论过程、协作关系与信息的时序变化。

EvoG 将模型外围的记忆组织、工具和决策策略作为演化对象，在保持基础模型固定的条件下，
从交互经验中发现问题并修订 Harness。系统从**五个基础工具、空的学习记忆和技能库**出发，
筛选有信息价值的轨迹、按需检查证据、归纳共性问题，再将修订后的 Harness 用于下一轮交互。

**论文亮点：**在 DeepSeek-V4-Flash 设置下，经过五次 Harness 更新，EverMemBench 的
pass@1 从 **71.07% 提升至 89.58%，增加 18.51 个百分点**。论文同时分析了按需轨迹披露
对分析成本的影响，并评估冻结后的 Harness 在 GroupMemBench 上的迁移表现。
具体结果及其适用范围见[实验结果](#实验结果)。

## 方法

<p align="center">
  <img src="docs/assets/evog-framework.png" alt="EvoGroup 四阶段自演化流程" width="1100">
</p>

### 1. 交互：生成回答与经验

群助手使用当前 Harness **Hₜ** 回答共享上下文中的问题，保存工具调用轨迹、回答与主观置信度。
低置信度回答会在**获得外部反馈之前**生成反思，说明已经检索的证据、尚未解决的事实与不确定性来源。

初始工具为 `list_files`、`read_file`、`grep_search`、`write_file` 和 `create_file`。
原始对话是事实证据，学习得到的笔记用于导航。

### 2. 轨迹筛选：结合置信度与外部信号

论文以 0.5 为置信度阈值，将主观置信度与外部正确性信号组合为四类经验：

| 类型 | 反映的问题 | 分析用途 |
| --- | --- | --- |
| **CC：高置信度、正确** | 常规成功行为 | 成功背景与对照 |
| **CW：高置信度、错误** | 尚未识别的失败 | 优先诊断 |
| **UC：低置信度、正确** | 脆弱的成功 | 优先诊断，并保留反思 |
| **UW：低置信度、错误** | 已识别的不确定性或失败 | 优先诊断，并保留反思 |

当前命令行流程使用可选的用户或业务 **accepted/rejected** 反馈。未反馈的交互保持“未判定”，
不会因为置信度低就被认定为错误。基础设施故障单独记录。

### 3. 轨迹分析：从局部证据到共性问题

**自适应渐进披露（APD）**先提供轨迹结构视图。分析智能体定位可能的问题阶段，再按需读取
局部事件、工具结果与字段；诊断引用必须对应实际检查过的证据范围。

**归桶分析（Bucketed Analysis）**将详细诊断压缩为保留原因和行动含义的简明诊断，
按推断的查询语义分组，再比较桶内和跨桶模式，生成带证据、覆盖范围、反例与不确定性的高层发现。

### 4. Harness 修订：通过四类接口演化

演化智能体根据发现生成有界修订。每项变更说明对应接口、证据、预期行为、回归风险与验证办法。

| 接口 | 改变什么 | 当前实现 |
| --- | --- | --- |
| **Representation** | 信息如何保存、关联与呈现 | 消息 metadata 的呈现 |
| **Operation** | 可执行的检索与证据操作 | 搜索词组合、返回条数与邻近记录 |
| **Policy** | 选择什么、何时执行、按什么顺序执行 | 群助手 prompt 与通用 Markdown skills |
| **Intervention** | 执行边界的检查或转换 | 引用要求、回答长度与引用数量限制 |

修订后的 **Hₜ₊₁** 保存为新版本，并用于后续交互。源消息、模型参数、预算和核心证据校验保持固定。
当前版本通过声明式配置表达修订，支持原子激活、过期计划检查与回滚。

## 实验结果

以下表格与图片来自**提供的论文稿件**，与本仓库的离线演示和软件测试分别报告。

### EverMemBench

主结果表报告的 pass@1（%）。**H₀** 为初始 Harness，**H*** 为已评估并选出的 Harness。
加粗表示该模型列中最高的已报告聚合结果。

| 方法 | GPT-5.5 | DeepSeek-V4-Flash | GLM-5.1 |
| --- | ---: | ---: | ---: |
| Mem0 | 56.50 | 43.71 | 52.42 |
| MemOS | 49.25 | 39.17 | 47.04 |
| A-MEM | 61.71 | 47.00 | 58.75 |
| MemRL | 61.54 | 55.92 | 57.33 |
| Codex | **85.67** | 82.63 | 77.88 |
| Claude Code | 84.58 | 85.75 | 76.46 |
| EvoGroup H₀ | 68.33 | 71.07 | 68.27 |
| EvoGroup H* | 84.52 | **89.58** | **83.63** |
| **H₀ → H* 增量** | **+16.19 pp** | **+18.51 pp** | **+15.36 pp** |

论文描述了从 2,400 道 EverMemBench 问题中固定抽取 720 道用于演化，以及另外 1,680 道留出问题。
上述数值沿用主表报告的聚合口径，本仓库没有重新计算。GPT-5.5 的 H* 在该表中仍低于 Codex 和 Claude Code。

### 冻结迁移至 GroupMemBench

演化后的 Harness 在没有进一步演化或调参的条件下迁移。论文报告 745 道问题及以下聚合结果：

| 模型 | H₀ | 冻结后的 H* | 增量 |
| --- | ---: | ---: | ---: |
| GPT-5.5 | 61.88% | 63.89% | +2.01 pp |
| DeepSeek-V4-Flash | 74.09% | 71.14% | −2.95 pp |

迁移效果随模型变化：GPT-5.5 提升，DeepSeek-V4-Flash 相对初始版本回退。
这些结果不能推导为所有模型、所有数据分布均获得提升。

### 分析效率与组件消融

在五轮匹配的轨迹分析对比中，APD 相比全轨迹分析平均**减少 42.5% 的分析时间**和
**41.5% 的 token 消耗**。

<p align="center">
  <img src="docs/assets/harness-ablation.png" alt="论文中的 Harness 组件消融结果" width="900">
</p>

上图保留论文原始组件消融图，比较单个演化组件替换初始 Harness 后的表现。
该设置下，工具和 prompt 的单项增益最大。过程消融还表明，移除 APD 或归桶分析会降低表现，
而轨迹筛选在已测试设置中的收益有限。
图表出处及稿件内的版本差异见[论文说明](docs/paper.md#source-notes)。

## 快速开始

### 安装

下述命令需要 **Python 3.11+** 和 [uv](https://docs.astral.sh/uv/)。在仓库根目录执行：

```bash
uv sync --extra dev
uv run evog --help
```

<details>
<summary>使用常规 Python 虚拟环境安装</summary>

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
evog --help
```

</details>

### 运行离线演示

```bash
uv run evog --workspace /tmp/evog-demo demo
```

演示使用合成群聊和确定性的模拟模型，不发送网络请求。
它贯通消息导入、带引用的回答、反馈、轨迹分析、修订计划和版本激活，用于验证命令流程。

### 查询自己的群上下文

```bash
export EVOG_BASE_URL=https://your-provider.example/v1
export EVOG_MODEL=your-model
export EVOG_API_KEY=your-key

uv run evog init
uv run evog ingest examples/messages.jsonl
uv run evog groups
uv run evog ask '最新的发布计划是什么？' --group product
```

模型服务需要支持 Chat Completions 和函数工具调用。导入格式为 UTF-8 JSONL，必填字段为
`group_id`、`message_id`、`sender`、带时区的 `timestamp` 和 `text`，可选字段为 `reply_to`
和字符串值的 `metadata`。参见[示例消息](examples/messages.jsonl)。
重复导入相同记录不会产生副本；同一源 ID 的内容冲突会拒绝整个导入。
跨群查询可重复指定 `--group`，所选群需要获得访问授权。

### 分析与修订

```bash
uv run evog feedback RUN_ID accepted --source user
uv run evog select
uv run evog analyze
uv run evog propose ANALYSIS_ID
uv run evog apply PLAN_ID
uv run evog revisions
uv run evog rollback REVISION_ID
```

使用前序命令返回的 ID。`apply` 激活通过结构校验的候选，业务效果需要在后续使用中验证。
当证据不足以支持修改时，空计划是有效结果。使用 `trace RUN_ID` 查阅轨迹，使用 `ask --json`
输出结构化回答。

## 仓库结构

```text
EvoG/
├── src/evog/
│   ├── cli.py                # evog 命令行入口
│   ├── app.py                # 内部命令调度
│   ├── runtime.py            # 群交互与反馈前反思
│   ├── tools.py              # 五个有范围约束的证据与导航工具
│   ├── analysis.py           # 筛选、APD、诊断与归桶发现
│   ├── evolution.py          # 计划、候选验证与激活
│   ├── harness.py            # 四类有界修订接口
│   ├── store.py              # 消息、轨迹、反馈与版本保存
│   ├── providers.py          # 模型调用
│   └── prompts/              # 交互、反思、分析、综合与演化
├── docs/                     # 论文说明、架构与配置
│   └── assets/               # 从论文导出的图片
├── examples/                 # 合成消息与命令行演示
├── tests/                    # 无付费模型调用的回归检查
└── .github/workflows/ci.yml   # 检查、测试与构建
```

## 文档与开发

- [论文说明与结果来源](docs/paper.md)
- [架构与运行边界](docs/architecture.md)
- [部署配置](docs/configuration.md)
- [从 AHE 派生项目迁移](docs/migration.md)
- [版本验证记录](docs/release-validation.md)
- [贡献指南](CONTRIBUTING.md) · [安全说明](SECURITY.md)

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv build
```

私有消息、轨迹与反馈保存在 Git 忽略的 `.evog/` 中。
引用检查验证来源已送达模型，语义正确性仍需验证；实际模型端点和业务质量需要部署时检查。

## 致谢与许可

研究项目基于 [Agentic Harness Engineering（AHE）](https://arxiv.org/abs/2604.25850) 发展。
文档组织参考 AHE 与 [HarnessX](https://github.com/Darwin-Agent/HarnessX)。
来源署名保留在 [NOTICE](NOTICE) 中，项目采用 [MIT](LICENSE) 许可。
