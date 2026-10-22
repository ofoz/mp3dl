# 部署手册（1Panel + Docker + OpenResty）

面向已有 **1Panel / Docker / OpenResty** 的 Linux 服务器，以域名 `mp3.dbas.fun` 为例。

> 仓库已公开：<https://github.com/ofoz/mp3dl> —— `git clone` 不需要任何凭据。
>
> 但**公开也意味着配置里的默认值全世界都能看到**，第 8 节的三条要求请务必执行。

---

## 0. 这套方案长什么样

```
公网用户
   │  https://mp3.dbas.fun  (443)
   ▼
OpenResty（宿主，1Panel 管理）——终止 TLS、SSE 不缓冲、超时 300s、访问日志
   │  proxy_pass http://127.0.0.1:9080
   ▼
mp3dl 容器（gunicorn 单进程 16 线程，UID 1000）
   │
   └── ./storage  ←→  /app/mp3dl/storage   （SQLite / 音频缓存 / 密钥 / 备份）
```

| 组件            | 位置             | 端口             | 职责                  |
| ------------- | -------------- | -------------- | ------------------- |
| OpenResty     | 宿主             | 80 / 443       | TLS 终止、反向代理、缓冲控制、日志 |
| mp3dl 容器      | 宿主回环           | 127.0.0.1:9080 | 全部业务逻辑              |
| SQLite + 音频缓存 | 宿主 `./storage` | —              | 持久化数据，容器重建不丢        |

### 三个不能改的设计约束

| 约束                     | 为什么                           | 破坏了会怎样                                            |
| ---------------------- | ----------------------------- | ------------------------------------------------- |
| **gunicorn 必须 `-w 1`** | 任务队列、直链缓存、限流计数、转码线程池全在进程内存    | 加 worker → 各进程状态独立：缓存互相看不见、任务进度错乱、**同一笔积分被重复扣**   |
| **端口只绑 `127.0.0.1`**   | 后端靠 `X-Forwarded-For` 识别真实 IP | 改成 `"9080:9080"` 直接暴露公网 → XFF 可随意伪造，**限流与审计全部失效** |
| **`storage/` 必须挂卷**    | 库、密钥、缓存都在里面                   | 不挂载 → 每次重建容器等于清库                                  |

需要横向扩展时，先把 `app/services/jobs.py` 的任务消费拆成独立进程，再考虑多副本。

---

## 1. 前置条件

| 项目     | 要求                                                  | 检查命令                                                        |
| ------ | --------------------------------------------------- | ----------------------------------------------------------- |
| 系统     | Linux x86_64 / aarch64（镜像基于 `python:3.13-slim` 多架构） | `uname -m`                                                  |
| Docker | 20.10+，含 compose 插件                                 | `docker compose version`                                    |
| 内存     | 1GB 起，建议 2GB                                        | `free -h`                                                   |
| 磁盘     | 系统 2GB + 缓存余量（默认上限 20GB）                            | `df -h /opt`                                                |
| 域名     | 已解析到本机公网 IP                                         | `dig +short mp3.dbas.fun`                                   |
| 出网     | 容器能访问音乐平台 API 与 GitHub                              | `docker run --rm curlimages/curl -sI https://music.163.com` |

> 1Panel 里如果装的是旧版 `docker-compose`（v1），把下文所有 `docker compose` 换成 `docker-compose` 即可。

---

## 2. 取代码

### 方式 A：git clone（推荐，便于后续 `git pull` 升级）

```bash
mkdir -p /opt/mp3dl && cd /opt/mp3dl
git clone https://github.com/ofoz/mp3dl.git .
```

国内服务器直连 GitHub 常常超时，任选一种：

```bash
# 走本机代理
git -c http.proxy=http://127.0.0.1:1080 clone https://github.com/ofoz/mp3dl.git .

# 只拉最新一次提交，体积最小
git clone --depth 1 https://github.com/ofoz/mp3dl.git .
```

> 第三方加速域名（ghproxy 之类）时好时坏，不写进本文档；网络不通时优先用下面的方式 B。

### 方式 B：下载源码包（服务器没有 git 或完全连不上 GitHub）

```bash
mkdir -p /opt/mp3dl && cd /opt/mp3dl
curl -L -o mp3dl.tar.gz https://codeload.github.com/ofoz/mp3dl/tar.gz/refs/heads/main
tar xzf mp3dl.tar.gz --strip-components=1 && rm mp3dl.tar.gz
```

### 方式 C：本机打包上传

```bash
# 本机执行（排除 storage/.venv/.git，别把本地数据库带上去）
rsync -av --exclude storage --exclude .git --exclude .venv --exclude __pycache__ \
  ./mp3dl/ root@<服务器IP>:/opt/mp3dl/
```

### 无论哪种方式，先验证依赖完整

```bash
cd /opt/mp3dl
ls vendor/musicdl/__init__.py    # 必须存在，否则启动即 ModuleNotFoundError
ls requirements.txt Dockerfile docker-compose.yml .env.example
```

`vendor/musicdl` 是音源解析库（2.4MB），以源码方式 import，**不通过 pip 安装，缺了整个站搜不了歌**。

---

## 3. 目录与权限

容器以 UID 1000（`appuser`）运行，宿主目录必须先交给它，否则 SQLite 写不进去，容器起来就崩在 `unable to open database file`。

```bash
cd /opt/mp3dl
mkdir -p storage/cache storage/tmp storage/backups
chown -R 1000:1000 storage
chmod 750 storage
```

---

## 4. 写 `.env`

```bash
cd /opt/mp3dl
cp .env.example .env
chmod 600 .env
openssl rand -hex 32        # 输出备用，下面要填进 MP3DL_SECRET
```

下面是**生产可用**的完整模板，已按 Docker + HTTPS 场景调整：

```ini
# ---------- 站点 ----------
MP3DL_SITE_NAME=MP3库
MP3DL_SLOGAN=搜歌即得 MP3，歌单一键打包

# 必须固定：换了它 = 所有登录态失效 + 已签发直链全部作废
MP3DL_SECRET=<上一步 openssl rand -hex 32 的输出>

# 走 HTTPS：让 Cookie 带 Secure、直链按 https 生成
MP3DL_SITE_HTTPS=1
MP3DL_DEBUG=0

# 容器看到的是 docker 网关 IP（172.17.0.1 / 172.18.0.1 等）。
# 默认值已覆盖 172.16.0.0/12；若你改过 docker 网段，这里要同步。
MP3DL_TRUSTED_PROXIES=127.0.0.1,::1,172.16.0.0/12,10.0.0.0/8,192.168.0.0/16

# ---------- 管理员（仅首次启动创建，之后改这里无效）----------
MP3DL_ADMIN_EMAIL=admin@dbas.fun
MP3DL_ADMIN_PASSWORD=<强密码，至少 12 位，别用示例值>

# ---------- 搜索 / 任务 ----------
MP3DL_SEARCH_SIZE=6
MP3DL_SOURCE_TIMEOUT=45
MP3DL_JOB_WORKERS=3
MP3DL_MAX_PLAYLIST=200
MP3DL_MAX_BATCH=100

# ---------- 下载 ----------
MP3DL_MP3_BITRATE=320
# 1 = MP3 让浏览器直连音源（省服务器带宽）；0 = 全部服务端中转
MP3DL_MP3_BROWSER=1

# ---------- 计费 ----------
MP3DL_BILLING=1
MP3DL_FREE_DAILY=10
MP3DL_PRICE_MP3=10
MP3DL_PRICE_TRANSCODE=10
MP3DL_PRICE_FLAC=50
MP3DL_TZ_OFFSET=8

# ---------- 缓存 ----------
# 单曲缓存保留时长（小时），从最后一次被下载起算；后台每 30 分钟清理一次
MP3DL_FILE_KEEP_HOURS=24
# 缓存总容量上限（GB），超了按 LRU 删到 80%
MP3DL_CACHE_MAX_GB=20

# ---------- 限流（每 IP）----------
MP3DL_RL_SEARCH=20
MP3DL_RL_DOWNLOAD=10
MP3DL_RL_DAILY=300
MP3DL_RL_AUTH=10
MP3DL_RL_REGISTER_DAY=3

# ---------- 卡密 ----------
MP3DL_CARD_PREFIX=MP3
MP3DL_CARD_CREDITS=100
```

### 四项必改（其余可先照抄）

| 变量                                           | 为什么必须改             | 改错的后果                                |
| -------------------------------------------- | ------------------ | ------------------------------------ |
| `MP3DL_SECRET`                               | 代码里带示例值，公开仓库人人可见   | 别人能伪造直链与封面令牌（曾实测可借它做 SSRF 打内网）       |
| `MP3DL_ADMIN_EMAIL` / `MP3DL_ADMIN_PASSWORD` | 同上，示例值是公开的         | 后台被直接登录                              |
| `MP3DL_SITE_HTTPS=1`                         | 反代后后端默认认为自己是 http  | Cookie 不带 Secure，或带了却被丢弃 → 登录成功但刷新掉线 |
| `MP3DL_TRUSTED_PROXIES`                      | 容器看到的对端是 docker 网关 | 不含该网段 → 所有用户被识别成反代 IP，**全员共享一个限流额度** |

> **管理员账号只在「库里不存在该邮箱」时创建。** 第一次启动前就要把邮箱密码填好；
>
> 之后改 `.env` 里的这两项不会生效，只能通过后台改密码接口处理。

> `MP3DL_HOST` / `MP3DL_PORT` 在 Docker 下**无效** —— 镜像里 gunicorn 固定绑 `0.0.0.0:9080`，
>
> 端口映射由 compose 的 `ports` 决定。

---

## 5. 构建并启动

```bash
cd /opt/mp3dl
docker compose up -d --build
docker compose logs -f --tail=100
```

正常日志顺序：建表 → 表结构迁移 → 创建管理员 → `Listening at: http://0.0.0.0:9080`。

验证：

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:9080/api/platforms   # 期望 200
docker compose ps                                                              # 期望 healthy
```

`/api/platforms` 返回 503 或空列表，说明音源库加载失败，先查 `docker compose logs` 里的 `musicdl` 报错。

> 构建时 pip 走阿里云镜像（`Dockerfile` 的 `ARG PIP_INDEX_URL`）。服务器在海外就改成官方源，否则反而慢：
>
> ```bash
> docker compose build --build-arg PIP_INDEX_URL=https://pypi.org/simple/ \
>                      --build-arg PIP_TRUSTED_HOST=pypi.org
> ```

### 5.1 构建卡在 `pip install` 报 DNS 失败

报错长这样：

```
NewConnectionError(... Failed to establish a new connection:
[Errno -3] Temporary failure in name resolution)
ERROR: Could not find a version that satisfies the requirement flask<4,>=3.0 (from versions: none)
```

**这不是代码或 requirements 的问题，是构建容器的 DNS 不通**。要区分两个 DNS：

| 场景                          | 谁在用           | 由谁配置                                |
| --------------------------- | ------------- | ----------------------------------- |
| `docker build` 期间的临时容器      | `pip install` | dockerd 默认（**不看** compose 的 `dns:`） |
| `docker compose up` 起来的运行容器 | 站内搜索音源        | compose 的 `dns:` 字段                 |

compose 里的 `dns: 223.5.5.5` 对**构建期完全不生效** —— 这是最常见的误判。Ubuntu 上如果 `/etc/resolv.conf` 是 `nameserver 127.0.0.53`（systemd-resolved），dockerd 会把容器 DNS 换成 `8.8.8.8`，国内基本不通，于是出现上面的报错。

按顺序排查：

```bash
# 1. 宿主自己能解析吗（能 ping 通主机名说明宿主正常）
getent hosts mirrors.aliyun.com || cat /etc/resolv.conf

# 2. 看 dockerd 有没有被注入坏 DNS
cat /etc/docker/daemon.json 2>/dev/null

# 3. 直接测构建容器的 DNS
docker run --rm busybox nslookup mirrors.aliyun.com
```

三种修法，任选：

**A. 让构建走宿主网络（本仓库已默认启用）**

`docker-compose.yml` 的 `build.network: host` 已配好，直接重跑即可：

```bash
docker compose build --no-cache
```

**B. 给 dockerd 显式指定 DNS（推荐同时做，运行容器也受益）**

```bash
cat > /etc/docker/daemon.json <<'EOF'
{
  "dns": ["223.5.5.5", "119.29.29.29"]
}
EOF
systemctl restart docker    # 会重启所有容器，选低峰期
```

**C. 兜底：宿主直接预拉依赖，构建只做 COPY**

如果服务器出网极不稳定，可以放弃构建期联网：

```bash
# 在能上网的机器上导出依赖包，拷到服务器
pip download -r requirements.txt -d wheelhouse --only-binary=:all: --platform manylinux2014_x86_64
```

然后把 `wheelhouse/` 一起 `scp` 上去，`Dockerfile` 里改成：

```dockerfile
COPY wheelhouse ./wheelhouse
RUN pip install --no-cache-dir --no-index --find-links=wheelhouse -r requirements.txt
```

> 构建成功后 `pip install` 那一层会被缓存，后续改代码重建不会再联网，所以这个问题通常只需要解决一次。

### 5.2 构建报 `requires a different python version`

```
ERROR: Ignored the following versions that require a different python version:
       2.0.0 Requires-Python >=3.12; 2.2.0 Requires-Python >=3.12
ERROR: Could not find a version that satisfies the requirement puremagic<3,>=2.1
```

这是**解释器版本太旧**：某个包的新版本抬高了 `Requires-Python` 下限，而镜像里的 Python 达不到。注意 pip 的措辞有误导性——它最后说 `from versions: 1.2, 1.3, ... 1.30`，看着像“包不存在”，实际是“2.x 全都要求 ≥3.12，你的 3.11 用不了”。

本仓库的约定：**镜像 Python 版本必须和开发环境的 `.venv` 一致**（当前都是 3.13）。改动方式：

```dockerfile
FROM python:3.13-slim      # 想换版本只改这一行，并同步 requirements 的兼容性
```

升级前建议先确认依赖都有对应轮子，避免落到源码编译（slim 镜像里没有 gcc / ffmpeg 头文件）：

```bash
# 在开发机上验证某个 Python 版本能否解析全部依赖（不真正下载）
pip download -r requirements.txt --no-deps --only-binary=:all: \
    --platform manylinux2014_x86_64 --python-version 3.13 -d /tmp/probe
```

`av` 和 `cryptography` 发布的是 `cp311-abi3` 稳定 ABI 轮子，3.11~3.13 通用；`lxml` / `orjson` / `Pillow` / `pycryptodome` / `Brotli` 都有 cp313 的 manylinux 轮子。

> `requirements.txt` 里版本区间按 **Python ≥ 3.11 都能装**来写（例如 `puremagic>=1.28,<3`：3.13 上装 2.x，3.11 上自动落到 1.30），这样即使临时把镜像降回 3.11 也不会构建失败。

---

## 6. 反代 + HTTPS

完整配置见 [`openresty-mp3.dbas.fun.conf`](./openresty-mp3.dbas.fun.conf)。1Panel 操作顺序：

1. **网站 → 创建网站**：域名 `mp3.dbas.fun`，类型「反向代理」，代理地址 `http://127.0.0.1:9080`
2. **网站设置 → HTTPS**：申请 Let's Encrypt 证书，开启「强制 HTTPS」
3. **网站设置 → 配置文件**：只把其中 `location / { ... }` 那一块，换成模板里的 `location /` 段（替换边界见 6.2）
4. 保存，OpenResty 自动重载

### 6.1 「生成的内容」指的是什么

指第 1 步创建网站时，1Panel 自动写到磁盘的那个站点配置文件：

```
/opt/1panel/apps/openresty/openresty/conf/conf.d/mp3.dbas.fun.conf
```

它大致长这样（不同 1Panel 版本细节有差异，`#SSL-START` / `#REWRITE-END` / `#SECURITY-END` 这类标记段是 1Panel 做界面化管理用的锚点，不要删）：

```nginx
server {
    listen 80;
    server_name mp3.dbas.fun;
    access_log /opt/1panel/apps/openresty/openresty/log/mp3.dbas.fun.access.log;
    error_log  /opt/1panel/apps/openresty/openresty/log/mp3.dbas.fun.error.log;

    location / {
        proxy_pass http://127.0.0.1:9080;          # 你在界面上填的代理地址
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    #SSL-START
    #SSL-END
    #REWRITE-END
    #SECURITY-END
}
```

这套默认值能让首页正常打开，但缺三样东西，正好是本项目必须的：

| 缺什么 | 后果 |
| --- | --- |
| `proxy_buffering off`（默认是 on） | SSE 流式搜索被攒批，进度条卡住后一次性弹出 |
| `proxy_read_timeout 300s`（默认 60s） | 全平台搜索、ZIP 打包超过 60s 直接 504 |
| `proxy_set_header Connection ""`（默认 `"upgrade"`） | 配合 `http/1.1` 长连接不稳定，SSE 容易断 |

所以「替换」= 把上面那个 `location / { ... }` 整块换掉，**不是整文件覆盖**。

### 6.2 替换的边界：只动一块，其余全保留

| 保留原样（1Panel 维护，动了会坏） | 需要替换 / 追加 |
| --- | --- |
| `server { }` 外框、`listen`、`server_name` | `location / { ... }` 整块 |
| `#SSL-START` … `#SSL-END`（证书路径、80→443 跳转都写在这里） | 需要 `/healthz` 探活就把模板里那段 `location = /healthz` 一起贴到 `location /` 后面 |
| `.well-known` / `acme-challenge` 校验段（删了证书续期失败） | |
| `access_log` / `error_log` | |

> **最容易踩的坑**：在编辑器里全选粘贴整个模板文件。这样会覆盖 SSL 段和 acme 校验段 —— 表现是 443 不再监听、Let's Encrypt 续期失败，而站点本身看起来「还好好的」。

### 6.3 更省事的做法：不整块替换，只补 4 行

如果你不想动结构，就在 1Panel 生成的那个 `location / { ... }` 里做 4 处改动，效果等价：

```nginx
    location / {
        proxy_pass http://127.0.0.1:9080;
        # ……1Panel 原有的 set_header 保留……

        proxy_http_version 1.1;
        proxy_set_header Connection        "";      # 改：原值是 "upgrade"
        proxy_buffering         off;                # 加
        proxy_request_buffering off;                # 加
        proxy_read_timeout      300s;               # 改：原值 60s

        # 若这里出现过 proxy_buffering on / proxy_cache on，删掉
    }
```

改完点「保存」，1Panel 会自动 `openresty -t` 校验并重载；报错会直接显示在弹窗里，按提示改回即可。

### 四项必配指令

| 指令                                            | 作用                          | 漏了的症状                                  |
| --------------------------------------------- | --------------------------- | -------------------------------------- |
| `proxy_set_header Host $host;`                | 后端用 `request.host_url` 生成直链 | 下载地址变成 `http://127.0.0.1:9080/...`     |
| `proxy_set_header X-Forwarded-Proto $scheme;` | 后端 `ProxyFix` 据此判断 HTTPS    | 登录成功但刷新掉线（Cookie 带 Secure 却在 HTTP 下传输） |
| `proxy_buffering off;`                        | SSE 流式搜索逐个推送                | 进度条卡住，最后一次性弹出全部结果                      |
| `proxy_read_timeout 300s;`                    | 实测单平台搜索约 30s，全平台更久          | 默认 60s 直接 504                          |


另外 `X-Forwarded-For` 必须用 `$proxy_add_x_forwarded_for`（**追加**，不是覆盖），否则真实 IP 丢失。

> gunicorn 的 `--timeout 180` 与反代的 `proxy_read_timeout 300` 是配套的：
>
> 反代等得更久，是为了让 gunicorn 有机会正常返回而不是被反代先掐断。
>
> 若你把 `MP3DL_SOURCE_TIMEOUT` 调大，这两个值要一起加。

---

## 7. 上线验收

```bash
# 1. 证书与跳转
curl -sI https://mp3.dbas.fun/ | head -3           # 期望 200，或 301 到 https
curl -sI http://mp3.dbas.fun/ | grep -i location   # 期望 301 到 https

# 2. 反代链路
curl -s -o /dev/null -w "%{http_code}\n" https://mp3.dbas.fun/api/platforms   # 期望 200
```

浏览器侧逐项过一遍：

| #  | 检查项              | 期望                                     |
| -- | ---------------- | -------------------------------------- |
| 1  | 注册新账号            | 成功，且同 IP 第 4 次注册被拒（429）                |
| 2  | 登录后刷新页面          | 仍是登录态（不是掉线）                            |
| 3  | 搜索「稻香」           | 进度逐一出现（不是最后一次性冒出）                      |
| 4  | 点播放              | 能出声；Network 里音频地址是**源站 CDN**，不是本站      |
| 5  | 下载 MP3           | 文件可播，ID3 有标题/封面                        |
| 6  | 下载 FLAC          | 扣 50 积分；若提示「源站不支持加密直连，已改为服务端中转」，说明走了中转 |
| 7  | 下载后看后台「今日下载」     | 数字 +1，积分按规则减少                          |
| 8  | 后台 → 卡密 → 生成     | 能生成，格式 `MP3-XXXX-XXXX-XXXX`            |
| 9  | 退出登录再访问 `/admin` | 被踢回首页或提示无权限                            |
| 10 | 在手机上打开           | 顶栏不溢出，账号菜单可用                           |

第 4 项最关键：如果音频地址是 `https://mp3.dbas.fun/api/dl/...` 而不是源站域名，说明直连降级了，检查 `Host` 头是否透传。

---

## 8. 仓库公开后的三条额外要求

代码和默认配置现在全世界可见，攻击者知道白名单结构、限流阈值、令牌格式。下面的措施是**必做**，不是建议。

**① `.env` 永远不要提交**

`.gitignore` 已排除 `.env`、`storage/`，但别手动 `git add -f`。如果你 fork 了自己的副本再推回公开仓库，先确认：

```bash
cd /opt/mp3dl
git status --short | grep -E "\.env|storage/" || echo "干净"
```

**② 收紧限流（默认值是按公开站设的，可再紧一点）**

```ini
MP3DL_RL_SEARCH=10        # 默认 20
MP3DL_RL_DOWNLOAD=6       # 默认 10
MP3DL_RL_REGISTER_DAY=1   # 默认 3，防批量注册小号薅免费额度
```

**③ 管理员邮箱别用可猜的**

`admin@` / `root@` 这类前缀配上公开仓库里的默认配置，等于把用户名直接告诉别人。用个不常见的邮箱，密码 16 位以上随机串。

另外：公开仓库的**代码不会自动同步到你的服务器**。有人提交 PR 也不会影响你，除非你主动 `git pull`。所以升级前先看一眼提交记录：

```bash
cd /opt/mp3dl && git log --oneline -5
```

---

## 9. 日常运维

### 升级

```bash
cd /opt/mp3dl
git pull
docker compose up -d --build
docker compose logs -f --tail=50
```

`storage/` 是挂载卷，重建容器不丢数据；表结构迁移在启动时自动执行。

如果 `git pull` 报冲突（通常是你在服务器上直接改过源码）：先 `git stash` 或 `git checkout -- .` 丢弃本地改动，再拉取。**配置文件走 `.env`，不需要改源码**。

### 备份

完整备份（数据库 + `.secret_key` + 缓存索引 + 备份文件）：

```bash
cd /opt/mp3dl
docker compose stop
tar czf /root/mp3dl-$(date +%F).tar.gz storage/
docker compose start
```

只备份数据库（在线，不中断服务）：

```bash
docker compose exec mp3dl python -c "
import sqlite3
s = sqlite3.connect('storage/mp3dl.db')
d = sqlite3.connect('/tmp/bak.db')
s.backup(d); d.close()"
docker cp mp3dl:/tmp/bak.db ./mp3dl-$(date +%F).db
```

### 恢复

```bash
cd /opt/mp3dl
docker compose down
rm -rf storage
tar xzf /root/mp3dl-YYYY-MM-DD.tar.gz          # 解出 storage/
chown -R 1000:1000 storage
docker compose up -d
```

> `storage/.secret_key` 一定要跟着一起备份。丢了它不丢数据，但所有用户被踢下线、已发出的直链全部失效。

### 清空业务数据（保留管理员）

```bash
docker compose exec mp3dl python tools/clean_test_data.py          # 预览，不动数据
docker compose exec mp3dl python tools/clean_test_data.py --yes    # 执行（自动备份到 storage/backups/）
```

会清掉所有非管理员账号及其任务、扣费、积分流水、卡密、下载日志、限流计数，并清空音频缓存。

> 别在生产库上跑 `tests/test_security.py`：它会注册账号、发卡密、充值，跑完记得清一次。

### 日志与资源

```bash
docker compose logs -f --tail=100      # 应用日志（JSON 轮转 20MB × 3）
du -sh storage/cache storage/mp3dl.db  # 缓存与库体积
docker stats mp3dl --no-stream         # CPU / 内存 / 网络
```

---

## 10. 故障排查

| 症状                                                                           | 原因                                                   | 处理                                                                           |
| ---------------------------------------------------------------------------- | ---------------------------------------------------- | ---------------------------------------------------------------------------- |
| 下载/播放地址是 `http://127.0.0.1:9080/...`                                         | 反代没传 `Host`                                          | 加 `proxy_set_header Host $host;`                                             |
| 登录成功，刷新后变未登录                                                                 | 后端认为不是 HTTPS，Cookie 带 Secure 被浏览器丢弃                  | 补 `X-Forwarded-Proto $scheme`，`.env` 设 `MP3DL_SITE_HTTPS=1`                  |
| 全员共用一个限流额度，后台 IP 全是 `172.x`                                                  | `MP3DL_TRUSTED_PROXIES` 未包含 docker 网段，或 XFF 用了覆盖而非追加 | 网段写进配置，XFF 改 `$proxy_add_x_forwarded_for`                                    |
| 搜索进度条卡住，最后一次性出现                                                              | `proxy_buffering on`                                 | 关闭缓冲                                                                         |
| 搜索 / 打包 504                                                                  | `proxy_read_timeout` 太短                              | 调到 300s，并确认 gunicorn `--timeout 180`                                         |
| 容器反复重启，日志 `unable to open database file`                                     | `storage` 属主不是 1000                                  | `chown -R 1000:1000 storage`                                                 |
| 启动报 `ModuleNotFoundError: musicdl`                                           | `vendor/` 没传完整                                       | 确认 `vendor/musicdl/__init__.py` 存在                                           |
| 构建报 `Ignored the following versions that require a different python version` | 镜像 Python 版本低于依赖要求                                   | 见 [5.2](#52-构建报-requires-a-different-python-version)，镜像与 `.venv` 版本对齐        |
| 构建时 `pip install` 报 `Temporary failure in name resolution`                   | 构建容器 DNS 不通，compose 的 `dns:` 不管构建期                   | 见 [5.1](#51-构建卡在-pip-install-报-dns-失败)，`build.network: host` + dockerd 配 DNS |
| 搜索全部平台超时                                                                     | 容器 DNS 不稳                                            | 确认 compose 的 `dns: 223.5.5.5 / 119.29.29.29` 生效，或换 `8.8.8.8`                 |
| 封面不显示                                                                        | 目标 CDN 不在白名单                                         | 域名后缀加进 `MP3DL_COVER_HOSTS`                                                   |
| 某平台搜不到歌 / 报签名错误                                                              | 平台接口变更                                               | 查 `/api/health`，把 `app/services/platforms.py` 里该平台的 `enabled` 置 false        |
| 改 `.env` 后不生效                                                                | compose 只在创建容器时读 `env_file`                          | `docker compose up -d` 重建容器（不是 `restart`）                                    |
| 后台打不开、提示无权限                                                                  | 当前账号不是管理员                                            | 用 `.env` 里配的管理员邮箱登录                                                          |

---

## 11. 安全与容量

- **不要**把 `ports` 改成 `"9080:9080"`。容器一旦直接对公网，`X-Forwarded-For` 就变可伪造，限流和审计全部失效。
- **不要**给 gunicorn 加 worker。原因见第 0 节。
- 1Panel 防火墙只放行 80/443，`9080` 保持仅回环。
- 缓存上限 `MP3DL_CACHE_MAX_GB` 按磁盘余量设；`MP3DL_FILE_KEEP_HOURS`（默认 24）控制单曲缓存从最后一次被下载起保留多久，超了按 LRU 删到 80%。
- 定期看 `storage/mp3dl.db` 体积，长期运行后明显膨胀就停服执行一次 `VACUUM`。
- 需要挂 CDN（Cloudflare 等）时：`MP3DL_TRUSTED_PROXIES` 要加上 CDN 回源网段，否则用户 IP 全变成 CDN 节点。

### 容量估算

| 项目       | 单首    | 20GB 上限约能存 |
| -------- | ----- | ---------- |
| MP3 320k | ~8MB  | 2500 首     |
| FLAC     | ~30MB | 660 首      |

注意 MP3 默认让浏览器直连音源，服务器**不落盘**；只有 FLAC 的混合内容降级、以及需要转码的平台才会写缓存。

---

## 12. 卸载

```bash
cd /opt/mp3dl
docker compose down --rmi local        # 停容器 + 删镜像（不删数据）
# 确认不再需要数据后再删：
rm -rf /opt/mp3dl
```

同时在 1Panel 里删除 `mp3.dbas.fun` 网站与证书。
