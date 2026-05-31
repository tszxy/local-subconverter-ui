# launchd

启动脚本 `scripts/start.sh` 会在运行期目录
（默认 `~/Library/Application Support/local-subconverter-ui/`）
自动生成两份 plist 并加载：

- `local.subconverter.plist` —— subconverter 转换内核
- `local.subconverter-ui.plist` —— 本地网页界面（使用项目自带 venv 的 Python）

因为 plist 里的路径依赖具体机器与用户目录，所以不再在仓库中保存固定副本，
改由脚本按当前环境生成，避免路径写死导致换机失效。
