# 构建上下文就是 mp3dl 目录本身（vendor/musicdl 随仓库提供，无外部依赖）
#   docker build -t mp3dl .
#   docker compose up -d --build

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

# PyPI 源可在构建时覆盖（海外服务器换成官方源）：
#   docker compose build --build-arg PIP_INDEX_URL=https://pypi.org/simple/ \
#                        --build-arg PIP_TRUSTED_HOST=pypi.org
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ARG PIP_TRUSTED_HOST=mirrors.aliyun.com
RUN pip config set global.index-url "$PIP_INDEX_URL" && \
    pip config set global.trusted-host "$PIP_TRUSTED_HOST" && \
    pip config set global.timeout 60 && \
    pip config set global.retries 10

WORKDIR /app/mp3dl

# 依赖单独一层，改代码不触发重装
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 音源解析库以源码方式 import（不 pip 安装）：vendor/musicdl
COPY vendor ./vendor
COPY app ./app
COPY web ./web
COPY tools ./tools
COPY run.py ./

# 运行期目录 + 非 root 用户（UID 1000，对应宿主 chown 1000:1000）
RUN mkdir -p storage/cache storage/tmp storage/backups \
 && useradd -u 1000 -m -s /bin/sh appuser \
 && chown -R appuser:appuser /app/mp3dl/storage

USER appuser

EXPOSE 9080

HEALTHCHECK --interval=30s --timeout=6s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:9080/api/platforms')" || exit 1

# 必须单进程多线程：任务队列、曲目缓存、限流计数都在进程内存里，
# 加 worker 会导致跨进程状态不一致（重复扣费、任务状态错乱）。
CMD ["gunicorn", "-w", "1", "-k", "gthread", "--threads", "16", \
     "--timeout", "180", "--graceful-timeout", "30", \
     "-b", "0.0.0.0:9080", "--access-logfile", "-", "run:app"]
