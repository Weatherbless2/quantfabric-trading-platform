# QtAdmin

`QtAdmin` 是 QuantFabric 的 C++ Qt 权限管理桌面端。它仅调用
`AuthAdminService` 的 HTTP 管理 API，不连接 XServer、交易柜台或权限数据库。

## Build

```bash
cmake -S . -B build
cmake --build build --target QtAdmin_0.1.0 -j"$(nproc)"
```

## Run

先启动本地测试链路中的 AuthAdminService：

```bash
./runtime/prepare.sh
./runtime/start.sh
```

然后启动桌面程序：

```bash
./build/QtAdmin_0.1.0
```

开发模式的默认登录地址为 `http://127.0.0.1:18080`；账号密码来自
`runtime/config/AuthAdmin.env`。管理端包含用户、菜单、角色绑定、账户授权和
审计查询。账户授权会同步写入 Casbin 规则，最终仍由 XServer 在交易操作时校验。
