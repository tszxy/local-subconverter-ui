# 本地订阅转换工具

一个运行在本机的订阅转换小工具，提供网页界面，可以把小火箭订阅链接、Base64 订阅内容、节点文本转换成 Clash / Mihomo 可用的订阅。所有内容只在本机处理。

## 功能

- 多个订阅地址合并转换
- 支持直接粘贴 `vless://`、`vmess://`、`trojan://`、`ss://` 等节点文本
- 内置 Mihomo / Clash.Meta 全协议模式，保留 VLESS 节点
- 支持把 Clash / Mihomo YAML 配置转换成 v2rayN 分享链接订阅
- 可调用本地 SubConverter 生成经典 Clash 配置
- 所有内容只在本机 `127.0.0.1` 处理

## 环境要求

- macOS（Apple Silicon / Intel）或 Linux（x86_64 / aarch64）
- 已安装 `python3`（脚本会自动创建虚拟环境并安装 `PyYAML`）

## 启动

进入仓库目录后运行：

```sh
./scripts/start.sh
```

脚本会自动完成：定位仓库目录、按系统架构下载对应的 subconverter、创建 Python 虚拟环境并安装依赖、生成并加载 launchd 服务。无需手填任何绝对路径。

启动后打开：

```
http://127.0.0.1:25501/
```

如需修改网页端口：

```sh
SUBUI_PORT=26000 ./scripts/start.sh
```

## 使用

1. 打开网页界面。
2. 粘贴订阅链接或节点内容。
3. 如果需要 VLESS，选择 `Mihomo / Clash.Meta（全协议）`。
4. 如果要把 Clash 配置转成 v2rayN，选择 `v2rayN（从 Clash 配置转换）`，并粘贴 Clash / Mihomo YAML 配置。
5. 点击 `生成转换链接`。
6. 复制生成的链接，导入 Clash Verge Rev、Mihomo Party、Clash.Meta 或 v2rayN。

全协议模式生成的本地订阅地址是：

```
http://127.0.0.1:25501/api/mihomo
```

v2rayN 模式生成的本地订阅地址是：

```
http://127.0.0.1:25501/api/v2rayn
```

## 停止

```sh
./scripts/stop.sh
```

## 配置项（环境变量）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `SUBUI_PORT` | `25501` | 网页界面监听端口 |
| `SUBUI_HOST` | `127.0.0.1` | 网页界面监听地址 |
| `SUBUI_BACKEND` | `http://127.0.0.1:25500` | 经典转换服务地址 |
| `SUBUI_RUN_DIR` | `~/Library/Application Support/local-subconverter-ui` | 运行期目录 |

## 安全说明

- 服务只监听本机，并校验请求 `Host` 头，阻止其它本地网页或 DNS rebinding 偷读你的订阅内容。
- 静态文件做了路径越界保护，不会读取仓库目录以外的文件。
- 请勿把真实订阅内容提交到仓库或公开分享；`ui/raw/` 已在 `.gitignore` 中忽略。

## 注意

- 经典 Clash 内核不支持 VLESS，请使用 Mihomo / Clash.Meta 内核。
- `http://127.0.0.1:25500/` 显示 404 是正常的，它是转换接口，不是网页界面。
