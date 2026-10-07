# Telegram 双渠道 5.0 验收记录

测试日期：2026-10-07（Asia/Shanghai）。本次只增加 Telegram 及独立渠道开关，
原 MQTT、统计查询、报告模板、数据库和其他 TeslaMate 服务保持原样。

## 本机 Docker

- AMD64 / ARM64 最终生产镜像派生的离线测试镜像分别通过 135 项回归。
- 两种架构的最终生产镜像均通过真实 HTTP 回环验证：全部 16 条原模板同时发送到
  企业微信与 Telegram 模拟端点，正文一致；失败、重定向、限流及 CLI 退出行为正确。
- 两版 /app 的全部 12 个公开应用文件、11 个固定运行依赖及 Python 3.9.25 一致。
  release/verified-app.sha256 已更新；运行依赖只新增 PySocks 1.7.1。
- Telegram 连接测试发送成功；另发送 1 条测试说明及全部 16 条原模板样例，
  每条都通过 HTTP 200、ok=true、实际 message_id 和匹配 Chat ID 校验。
- 实际 Telegram 发送从本机 ARM64 5.0 生产镜像运行，使用指定机器人及 SOCKS5 代理。
  Bot Token、数字收件人 ID、私有 YAML 不进入公开仓库或镜像。
- 本次企业微信用真实 requests/HTTP 回环服务验证；没有向额外的真实群机器人试发。

全部车辆、行程、温度、充电和服务状态为模拟数据，没有连接真实 PostgreSQL、
MQTT 或车辆。接口确认表示消息已被 Telegram 接受，客户端展示由收件人查看。

## 原逻辑与配置核对

mqtt_listener.py、task_scheduler.py、database_manager.py 的内容与 4.1 完全一致。
main.py 中启动/关闭通知的原调用及正文、样例生成函数也完全一致。
公开 YAML 中数据库、MQTT、报告时间、温度阈值、日志和健康检查段落保持原样。
服务器 Compose 只更新通知镜像版本，其他服务、端口、网络及卷完全一致。

## 5.0 发布

阿里云发布两个已测试平台，并提供统一 5.0 标签。GitHub 发布流程从该不可变摘要
拉取同一批镜像，在原生 AMD64 / ARM64 再次验证全部源码摘要、依赖、135 项离线回归
和真实 HTTP 回环，全部成功后原样同步全部架构至公开 Packages，不重建生产镜像。
阿里云统一清单摘要：sha256:e018cb55b1d21abf957f23f2d764f2ea8175da9ecd4ae8236c390202a6fc4490。
AMD64 镜像 ID：sha256:2959f45c9075d3cd45d25976cfc899ca70e9821e3c41a194e746970daa1e5079。
ARM64 镜像 ID：sha256:dfed9846c24e05b7d5f57d7649c7adcc3ab30966ed276d142946e7dfc545860f。
发布验收日期：2026-10-08（Asia/Shanghai）。
GitHub 原生 AMD64 / ARM64 各通过 135 项离线回归及全部双渠道 HTTP 回环检查，
再原样同步阿里云镜像。两个仓库的清单、平台镜像、配置和层摘要完全相同；
镜像包为公开可见，关联本仓库。已用无登录凭据的 Docker 配置分别拉取
阿里云与 GitHub 的 AMD64、ARM64 5.0，四次镜像 ID 均与本机验收镜像一致。
流程：[5.0 双架构复测与镜像同步](https://github.com/FlamingYouth/smart-car/actions/runs/37648253993)。

以下保留此前 4.0 / 4.1 的历史测试记录。

---

# Webhook 迁移验收记录

首次验收日期：2026-10-01（Asia/Shanghai）。首次验收时未提交或上传；
后续镜像 `4.0` 发布、双架构复测和 GitHub Packages 验收另行记录。

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

## GitHub 源码与 Packages 发布验收

发布时间：2026-10-01（Asia/Shanghai）。

- 公开源码仓库：[FlamingYouth/smart-car](https://github.com/FlamingYouth/smart-car)。
- 首个干净源码提交：`1a01a16f6f22264c4a0b38ef62f16a8478471d0d`。
- 公开镜像包：[smart-car-tesla-notifier](https://github.com/FlamingYouth/smart-car/pkgs/container/smart-car-tesla-notifier)。
- 发布流程：[Verify and mirror tested container 4.0](https://github.com/FlamingYouth/smart-car/actions/runs/36748417878)，全部任务成功。

GitHub 仅提交当前审查过的 33 个公开文件，使用独立的新 Git 历史，
没有复制原 Gitee 历史、生产配置、环境文件、日志或本地备份。
提交前再次检查暂存内容与当前公开源码逐字一致，并检查已知新旧凭据未被包含。
原项目的 Gitee 远程和本地历史保留不动。

GitHub 原生 AMD64、ARM64 执行环境分别拉取已发布的不可变镜像摘要，
核对镜像 ID、9 个应用文件摘要和运行依赖，两种架构各通过 74 项离线回归，
以及 16 条模板、HTTP 拒绝/重定向、CLI 成功/失败与无代理直连冒烟。
测试没有使用真实机器人密钥，没有接入生产车辆服务。

测试通过后原样同步到：

```text
ghcr.io/flamingyouth/smart-car-tesla-notifier:4.0
```

同步使用 `--all --preserve-digests`，没有重新构建生产镜像。
GitHub 与阿里云的统一清单摘要均为本页记录的 `sha256:e9163bbf...`；
两种平台的清单、镜像配置和层内容保持一致。
发布流程校验镜像包关联 `FlamingYouth/smart-car`，页面显示 `Public` 与两种架构。

使用不含登录凭据的临时 Docker 配置完成匿名清单查询，
并分别反向拉取 GitHub 的 AMD64、ARM64 镜像，
清单摘要和镜像 ID 与本页已测试的两个平台逐一相同。
确认无需 GitHub 登录即可拉取；没有修改 Docker 全局登录信息或启动正式服务。
本节与 README 的后续验收补充只是文档变更，不改变已测试、已发布的镜像内容。

## 总结去除超链接的本地复测（尚未发布）

2026-10-01，按作者的微信显示反馈，移除日报、周报、月报尾部的
“查看详情”超链接，原标题、正文、emoji、换行和统计数字不变。
仍使用群机器人 Markdown，不额外改变消息模板或统计算法。
旧 `url` 参数保留接口兼容，但不再进入发送内容，也不再因无用的旧地址阻止报告发送。

- 本地候选镜像：`codex-smart-car-summary-no-links:4.0-test`，`linux/arm64`。
- 镜像 ID：`sha256:41e533996da79f11a140f45c138cab787d8fc218978d9bab9c780071a8c405c4`。
- 主机离线回归：77 passed；同一候选镜像派生测试层的 Docker 回归：77 passed。
- 真实 HTTP 回环冒烟通过，并逐条校验三种总结的发送内容只含原标题和正文，
  不含详情地址或链接标记；其他模板与错误处理流程通过。
- 原 mqtt_listener.py、task_scheduler.py、database_manager.py 的摘要保持不变。
- 候选公开源码与镜像应用文件复查未发现已知新旧凭据。

从该候选镜像仅向原授权机器人发送三条模拟总结：日报、周报、月报各一条，
没有额外发送说明或其他通知。三条均得到 HTTP 200、整数 errcode=0，
试发进程退出码为 0，一次性容器已自动移除。
生成过程禁止真实 PostgreSQL/MQTT 连接，没有接入或操作车辆。
实际微信排版仍须由作者在客户端确认。

本次只完成本地 ARM64 验收，没有声称新修订已通过 AMD64 测试。
未提交新的 GitHub 源码、未上传镜像，阿里云和 GitHub Packages 的 `4.0` 保持原样。

## 4.1 普通文本总结与恢复网址验收

验收日期：2026-10-01（Asia/Shanghai）。
作者反馈去掉链接仍不能解决微信显示，因此本次改用与其他通知相同的普通文本 `text`，
不再使用 Markdown；恢复配置的详情网址，正文末尾为 `查看详情：https://…`。
原标题、正文、emoji、换行与统计数据保持不变，没有改动统计查询或车辆事件模板。

- ARM64 候选镜像：`codex-smart-car-plain-summary-arm64:4.1`。
- ARM64 镜像 ID：`sha256:b5edfdba2cdb89bed585677862f4ad3efdb19f8a30453dd2b2088b586727edd0`。
- AMD64 候选镜像：`codex-smart-car-plain-summary-amd64:4.1`。
- AMD64 镜像 ID：`sha256:4e0973723b5cc83f665cc79a9205f822a00b956aa87029714afc9428a83a1605`。
- 主机离线回归：79 passed。
- ARM64、AMD64 的最终镜像测试层分别通过 79 项 Docker 离线回归。
- 两种架构的真实 HTTP 回环冒烟通过：全部 16 条通知均为 `text`，
  三种报告逐字包含原标题、正文和恢复的详情网址，没有 Markdown 链接标记。
- 新增普通文本报告 2048 UTF-8 字节分段与网址原样保留测试，
  非法协议、含登录凭据或控制字符的详情网址拒绝发送。
- 两种镜像的 9 个应用文件摘要逐一一致，`pip check` 均通过。
- 原 mqtt_listener.py、task_scheduler.py、database_manager.py 摘要仍与初始验收相同。
- 主机格式检查、静态检查、根目录及服务器 Compose 静态校验通过。

从同一 ARM64 最终候选镜像，向原授权的机器人只发送日报、周报、月报各一条模拟数据。
三次请求均为 `text`，HTTP 200、整数 errcode=0；进程退出码为 0，
没有额外发送说明或其他通知，一次性容器已自动移除。
测试使用服务器私有配置的详情网址，但只把网址放入消息，没有访问 Grafana。
生成过程禁止真实 PostgreSQL/MQTT 连接，没有接入或操作车辆。
接口结果只确认消息被接受，实际微信显示仍由作者在客户端检查。

凭据复查同时覆盖原公开示例、原本机和服务器私有备份中的实际凭据，
以及新机器人地址和 key；公开源码和两种生产镜像应用文件均未发现这些凭据。
配置文件中的示例字段名不当作真实凭据。私有 `.env*`、根目录及服务器
`config-prod.yaml` 和备份保持 Git/Docker 忽略，不提交旧 Gitee 历史。
本次更新两份 Compose 的通知镜像为 `4.1`，不升级其他组件或启动正式服务。
前一轮单独移除链接的本地中间修订没有发布，旧 `4.0` 保留供回退。

### 4.1 阿里云发布

已上传 `4.1-arm64`、`4.1-amd64` 和自动匹配平台的统一 `4.1`：

```text
registry.cn-hangzhou.aliyuncs.com/bigbey/smart-car-tesla-notifier:4.1
```

- 统一清单摘要：`sha256:03b2661a23de6aaa02447a1748202354cb51f5fafd6939f8db60c07156ad1c93`。
- ARM64 平台清单：`sha256:5610f4522a192c3643f722e76b90e6c6203d23a328cf39e217794bda1a1039f3`。
- AMD64 平台清单：`sha256:e25f1afd8d6d39167deba08072e30bb49d1b4cfebd2265a7c16ebe99210f245b`。
- 两个平台镜像 ID 即本节记录的最终候选镜像 ID，没有发布测试依赖层。
- 新版非 root 容器断网只读加载服务器私有配置成功，不启动正式服务。

使用不含登录信息的临时 Docker 配置，从阿里云统一 `4.1` 标签分别匿名拉取
AMD64、ARM64，返回的统一清单摘要与镜像 ID 均与本节记录完全一致。
ARM64 首次反向拉取遇到临时网络 EOF，重试只读拉取后成功；没有重发机器人消息。
服务器私有配置与备份逐项、逐字比较，除已授权的通知配置迁移外，
数据库、MQTT、通知时间、阈值、日志和健康检查配置保持不变。

GitHub Packages 使用仓库临时授权，从该不可变摘要原样同步全部架构。
发布流程会在原生 AMD64、ARM64 执行环境再次核对镜像 ID、应用文件与全部测试，
并拒绝覆盖与新摘要不同的同名版本；同步后检查包关联和公开状态。
该流程不重新构建生产镜像，不需要上传 Docker 登录信息或个人 Token。

### 4.1 GitHub Packages 发布与最终反向验证

- 源码发布提交：`36cc4511f4d801bc176abc078c6b9db84f217a93`，基于独立干净历史。
- [4.1 发布流程](https://github.com/FlamingYouth/smart-car/actions/runs/36764659774) 全部成功。
- 原生 GitHub ARM64、AMD64 环境各通过 79 项离线回归与真实 HTTP 回环冒烟。
- 生产镜像未重新构建，使用 `--all --preserve-digests` 原样同步到公开镜像包，
  流程确认包关联 `FlamingYouth/smart-car`，可见性为 `public`。

```text
ghcr.io/flamingyouth/smart-car-tesla-notifier:4.1
```

GitHub 与阿里云的统一清单摘要均为：
`sha256:03b2661a23de6aaa02447a1748202354cb51f5fafd6939f8db60c07156ad1c93`。
两种平台清单、镜像配置和所有层摘要均保留。
使用无登录信息的临时 Docker 配置分别匿名拉取 GitHub 的两个平台，
摘要和镜像 ID 与本页记录的最终镜像逐一一致；本地统一标签最后保持 ARM64。
旧阿里云 `4.0` 的平台清单再次只读查询，仍为初始发布的 `1ec9f...` 与 `cc8de9...`，
未覆盖、删除或改动旧版本、数据卷以及其他项目。

README、CHANGELOG、两份 Compose 和发布验证摘要均已更新。
服务器部署的私有配置可沿用，不会随源码提交或镜像发布上传。
后续最终验收文档补充只改文档，不改变已测试和发布的生产镜像。
