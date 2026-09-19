# alex 旅小帮 · AI Travel Planner

微信小程序 + FastAPI 后端的 AI 旅行规划工具：输入目的地 / 天数 / 兴趣，由 **DeepSeek 驱动的三 Agent 协作**（Researcher → Planner → Critic）生成逐日行程，并展示 AI 实际参考的真实帖子来源。

> 前身为 [Streamlit 单机版](legacy/travel_agent.py)（已归档），现重构为「微信小程序 + 云托管后端」完整工程。

## ✨ 功能亮点

| 功能 | 说明 |
|---|---|
| 🤖 三 Agent 协作 | Researcher（搜资料）→ Planner（排行程）→ Critic（挑毛病）→ Planner 终稿 |
| 📺 B站直调搜索 | 直连 `api.bilibili.com` 官方接口，免登录、服务器可跑；带 buvid3 会话 + 实体词相关性校验，返回真实视频链接 / UP主 / 播放量 / 发布时间 |
| 🏝️ 携程真实游记 | 百度 `site:` 语法锁定携程 UGC，一手游记攻略 |
| 🔍 百度事实兜底 | 开放时间 / 票价 / 交通等硬事实，仅在主力源未覆盖时调用 |
| 📑 来源透明 | 小程序与 Web demo 均展示「AI 参考来源」：旅行主题优先 + 播放量排序 + 携程保底席位，默认露 6 条其余折叠 |
| 📕 小红书入口 | 合规深链：复制官方搜索链接，跳转看最新真实笔记（不抓取内容） |
| 🌤️ 行程内天气 | 按出行日期拉取目的地天气预报（WMO 代码转图标） |
| 📅 一键带走 | 行程导出 .ics 日历 / .md 笔记 / .txt 纯文本，复制即用 |
| 💬 微信内网调用 | `wx.cloud.callContainer` 走微信私有链路，**免 request 合法域名、免域名备案** |

## 🏗️ 架构

```
┌─────────────────┐   callContainer(微信内网)   ┌──────────────────────┐
│  微信小程序       │ ──────────────────────────▶ │  微信云托管 FastAPI    │
│  miniprogram/    │                             │  server/main.py      │
│  表单/结果/来源区  │ ◀────────────────────────── │  异步任务 + 轮询       │
└─────────────────┘                             └──────────┬───────────┘
                                                           │
                                                ┌──────────▼───────────┐
                                                │  agent_engine.py     │
                                                │  Agno 三 Agent 协作   │
                                                │  DeepSeek (LLM)      │
                                                ├──────────────────────┤
                                                │ 搜索工具:             │
                                                │  · BilibiliSearch    │
                                                │  · SiteSearch(携程)   │
                                                │  · BaiduSearch(兜底)  │
                                                └──────────────────────┘
```

长耗时生成走「异步提交 + 轮询」（`/api/plan/async`），规避单次调用 60s 上限。

## 📁 目录结构

```
├── miniprogram/           # 微信小程序端（原生）
│   ├── app.js             # 云环境初始化 + 全局配置
│   ├── pages/index/       # 表单 → 加载动画 → 行程结果 + 来源区
│   └── utils/request.js   # callContainer / wx.request 双通道封装
├── server/                # FastAPI 后端（部署到微信云托管）
│   ├── main.py            # API：/health、/api/plan/async、/api/weather
│   ├── agent_engine.py    # 三 Agent + 自定义搜索工具（核心逻辑）
│   ├── demo.html          # 网页演示版（与小程序功能对齐，含来源区）
│   └── Dockerfile         # 云托管容器
├── legacy/                # 旧版归档
│   └── travel_agent.py    # Streamlit 单机版（第一代原型）
├── 云托管部署指南.md        # 从零部署到微信云托管
└── miniprogram/上架指南.md # 小程序提审 / 上架要点
```

## 🚀 快速开始

### 1. 跑后端（本地）

```bash
cd server
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt   # Windows
copy .env.example .env                                     # 填入 DEEPSEEK_API_KEY
.venv\Scripts\python -m uvicorn main:app --reload --port 8000
```

浏览器打开 `http://127.0.0.1:8000/` 即可用 Web demo 体验（与小程序功能一致）。

### 2. 跑小程序

1. 微信开发者工具导入 `miniprogram/` 目录
2. 本地调试：`详情 → 本地设置 → 勾选「不校验合法域名」`，并在 `app.js` 把 `useContainer` 设为 `false`、`apiBase` 指向 `http://127.0.0.1:8000`
3. 云端调试：`useContainer` 设为 `true`，`cloudEnv` / `cloudService` 填自己的云托管环境与服务名

### 3. 部署到微信云托管

详见 [云托管部署指南.md](云托管部署指南.md)。要点：

- 上传 `server/` 代码包，监听端口 `80`，健康检查 `/health`
- 环境变量配置 `DEEPSEEK_API_KEY`
- 运行模式选「**持续运行**」（自动扩缩容会缩到 0 导致 503）
- 小程序端用 `callContainer` 调用：**不需要配置 request 合法域名，也不需要备案**

## 🔧 搜索源策略（为什么这样设计）

| 决策 | 原因 |
|---|---|
| B站用官方接口而非百度 `site:` | 百度索引旧、返回跳转链；官方接口有播放量/发布时间，内容新鲜 |
| 必须带 buvid3 Cookie | 实测匿名请求约 1/3 概率被 B站降级，返回与关键词无关的泛化热门 |
| 结果做实体词相关性校验 | 降级/模糊匹配会混入无关内容，宁缺毋滥 |
| 携程保底展示席位 | 无播放量字段会被 B站高播放内容挤出首屏，但它质量确实好 |
| 展示层排序折叠而非硬过滤 | 主题硬过滤容易误杀，先「挑重点展示」，LLM 拿到的数据不变 |

## ⚠️ 免责声明

- 行程由 AI 生成，门票价格 / 开放时间 / 交通信息请以官方渠道为准
- 「AI 参考来源」链接指向第三方平台（B站 / 携程 / 百度）公开内容，版权归原作者所有
- 小红书入口仅为官方搜索链接复制，本项目不抓取、不存储任何小红书内容

## 📄 License

[MIT](LICENSE)
