"""
AI Travel Planner —— FastAPI 后端
=================================

职责：
- 持有 DeepSeek API Key（绝不下发到前端小程序）
- 暴露 POST /api/plan 接口，接收用户偏好，调用 agent_engine.generate_itinerary 跑三 Agent 流水线
- 没有配置 Key 时自动进入 mock 模式（返回示例行程），方便本地验证接口与前端接通，无需真实额度
- 开启 CORS，允许前端 demo（含 file:// / 不同端口）访问

本地启动：
    cd server
    python -m venv .venv
    .venv/Scripts/python -m pip install -r requirements.txt
    # 复制 .env.example 为 .env 并填入 DEEPSEEK_API_KEY（可选，不填则 mock 模式）
    .venv/Scripts/python -m uvicorn main:app --reload --port 8000
"""

import os
import json
import threading
import uuid
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

# 前端 demo.html 路径（server 的上一级目录）
DEMO_PATH = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "demo.html"))

# 明确按本文件所在目录加载 .env，避免 uvicorn 后台进程 cwd 不同导致读不到 key
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")


# ---------- 日期工具（与前端 demo 保持一致） ----------
def _pad(n: int) -> str:
    return f"{n:02d}"


def _fmt_iso(d: datetime) -> str:
    return f"{d.year}-{_pad(d.month)}-{_pad(d.day)}"


def _add_days_iso(iso: str, n: int) -> str:
    d = datetime.strptime(iso, "%Y-%m-%d")
    return _fmt_iso(d + timedelta(days=n))


def _build_dates(start: str, n: int) -> List[str]:
    return [_add_days_iso(start, i) for i in range(n)]


# ---------- 请求模型 ----------
class PlanRequest(BaseModel):
    destination: str
    num_days: int = 5
    budget: str = "舒适"          # 经济 / 舒适 / 轻奢
    interests: List[str] = []     # 中文兴趣标签
    travel_style: str = "balanced"  # relaxed / balanced / adventure
    extra_notes: str = ""         # 个人偏好自由文本（带娃、忌口、节奏等）
    start_date: Optional[str] = None  # ISO 日期，缺省为今天


# ---------- mock 行程（无 Key 时返回，结构同真实接口） ----------
# 与真实接口一致的结构化 JSON：前端优先用 itinerary_json 渲染清爽卡片
MOCK_ITINERARY_JSON = {
    "destination": "成都",
    "summary": "成都3天以美食与休闲为主，节奏轻松，人均约¥1500（含住宿交通）。不辣可选清汤火锅、甜水面、白味钵钵鸡；地铁用天府通APP，景点多支持微信/支付宝。",
    "days": [
        {
            "day": 1,
            "theme": "老城烟火 · 宽窄巷子与盖碗茶",
            "slots": [
                {"period": "morning", "items": [
                    {"title": "宽窄巷子", "category": "观光", "duration": "2小时", "note": "青砖院落逛吃，井巷子看文化墙，建议早上去人少"},
                    {"title": "鹤鸣茶社", "category": "休闲", "duration": "1.5小时", "note": "人民公园喝盖碗茶，体验老成都慢生活，茶资¥30/人"},
                ]},
                {"period": "afternoon", "items": [
                    {"title": "奎星楼街", "category": "美食", "duration": "1.5小时", "note": "冒椒火辣串串，本地人排队王，人均¥60，可选清汤锅底不辣"},
                    {"title": "武侯祠 + 锦里", "category": "观光", "duration": "2.5小时", "note": "三国文化，锦里红灯笼小吃街，门票¥50"},
                ]},
                {"period": "evening", "items": [
                    {"title": "九眼桥", "category": "休闲", "duration": "自由", "note": "府南河散步，酒吧街氛围，夜景不错"},
                ]},
            ],
        },
        {
            "day": 2,
            "theme": "熊猫与文艺 · 城市松弛感",
            "slots": [
                {"period": "morning", "items": [
                    {"title": "成都大熊猫繁育研究基地", "category": "观光", "duration": "3小时", "note": "门票¥55，务必早8点前到避开人潮，看熊猫进食最活跃"},
                ]},
                {"period": "afternoon", "items": [
                    {"title": "建设路小吃城", "category": "美食", "duration": "1.5小时", "note": "甜水面、钵钵鸡（白味不辣）、蛋烘糕，人均¥40"},
                    {"title": "东郊记忆", "category": "拍照", "duration": "2小时", "note": "工业风文创园，红砖厂房+涂鸦墙，拍照出片"},
                ]},
                {"period": "evening", "items": [
                    {"title": "蜀九香火锅", "category": "美食", "duration": "2小时", "note": "人均¥120，鸳鸯锅满足不辣需求，环境干净"},
                ]},
            ],
        },
        {
            "day": 3,
            "theme": "周边慢游 · 都江堰与青城山",
            "slots": [
                {"period": "morning", "items": [
                    {"title": "地铁2号线→都江堰", "category": "交通", "duration": "1小时+", "note": "犀浦换乘城际列车到都江堰，千年水利工程门票¥80"},
                ]},
                {"period": "afternoon", "items": [
                    {"title": "南桥", "category": "美食", "duration": "1小时", "note": "南桥边吃蹄花汤，岷江水景廊桥拍照"},
                    {"title": "青城山前山", "category": "观光", "duration": "3小时", "note": "道教圣地，步道平缓，缆车可选，建议穿舒适鞋"},
                ]},
                {"period": "evening", "items": [
                    {"title": "春熙路", "category": "购物", "duration": "自由", "note": "返程前买伴手礼（兔头、竹叶青茶），地铁直达"},
                ]},
            ],
        },
    ],
    "tips": [
        "地铁用『天府通APP』扫码乘车，景点多支持微信/支付宝",
        "不辣推荐：清汤/鸳鸯火锅、甜水面、白味钵钵鸡、蹄花汤",
        "大熊猫基地务必早8点前到，避开旅行团人潮",
        "宽窄巷子、锦里偏商业化，想尝地道去找小巷子里的本地馆子",
    ],
}

MOCK_RESEARCH = "（mock）在百度与小红书检索到：成都火锅本地推荐、宽窄巷子避坑指南、大熊猫基地最佳时段、都江堰交通路线。"
MOCK_CRITIC = "（mock）行程节奏合理，美食覆盖充分；建议 Day2 熊猫基地与东郊记忆距离较远，可预留更多交通时间。"
MOCK_SOURCES = [
    {"title": "成都本地人私藏火锅店推荐（附人均/避坑）", "url": "https://www.xiaohongshu.com/search_result?keyword=成都本地火锅", "abstract": "（示例）本地人常去的老牌火锅，微辣可选鸳鸯锅，人均¥120左右。", "source": "小红书"},
    {"title": "宽窄巷子 vs 奎星楼街，游客Vs本地人怎么选", "url": "https://www.baidu.com/s?wd=成都宽窄巷子避坑", "abstract": "（示例）宽窄巷子偏商业化，想尝地道去小巷子里的本地馆子。", "source": "百度"},
    {"title": "成都大熊猫基地最佳参观时间攻略", "url": "https://www.baidu.com/s?wd=成都大熊猫基地攻略", "abstract": "（示例）务必早8点前到，避开旅行团人潮，看熊猫进食最活跃。", "source": "百度"},
]


# ---------- 异步任务 + 天气代理（供小程序调用） ----------
TASKS: dict = {}
TASK_LOCK = threading.Lock()


def _build_mock_result(req: PlanRequest, start: str, dates: List[str]) -> dict:
    return {
        "destination": req.destination,
        "num_days": req.num_days,
        "budget": req.budget,
        "travel_style": req.travel_style,
        "extra_notes": req.extra_notes,
        "start_date": start,
        "dates": dates,
        "itinerary": "",
        "itinerary_json": MOCK_ITINERARY_JSON,
        "research": MOCK_RESEARCH,
        "sources": MOCK_SOURCES,
        "critic": MOCK_CRITIC,
        "is_china": True,
        "engine": "mock",
        "mock": True,
    }


def _range_dates(start: str, end: str) -> List[str]:
    s = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end, "%Y-%m-%d")
    out, cur = [], s
    while cur <= e:
        out.append(_fmt_iso(cur))
        cur += timedelta(days=1)
    return out


def _align_weather(daily, dates):
    if not daily or not daily.get("time"):
        return [None] * len(dates)
    m = {}
    for i, t in enumerate(daily["time"]):
        m[t] = {
            "code": daily["weather_code"][i],
            "max": daily["temperature_2m_max"][i],
            "min": daily["temperature_2m_min"][i],
        }
    return [m.get(d) for d in dates]


def _geocode(name):
    url = "https://geocoding-api.open-meteo.com/v1/search?name=" + urllib.parse.quote(name) + "&count=1&language=zh"
    req = urllib.request.Request(url, headers={"User-Agent": "ai-travel-planner/1.0"})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read().decode("utf-8")).get("results", [None])[0]


def _forecast(lat, lon, start, end):
    url = ("https://api.open-meteo.com/v1/forecast?latitude=" + str(lat) + "&longitude=" + str(lon)
           + "&daily=weather_code,temperature_2m_max,temperature_2m_min&timezone=auto"
           + "&start_date=" + start + "&end_date=" + end)
    req = urllib.request.Request(url, headers={"User-Agent": "ai-travel-planner/1.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8")).get("daily")


def _run_task(task_id: str, req_dict: dict, key: str):
    try:
        if not key:
            result = {
                "destination": req_dict["destination"],
                "num_days": req_dict["num_days"],
                "budget": req_dict["budget"],
                "travel_style": req_dict["travel_style"],
                "extra_notes": req_dict["extra_notes"],
                "start_date": req_dict["start_date"],
                "dates": req_dict["dates"],
                "itinerary": "",
                "itinerary_json": MOCK_ITINERARY_JSON,
                "research": MOCK_RESEARCH,
                "sources": MOCK_SOURCES,
                "critic": MOCK_CRITIC,
                "is_china": True,
                "engine": "mock",
                "mock": True,
            }
            status, error = "done", None
        else:
            from agent_engine import generate_itinerary
            res = generate_itinerary(req_dict, key)
        res.update({
            "destination": req_dict["destination"],
            "num_days": req_dict["num_days"],
            "budget": req_dict["budget"],
            "start_date": req_dict["start_date"],
            "dates": req_dict["dates"],
            "mock": False,
        })
        if "sources" not in res:
            res["sources"] = []
            result, status, error = res, "done", None
    except Exception as e:  # noqa: BLE001
        result, status, error = None, "failed", f"generation failed: {e}"
    with TASK_LOCK:
        TASKS[task_id] = {"status": status, "result": result, "error": error}


# ---------- 应用 ----------
app = FastAPI(title="AI Travel Planner API", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "has_key": bool(DEEPSEEK_API_KEY), "mock_mode": not bool(DEEPSEEK_API_KEY)}


# 把前端 demo.html 直接挂到根路径，方便手机/局域网同源访问（无需跨域、无需 file://）
@app.get("/")
def index():
    return FileResponse(DEMO_PATH)


@app.post("/api/plan")
def plan(req: PlanRequest):
    if not req.destination or not req.destination.strip():
        raise HTTPException(status_code=400, detail="destination is required")

    start = req.start_date or _fmt_iso(datetime.today())
    dates = _build_dates(start, req.num_days)

    if not DEEPSEEK_API_KEY:
        # 无 Key：mock 模式，结构保持与真实一致，方便联调
        return _build_mock_result(req, start, dates)

    # 有 Key：调用真实三 Agent 流水线
    try:
        from agent_engine import generate_itinerary
        res = generate_itinerary(
            {
                "destination": req.destination,
                "num_days": req.num_days,
                "budget": req.budget,
                "interests": req.interests,
                "travel_style": req.travel_style,
                "extra_notes": req.extra_notes,
                "start_date": start,
            },
            DEEPSEEK_API_KEY,
        )
        res.update({
            "destination": req.destination,
            "num_days": req.num_days,
            "budget": req.budget,
            "start_date": start,
            "dates": dates,
            "mock": False,
        })
        if "sources" not in res:
            res["sources"] = []
        return res
    except Exception as e:  # noqa: BLE001 - 对外暴露错误信息便于调试
        raise HTTPException(status_code=500, detail=f"generation failed: {e}")


# ---------- 天气代理：Open-Meteo（小程序走后端，单域名白名单） ----------
@app.get("/api/weather")
def weather(dest: str = "", start: str = "", end: str = ""):
    if not dest or not start or not end:
        return {"weather": [], "note": "参数缺失", "ok": False}
    try:
        g = _geocode(dest)
        if not g:
            return {"weather": [], "note": f"未找到「{dest}」的天气数据", "ok": False}
        try:
            daily = _forecast(g["latitude"], g["longitude"], start, end)
        except Exception:
            dates = _range_dates(start, end)
            return {"weather": [None] * len(dates), "note": "天气服务暂不可用或日期超出可预报范围，未编造", "ok": False}
        dates = _range_dates(start, end)
        w = _align_weather(daily, dates)
        far = sum(1 for x in w if x is None)
        if far == len(w):
            note = "这段时间天气暂查不到，未编造"
        elif far > 0:
            note = "部分日期超出可预报范围（约未来 16 天），已如实标注"
        else:
            note = "天气数据来自 Open-Meteo，为真实预报，仅供参考"
        return {"weather": w, "note": note, "ok": far == 0}
    except Exception:
        return {"weather": [], "note": "天气服务暂不可用", "ok": False}


# ---------- 异步行程生成（解决小程序 wx.request 60s 超时限制） ----------
@app.post("/api/plan/async")
def plan_async(req: PlanRequest):
    start = req.start_date or _fmt_iso(datetime.today())
    dates = _build_dates(start, req.num_days)
    req_dict = {
        "destination": req.destination,
        "num_days": req.num_days,
        "budget": req.budget,
        "interests": req.interests,
        "travel_style": req.travel_style,
        "extra_notes": req.extra_notes,
        "start_date": start,
        "dates": dates,
    }
    task_id = uuid.uuid4().hex
    with TASK_LOCK:
        TASKS[task_id] = {"status": "pending", "result": None, "error": None}
    threading.Thread(target=_run_task, args=(task_id, req_dict, DEEPSEEK_API_KEY), daemon=True).start()
    return {"task_id": task_id}


@app.get("/api/plan/async/{task_id}")
def plan_async_result(task_id: str):
    with TASK_LOCK:
        task = TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return task
