# -*- coding: utf-8 -*-
"""智能租房搜索系统 — Flask Web UI

启动:
    # Windows
    set DEEPSEEK_API_KEY=sk-xxx && python app.py
    # macOS / Linux
    export DEEPSEEK_API_KEY=sk-xxx && python3 app.py

    浏览器打开 http://127.0.0.1:5050

Endpoints:
    GET  /                  主页面 (搜索表单+地图+房源列表+AI面板)
    GET  /api/demo          返回上一次的测试数据 (无需LLM/采集)
    POST /api/search        启动搜索任务 (后台执行Loop)
    GET  /api/status/<jid>  轮询任务进度
    GET  /api/result/<jid>  获取任务最终结果
    POST /api/listings/import 导入个人房源文本
    GET  /api/listings       查询本地房源库
    GET  /api/prices         查询区域价格统计
"""
import os, sys, json, time, uuid, threading, io, traceback
from contextlib import redirect_stdout, redirect_stderr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

from flask import Flask, request, jsonify, render_template, abort

from config import (GAODE_API_KEY, DATA_DIR, TRANSIT_SPEED_KMH,
                    ROUTE_FACTOR, PREFILTER_MULTIPLIER,
                    MAX_CONCURRENT, REQUEST_TIMEOUT, MAX_EXTRACTION_RETRIES,
                    LLM_BASE_URL, LLM_MODEL, LLM_TIMEOUT)
from src.gaode import GaodeClient
from src.feasible_domain import FeasibleDomain
from src.llm import LLMClient
from src.agents.planner import PlannerAgent
from src.agents.developer import DeveloperAgent
from src.agents.evaluator import EvaluatorAgent
from src.loop import RentalSearchLoop
from src.collectors.douban import DoubanCollector
from src.models import UserRequirement, Platform, Listing
from src.listing_store import ListingStore

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024
LISTING_STORE = ListingStore(os.path.join(DATA_DIR, "rentals.db"))

# 全局任务表 (内存存储, 进程重启清空)
_JOBS: dict = {}
_JOBS_LOCK = threading.Lock()


# ----------------------------------------------------------------
#  工具函数
# ----------------------------------------------------------------
def _serialize_listing(li: Listing) -> dict:
    """Listing → JSON-able dict"""
    return {
        "title": li.title,
        "description": li.description[:200] if li.description else "",
        "price_monthly": li.price_monthly,
        "deposit_method": li.deposit_method,
        "city": li.city,
        "district": li.district,
        "neighborhood": li.neighborhood,
        "address_raw": li.address_raw,
        "room_type": li.room_type,
        "layout": li.layout,
        "area_sqm": li.area_sqm,
        "floor": li.floor,
        "contact": li.contact,
        "available_from": li.available_from,
        "highlights": li.highlights,
        "source_platform": li.source_platform,
        "source_url": li.source_url,
        "confidence": round(li.confidence, 2),
        "is_rental": li.is_rental,
        "rental_subtype": li.rental_subtype,
        "attempts": li.extraction_attempts,
    }


def _serialize_station(st: dict) -> dict:
    """ViableStation dict → frontend-friendly"""
    return {
        "name": st["name"],
        "lng": st.get("lng") or st.get("longitude"),
        "lat": st.get("lat") or st.get("latitude"),
        "commute_min": st.get("commute_min", 0),
        "distance_km": st.get("distance_km", 0),
        "walking_m": st.get("walking_m", 0),
        "transfers": st.get("transfers", 0),
    }


def _build_loop_components(use_stub: bool, max_posts: int):
    """构造Loop所需的依赖: gaode+fd+llm+douban+agents"""
    gaode = GaodeClient(GAODE_API_KEY, timeout=REQUEST_TIMEOUT)
    fd = FeasibleDomain(gaode, DATA_DIR,
                        transit_speed=TRANSIT_SPEED_KMH,
                        route_factor=ROUTE_FACTOR,
                        prefilter_multiplier=PREFILTER_MULTIPLIER,
                        max_concurrent=MAX_CONCURRENT)

    # LLM: 从环境变量读key
    llm_key = os.environ.get("DEEPSEEK_API_KEY") or \
              os.environ.get("LLM_API_KEY")
    llm = (LLMClient(llm_key, LLM_BASE_URL, LLM_MODEL,
                     timeout=LLM_TIMEOUT)
           if llm_key else None)

    douban = DoubanCollector(use_stub=use_stub,
                             delay_range=(1, 2),
                             max_pages=2,
                             max_posts=max_posts)

    # 小红书采集器
    from src.collectors.xiaohongshu import XiaohongshuCollector
    xiaohongshu = XiaohongshuCollector(use_stub=use_stub,
                                       max_posts=max_posts)

    planner = PlannerAgent(fd)
    developer = DeveloperAgent(llm)
    developer.register_collector(Platform.DOUBAN, douban)
    developer.register_collector(Platform.XIAOHONGSHU, xiaohongshu)
    evaluator = EvaluatorAgent()

    loop = RentalSearchLoop(planner, developer, evaluator,
                            max_retries=MAX_EXTRACTION_RETRIES)
    return loop


def _run_search_job(job_id: str, req: UserRequirement,
                    use_stub: bool, max_posts: int, listing_filters: dict):
    """后台线程: 执行完整Loop"""
    with _JOBS_LOCK:
        _JOBS[job_id]["status"] = "running"
        _JOBS[job_id]["started_at"] = time.time()

    # 捕获print输出到logs
    log_buf = io.StringIO()
    try:
        with redirect_stdout(log_buf), redirect_stderr(log_buf):
            loop = _build_loop_components(use_stub=use_stub,
                                          max_posts=max_posts)
            start = time.time()
            result = loop.run(req)
            elapsed = time.time() - start

        # 提取最终结果
        listings = [_serialize_listing(li) for li in result["listings"]]
        stations = [_serialize_station(s)
                    for s in (result.get("plan").viable_stations
                              if result.get("plan") else [])]
        work_loc = (result.get("plan").work_location
                    if result.get("plan") else {})

        # 将可用的结构化房源写入本地库，再合并符合条件的历史个人房源。
        for item in listings:
            if not item.get("price_monthly"):
                continue
            try:
                LISTING_STORE.save({
                    **item,
                    "raw_text": item.get("description", ""),
                    "station": item.get("address_raw", ""),
                    "listing_type": item.get("rental_subtype", ""),
                    "is_personal": item.get("rental_subtype") in
                                   ("转租", "直租", "房东直租", "找室友"),
                })
            except ValueError:
                pass

        station_names = [station["name"] for station in stations]
        stored_listings = LISTING_STORE.list_for_stations(
            station_names,
            city=req.city,
            lease_term=listing_filters.get("lease_term", ""),
            room_type=listing_filters.get("room_type", ""),
            personal_only=listing_filters.get("personal_only", False),
            budget_min=req.budget_min,
            budget_max=req.budget_max,
            recent_days=60,
        )
        seen = {(item.get("source_url"), item.get("title")) for item in listings}
        for item in stored_listings:
            key = (item.get("source_url"), item.get("title"))
            if key not in seen:
                listings.append(item)
                seen.add(key)

        price_summaries = []
        for station_name in station_names:
            summary = LISTING_STORE.price_stats(
                city=req.city,
                area=station_name,
                lease_term=listing_filters.get("lease_term", ""),
                room_type=listing_filters.get("room_type", ""),
                personal_only=listing_filters.get("personal_only", False),
                recent_days=60,
            )
            if summary["sample_count"]:
                price_summaries.append({"area": station_name, **summary})

        # 写回job
        with _JOBS_LOCK:
            _JOBS[job_id].update({
                "status": "done",
                "finished_at": time.time(),
                "elapsed": round(elapsed, 1),
                "listings": listings,
                "viable_stations": stations,
                "work_location": work_loc,
                "price_summaries": price_summaries,
                "stats": result["stats"],
                "criteria": (result["criteria"].rules_description
                             if result.get("criteria") else ""),
                "logs": log_buf.getvalue().splitlines(),
            })
    except Exception as e:
        err = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        with _JOBS_LOCK:
            _JOBS[job_id].update({
                "status": "error",
                "finished_at": time.time(),
                "error": str(e),
                "logs": (log_buf.getvalue().splitlines() +
                         [f"[ERROR] {err}"]),
            })


def _find_latest_test_result() -> dict:
    """加载最近一次的e2e测试结果 (data/e2e_*.json)"""
    try:
        files = [f for f in os.listdir(DATA_DIR)
                 if f.startswith("e2e_") and f.endswith(".json")]
        if not files:
            return {}
        files.sort(reverse=True)  # 文件名带时间戳, 降序
        path = os.path.join(DATA_DIR, files[0])
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {"file": files[0], "data": data, "path": path}
    except Exception as e:
        return {"error": str(e)}


# ----------------------------------------------------------------
#  路由
# ----------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/demo")
def demo():
    """返回上一次端到端测试结果 (无需LLM/采集, 即开即看)"""
    res = _find_latest_test_result()
    if "error" in res:
        return jsonify({"ok": False, "error": res["error"]})
    if not res:
        return jsonify({"ok": False, "error": "暂无历史测试数据"})
    data = res["data"]
    return jsonify({
        "ok": True,
        "source": res["file"],
        "listings": data.get("listings", []),
        "stats": data.get("stats", {}),
        "elapsed": data.get("elapsed", 0),
        "viable_stations": [
            {"name": "西二旗", "lng": 116.296, "lat": 40.072},
            {"name": "朱辛庄", "lng": 116.330, "lat": 40.073},
        ],  # 测试数据,实际从结果文件读取
        "work_location": {"lng": 116.299, "lat": 40.044},
    })


@app.route("/api/search", methods=["POST"])
def search():
    """启动搜索任务 (后台线程)"""
    payload = request.get_json(force=True) or {}
    city = payload.get("city", "北京").strip()
    work = (payload.get("work") or "").strip()
    commute = int(payload.get("commute", 40))
    budget_min = int(payload.get("budget_min", 0)) or None
    budget_max = int(payload.get("budget_max", 0)) or None
    use_stub = bool(payload.get("use_stub", False))
    max_posts = int(payload.get("max_posts", 8))
    lease_term = (payload.get("lease_term") or "不限").strip()
    room_type = (payload.get("room_type") or "不限").strip()
    personal_only = bool(payload.get("personal_only", False))

    if not work:
        return jsonify({"ok": False, "error": "工作地点必填"}), 400
    if not GAODE_API_KEY:
        return jsonify({
            "ok": False,
            "error": "未配置 GAODE_API_KEY，请在 .env 中填写高德 Web 服务 Key 后重启系统。",
        }), 503

    req = UserRequirement(city=city, work_address=work,
                          max_commute_min=commute,
                          budget_min=budget_min,
                          budget_max=budget_max)

    job_id = f"job_{uuid.uuid4().hex[:12]}"
    with _JOBS_LOCK:
        _JOBS[job_id] = {
            "status": "pending",
            "started_at": None,
            "finished_at": None,
            "request": {"city": city, "work": work,
                        "commute": commute,
                        "budget_min": budget_min,
                        "budget_max": budget_max,
                        "use_stub": use_stub,
                        "max_posts": max_posts,
                        "lease_term": lease_term,
                        "room_type": room_type,
                        "personal_only": personal_only},
            "logs": [],
        }

    # 启动后台线程
    t = threading.Thread(target=_run_search_job,
                         args=(job_id, req, use_stub, max_posts, {
                             "lease_term": lease_term,
                             "room_type": room_type,
                             "personal_only": personal_only,
                         }),
                         daemon=True)
    t.start()

    return jsonify({"ok": True, "job_id": job_id})


@app.route("/api/status/<job_id>")
def status(job_id):
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if not job:
        return jsonify({"ok": False, "error": "任务不存在"}), 404

    # 只返回最近50条日志(进度滚动)
    logs = job.get("logs", [])[-50:]
    elapsed = None
    if job.get("started_at"):
        end = job.get("finished_at") or time.time()
        elapsed = round(end - job["started_at"], 1)

    return jsonify({
        "ok": True,
        "status": job["status"],
        "elapsed": elapsed,
        "logs": logs,
        "request": job.get("request", {}),
        "error": job.get("error"),
    })


@app.route("/api/result/<job_id>")
def result(job_id):
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if not job:
        return jsonify({"ok": False, "error": "任务不存在"}), 404
    if job["status"] != "done":
        return jsonify({"ok": False,
                        "error": f"任务状态: {job['status']}",
                        "status": job["status"]}), 400

    return jsonify({
        "ok": True,
        "listings": job.get("listings", []),
        "viable_stations": job.get("viable_stations", []),
        "work_location": job.get("work_location", {}),
        "price_summaries": job.get("price_summaries", []),
        "stats": job.get("stats", {}),
        "criteria": job.get("criteria", ""),
        "elapsed": job.get("elapsed", 0),
    })


@app.route("/api/listings/import", methods=["POST"])
def import_listing():
    """保存用户粘贴的个人房源文本；显式字段优先于规则识别。"""
    payload = request.get_json(force=True) or {}
    raw_text = str(payload.get("raw_text") or "")
    if not raw_text.strip():
        return jsonify({"ok": False, "error": "房源原文必填"}), 400
    if len(raw_text) > 50000:
        return jsonify({"ok": False, "error": "房源原文不能超过50000字"}), 400
    try:
        item = LISTING_STORE.save(payload)
        stats = LISTING_STORE.price_stats(
            city=item["city"],
            area=item["station"] or item["neighborhood"] or item["district"],
            lease_term=item["lease_term"],
            room_type=item["room_type"],
            personal_only=False,
            recent_days=60,
        )
        return jsonify({"ok": True, "listing": item, "price_stats": stats})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.route("/api/listings")
def local_listings():
    """按区域、租期、房型和预算查询本地房源库。"""
    try:
        items = LISTING_STORE.list(
            city=(request.args.get("city") or "").strip(),
            area=(request.args.get("area") or "").strip(),
            lease_term=(request.args.get("lease_term") or "").strip(),
            room_type=(request.args.get("room_type") or "").strip(),
            personal_only=request.args.get("personal_only") in ("1", "true"),
            budget_min=request.args.get("budget_min") or None,
            budget_max=request.args.get("budget_max") or None,
            recent_days=min(max(int(request.args.get("days", 60)), 1), 365),
            limit=min(max(int(request.args.get("limit", 100)), 1), 500),
        )
        return jsonify({"ok": True, "listings": items, "count": len(items)})
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": f"查询参数无效: {exc}"}), 400


@app.route("/api/prices")
def price_reference():
    """返回近期区域房源的稳健价格统计。"""
    try:
        area = (request.args.get("area") or "").strip()
        if not area:
            return jsonify({"ok": False, "error": "区域或地铁站必填"}), 400
        filters = {
            "city": (request.args.get("city") or "北京").strip(),
            "area": area,
            "lease_term": (request.args.get("lease_term") or "").strip(),
            "room_type": (request.args.get("room_type") or "").strip(),
            "personal_only": request.args.get("personal_only") in ("1", "true"),
            "recent_days": min(max(int(request.args.get("days", 60)), 1), 365),
        }
        stats = LISTING_STORE.price_stats(**filters)
        items = LISTING_STORE.list(limit=20, **filters)
        return jsonify({
            "ok": True,
            "area": area,
            "stats": stats,
            "listings": items,
        })
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": f"查询参数无效: {exc}"}), 400


# ----------------------------------------------------------------
#  入口
# ----------------------------------------------------------------
if __name__ == "__main__":
    if not GAODE_API_KEY:
        print("  [提示] 未设置 GAODE_API_KEY，搜索功能暂不可用")
        print("  请复制 .env.example 为 .env 并填写自己的高德 Web 服务 Key")
        print()
    # 检查LLM key
    if not (os.environ.get("DEEPSEEK_API_KEY") or
            os.environ.get("LLM_API_KEY")):
        print("  [提示] 未设置 DEEPSEEK_API_KEY")
        print("  通勤可行域仍可使用，房源结构化提取将自动跳过")
        print()

    print("=" * 50)
    print("  智能租房搜索系统 — Web UI")
    port = int(os.environ.get("PORT", "5050"))
    print(f"  访问: http://127.0.0.1:{port}")
    print("=" * 50)

    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
