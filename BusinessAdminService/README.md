# QuantFabric 业务后台服务

`BusinessAdminService` 是业务控制面，用 Python 提供产品、资产单元、资金账户、证券主数据、
期货品种、发布版本与审计的管理 API。交易执行仍由 C++ 核心负责。

```text
Python 后台 UI / QtAdmin 扩展
        -> BusinessAdminService
        -> AuthAdminService/Casbin
        -> PostgreSQL/SQLite 业务配置库

交易核心 C++
        -> 只读取已发布版本
        -> 不读取草稿
```

## 当前范围

- 草稿版本、校验、发布、退役
- 第一批低风险配置页：市场、机房、产品、资产单元、资金账户、账户关联
- 第二批配置页：证券主数据、期货品种、期货合约
- 只读视图：资产快照、行情库状态、配置审计
- 证券买入权限一键发布：复制当前版本、修改单个证券、校验、发布和审计在一次受控操作中完成

## 权限动作

- `business:read`
- `business:write`
- `business:publish`
- `asset:read`

这些动作仍由 `AuthAdminService` 统一判定，`BusinessAdminService` 只复用短会话和 Casbin。

## 快捷开关

日常验证单个证券的买入权限时，在“证券主数据”选中证券后点击“一键切换买入并发布”并确认即可。
该操作同时要求 `business:write` 和 `business:publish`：服务端会复制当前已发布版本，仅变更该证券的
`buy_allowed`，校验全部配置后再发布。审计中会保留来源版本、改前改后值和操作人，因此仍可通过复制
历史版本回滚；其他证券规则不会丢失或被重置。

## 运行

```bash
python3 -m venv .business-venv
.business-venv/bin/python -m pip install -r BusinessAdminService/requirements.txt

export QF_AUTH_INTERNAL_KEY="$(sed -n 's/^QF_AUTH_INTERNAL_KEY=//p' runtime/config/AuthAdmin.env)"
export QF_BUSINESS_DATABASE_URL="sqlite:///$PWD/runtime/data/business_admin.db"
export QF_BUSINESS_AUTH_URL="http://127.0.0.1:18080"

.business-venv/bin/python -m uvicorn BusinessAdminService.app:app --host 127.0.0.1 --port 19080
```

浏览器打开：`http://127.0.0.1:19080/`

团队本地运行也可以直接使用统一脚本：

```bash
./runtime/prepare.sh
./runtime/start-business-admin.sh
```

PostgreSQL 部署时先创建专用数据库，再按顺序执行
`migrations/postgresql/001_business_control_plane.sql`、`002_instrument_master.sql`
和 `003_operational_read_models.sql`，然后将 `QF_BUSINESS_DATABASE_URL` 改为
`postgresql+psycopg://...`。服务启动时会检查第一张迁移表，不会自动替 PostgreSQL
创建数据库、用户或密码。

## C++ 运行策略

发布版本才会被 C++ `XServer` 读取。启用前必须先发布与实际交易链路匹配的市场、产品、
账户关联和证券规则：

```bash
export QF_BUSINESS_POLICY_ENABLED=true
export QF_BUSINESS_POLICY_REFRESH_SECONDS=30
./runtime/prepare.sh
./runtime/start.sh
```

未设置开关或值为 `false` 时，XServer 保持原有测试行为。启用后，启动日志应出现
`activated published business policy version:<n>`；控制面短暂不可用时，XServer 保留最后一次
完整加载的版本，首次加载失败则拒绝订阅和订单。该策略只包含运行准入规则，不包含密码、草稿
或实时资金。

## 说明

- 原始 `表结构/` 目录只作为领域参考，不直接执行。
- 清洗后的结构见 `migrations/postgresql/` 和 `DATA_DICTIONARY.md`。
- 历史 K 线仍在行情库中，后台只查覆盖率与时间范围，不复制数据。
- `business_asset_snapshot` 是只读事实表，后续由 C++ 同步写入，不提供人工编辑接口。
