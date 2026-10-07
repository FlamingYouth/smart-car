# 版本记录

## 5.0 — 2026-10-07

- 新增 Telegram 通知，支持 Bot Token、数字 Chat ID 和可持久化的 HTTP/SOCKS5 代理。
- YAML 增加 `wechat.enabled` 和 `telegram.enabled`，可分别开关或同时开启。
- 原配置继续默认启用企业微信、关闭 Telegram；关闭的渠道不用填写凭据。
- 两个渠道独立冷却、去重、限流；单个渠道发送失败仍会尝试另一个。
- 保持全部车辆事件、数据库查询、报告模板和详情网址，原 16 条样例可同时发送到两渠道。
- 新增只测试 Telegram / 已启用通知的 CLI；样例工具可按渠道选择。
- 通知镜像升级至 `5.0`，TeslaMate、Grafana、数据库及 MQTT 镜像和配置保持原样。
- 私有通知配置排除在 Git 和镜像之外；运行依赖仅增加固定版本 PySocks。

镜像地址：

```text
registry.cn-hangzhou.aliyuncs.com/bigbey/smart-car-tesla-notifier:5.0
ghcr.io/flamingyouth/smart-car-tesla-notifier:5.0
```

从 4.1 升级时沿用现有私有配置，添加需要启用的 Telegram 字段即可。
只更新 `tesla-notifier` 服务，不创建或清空数据库卷。具体配置见 README，
测试与发布记录见 TEST_REPORT.md。

## 4.1 — 2026-10-01

- 日报、周报、月报改为企业微信群机器人普通文本 `text`，与其他通知使用相同发送格式。
- 恢复“查看详情”网址：正文末尾使用 `查看详情：https://…`，不再使用 Markdown 链接标记。
- 保留原有标题、正文、emoji、换行、统计数字、通知开关、时间与阈值。
- 总结使用普通文本的 2048 UTF-8 字节分段上限，超长内容不丢字、不拆字符。
- 保留安全网址校验，不发送非法协议、含登录凭据或控制字符的详情地址。
- 更新根目录和服务器部署 Compose 的通知镜像标签，不升级 TeslaMate、Grafana、数据库或 MQTT。
- 旧 `4.0` 镜像保留，不覆盖旧标签；去除超链接但仍使用 Markdown 的中间修订没有发布。

镜像地址：

```text
registry.cn-hangzhou.aliyuncs.com/bigbey/smart-car-tesla-notifier:4.1
ghcr.io/flamingyouth/smart-car-tesla-notifier:4.1
```

### 从 4.0 / 旧通知镜像升级

只把现有 Compose 的 `tesla-notifier.image` 改为上述阿里云 `4.1`。
已经迁移到 `wechat.webhook_url` 的私有配置无需重填或覆盖；
仍使用自建应用的旧配置则把 `wechat` 改为自己的群机器人 Webhook，
删除旧 `corpid`、`corpsecret`、`agentid`、`touser` 和通知 `proxy`。
保留数据库、MQTT、通知时间和阈值，以及 TeslaMate 的 `NOMINATIM_PROXY`。

以有 Docker 权限的账号，在部署目录执行：

```bash
docker compose pull tesla-notifier
docker compose up -d --no-deps --no-build tesla-notifier
docker compose logs -f tesla-notifier
```

Linux 只读挂载的私有配置必须让容器 UID 1000 可读。
需要调整时仅对该文件以 root 执行 `chown 1000:1000 config-prod.yaml`
和 `chmod 600 config-prod.yaml`。不要修改数据库卷或其他服务权限。

### 回退

把通知镜像标签改回 `4.0`，再执行上述拉取和单服务更新命令。
回退会恢复旧版 Markdown 总结显示，但无需改变 Webhook 配置。
这两个版本没有数据库结构迁移，不删除车辆数据或数据卷。

实际测试结果、双架构摘要、三条真实机器人试发和发布流程链接见 [测试报告](TEST_REPORT.md)。
群接口成功回应只确认消息被接口接受，实际微信排版仍需作者在客户端查看。

### 发布验收

- 本地 Docker 的 AMD64、ARM64 各通过 79 项回归及真实 HTTP 回环测试。
- GitHub 原生 AMD64、ARM64 各再次通过 79 项回归，之后原样同步到公开 Packages。
- 阿里云与 GitHub 的两种架构均已匿名拉取，镜像 ID 与最终测试镜像完全相同。
- 向作者授权机器人发送三条普通文本模拟总结，均获 HTTP 200、整数 errcode=0。
- 私有配置与已知新旧凭据未进入公开源码或生产镜像；旧 `4.0` 平台清单保持原样。

发布流程：[4.1 双架构测试与镜像同步](https://github.com/FlamingYouth/smart-car/actions/runs/36764659774)。

## 4.0 — 2026-10-01

- 将企业微信自建应用通知改为群机器人 Webhook，移除通知代理和应用 Token。
- 保留原有通知模板；当时的日报、周报、月报使用 Markdown 并附带详情链接。
- 完成 Docker 双架构测试，发布阿里云镜像与公开 GitHub Packages。
- 本项目约一年前开始编写，原功能稳定使用后整理公开；新版 Webhook 的验收单独记录。
