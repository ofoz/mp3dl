# 部署方案（1Panel + Docker + OpenResty）

面向已有 **1Panel / Docker / OpenResty** 的 Linux 服务器，域名 `mp3.dbas.fun`。
整体结构：

```
公网 → OpenResty（宿主，终止 TLS）→ 127.0.0.1:8080 → mp3dl 容器（gunicorn 单进程 16 线程）
                                                        └── ./storage 挂载到宿主
```

容器只监听宿主回环，不对公网暴露端口；TLS、限流、访问日志都交给 OpenResty。

---

## 0. 前置条件

| 项目 | 要求 |
|---|---|
| 系统 | Linux x86_64（aarch64 亦可，镜像基于 `python:3.11-slim` 多架构） |
| Docker | 20.10+，含 `docker compose` 插件 |
| 磁盘 | 系统 + 缓存各留余量，默认缓存上限 20GB（`MP3DL_CACHE_MAX_GB`） |
| 内存 | 1GB 起，建议 2GB（16 线程 × 每请求峰值，主要看并发下载） |
| 域名 | `mp3.dbas.fun` 已解析到本机公网 IP |

---

## 1. 取代码

仓库是私有的，两种方式二选一。

**方式 A：用 GitHub Token 克隆**

```bash
mkdir -p /opt/mp3dl && cd /opt/mp3dl
git clone https://<用户名>:<PAT>@github.com/ofoz/mp3dl.git .
```

**方式 B：本地打包上传**

```bash
# 本机执行（注意排除 storage，它不该上服务器前的旧数据）
rsync -av --exclude storage --exclude .git --exclude .venv \
  ./mp3dl/ root@<服务器IP>:/opt/mp3dl/
```

> 代码必须**完整包含 `vendor/` 目录**，音源解析库以源码方式引入，缺了它启动就会 ImportError。

---

## 2. 准备目录与权限

容器以 UID 1000（`appuser`）运行，宿主目录要先交给它，否则 SQLite 写不进去、容器起来就崩。

```bash
cd /opt/mp3dl
mkdir -p storage/cache storage/tmp storage/backups
chown -R 1000:1000 storage
chmod 750 storage
```

---

## 3. 写 `.env`

```bash
cp .env.example .env
openssl rand -hex 32          # 复制输出备用
```

下面这份是**生产可用**的完整模板，关键项已按 Docker + HTTPS 场景改好：

```ini
# ---------- 站点 ----------
MP3DL_SITE_NAME=MP3库
MP3DL_SLOGAN=搜歌即得 MP3，歌单一键打包

# 32 字节随机串，必须固定：换了它 = 所有登录态失效 + 已签发的直链全部作废
MP3DL_SECRET=<上一步 openssl 生成的字符串>

# 走 HTTPS，让 Cookie 带 Secure、直链按 https 生成
MP3DL_SITE_HTTPS=1
MP3DL_DEBUG=0

# 容器内看到的是 docker 网关 IP（172.17.0.1 / 172.18.0.1 等），
# 默认值已覆盖 172.16.0.0/12；若你改过 docker 网段，这里要同步改
MP3DL_TRUSTED_PROXIES=127.0.0.1,::1,172.16.0.0/12,10.0.0.0/8,192.168.0.0/16

# ---------- 管理员（仅首次启动创建，之后改这里无效）----------
MP3DL_ADMIN_EMAIL=admin@dbas.fun
MP3DL_ADMIN_PASSWORD=<一个强密码，至少 12 位>

# ---------- 搜索 / 任务 ----------
MP3DL_SEARCH_SIZE=6
MP3DL_SOURCE_TIMEOUT=45
MP3DL_JOB_WORKERS=3
MP3DL_MAX_PLAYLIST=200
MP3DL_MAX_BATCH=100

# ---------- 下载 ----------
MP3DL_MP3_BITRATE=320
# 1 = MP3 浏览器直连音源（省服务器带宽）；0 = 全部服务端中转
MP3DL_MP3_BROWSER=1

# ---------- 计费 ----------
MP3DL_BILLING=1
MP3DL_FREE_DAILY=10
MP3DL_PRICE_MP3=10
MP3DL_PRICE_TRANSCODE=10
MP3DL_PRICE_FLAC=50
MP3DL_TZ_OFFSET=8

# ---------- 缓存 ----------
MP3DL_CACHE_TTL_HOURS=48
MP3DL_FILE_KEEP_HOURS=24
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

> `MP3DL_HOST` / `MP3DL_PORT` 在 Docker 下**无效**——镜像里 gunicorn 固定绑 `0.0.0.0:8080`，
> 端口映射由 compose 的 `ports` 决定。

---

## 4. 构建并启动

```bash
cd /opt/mp3dl
docker compose up -d --build
docker compose logs -f --tail=100
```

正常会看到建表、迁移、管理员创建，最后是 gunicorn 的 `Listening at: http://0.0.0.0:8080`。

验证容器内链路：

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/api/platforms   # 期望 200
docker compose ps                                                              # 期望 healthy
```

---

## 5. OpenResty 反代 + HTTPS

完整配置见 [`deploy/openresty-mp3.dbas.fun.conf`](./openresty-mp3.dbas.fun.conf)，1Panel 操作顺序：

1. **网站 → 创建网站**：域名 `mp3.dbas.fun`，类型选「反向代理」，代理地址 `http://127.0.0.1:8080`
2. **网站设置 → HTTPS**：申请 Let's Encrypt 证书，开启「强制 HTTPS」
3. **网站设置 → 配置文件**：把模板里的 `location /` 段落替换上去
4. 保存后 OpenResty 会自动重载

配置里**必须有的四项**（漏任一项都会出问题，对应症状见第 8 节）：

| 指令 | 作用 |
|---|---|
| `proxy_set_header Host $host;` | 后端靠它生成直链；传错则下载地址变成 `127.0.0.1` |
| `proxy_set_header X-Forwarded-Proto $scheme;` | 后端 `ProxyFix` 据此判断 HTTPS，决定 Cookie 是否加 Secure |
| `proxy_buffering off;` | SSE 流式搜索不缓冲，否则前端进度「卡住后一次性出现」 |
| `proxy_read_timeout 300s;` | 实测单平台搜索约 30s，默认 60s 会 504 |

---

## 6. 上线后验收

```bash
# 1. 域名解析与证书
curl -sI https://mp3.dbas.fun/ | head -3

# 2. 直链生成的 Host 是否正确（关键：不能出现 127.0.0.1）
#    登录后点任意歌曲播放，浏览器 Network 里看 /api/download 返回的 url 前缀
#    应为 https://mp3.dbas.fun/...  而不是 http://127.0.0.1:8080/...

# 3. Cookie 是否带 Secure
curl -sI https://mp3.dbas.fun/ | grep -i set-cookie

# 4. 限流是否按真实 IP 生效（换手机流量访问，触发搜索频率限制，应返回 429）
```

网页侧逐项确认：注册 → 登录 → 搜索 → 播放 → 下载 → 积分扣减 → 后台登录。

---

## 7. 日常运维

**升级**

```bash
cd /opt/mp3dl
git pull
docker compose up -d --build
docker compose logs -f --tail=50
```

`storage/` 是挂载卷，重建容器不丢数据；表结构迁移在启动时自动执行。

**备份**（含数据库、`.secret_key`、缓存索引）

```bash
cd /opt/mp3dl
docker compose stop
tar czf /root/mp3dl-$(date +%F).tar.gz storage/
docker compose start
```

只备份数据库（在线、不中断服务）：

```bash
docker compose exec mp3dl python -c "
import sqlite3; s=sqlite3.connect('storage/mp3dl.db'); d=sqlite3.connect('/tmp/bak.db')
s.backup(d); d.close()"
docker cp mp3dl:/tmp/bak.db ./mp3dl-$(date +%F).db
```

**恢复**

```bash
docker compose down
rm -rf storage && tar xzf mp3dl-YYYY-MM-DD.tar.gz   # 或解压到 storage/
chown -R 1000:1000 storage
docker compose up -d
```

> `.secret_key` 一定要跟库一起备份。丢了它不影响数据，但所有用户被踢下线、已发出的直链全部失效。

**清空业务数据**（保留管理员）

```bash
docker compose exec mp3dl python tools/clean_test_data.py          # 预览
docker compose exec mp3dl python tools/clean_test_data.py --yes    # 执行（自动备份到 storage/backups/）
```

**查看资源占用**

```bash
docker stats mp3dl --no-stream
du -sh /opt/mp3dl/storage/cache
```

---

## 8. 常见问题

| 症状 | 原因 | 处理 |
|---|---|---|
| 下载/播放地址是 `http://127.0.0.1:8080/...` | 反代没传 `Host` | 加 `proxy_set_header Host $host;` |
| 登录成功但刷新又变未登录 | `X-Forwarded-Proto` 没传，后端认为不是 HTTPS，Cookie 带了 Secure 却在 HTTP 下丢弃；或 `MP3DL_SITE_HTTPS` 与实际情况不符 | 补 `X-Forwarded-Proto $scheme`，`.env` 里 `MP3DL_SITE_HTTPS=1` |
| 所有人都共用一个限流额度 / 后台看到的 IP 全是 `172.x` | `MP3DL_TRUSTED_PROXIES` 没包含 docker 网段，或反代用了 `X-Forwarded-For $remote_addr` 覆盖而不是追加 | 用 `$proxy_add_x_forwarded_for`，并把 docker 网段写进 `MP3DL_TRUSTED_PROXIES` |
| 搜索进度条卡住，最后一次性出来 | `proxy_buffering on` | 关闭缓冲 |
| 搜索/打包 504 | `proxy_read_timeout` 太短（默认 60s） | 调到 300s |
| 容器反复重启，日志 `unable to open database file` | `storage` 目录属主不是 1000 | `chown -R 1000:1000 storage` |
| 启动报 `ModuleNotFoundError: musicdl` | `vendor/` 没上传完整 | 确认 `/opt/mp3dl/vendor/musicdl/__init__.py` 存在 |
| 搜索全部平台超时 | 容器 DNS 解析不稳定 | 确认 compose 里 `dns: 223.5.5.5 / 119.29.29.29` 生效，或换 `8.8.8.8` |
| 封面不显示 | 目标 CDN 不在白名单 | 把域名后缀加进 `MP3DL_COVER_HOSTS` |

---

## 9. 安全与容量建议

- **不要**把 `ports` 改成 `"8080:8080"`。一旦容器直接暴露公网，`X-Forwarded-For` 就变可伪造，限流和审计全部失效。
- **不要**给 gunicorn 加 worker（`-w 2` 及以上）。任务队列、缓存索引、限流计数都在进程内存，多进程会导致重复扣费、任务状态错乱。
- 1Panel 的「防火墙」只放行 80/443，`8080` 保持仅回环。
- 缓存上限 `MP3DL_CACHE_MAX_GB` 按磁盘余量设，超了会按 LRU 清理；`MP3DL_CACHE_TTL_HOURS` 控制单曲缓存保留时长。
- 定期检查 `storage/mp3dl.db` 体积；若是长期运行后明显膨胀，停服执行一次 `VACUUM`。
