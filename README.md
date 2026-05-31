# 本地订阅转换工具

一个运行在本机的订阅转换小工具，提供网页界面，可以把小火箭订阅链接、Base64 订阅内容、节点文本转换成 Clash / Mihomo 可用的订阅。

## 功能

- 多个订阅地址合并转换
- 支持直接粘贴 `vless://`、`vmess://`、`trojan://`、`ss://` 等节点文本
- 内置 Mihomo / Clash.Meta 全协议模式，保留 VLESS 节点
- 支持把 Clash / Mihomo YAML 配置转换成 v2rayN 分享链接订阅
- 可调用本地 SubConverter 生成经典 Clash 配置
- 所有内容只在本机 `127.0.0.1` 处理

## 启动

```bash
cd /Users/zhang/Documents/Codex/2026-05-10/clash
./scripts/start.sh
```

启动后打开：

```text
http://127.0.0.1:25501/
```

## 使用

1. 打开网页界面。
2. 粘贴订阅链接或节点内容。
3. 如果需要 VLESS，选择 `Mihomo / Clash.Meta（全协议）`。
4. 如果要把 Clash 配置转成 v2rayN，选择 `v2rayN（从 Clash 配置转换）`，并粘贴 Clash / Mihomo YAML 配置。
5. 点击 `生成转换链接`。
6. 复制生成的链接，导入 Clash Verge Rev、Mihomo Party、Clash.Meta 或 v2rayN。

全协议模式生成的本地订阅地址是：

```text
http://127.0.0.1:25501/api/mihomo
```

v2rayN 模式生成的本地订阅地址是：

```text
http://127.0.0.1:25501/api/v2rayn
```

## 停止

```bash
cd /Users/zhang/Documents/Codex/2026-05-10/clash
./scripts/stop.sh
```

## 注意

- 经典 Clash 内核不支持 VLESS，请使用 Mihomo / Clash.Meta 内核。
- 不要把真实订阅内容提交到仓库或公开分享。
- `http://127.0.0.1:25500/` 显示 404 是正常的，它是转换接口，不是网页界面。
