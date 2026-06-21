# piPy-teams

piPy 团队协调扩展 - 为 piPy 提供多智能体团队协作能力。

## 项目特性

### 核心功能
- **团队管理**: 创建和管理多智能体团队，支持自定义团队名称、描述和成员配置
- **队友生成**: 动态添加团队成员，自动创建会话线程并注册邮箱路由
- **消息传递**: 支持点对点消息和广播消息，多种消息类型（文本、关闭请求、计划审批请求）
- **任务管理**: 完整的任务看板功能，支持任务创建、更新、依赖关系管理和状态跟踪
- **邮箱轮询**: 后台轮询机制自动检测新消息并触发队友响应
- **状态管理**: 完整的队友生命周期管理（idle、listening、active、shutting_down、shutdown）

### 技术特性
- **共享数据库**: 与 oma-server 共享 SQLite 数据库（oma.db），实现数据一致性
- **运行时隔离**: 使用 ContextVar 实现请求级别的运行时隔离，避免状态污染
- **平台集成**: 与 OMA platform 深度集成，支持会话事件追加和排队
- **异步架构**: 基于 asyncio 的异步消息处理和轮询循环
- **可配置轮询**: 支持自定义轮询间隔和空闲超时设置
- **优雅关闭**: 完整的队友关闭状态机，确保资源正确释放

### 工具集
项目提供以下 piPy 工具：
- `team_create` - 创建团队
- `spawn_teammate` - 添加队友
- `send_team_message` - 发送团队消息
- `read_team_messages` - 读取团队消息
- `team_task_create` - 创建任务
- `team_task_update` - 更新任务
- `team_task_list` - 列出任务
- `team_task_get` - 获取任务详情

## 项目架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        piPy Host Process                        │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              Extension Layer (team_extension.py)         │  │
│  │  - register() API registration                           │  │
│  │  - Tool registration & filtering                          │  │
│  └────────────────────┬─────────────────────────────────────┘  │
│                       │                                        │
│  ┌────────────────────▼─────────────────────────────────────┐  │
│  │              Tool Layer (tools.py)                       │  │
│  │  - TeamCreateTool, SpawnTeammateTool                     │  │
│  │  - SendTeamMessageTool, ReadTeamMessagesTool              │  │
│  │  - TeamTask* tools                                       │  │
│  └────────────────────┬─────────────────────────────────────┘  │
│                       │                                        │
│  ┌────────────────────▼─────────────────────────────────────┐  │
│  │           Business Logic Layer (service.py)              │  │
│  │  - Team CRUD operations                                  │  │
│  │  - Member management                                    │  │
│  │  - Message routing & delivery                            │  │
│  │  - Task board operations                                 │  │
│  └────────────────────┬─────────────────────────────────────┘  │
│                       │                                        │
│  ┌────────────────────▼─────────────────────────────────────┐  │
│  │              Runtime Layer (runtime.py)                  │  │
│  │  - ContextVar-based isolation                           │  │
│  │  - TeamRuntime configuration                             │  │
│  │  - Session/tenant context                                │  │
│  └────────────────────┬─────────────────────────────────────┘  │
│                       │                                        │
│  ┌────────────────────▼─────────────────────────────────────┐  │
│  │           Loop Manager (loop.py)                         │  │
│  │  - TeammateLoopManager                                   │  │
│  │  - Background poll tasks                                 │  │
│  │  - Mailbox monitoring                                    │  │
│  └────────────────────┬─────────────────────────────────────┘  │
│                       │                                        │
│  ┌────────────────────▼─────────────────────────────────────┐  │
│  │         Platform Integration (platform.py)              │  │
│  │  - append_session_events()                                │  │
│  │  - enqueue_session_events()                              │  │
│  └────────────────────┬─────────────────────────────────────┘  │
│                       │                                        │
│  ┌────────────────────▼─────────────────────────────────────┐  │
│  │            Data Layer (store.py)                         │  │
│  │  - SQLite persistence (shared oma.db)                    │  │
│  │  - TeamStore: sessions, teams, members, messages        │  │
│  │  - Task board storage                                    │  │
│  └────────────────────┬─────────────────────────────────────┘  │
│                       │                                        │
│  ┌────────────────────▼─────────────────────────────────────┐  │
│  │              SQLite Database (oma.db)                    │  │
│  │  - sessions, agents, teams                              │  │
│  │  - team_members, agent_messages                          │  │
│  │  - team_tasks                                            │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘

                          External Dependencies
┌──────────────────────┐    ┌──────────────────────┐    ┌──────────────────────┐
│   pi-agent (tools)   │    │    pi-ai (types)     │    │  OMA Platform (harness)│
│  - AgentToolResult   │    │  - TextContent       │    │  - Session events     │
└──────────────────────┘    └──────────────────────┘    └──────────────────────┘
```

## 安装和使用

### 环境要求
- Python >= 3.11
- uv (Python 包管理器)

### 安装步骤

```bash
# 克隆项目
cd /path/to/piPy-teams

# 安装依赖
uv sync

# 运行测试
uv run pytest packages/pi_team/tests/ -v
```

### 作为 piPy 扩展加载

```bash
cd /path/to/piPy
uv run pipy --extension /path/to/piPy-teams/extensions/team_extension.py
```

### 环境变量配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `OMA_DATABASE_PATH` | `./data/oma.db` | 共享数据库路径 |
| `DATABASE_PATH` | (fallback) | 备用数据库路径 |
| `PIPY_TEAMS_EXTENSION` | sibling repo path | 扩展文件位置覆盖 |
| `TEAMMATE_POLL_INTERVAL_SEC` | `2.0` | 邮箱轮询间隔（秒） |
| `TEAMMATE_IDLE_TIMEOUT_SEC` | `600` | 轮询空闲超时（秒） |

### OMA Platform 集成

oma-platform 通过以下环境变量解析扩展路径：

- `PIPY_TEAMS_EXTENSION`: 默认为 `../piPy-teams/extensions/team_extension.py`（oma-platform 的同级目录）

主机必须在扩展加载前配置 `TeamRuntime`（参见 `oma_adapter/team_bridge.py`）。

## 项目结构

```
piPy-teams/
├── extensions/
│   ├── team_extension.py    # piPy 扩展入口
│   └── README.md            # 扩展使用说明
├── packages/
│   └── pi_team/
│       ├── pyproject.toml   # 包配置
│       └── src/pi_team/
│           ├── __init__.py
│           ├── client.py    # 客户端接口
│           ├── ids.py       # ID 生成器
│           ├── loop.py      # 队友轮询循环
│           ├── paths.py     # 路径工具
│           ├── platform.py  # 平台集成
│           ├── runtime.py   # 运行时配置
│           ├── serialize.py # 序列化工具
│           ├── service.py   # 业务逻辑
│           ├── shutdown.py  # 关闭状态机
│           ├── store.py     # 数据持久化
│           ├── tools.py     # piPy 工具类
│           └── types.py     # 数据类型定义
├── pyproject.toml           # 项目配置
├── readme.md               # 本文件
└── uv.lock                 # 依赖锁定
```

## 开发指南

### 运行测试

```bash
cd piPy-teams
uv sync
uv run pytest packages/pi_team/tests/ -v
```

### 代码架构原则

1. **分层清晰**: 扩展层 → 工具层 → 业务层 → 数据层
2. **运行时隔离**: 使用 ContextVar 避免请求间状态污染
3. **异步优先**: 所有 I/O 操作使用异步模式
4. **数据一致性**: 与 oma-server 共享数据库，保持数据同步
5. **优雅降级**: 运行时未配置时工具自动禁用

## 许可证

本项目遵循 piPy 项目的许可证。

## 相关项目

- [piPy](https://gitee.com/www6v6v/piPy) - Python 智能体框架
- [oma-platform](../oma-platform) - OMA 平台实现
- [piPy-subagent](../piPy-subagent) - piPy 子智能体扩展