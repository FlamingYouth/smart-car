FROM python:3.9-slim@sha256:2d97f6910b16bd338d3060f261f53f144965f755599aab1acda1e13cf1731b1b
LABEL org.opencontainers.image.version="5.1"
LABEL org.opencontainers.image.source="https://github.com/FlamingYouth/smart-car"

# 设置工作目录
WORKDIR /app

# 复制requirements.txt并安装Python依赖
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

# 复制应用代码
COPY main.py wechat_client.py telegram_client.py notification_client.py \
     mqtt_listener.py database_manager.py task_scheduler.py ./
COPY config.yaml ./
COPY scripts/ ./scripts/

# 创建日志目录和非root用户
RUN useradd -m -u 1000 tesla \
    && mkdir -p /app/logs \
    && chown -R tesla:tesla /app
USER tesla

# 启动命令
CMD ["python", "main.py"]
