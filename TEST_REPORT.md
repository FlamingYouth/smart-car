# Webhook 迁移验收记录

首次验收日期：2026-10-01（Asia/Shanghai）。首次验收时未提交或上传；
后续镜像 `4.0` 发布与双架构复测另行记录。

## 用户复测镜像

- 名称：`codex-smart-car-webhook:3.1.0`
- 平台：`linux/arm64`
- 精确镜像 ID：`sha256:da408f62377a152c5baad5b52c26cc3c4dd058aaa31e7b3dc522a8101c2f7e58`
- 非 root 运行用户：`tesla` / UID 1000。
- 基础镜像摘要和完整运行依赖已固定在 Dockerfile、requirements.lock。
- 首次通知验收只验证本机 ARM64；发布前另行完成 AMD64 复测。

## 测试结果

- 本机离线回归：74 passed。
- 同一最终镜像派生的 Linux Docker 离线回归：74 passed。
- Docker 回环 HTTP 冒烟：通过。16 条模板走真实 requests/HTTP 栈；
  HTTP 403、302、API 拒绝和缺失 errcode 都判失败，不跟随重定向，
  不请求应用 Token；CLI 成功与失败退出行为正确。
- 设置不可用 HTTP_PROXY / HTTPS_PROXY / ALL_PROXY 后仍通过回环发送，
  确认通知请求不使用环境代理。
- 真实机器人样例：最终镜像向用户授权的新机器人发送 1 条说明和 16 条样例，
  每条都通过客户端的 HTTP 200、整数 errcode=0 校验，进程退出码为 0。
  接口确认不等于人工确认手机/桌面客户端的实际显示，请用户检查群消息。

| 当前实际通知 | 样例数 | 检查分支 |
| --- | ---: | --- |
| 系统启动 | 1 | 模拟服务状态 |
| 充电结束 | 4 | 完成/停止 × 详细/简化 |
| 软件更新 | 1 | 当前版本、新版本 |
| 温度告警 | 4 | 车内/环境 × 高/低 |
| 行程完成 | 2 | 电量百分比、kWh 回退 |
| 昨日总结 | 1 | 原标题、正文、详情链接 |
| 上周总结 | 1 | 原标题、正文、详情链接 |
| 上月总结 | 1 | 原标题、正文、详情链接 |
| 系统关闭 | 1 | 模拟生命周期 |

全部数据在内存中生成。没有连接真实 PostgreSQL、MQTT 或车辆，
没有启动正式监控，没有控制车辆。样例详情链接沿用本地原配置，
测试程序只把链接放入消息，没有访问 Grafana。

## 模板与配置保护

以下三个原文件与修改前 SHA-256 完全一致：

- mqtt_listener.py：`9e016117d1a33203f45c07d93e92f23d78f05fa31c9cbf78fab4dd8c1814ad86`
- task_scheduler.py：`240f9fbbce660a6b24f181f44b222a59dcfc9b62c8e335c8b1ecb06a8e124fdf`
- database_manager.py：`cceb5fb43d87704fe43b148287c1718b2bf0f11da3847f665c6236f8de7ff3fa`

main.py 中启动、关闭消息的原文未改。
原应用报告卡片改为群机器人 Markdown，原文和链接保留，卡片显示样式有所不同。
原来只记日志的休眠/唤醒、已移除的车门通知没有重新启用；
旧“开始充电”等未实现流程也没有额外开发。

原 config.yaml、config-prod.yaml、.env 已在本地 private-backups/ 中备份。
生产数据库、MQTT、定时、温度和日志配置除旧通知收件人项外保持不变。
当前公开 config.yaml 已改为无密钥示例；新地址仅保存在私有配置中。
公开源码和镜像 /app 文件均检查未发现本次 Webhook 或原配置中的已知凭据。
私有配置、测试环境文件和备份均被 Git/Docker 忽略。
这不代表旧 Git 历史或旧镜像已经去除旧凭据；本次没有改写历史、删除旧镜像。

Compose 静态校验通过。非 root 容器在本机能够读取只读挂载的私有配置。
未启动正式 Compose；未改动其他项目的容器、卷或 Docker 全局配置。
一次性样例容器正常退出并自动移除，最终镜像和离线测试镜像保留供复测。

## 用户复测

至少与上一轮试发间隔一分钟，在项目目录执行：

```bash
docker run --rm --env-file .env.webhook-test \
  -v "$PWD/config-prod.yaml:/app/config.yaml:ro" \
  codex-smart-car-webhook:3.1.0 \
  python scripts/send_notification_samples.py --send
```

仅预览：去掉 `--send`；仅发日报：保留 `--send` 并加 `--only daily_summary`。
上述测试不连接真实车辆服务，不改变生产通知开关。
正式部署说明见 README.md，确认样式和样例后再接入自己的服务。

## 镜像 4.0 发布与双架构复测

发布时间：2026-10-01（Asia/Shanghai）。阿里云发布地址：

```text
registry.cn-hangzhou.aliyuncs.com/bigbey/smart-car-tesla-notifier:4.0
```

- 统一标签清单摘要：`sha256:e9163bbfc54fd6cac73c4d035fff6306c06cef9172d9c79d6540ca9ebf9daf46`。
- AMD64 平台清单：`sha256:1ec9f187cd7075f589fa0cebaf3a6679ec15022092f4210a7bdcdcab759a1ad2`。
- ARM64 平台清单：`sha256:cc8de992328643e99213132af0fc2df8d766fd94e0373e24a1cb6091ae217a0f`。
- AMD64 镜像 ID：`sha256:fc9f4af3f88252dd18dd0f390f20537ab16bd25b109f6eed19a1b1a8486a6450`。
- ARM64 镜像 ID 与本机此前复测镜像完全相同，即本页记录的 `da408f...`。

两种架构分别通过 74 项容器离线回归；AMD64 在桌面 Docker 的模拟执行环境中测试，
不等于在用户真实服务器或真实车辆服务上联调。两者均通过真实 HTTP 回环冒烟，
9 个应用源码/配置文件 SHA-256 逐一一致，运行依赖版本由相同 requirements.lock 固定。
源码和镜像应用文件复查未发现本次 Webhook 或原配置中的已知凭据。

平台标签 `4.0-amd64`、`4.0-arm64` 与统一 `4.0` 一起上传，
正常使用只需拉取 `4.0`，Docker 自动匹配平台。
已通过统一标签分别反向拉取 AMD64 和 ARM64，镜像 ID 与对应的测试镜像一致。
保留原远程 `3.0`，没有覆盖、删除或启动正式服务。
根目录与 server-deploy 的 Compose 仅更新通知镜像标签；
没有升级其他组件，也没有另改应用版本号。
README 已按作者说明补充“约一年前编写、原功能稳定测试后整理公开”的背景。
