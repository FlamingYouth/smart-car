# Tesla 通知：企业微信 / Telegram

基于 TeslaMate 的只读通知程序，通过 MQTT 接收车辆状态、查询 PostgreSQL，
向企业微信群机器人和 Telegram 发送消息。两个渠道独立使用
`enabled: true/false` 开关，可以只开一个，也可以同时开启；其中一个失败仍尝试另一个。
企业微信继续使用原 Webhook，Telegram 可单独配置 HTTP/SOCKS5 代理。

现有通知模板的文字、emoji、换行、标题和统计内容保持不变。
`5.0` 的日报、周报、月报与其他通知一样，统一使用群机器人普通文本 `text`，
不再使用 Markdown 或应用卡片。原标题、正文、emoji、换行和统计数字保留；
恢复详情网址，末尾为 `查看详情：https://…`，不使用 `[文字](网址)` 标记。
网址来自 `scheduler.grafana_url`，程序只把它放进通知，不访问 Grafana。
具体变更见 [版本记录](CHANGELOG.md)，真实微信显示仍以客户端实际结果为准。

## 项目公开说明

这个项目约一年前开始编写。作者在自己的使用环境中持续测试，
确认原有功能稳定后，才在一年后整理公开。
5.0 在原企业微信通知基础上添加 Telegram，不改变车辆事件、统计查询、
通知模板、日报时间、阈值或其他 TeslaMate 服务。发布前使用本机 Docker
进行离线回归、真实 HTTP 回环检查，并向授权 Telegram 机器人逐条试发全部样例。
当前通知镜像发布标签为 `5.0`；这不是 TeslaMate 等其他组件的升级版本号。
具体测试范围见 [测试报告](TEST_REPORT.md)。

GitHub 源码：[FlamingYouth/smart-car](https://github.com/FlamingYouth/smart-car)。
GitHub Packages：[smart-car-tesla-notifier](https://github.com/users/FlamingYouth/packages/container/package/smart-car-tesla-notifier)。

## 当前实际发送的通知

- 系统启动、系统关闭。
- 充电完成、充电停止（有详细数据时使用详细模板，否则使用简化模板）。
- 软件更新提醒（TeslaMate MQTT 事件触发）。
- 车内过高/过低、环境过高/过低四种温度告警。
- 行程完成（原电量百分比模板及缺少电量数据时的 kWh 模板）。
- 昨日总结、上周总结、上月总结。

车辆休眠/唤醒当前只记日志，车门通知已移除，“开始充电”等旧配置项
尚没有实际发送流程。这次没有恢复这些功能，也没有改变统计算法或增加车辆控制。
三种统计报告目前显示行驶次数、充电次数、行驶里程、充入电量和平均车速，
不会额外显示费用、家充比例或电池健康。

## 配置

需要 Python 3.9+，推荐直接使用 Docker。正式运行还需要现有 TeslaMate 的
PostgreSQL 和 MQTT，程序不包含 TeslaMate，也不提供网页界面。

在企业微信电脑版中打开目标内部群，添加群机器人并复制 Webhook。
妥善保管完整地址，它相当于这个机器人的发送密钥。

首次部署：

```bash
cp config.yaml config-prod.yaml
cp .env.example .env
```

已经存在私有配置时不要用以上复制命令覆盖。

在 `config-prod.yaml` 中设置：

```yaml
wechat:
  enabled: true
  webhook_url: "" # 在本地填完整群机器人 Webhook

telegram:
  enabled: true
  bot_token: ""   # 在私有文件中填 BotFather 提供的 Token
  chat_id: ""     # 接收者的数字 Chat ID
  proxy: ""       # 留空直连；支持 http/https/socks5/socks5h

database:
  host: "your-db-host"
  port: 5432
  database: "teslamate"
  user: "teslamate"
  password: "your-db-password"

mqtt:
  host: "your-mqtt-host"
  port: 1883
  user: null
  password: null

scheduler:
  timezone: "Asia/Shanghai"
  grafana_url: "https://grafana.example.com/"
```

开关使用 YAML 的 `true` / `false`，不要加引号。为兼容旧私有配置，
未填写 `wechat.enabled` 时默认开启企业微信，未填写 `telegram.enabled` 时默认关闭 Telegram。
关闭的渠道无需填写凭据，两个都关闭时继续监控而不发送通知。

也可以在私有 `.env` 文件设置 `WECHAT_ENABLED`、`WECHAT_WEBHOOK_URL`、
`TELEGRAM_ENABLED`、`TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`、`TELEGRAM_PROXY`。
非空环境变量优先于 YAML；空环境变量不会抹掉 YAML 配置；环境开关同样填 `true` / `false`。

私聊收件人先向对应机器人发送 `/start`，再填写数字 Chat ID；不能用个人 `@用户名` 代替。
Telegram 保持原通知的普通文本、emoji 和详情网址，不启用 Markdown/HTML 解析。
[Telegram Bot API](https://core.telegram.org/bots/api#sendmessage)

代理只对 Telegram 生效，企业微信继续直连。服务器可按实际情况填写
`socks5h://127.0.0.1:7897`；本机 Docker Desktop 访问宿主机代理时填写
`socks5h://host.docker.internal:7897`。`127.0.0.1` 在容器内指容器本身。
`socks5h` 由代理解析域名，镜像已含 PySocks，无需另外安装。
[Requests SOCKS 配置](https://requests.readthedocs.io/en/latest/user/advanced/#socks)

旧 `WECHAT_CORPID`、`WECHAT_CORPSECRET`、`WECHAT_AGENTID`、
`WECHAT_TOUSER`、`WECHAT_PROXY` 不再使用，旧 `target_users` 不再决定收件人；
消息发到 Webhook 所属的群，不默认 @所有人。

`config.yaml` 是无密钥的公开示例，也是镜像中的默认配置。
`config-prod.yaml`、`.env*`、`.private/`、`private-backups/` 被排除在 Git 和镜像之外。
不要把真实凭据写进公开文件，或直接把整个目录复制进镜像。
Linux 上只读挂载的生产配置仍需要容器内 UID 1000 可读取；例如仅对该文件
设置 `chown 1000:1000 config-prod.yaml` 和 `chmod 600 config-prod.yaml`。
这是主机文件权限操作，不是容器启动命令。

## 先测试通知

以下命令只发送通知，不连接车辆、PostgreSQL 或 MQTT。私有配置先设置好渠道开关、
Webhook、Token、Chat ID 和容器可用的代理，再只读挂载：

```bash
docker run --rm --user "$(id -u):$(id -g)" \
  -v "$PWD/config-prod.yaml:/app/config.yaml:ro" \
  registry.cn-hangzhou.aliyuncs.com/bigbey/smart-car-tesla-notifier:5.0 \
  python main.py --test-notifications
```

`--test-wechat` 只测试企业微信，`--test-telegram` 只测试 Telegram；
关闭的渠道不会被测试命令强行启用。只测通知时不要使用 `start.sh --test`，
该旧启动脚本还会检查数据库和 MQTT。

一次发送全部现有模板的模拟样例：

```bash
docker run --rm --user "$(id -u):$(id -g)" \
  -v "$PWD/config-prod.yaml:/app/config.yaml:ro" \
  registry.cn-hangzhou.aliyuncs.com/bigbey/smart-car-tesla-notifier:5.0 \
  python scripts/send_notification_samples.py --send
```

每个启用渠道会收到一条说明及 16 条样例，覆盖 9 类实际通知。
车辆、地址、温度、行程、充电数据在内存中模拟；生产模板正文没有改动。
测试进程临时关闭样例冷却和去重，不更改 YAML 中的生产设置。

不加 `--send` 只预览；`--channel telegram` / `--channel wechat` 可只选一个已启用渠道，
`--only daily_summary` 可只发某一类，`--only temperature_inside_high` 可只发一个分支。
测试前后至少间隔一分钟，避免机器人服务端限流。

## 正式 Docker 部署

先完成上述试发，确认后再接入自己的数据库和 MQTT：

`5.0` 的发布地址：

```text
registry.cn-hangzhou.aliyuncs.com/bigbey/smart-car-tesla-notifier:5.0
```

GitHub Packages 备用镜像地址：

```bash
docker pull ghcr.io/flamingyouth/smart-car-tesla-notifier:5.0
```

`5.0` 已在阿里云和公开 GitHub Packages 发布，并关联本仓库。
AMD64、ARM64 的匿名反向拉取均已验证；两边镜像清单摘要完全相同。
本地 Docker 与 GitHub 原生双架构各通过 135 项完整回归，具体范围见 [测试报告](TEST_REPORT.md)。

Packages 发布流程从已测试的阿里云镜像摘要同步，不重新构建生产镜像。
两个平台在 GitHub 上再次进行源码摘要、依赖检查、离线回归和 HTTP 测试；
全部通过后才同步所有架构，并校验两个仓库的镜像清单摘要完全相同。
发布使用仓库级临时授权，不需要把 Docker 密码或个人 Token 写进源码。
需要自行发布时，在 GitHub Actions 中手动运行 `Verify and mirror tested container 5.0`；
普通源码提交不会自动发布镜像。新 Packages 默认私有，发布后需在包设置中改为公开，
并确认源码仓库关联；首次发布的具体结果见 TEST_REPORT.md。

同一标签支持 `linux/amd64` 和 `linux/arm64`，拉取时自动选择架构；
两种镜像使用相同应用源码、锁定的运行依赖版本，并分别完成容器回归测试。
旧 `4.0` / `4.1` 保留供回退，不覆盖旧标签。
旧的本机测试别名对应历史版本；测试新版请使用 `5.0`。

服务器直接拉取镜像，无需重新构建。确保私有配置已设置，文件可被容器 UID 1000 读取：

```bash
docker compose pull tesla-notifier
docker compose up -d --no-deps --no-build tesla-notifier
docker compose logs -f tesla-notifier
```

较旧环境使用 `docker-compose` 代替 `docker compose`。
仓库根目录的 Compose 使用上述阿里云 `5.0` 镜像，只读挂载私有配置，
并检查核心服务启动后的健康标记。需要自己从源码构建时，另执行 `docker compose build`。
不要在测试阶段运行正式 Compose 启动命令：它会接入已配置的真实服务。

`server-deploy/docker-compose.yml` 是作者提供的完整 TeslaMate 部署配置，
通知服务使用 `5.0`，其余服务、端口、卷与网络保持作者提供的配置。
服务器专用私有 `server-deploy/config-prod.yaml` 与该 Compose 放在同一目录，
数据库地址为 `database:5432`、MQTT 为 `mosquitto:1883`；不要混用根目录的本机连接配置。
完整 Webhook 与数据库密码只能保存在自己的私有文件中，不能提交公开仓库。
TeslaMate 的 `NOMINATIM_PROXY` 是地址查询相关配置，
不属于已移除的微信通知代理，本次保持不动。

## 通知开关和频率

```yaml
notifications:
  temperature_alert:
    enabled: true
    rate_limit_seconds: 300
    enable_dedup: true
  daily_summary:
    enabled: true
    send_hour: 22
  weekly_summary:
    enabled: true
    send_day: 0
    send_hour: 9
  monthly_summary:
    enabled: true
    send_day: 1
    send_hour: 9

temperature_alerts:
  inside_temp_min: -10.0
  inside_temp_max: 60.0
  outside_temp_min: -30.0
  outside_temp_max: 50.0
```

按类型、车辆独立冷却/去重，传输失败不记为成功。
为保留旧接口行为，禁用、冷却或重复消息的跳过返回 True，
不代表额外发出了一条消息。测试工具使用的全部样例已关闭这类跳过。

每个渠道的客户端独立冷却、去重，并且每滚动分钟最多尝试 18 次请求，
包括失败和超长消息分段。Telegram 同一 Chat ID 的请求至少间隔 1.1 秒。
这是本进程的安全上限，不是跨进程共享限额；同一机器人不要并行跑多个实例。
超出限额立即返回失败，不排队，不自动补发。
网络/API 错误不自动重试，避免超时后重复通知；
后续不同事件仍可尝试发送。若手工重试一次部分成功的超长消息，
已收到的前半部分可能重复。
当前所有通知使用普通文本。企业微信按 UTF-8 字节最多 2048 分段，
Telegram 为遵守 4096 字符上限，按 4096 UTF-8 字节保守分段，字符不会被截断。
这些限制见[官方连接器说明](https://support.huaweicloud.com/usermanual-codeartslink/codeartslink_03_0053.html)；
机器人服务端频率限制见[腾讯云官方说明](https://cloud.tencent.com/document/product/248/50413)。

## 排错和测试

企业微信只接受官方 HTTPS Webhook；Telegram 只请求官方 Bot API。
两者不跟随重定向、不使用 HTTP_PROXY / HTTPS_PROXY / ALL_PROXY；
Telegram 只使用 YAML 或 TELEGRAM_PROXY 显式配置的代理。企业微信不请求应用 Token。
企业微信在 HTTP 200 且 JSON 的整数 `errcode=0` 时才算发送成功。
Telegram 仅在 HTTP 200、`ok=true` 且返回匹配 Chat ID 的实际消息后记为成功。
通知传输日志不打印 Webhook、Bot Token、异常原文或可能含密钥的响应正文。
如失败，检查机器人是否还在目标群、地址是否有效、服务端限流和容器网络，
不要为了排错把密钥贴进公开日志或 Issue。

执行离线回归测试：

```bash
pip install -r requirements-dev.txt
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python tests/run_offline.py
```

在相同生产镜像基础上做 Docker 回归：

```bash
docker build -t codex-smart-car-runtime:5.0 .
docker build --build-arg BASE_IMAGE=codex-smart-car-runtime:5.0 \
  -f tests/Dockerfile -t codex-smart-car-tests:5.0 .
docker run --rm --network none \
  -e PYTHONDONTWRITEBYTECODE=1 -e PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  -v "$PWD/tests:/app/tests:ro" \
  codex-smart-car-tests:5.0 python tests/run_offline.py
```

测试覆盖：双渠道开关、同时发送与失败隔离、Telegram 代理及限速、
Token 隐藏、原发送协议、空环境变量、企业微信无代理、非法 Webhook、
HTTP/API/JSON/网络失败、去重、按车限流、并发、全局频率、超长 Unicode、
三种普通文本报告、恢复的详情网址、2048 字节报告分段，
以及原来的 MQTT/统计/时区/健康检查回归。
单元测试用模拟服务，不代表真实 TeslaMate 或真实车辆联调已完成。
