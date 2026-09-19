# AI Travel Planner —— 后端服务

把 `ai-travel-agent` 的「三 Agent 协作（Researcher → Planner → Critic → Planner 终稿）」封装成 HTTP 接口，
供微信小程序 / 网页前端调用。**DeepSeek Key 由后端持有，前端只负责收集偏好与展示结果。**

## 目录
- `agent_engine.py`：从 travel_agent.py 抽出的纯逻辑层（去 Streamlit），`generate_itinerary(prefs, api_key)` 跑完整流水线
- `main.py`：FastAPI 应用，暴露 `/api/plan`
- `requirements.txt`、`server/.env.example`：依赖与配置示例

## 快速启动
```bash
cd server
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt   # Mac/Linux 用 bin/python

# 可选：复制并填入 Key；不填则自动进入 mock 模式
copy .env.example .env

.venv\Scripts\python -m uvicorn main:app --reload --port 8000
```

启动后：
- 接口文档（Swagger）：http://127.0.0.1:8000/docs
- 健康检查：GET http://127.0.0.1:8000/

## 接口契约
`POST /api/plan`

请求体：
```json
{
  "destination": "成都",
  "num_days": 3,
  "budget": "舒适",
  "interests": ["美食", "拍照打卡"],
  "start_date": "2026-08-10"
}
```

返回（真实 / mock 结构一致）：
```json
{
  "destination": "成都",
  "num_days": 3,
  "budget": "舒适",
  "start_date": "2026-08-10",
  "dates": ["2026-08-10", "2026-08-11", "2026-08-12"],
  "itinerary": "最终行程（Markdown 文本）",
  "research": "Researcher 搜索结果",
  "critic": "Critic 审查意见",
  "is_china": true,
  "engine": "百度 + 小红书",
  "mock": false
}
```

## mock 模式说明
未配置 `DEEPSEEK_API_KEY` 时，接口返回示例行程（`mock: true`）。这是为了：
1. 不消耗真实额度即可验证接口连通性与前端接通；
2. 没有 Key 也能把整套 demo 跑起来演示。

配置 Key 后，自动切换为真实调用 agno 三 Agent 生成个性化行程。
