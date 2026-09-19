// pages/index/index.js —— 小程序首页：表单 + 加载 + 结果渲染（与 demo.html 完全一致）
const { request } = require('../../utils/request.js');

// ---------- 常量 ----------
const BUDGETS = ["经济", "舒适", "轻奢"];
const STYLES = [
  { v: "relaxed", label: "轻松" },
  { v: "balanced", label: "均衡" },
  { v: "adventure", label: "紧凑" }
];
const INTEREST_EMO = {
  "美食": "🍜", "自然风光": "🏞️", "历史人文": "🏛️",
  "拍照打卡": "📸", "购物": "🛍️", "夜生活": "🌃"
};
const INTERESTS = ["美食", "自然风光", "历史人文", "拍照打卡", "购物", "夜生活"]
  .map(v => ({ v, emo: INTEREST_EMO[v], on: ["美食", "自然风光", "拍照打卡"].includes(v) }));

const EXAMPLES = [
  { title: "成都 3 天美食之旅", dest: "成都", days: 3, budgetIdx: 1, styleIdx: 1, prefs: "", int: ["美食", "拍照打卡"] },
  { title: "东京 5 天亲子游", dest: "东京", days: 5, budgetIdx: 2, styleIdx: 0, prefs: "带 2 个孩子，行程别太赶、多亲子项目", int: ["自然风光", "购物"] },
  { title: "清迈悠闲度假", dest: "清迈", days: 4, budgetIdx: 0, styleIdx: 0, prefs: "想慢节奏度假、泡酒店和夜市", int: ["自然风光", "夜生活"] }
];

// 天气 WMO 代码 → 图标 + 文字
const WMO = {
  0: ["☀️", "晴"], 1: ["🌤️", "晴间多云"], 2: ["⛅", "局部多云"], 3: ["☁️", "阴"],
  45: ["🌫️", "雾"], 48: ["🌫️", "雾凇"],
  51: ["🌦️", "毛毛雨"], 53: ["🌦️", "毛毛雨"], 55: ["🌦️", "毛毛雨"],
  56: ["🌧️", "冻毛雨"], 57: ["🌧️", "冻毛雨"],
  61: ["🌧️", "小雨"], 63: ["🌧️", "中雨"], 65: ["🌧️", "大雨"],
  66: ["🌧️", "冻雨"], 67: ["🌧️", "冻雨"],
  71: ["❄️", "小雪"], 73: ["❄️", "中雪"], 75: ["❄️", "大雪"], 77: ["❄️", "雪粒"],
  80: ["🌦️", "阵雨"], 81: ["🌦️", "阵雨"], 82: ["⛈️", "强阵雨"],
  85: ["🌨️", "阵雪"], 86: ["🌨️", "阵雪"],
  95: ["⛈️", "雷暴"], 96: ["⛈️", "雷暴伴雹"], 99: ["⛈️", "强雷暴"]
};
const wmo = (code) => WMO[code] || ["🌡️", "未知"];

// 类别 → 图标 + 配色（结果页渲染前注入到数据上，避免 WXML 调函数）
const CAT = {
  "美食": { icon: "🍜", color: "#ff7a59" },
  "观光": { icon: "🏞️", color: "#2bb3a3" },
  "拍照": { icon: "📷", color: "#9b6dff" },
  "交通": { icon: "🚇", color: "#4a90e2" },
  "住宿": { icon: "🏨", color: "#e0a13c" },
  "购物": { icon: "🛍️", color: "#e0609a" },
  "休闲": { icon: "☕", color: "#7a8aa0" },
  "其他": { icon: "📍", color: "#8a93a6" }
};
const PERIOD = { morning: "🌅 上午", afternoon: "☀️ 下午", evening: "🌙 晚上" };

// ---------- 日期工具 ----------
const pad = (n) => String(n).padStart(2, "0");
const fmtISO = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const todayISO = () => fmtISO(new Date());
const addDaysISO = (iso, n) => {
  const d = new Date(iso.replace(/-/g, "/") + " 00:00:00");
  d.setDate(d.getDate() + n);
  return fmtISO(d);
};
const md = (iso) => iso.slice(5).replace("-", "/");
const WK = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
const fmtCN = (iso) => {
  const d = new Date(iso.replace(/-/g, "/") + " 00:00:00");
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日 ${WK[d.getDay()]}`;
};

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

Page({
  data: {
    dest: "成都",
    days: 5,
    budgets: BUDGETS,
    budgetIdx: 1,
    interests: INTERESTS,
    styles: STYLES,
    styleIdx: 1,
    prefs: "",
    today: todayISO(),
    selectedDate: todayISO(),
    dateLabel: "",
    examples: EXAMPLES,

    view: "home",          // home / loading / result
    loadingStep: 0,        // 0..3 三 Agent 动画进度
    statusBarHeight: 44,   // 默认值（onLoad 中会更新为真实值）

    weather: [],
    weatherNote: "",
    weatherOk: false,

    rCity: "", rDays: "", rBudget: "", rStyle: "", rRange: "", rReq: "",
    rTemp: "—", rWeather: "待定", rSpots: 0,
    planJson: { summary: "", days: [], tips: [] },
    dates: [],

    // AI 参考来源（后端 plan.sources；展示策略与 demo.html 一致：
    // 旅行主题词优先 + 播放量降序 + 携程保底席位，默认只露 6 条其余折叠）
    srcTop: [], srcRest: [], srcTotal: 0, sourcesOpen: false,
    xhsUrl: ""
  },

  onLoad() {
    // 获取设备状态栏高度（用于自定义导航 offset）
    const info = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync();
    this.setData({
      statusBarHeight: info.statusBarHeight || 44,
      dateLabel: fmtCN(this.data.selectedDate)
    });
  },

  // ---------- 表单交互 ----------
  onDestInput(e) { this.setData({ dest: e.detail.value }); },
  onPrefsInput(e) { this.setData({ prefs: e.detail.value }); },

  minusDay() { this.setData({ days: Math.max(1, this.data.days - 1) }); },
  plusDay() { this.setData({ days: Math.min(14, this.data.days + 1) }); },

  selectBudget(e) {
    const idx = Number(e.currentTarget.dataset.idx);
    this.setData({ budgetIdx: idx });
  },
  selectStyle(e) {
    const idx = Number(e.currentTarget.dataset.idx);
    this.setData({ styleIdx: idx });
  },
  toggleInterest(e) {
    const idx = Number(e.currentTarget.dataset.idx);
    const interests = this.data.interests.slice();
    interests[idx] = Object.assign({}, interests[idx], { on: !interests[idx].on });
    this.setData({ interests });
  },
  onDateChange(e) {
    const iso = e.detail.value;       // picker 返回 YYYY-MM-DD
    this.setData({ selectedDate: iso, dateLabel: fmtCN(iso) });
  },

  applyExample(e) {
    const idx = Number(e.currentTarget.dataset.idx);
    const ex = EXAMPLES[idx];
    if (!ex) return;
    const interests = this.data.interests.map(it => Object.assign({}, it, { on: ex.int.includes(it.v) }));
    this.setData({
      dest: ex.dest, days: ex.days, budgetIdx: ex.budgetIdx, styleIdx: ex.styleIdx,
      prefs: ex.prefs || "", interests
    });
  },

  // ---------- 主流程 ----------
  async generate() {
    if (this.data.view === "loading") return;

    const dest = (this.data.dest || "").trim() || "成都";
    const days = this.data.days;
    const budget = BUDGETS[this.data.budgetIdx];
    const style = STYLES[this.data.styleIdx].v;
    const interests = this.data.interests.filter(i => i.on).map(i => i.v);
    const prefs = this.data.prefs.trim();
    const sdate = this.data.selectedDate || todayISO();

    const dates = [];
    for (let i = 0; i < days; i++) dates.push(addDaysISO(sdate, i));

    this.setData({
      rCity: dest,
      rDays: days + " 天 " + (days - 1) + " 晚",
      rBudget: budget,
      rStyle: STYLES[this.data.styleIdx].label,
      rRange: md(dates[0]) + "–" + md(dates[dates.length - 1]),
      rReq: prefs,
      dates,
      view: "loading",
      loadingStep: 0
    });

    this._runAgentAnim();

    const weatherPromise = this._getWeather(dest, dates);

    let plan = null, planErr = null;
    try {
      plan = await this._submitPlan({
        destination: dest, num_days: days, budget,
        interests, travel_style: style, extra_notes: prefs, start_date: sdate
      });
    } catch (e) {
      planErr = (e && e.message) || "生成失败";
    }

    let res;
    try {
      res = await weatherPromise;
    } catch (e) {
      res = { weather: dates.map(() => null), note: "天气查询失败", ok: false };
    }

    this._renderResult(plan, res, dates, planErr);
  },

  _runAgentAnim() {
    if (this._animTimer) clearInterval(this._animTimer);
    let step = 0;
    this._animTimer = setInterval(() => {
      step++;
      this.setData({ loadingStep: step });
      if (step >= 3) clearInterval(this._animTimer);
    }, 700);
  },

  // 天气走后端 /api/weather（单域名白名单）
  async _getWeather(dest, dates) {
    const start = dates[0], end = dates[dates.length - 1];
    return await request({
      url: `/api/weather?dest=${encodeURIComponent(dest)}&start=${start}&end=${end}`
    });
  },

  // 提交行程任务 + 轮询（解决 wx.request 60s 超时限制）
  async _submitPlan(payload) {
    const resp = await request({ url: "/api/plan/async", method: "POST", data: payload, timeout: 10000 });
    const taskId = resp.task_id;
    if (!taskId) throw new Error("提交失败：未返回任务 ID");
    for (let i = 0; i < 60; i++) {        // 最多约 3 分钟（60 × 3s）
      await sleep(3000);
      const st = await request({ url: `/api/plan/async/${taskId}`, timeout: 8000 });
      if (st.status === "done") return st.result;
      if (st.status === "failed") throw new Error(st.error || "生成失败");
    }
    throw new Error("生成超时（请稍后重试）");
  },

  _renderResult(plan, res, dates, planErr) {
    // 天气预处理（WXML 不能算周几/图标，这里算好）
    const labels = ["今天", "明天", "后天"];
    const weather = (res.weather || []).map((x, i) => {
      const lab = labels[i] || md(dates[i]);
      if (!x) return { far: true, label: lab };
      const [icon, text] = wmo(x.code);
      return { icon, text, max: x.max, min: x.min, label: lab };
    });

    // 行程预处理：注入图标/配色/日期标签/天气
    let planJson = null;
    let total = 0;
    if (plan && plan.itinerary_json && Array.isArray(plan.itinerary_json.days) && plan.itinerary_json.days.length) {
      planJson = JSON.parse(JSON.stringify(plan.itinerary_json));
      planJson.days.forEach((d, i) => {
        const dt = dates[i];
        d.dlabel = dt ? (md(dt) + " " + WK[new Date(dt.replace(/-/g, "/") + " 00:00:00").getDay()]) : "";
        const w = (res.weather && res.weather[i]) || null;
        d.wstr = w ? (wmo(w.code)[0] + " " + w.max + "°/" + w.min + "°") : "天气待定";
        (d.slots || []).forEach(s => {
          s.periodLabel = PERIOD[s.period] || (s.period || "");
          (s.items || []).forEach(it => {
            const c = CAT[it.category] || CAT["其他"];
            it.icon = c.icon; it.color = c.color;
          });
        });
        (d.slots || []).forEach(s => total += (s.items || []).length);
      });
    }

    const w0 = (res.weather && res.weather[0]) || null;
    const srcPrep = this._prepareSources(plan && plan.sources, this.data.rCity);
    this.setData({
      weather,
      weatherNote: res.note || "",
      weatherOk: !!res.ok,
      planJson: planJson || { summary: "", days: [], tips: [] },
      rSpots: total,
      rTemp: w0 ? w0.max + "°" : "—",
      rWeather: w0 ? wmo(w0.code)[1] : "待定",
      srcTop: srcPrep.srcTop,
      srcRest: srcPrep.srcRest,
      srcTotal: srcPrep.srcTotal,
      sourcesOpen: false,
      view: "result"
    });

    if (!plan) {
      // 把真实错误暴露出来，便于定位（域名未放行 / 后端没起 / 地址错 等）
      const detail = (planErr || "后端未返回行程").slice(0, 60);
      const g = (getApp() && getApp().globalData) || {};
      const tips = g.useContainer !== false
        ? "\n\n自查：①小程序后台「基础库最低版本」≥ 2.23.0；②app.js 的 cloudEnv / cloudService 是否与云托管控制台一致；③云托管服务是否为「运行中」（不是已暂停）。"
        : "\n\n自查：①开发者工具「详情→本地设置」勾选「不校验合法域名」；②确认后端已启动；③app.js 的 apiBase 指向本机 127.0.0.1:8000（模拟器）或局域网 IP（真机）。";
      wx.showModal({
        title: "生成失败",
        content: detail + tips,
        showCancel: false
      });
    } else if (!planJson) {
      wx.showToast({ title: "行程格式异常，检查后端", icon: "none" });
    }
  },

  // ---------- AI 参考来源（排序/折叠/携程保底，策略与 demo.html 对齐） ----------
  _prepareSources(rawSources, dest) {
    const TRAVEL_WORDS = ["攻略", "美食", "景点", "酒店", "住宿", "民宿", "路线", "行程", "交通",
      "机位", "避坑", "小吃", "vlog", "citywalk", "一日游", "二日游", "三日游", "自由行",
      "打卡", "探店", "游记", "口岸", "过关", "玩"];
    const CLS = { "小红书": "xhs", "百度": "bd", "B站": "bili", "携程": "ctrip" };
    const playOf = s => {
      const m = (s.abstract || "").match(/播放：([\d,]+)/);
      return m ? +m[1].replace(/,/g, "") : 0;
    };
    const list = (rawSources || []).map(s => Object.assign({}, s, {
      cls: CLS[s.source] || "unk",
      play: playOf(s)
    }));
    const travelOf = s => {
      const t = (s.title || "").toLowerCase();
      return TRAVEL_WORDS.some(w => t.indexOf(w) !== -1) ? 1 : 0;
    };
    list.sort((a, b) => (travelOf(b) - travelOf(a)) || (b.play - a.play));

    const TOP_N = 6;
    let head = list.slice(0, TOP_N);
    let rest = list.slice(TOP_N);
    // 携程保底席位：前 TOP_N 无携程且库里有 → 插到第 2 位
    if (head.length && !head.some(s => s.source === "携程")) {
      const ci = list.findIndex(s => s.source === "携程");
      if (ci !== -1) {
        const ctrip = list[ci];
        const dropped = head[head.length - 1];
        head = [head[0], ctrip].concat(head.slice(1, head.length - 1));
        rest = [dropped].concat(rest.filter(s => s !== ctrip));
      }
    }
    return { srcTop: head, srcRest: rest, srcTotal: list.length };
  },

  toggleSources() { this.setData({ sourcesOpen: !this.data.sourcesOpen }); },

  // 小程序内打不开外链（个人主体无 web-view 权限），复制链接让用户去浏览器/小红书打开
  onCopyLink(e) {
    const url = e.currentTarget.dataset.url;
    if (!url) return;
    wx.setClipboardData({
      data: url,
      success: () => wx.showToast({ title: "链接已复制", icon: "success" })
    });
  },

  // 小红书实时笔记：复制搜索链接（合规：不抓内容，跳官方搜索）
  onXhs() {
    const dest = this.data.rCity || "旅行";
    const url = "https://www.xiaohongshu.com/search_result?keyword=" +
      encodeURIComponent(dest + " 旅游攻略");
    wx.setClipboardData({
      data: url,
      success: () => wx.showModal({
        title: "📕 小红书搜索链接已复制",
        content: "粘贴到浏览器或小红书 App 搜索框，即可看「" + dest + "」最新真实笔记。",
        showCancel: false,
        confirmText: "好的"
      })
    });
  },

  // 朋友圈分享
  onShareTimeline() {
    const city = this.data.rCity || "旅行";
    return { title: `${city}${this.data.rDays} AI 旅行方案，拿走不谢` };
  },

  backHome() { this.setData({ view: "home" }); },

  // 分享（button open-type="share" 触发）
  onShareAppMessage() {
    const city = this.data.rCity || "旅行";
    return {
      title: `${city}${this.data.rDays} AI 旅行方案，拿走不谢`,
      path: "/pages/index/index"
    };
  },

  // 分享按钮（普通 tap，也可触发 share）
  onShare() {
    wx.showShareMenu({ withShareTicket: true });
    wx.showToast({ title: "请点击右上角 ··· 分享", icon: "none" });
  },

  // 下载卡：复制行程到剪贴板
  onDownload(e) {
    const type = e.currentTarget.dataset.type;
    const plan = this.data.planJson;
    if (!plan || !plan.days || !plan.days.length) {
      wx.showToast({ title: "暂无行程数据", icon: "none" });
      return;
    }
    let text = "";
    const city = this.data.rCity || "";
    const days = this.data.rDays || "";

    if (type === "txt" || type === "md") {
      // 纯文本 / Markdown
      const lines = [];
      if (type === "md") lines.push("# " + city + " " + days + " 行程方案\n");
      else lines.push(city + " " + days + " 行程方案\n");
      if (plan.summary) lines.push((type === "md" ? "> " : "") + plan.summary + "\n");
      (plan.days || []).forEach(d => {
        if (type === "md") lines.push("## Day " + (d.day || "") + " · " + (d.theme || ""));
        else lines.push("— Day " + (d.day || "") + " · " + (d.theme || "") + " —");
        (d.slots || []).forEach(s => {
          lines.push((type === "md" ? "### " : "") + (s.periodLabel || ""));
          (s.items || []).forEach(it => {
            const dur = it.duration ? " (" + it.duration + ")" : "";
            if (type === "md") lines.push("- **" + (it.title || "") + "**" + dur);
            else lines.push("  • " + (it.title || "") + dur);
            if (it.note) lines.push(type === "md" ? "  " + it.note : "    " + it.note);
          });
        });
        lines.push("");
      });
      if (plan.tips && plan.tips.length) {
        if (type === "md") lines.push("## 💡 实用贴士");
        else lines.push("💡 实用贴士");
        plan.tips.forEach(t => lines.push((type === "md" ? "- " : "• ") + t));
      }
      text = lines.join("\n");
    } else if (type === "ics") {
      // 生成简易 .ics 日历
      const icsLines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//AI Travel Planner//", "CALSCALE:GREGORIAN"];
      const dates = this.data.dates || [];
      (plan.days || []).forEach((d, i) => {
        const dt = dates[i];
        if (!dt) return;
        const dtStr = dt.replace(/-/g, "");
        (d.slots || []).forEach(s => {
          (s.items || []).forEach(it => {
            icsLines.push("BEGIN:VEVENT");
            icsLines.push("DTSTART;VALUE=DATE:" + dtStr);
            icsLines.push("DTEND;VALUE=DATE:" + dtStr);
            icsLines.push("SUMMARY:" + ((it.title || "").replace(/[,;]/g, "")));
            icsLines.push("DESCRIPTION:" + ((it.note || "").replace(/[,;\\]/g, "")));
            icsLines.push("END:VEVENT");
          });
        });
      });
      icsLines.push("END:VCALENDAR");
      text = icsLines.join("\r\n");
    }

    if (text) {
      wx.setClipboardData({
        data: text,
        success: () => wx.showToast({ title: "已复制到剪贴板", icon: "success" })
      });
    }
  }
});
