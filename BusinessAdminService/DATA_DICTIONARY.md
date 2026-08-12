# 业务数据字典与清洗映射

原始 `表结构/` 是业务领域参考，不是可直接执行的 PostgreSQL 迁移。业务后台使用
`business_*` 表，原因是配置需要草稿、校验、发布、回滚与审计，不能直接让正在运行的
交易核心读取用户正在编辑的行。

## 配置版本

| 表 | 含义 | 写入方 | 交易核心是否读取 |
| --- | --- | --- | --- |
| `business_config_version` | 草稿、校验、发布版本 | 后台 | 仅读取 `PUBLISHED` |
| `business_config_audit` | 配置变更、校验、发布审计 | 后台 | 否 |
| `business_published_config_version` | 当前有效版本视图 | 迁移创建 | 是，后续接入 |

## 原始表映射

| 原始表 | 清洗后模块/表 | 规则 |
| --- | --- | --- |
| `market` | `business_market` | 统一 `market_code`；版本内唯一 |
| `colo_list` | `business_colocation` | 修复原始 `coloid`/`colo_id` 名称冲突，机房编号从 1000 起 |
| `fundinfo` | `business_product` | 修复错误的 `status` 约束，改为 `fundstatus/status` 枚举 |
| `projectacct` | `business_project_account` | 初始资金为配置；实时可用资金不在本表编辑 |
| `fundacct` | `business_fund_account` | 账户、券商、机房等配置；实时资金从柜台同步 |
| `fundacctlink` | `business_fund_account_link` | 补齐产品、资产单元、账户的版本内外键与默认账户唯一性 |
| `stkinfo` | `business_security_master` | 仅保留交易所、买卖/撤单、最小价格单位和数量规则等核心配置 |
| `ft_product` | `business_futures_product` | 合约品种、乘数、最小变动价位、保证金规则 |
| `ft_stkinfo` | `business_futures_contract` | 期货合约与品种关联 |
| `fundasset` | `business_asset_snapshot` | 只读事实快照，后续由 C++ 同步写入 |
| `stkprice_*`、`extprice_*` | 原行情库，只读 | 后台查询覆盖率/时间范围，不复制 K 线 |

## 原始脚本发现的问题

- `USE ta_data`、`CREATE DATABASE IF NOT EXISTS` 与 PostgreSQL 迁移语法不兼容。
- `000create_db_user.sql` 包含演示账号、密码、测试数据与删除语句，不可作为生产迁移。
- `colo_list` 定义 `coloid`，主键却引用 `colo_id`；已统一为 `colo_id`。
- `fundinfo` 的 `CHECK (status ...)` 引用了不存在的字段；已改为产品状态约束。
- `013create_ft_margin.sql` 实际重复了 `ft_stkinfo`，没有可验证的期货保证金表定义；暂不实现，待业务确认。
- 原脚本缺少草稿/发布状态、版本隔离、默认账户唯一性与业务审计；已补齐。

## 发布规则

1. 管理员新建草稿版本，或从已发布版本复制。
2. 编辑市场、机房、产品、资产单元、资金账户、账户关联、证券及期货规则。
3. 服务端校验跨表引用、产品归属、默认账户唯一性、证券数量范围及期货品种关联。
4. 校验通过后，具有 `business:publish` 权限的操作员发布该版本；上一版自动变为 `RETIRED`。
5. C++ 核心后续仅拉取 `business_published_config_version` 对应数据，绝不读取草稿。

`business:read`、`business:write`、`business:publish`、`asset:read` 由
AuthAdminService/Casbin 判定。`asset:adjust` 预留给双人复核的专用流程，当前没有写接口。
