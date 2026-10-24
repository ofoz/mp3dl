"""平台列表 / 搜索（SSE 流式 + 普通 JSON）/ 平台健康检查"""
import json
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout, as_completed

from flask import Blueprint, Response, jsonify, request, stream_with_context

from .. import ratelimit, security
from ..config import Config
from ..services import platforms

bp = Blueprint("catalog", __name__, url_prefix="/api")

_health_cache = {"ts": 0, "data": None}
_health_lock = threading.Lock()


@bp.get("/platforms")
def list_platforms():
    items = [platforms.meta_payload(k) for k in platforms.ENABLED_SOURCES]
    return jsonify({"platforms": items, "site": {"name": Config.SITE_NAME, "slogan": Config.SITE_SLOGAN}})


def _parse_sources(raw):
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    return [s for s in str(raw).split(",") if s.strip()]


def _sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@bp.get("/search/stream")
def search_stream():
    keyword = (request.args.get("q") or "").strip()
    if not keyword:
        return jsonify({"error": "请输入搜索关键词"}), 400
    if len(keyword) > 80:
        return jsonify({"error": "关键词过长"}), 400
    ratelimit.check_search(security.client_ip())
    sources = platforms.normalize_sources(_parse_sources(request.args.get("platforms")))

    def generate():
        yield _sse("start", {"q": keyword, "sources": sources})
        budget = max([platforms.source_timeout(s) for s in sources] or [Config.SOURCE_TIMEOUT]) + 10
        deadline = time.time() + budget
        events = queue.Queue()
        pool = ThreadPoolExecutor(max_workers=max(len(sources), 1))

        def run(src):
            """一个平台一个线程：曲目解析出一首就丢进队列，前端立刻能渲染。"""
            def on_track(payload):
                events.put(("track", src, payload))
            try:
                result = platforms.search_stream(src, keyword, "mp3", on_track)
                events.put(("platform", src, result))
            except Exception as err:
                events.put(("platform", src, {
                    "platform": src, "label": platforms.PLATFORMS.get(src, {}).get("label", src),
                    "count": 0, "elapsed": 0, "tracks": [], "error": str(err)[:160],
                }))

        for src in sources:
            pool.submit(run, src)

        pending = set(sources)
        last_emit = time.time()
        try:
            while pending:
                remain = deadline - time.time()
                if remain <= 0:
                    for src in list(pending):
                        yield _sse("platform", {
                            "platform": src, "label": platforms.PLATFORMS.get(src, {}).get("label", src),
                            "count": 0, "tracks": [], "error": "timeout",
                        })
                    break
                try:
                    kind, src, payload = events.get(timeout=min(remain, 1.0))
                except queue.Empty:
                    # 首屏拿数据前可能有十几秒静默，定期发注释行保活，避免中间层掐断
                    if time.time() - last_emit > 15:
                        last_emit = time.time()
                        yield ": ping\n\n"
                    continue
                last_emit = time.time()
                if kind == "track":
                    yield _sse("track", {"platform": src, "track": payload})
                    continue
                pending.discard(src)
                yield _sse("platform", payload)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        yield _sse("done", {"ok": True})

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                             "Connection": "keep-alive"})


@bp.get("/search")
def search_plain():
    keyword = (request.args.get("q") or "").strip()
    if not keyword:
        return jsonify({"error": "请输入搜索关键词"}), 400
    if len(keyword) > 80:
        return jsonify({"error": "关键词过长"}), 400
    ratelimit.check_search(security.client_ip())
    sources = platforms.normalize_sources(_parse_sources(request.args.get("platforms")))
    results = platforms.search_all(keyword, sources)
    return jsonify({"q": keyword, "results": results})


@bp.get("/health")
def health():
    """各平台可用性探活（结果缓存 5 分钟，避免每次请求都真打接口）。"""
    with _health_lock:
        if _health_cache["data"] and time.time() - _health_cache["ts"] < 300:
            return jsonify(_health_cache["data"])

    def probe(source):
        started = time.time()
        try:
            res = platforms.search_one(source, "周杰伦", "mp3")
            return {"platform": source, "ok": res["count"] > 0, "count": res["count"],
                    "elapsed": round(time.time() - started, 1)}
        except Exception as err:
            return {"platform": source, "ok": False, "count": 0,
                    "elapsed": round(time.time() - started, 1), "error": str(err)[:120]}

    with ThreadPoolExecutor(max_workers=len(platforms.DEFAULT_SOURCES)) as pool:
        items = list(pool.map(probe, platforms.DEFAULT_SOURCES))
    data = {"ts": int(time.time()), "platforms": items,
            "ok": all(i["ok"] for i in items) if items else False}
    with _health_lock:
        _health_cache.update({"ts": time.time(), "data": data})
    return jsonify(data)
