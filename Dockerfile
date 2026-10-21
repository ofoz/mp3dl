# 构建上下文必须是工作区根目录（需要 musicdl-src）
# docker build -f mp3dl/Dockerfile -t mp3dl .
# 或直接：cd mp3dl && docker compose up -d --build

FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai

RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && \
    pip config set global.trusted-host mirrors.aliyun.com

COPY mp3dl/requirements.txt /app/mp3dl/requirements.txt
RUN pip install --no-cache-dir -r /app/mp3dl/requirements.txt

# 音源解析库（不安装，直接以源码方式 import）
COPY musicdl-src /app/musicdl-src
COPY mp3dl /app/mp3dl

RUN mkdir -p /app/mp3dl/storage/cache /app/mp3dl/storage/tmp

WORKDIR /app/mp3dl
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=6s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/api/platforms')" || exit 1

# 单进程 + 多线程：任务队列与曲目缓存都在进程内，不要加 worker
CMD ["gunicorn", "-w", "1", "-k", "gthread", "--threads", "16", \
     "--timeout", "180", "--graceful-timeout", "30", \
     "-b", "0.0.0.0:8080", "--access-logfile", "-", "run:app"]
