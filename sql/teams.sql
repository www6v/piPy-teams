-- ============================================================================
-- teams.sql
-- piPy-teams - 团队协作扩展表结构 DDL
-- 来源: piPy-teams/packages/pi_team/src/pi_team/store.py
--        + piPy-teams/packages/pi_team/tests/test_team_tools.py
-- 数据库: 与 oma-platform 共享同一库
--        * MySQL: DATABASE_URL (mysql://… / mysql+aiomysql://… / Go @tcp DSN)
--        * SQLite (legacy/tests): OMA_DATABASE_PATH / DATABASE_PATH, 缺省 ./data/oma.db
-- 说明: 本模块不单独建库; 表的 DDL 同时维护在
--        oma-platform/scripts/sql/platform.sql (SQLite) 与
--        oma-platform/scripts/sql/platform_mysql.sql (MySQL) 中,
--        由 oma-platform 的 migration (017_teams.sql, 018_team_tasks.sql)
--        在启动时创建。本文件仅作为本模块自包含的参考副本。
-- 本模块读取 (只读, 不拥有): sessions, agents
-- ============================================================================

-- ============================================================================
-- teams — 团队定义; 每个 team 隶属于某个 session, 由 lead_agent 带队
-- ============================================================================

CREATE TABLE IF NOT EXISTS teams (
  id              TEXT PRIMARY KEY NOT NULL,
  session_id      TEXT NOT NULL,
  tenant_id       TEXT NOT NULL,
  name            TEXT NOT NULL,
  description     TEXT,
  lead_thread_id  TEXT NOT NULL DEFAULT 'sthr_primary',
  lead_agent_id   TEXT NOT NULL,
  status          TEXT NOT NULL DEFAULT 'active',
  created_at      INTEGER NOT NULL,
  UNIQUE(session_id, name)
);

CREATE INDEX IF NOT EXISTS idx_teams_session
  ON teams (session_id);

-- ============================================================================
-- team_members — 团队成员 (每个 member 对应一个 agent)
-- plan_mode_required: 是否需要 lead 审批才能执行动作 (0/1)
-- backend_type:     'in_process' | 'sub_agent' | 其他后端
-- ============================================================================

CREATE TABLE IF NOT EXISTS team_members (
  id              TEXT PRIMARY KEY NOT NULL,
  team_id         TEXT NOT NULL REFERENCES teams(id),
  agent_id        TEXT NOT NULL,
  display_name    TEXT NOT NULL,
  color           TEXT,
  thread_id       TEXT,
  role            TEXT,
  plan_mode_required INTEGER NOT NULL DEFAULT 0,
  backend_type    TEXT NOT NULL DEFAULT 'in_process',
  status          TEXT NOT NULL DEFAULT 'idle',
  joined_at       INTEGER NOT NULL,
  UNIQUE(team_id, display_name)
);

CREATE INDEX IF NOT EXISTS idx_team_members_team
  ON team_members (team_id);

-- ============================================================================
-- agent_messages — 团队成员之间的消息 (广播 / 私聊)
-- to_member_id 为空字符串或 NULL 表示广播给全员
-- read_at       为 NULL 表示未读, 否则为毫秒时间戳
-- ============================================================================

CREATE TABLE IF NOT EXISTS agent_messages (
  id              TEXT PRIMARY KEY NOT NULL,
  team_id         TEXT NOT NULL REFERENCES teams(id),
  from_member_id  TEXT NOT NULL,
  to_member_id    TEXT,
  message_type    TEXT NOT NULL DEFAULT 'text',
  body            TEXT NOT NULL,
  summary         TEXT,
  read_at         INTEGER,
  created_at      INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_messages_team_recipient
  ON agent_messages (team_id, to_member_id, read_at);

-- ============================================================================
-- team_tasks — 团队任务 (可选依赖关系 + 自由 metadata)
-- blocks_json / blocked_by_json: JSON 数组, 元素为 task_id
-- metadata_json:                 自由 JSON 对象
-- ============================================================================

CREATE TABLE IF NOT EXISTS team_tasks (
  id              TEXT PRIMARY KEY NOT NULL,
  team_id         TEXT NOT NULL REFERENCES teams(id),
  subject         TEXT NOT NULL,
  description     TEXT,
  active_form     TEXT,
  owner_member_id TEXT,
  status          TEXT NOT NULL DEFAULT 'pending',
  blocks_json     TEXT NOT NULL DEFAULT '[]',
  blocked_by_json TEXT NOT NULL DEFAULT '[]',
  metadata_json   TEXT,
  created_at      INTEGER NOT NULL,
  updated_at      INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_team_tasks_team
  ON team_tasks (team_id, status);
