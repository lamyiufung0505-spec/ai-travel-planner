"""
AI Travel Planner —— 核心引擎（后端可复用版）
============================================

从 ai-travel-agent 的 travel_agent.py 抽出的**纯逻辑层**，去掉了 Streamlit 的 UI 代码，
让同一套「三 Agent 协作（Researcher → Planner → Critic → Planner 终稿）」能被 FastAPI 后端直接调用。

为什么单独抽一层？
- travel_agent.py 顶层有 st.title(...) 等 Streamlit 代码，直接 import 会触发 UI 运行时不报错；
- 后端（服务器）持有 DeepSeek Key，前端小程序只负责收集偏好 + 展示，符合「Key 不进前端」的安全约束；
- 抽成函数后，原 Streamlit 版本和后端版本共用同一套 Agent 定义逻辑，互不污染。

注意：本文件与 travel_agent.py 的核心指令（researcher/planner/critic 的 prompt、搜索引擎切换、
小红书工具、中国城市判断）保持一致，便于对照学习。
"""

from textwrap import dedent
from agno.agent import Agent
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.baidusearch import BaiduSearchTools
from agno.tools.toolkit import Toolkit
from baidusearch.baidusearch import search
from agno.models.deepseek import DeepSeek
from icalendar import Calendar, Event
from datetime import datetime, timedelta
import pycountry
import threading
import time
import http.cookiejar
import urllib.request
import urllib.parse
import json
import re


# ===== 搜索来源记录（用于前端展示「AI 实际搜到了哪些帖子/网页」） =====
# 研究员在跑 DeepSeek 时会真实调用百度/小红书搜索工具，我们把每次工具的原始结果
# 记下来随接口返回，方便在 demo 里查看。用 threading.local 避免并发请求串味。

_CAPTURE = threading.local()


def _record_source(item: dict, source_name: str):
    if not hasattr(_CAPTURE, "sources"):
        _CAPTURE.sources = []
    url = (item.get("url") or "").strip()
    # 只保留真实外链：过滤掉百度站内搜索页（相对路径 /s?wd=... 或 baidu.com 搜索页）
    if not (url.startswith("http://") or url.startswith("https://")):
        return
    if "baidu.com/s?" in url or "baidu.com/s/?" in url:
        return
    _CAPTURE.sources.append({
        "title": (item.get("title") or "").strip(),
        "abstract": (item.get("abstract") or "").strip(),
        "url": url,
        "source": source_name,
    })


def _reset_sources():
    _CAPTURE.sources = []


def _get_sources():
    seen, out = set(), []
    for it in getattr(_CAPTURE, "sources", []):
        u = it.get("url", "")
        if u in seen:
            continue
        seen.add(u)
        out.append(it)
    return out


# ===== 自定义工具：小红书搜索（带来源记录） =====
# 原理：百度搜索支持 site: 语法（如 "成都美食 site:xiaohongshu.com"），
# 我们只搜小红书域名下的内容，获取到真实用户的旅行体验分享。
class XiaohongshuSearchTools(Toolkit):
    def __init__(self, fixed_max_results: int = None, fixed_language: str = "zh", **kwargs):
        self.fixed_max_results = fixed_max_results
        self.fixed_language = fixed_language
        super().__init__(name="xiaohongshu", tools=[self.xiaohongshu_search], **kwargs)

    def xiaohongshu_search(self, query: str, max_results: int = 5, language: str = "zh") -> str:
        """在小红书上搜索高质量的旅行攻略和真实体验分享笔记。"""
        if len(language) != 2:
            try:
                language = pycountry.languages.lookup(language).alpha_2
            except LookupError:
                language = "zh"
        max_results = self.fixed_max_results or max_results
        site_query = f"{query} site:xiaohongshu.com"
        results = search(keyword=site_query, num_results=max_results)
        res = []
        for idx, item in enumerate(results, 1):
            res.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "abstract": item.get("abstract", ""),
                "rank": str(idx),
            })
        # 记录来源供前端展示
        for it in res:
            _record_source(it, "小红书")
        return json.dumps(res, indent=2, ensure_ascii=False)


# ===== B站官方搜索工具（直接调 api.bilibili.com，免登录、服务器可跑） =====
# 与 SiteSearchTools（百度 site: 拼法）不同：这里是真实 B站搜索接口，
# 返回干净的真实视频链接（bilibili.com/video/BV...）、UP主、播放量、时长，
# 不受百度索引时效与限流影响，内容天然新鲜（实测常见 2026 年新内容）。
#
# ⚠️ 两个实测踩出来的坑，都已在这里修掉：
#   1. 必须带 buvid3 Cookie。匿名请求实测约每 2~3 次就被 B站降级一次，
#      返回与关键词完全无关的泛化热门（搜「泉州 旅游攻略」却给出贵州攻略 / 游戏区视频）。
#      带上 buvid3 后连续 3 轮全部精准。做法：先访问 www.bilibili.com 取 Set-Cookie。
#   2. 结果必须做相关性校验。万一还是被降级，也绝不让垃圾流进 LLM：
#      标题/简介里没出现查询中的实体词（目的地、景点名）就整批丢弃，宁缺毋滥。
class BilibiliSearchTools(Toolkit):
    """在 B站 上搜索真实旅行 vlog / 攻略视频（真实链接、免登录、服务器可跑）。"""

    _UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    _opener = None
    _cookie_at = 0.0
    _cookie_ttl = 1800          # cookie 有效期（秒）
    _min_interval = 0.8         # 两次请求最小间隔，别打太猛把风控惹毛
    _last_call_at = 0.0
    _lock = threading.Lock()

    # 通用旅行词：既不能用来判断「结果和目的地是否相关」，也**不该出现在发给 B站的 query 里**
    # （实测：query 带「本地人 美食」会让 B站优先返回全国各地的「XX本地人美食」高播放视频）
    _STOPWORDS = {
        "攻略", "旅游", "旅行", "推荐", "必去", "美食", "住宿", "酒店", "民宿",
        "景点", "路线", "行程", "打卡", "游玩", "好玩", "一日游", "三日游", "五日游",
        "自由行", "周边游", "自驾", "徒步", "避坑", "指南", "最新", "教程",
        "实拍", "全集", "合集", "视频", "怎么玩", "有哪些", "当地", "本地", "一天",
        # —— 二轮补充（香港屯门实测混入「南京/潮州/广州本地人美食」复盘）——
        "本地人", "必吃", "必玩", "必看", "小吃", "探店", "吃喝", "好吃", "宝藏",
        "正宗", "特色", "游记", "vlog", "Vlog", "VLOG", "保姆级", "掏箱底", "吐血整理",
        "分享", "整理", "超全", "排行榜", "榜单", "排行", "小长假", "假期", "周末",
        "市区", "探秘", "第二期", "第一期", "系列",
    }

    # 运输爱好者内容（POV/驾驶实录）：地点对但对旅行规划没价值，直接过滤
    _TRANSIT_BLACKLIST = ("pov", "驾驶", "报站", "前方展望", "行车记录", "全程展望")

    # 时政/社会类内容黑名单：与旅行无关且踩合规红线，标题命中即弃
    # （实测：query 只剩「香港」单词时，B站综合搜索会返回时政视频，绝对不能进来源区）
    _POLITICS_BLACKLIST = (
        "乱港", "之乱", "暴力", "游行", "示威", "黑暴", "反修例", "大起底",
        "实录曝光", "事件真相", "局势",
    )

    # UP主营销话术 / 弱关键词：只从「发给 B站的 query」里剔除。
    # 注意与 _STOPWORDS 区分：美食/酒店/交通这类**主题词保留在 query 里**
    # （「香港 美食」对 B站是精准组合），只有话术类词会把搜索带沟里。
    _QUERY_FILLERS = {
        "本地人", "土著", "掏箱底", "吐血整理", "保姆级", "必吃", "必玩", "必看",
        "探店", "吃喝", "好吃", "宝藏", "正宗", "超全", "排行榜", "榜单", "排行",
        "小长假", "探秘", "整理", "分享", "合集", "全集", "系列", "第二期", "第一期",
        "推荐", "避坑", "指南", "最新", "实用", "干货", "攻略", "旅游", "旅行",
    }

    @classmethod
    def _ensure_session(cls):
        """拿到带 buvid3 的 opener（首次访问首页取 Set-Cookie），带 TTL 自动刷新。"""
        now = time.time()
        with cls._lock:
            if cls._opener and (now - cls._cookie_at) < cls._cookie_ttl:
                return cls._opener
            jar = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
            try:
                opener.open(
                    urllib.request.Request(
                        "https://www.bilibili.com/", headers={"User-Agent": cls._UA}
                    ),
                    timeout=15,
                ).read()
            except Exception:
                pass        # 拿不到 cookie 就退化匿名；靠第 2 道相关性校验兜底
            cls._cookie_header = "; ".join(f"{c.name}={c.value}" for c in jar)
            cls._opener = opener
            cls._cookie_at = now
            return cls._opener

    @classmethod
    def _search_raw(cls, keyword: str, page: int = 1):
        opener = cls._ensure_session()
        with cls._lock:                       # 简单节流，避免短时高频请求
            gap = time.time() - cls._last_call_at
            if cls._min_interval - gap > 0:
                time.sleep(cls._min_interval - gap)
            cls._last_call_at = time.time()
        url = ("https://api.bilibili.com/x/web-interface/search/all/v2?keyword="
               + urllib.parse.quote(keyword) + f"&page={page}")
        req = urllib.request.Request(url, headers={
            "User-Agent": cls._UA,
            "Referer": "https://www.bilibili.com/",
            "Cookie": getattr(cls, "_cookie_header", ""),
        })
        with opener.open(req, timeout=12) as resp:
            return json.loads(resp.read())

    @staticmethod
    def _entity_terms(query: str):
        """抽出能代表「这个目的地/主题」的实体词，通用旅行词一律剔除。"""
        terms = []
        for tok in re.split(r"[\s,，、/|]+", query or ""):
            tok = tok.strip()
            if len(tok) < 2:
                continue
            if tok in BilibiliSearchTools._STOPWORDS or tok.lower() in BilibiliSearchTools._STOPWORDS:
                continue
            terms.append(tok)
        return terms

    @staticmethod
    def _fmt_time(unix_ts):
        try:
            return time.strftime("%Y-%m", time.localtime(int(unix_ts)))
        except Exception:
            return ""

    @staticmethod
    def _split_destination(dest):
        """把目的地切成可校验的词集：『香港屯门』→ ['香港屯门', '香港', '屯门']。"""
        dest = (dest or "").strip()
        if not dest:
            return []
        terms = set()
        for seg in re.split(r"[\s,，、/|]+", dest):
            seg = seg.strip()
            if not seg:
                continue
            terms.add(seg)
            if len(seg) >= 3:                 # 中文地名 3 字以上：头尾各取 2 字做宽松召回
                terms.add(seg[:2])
                terms.add(seg[-2:])
        for tok in re.findall(r"[A-Za-z]{2,}", dest):     # 英文地名
            terms.add(tok.lower())
        return [t for t in terms if t]

    @classmethod
    def _clean_query(cls, query):
        """发请求前剔除营销话术词、并保证目的地在场 —— 从源头别让 B站跑偏。
        只剔 _QUERY_FILLERS（话术/弱词），保留美食/酒店/交通这类主题词。"""
        dest = (getattr(_CAPTURE, "destination", "") or "").strip()
        toks = [t for t in re.split(r"[\s,，、/|]+", query or "") if t]
        kept = [t for t in toks
                if t not in cls._QUERY_FILLERS and t.lower() not in cls._QUERY_FILLERS]
        if dest:
            head = re.split(r"[\s,，、/|]+", dest)[0]
            dest_words = cls._split_destination(dest)
            joined = " ".join(kept)
            if not kept:
                kept = [head]
            elif not any(d.lower() in joined.lower() for d in dest_words):
                kept = [head] + kept          # query 里没带目的地 → 补到最前
        return " ".join(kept) or (query or "").strip()

    def __init__(self, fixed_max_results: int = 5, **kwargs):
        self.fixed_max_results = fixed_max_results
        super().__init__(name="B站", tools=[self.search], **kwargs)

    def search(self, query: str, max_results: int = 5, language: str = "zh") -> str:
        """在 B站 搜索高质量的旅行 vlog / 在地攻略视频（真实链接、带播放量与时长）。"""
        max_results = self.fixed_max_results or max_results
        keyword = self._clean_query(query)          # 先清洗：剔通用词 + 补目的地，别让 B站跑偏
        try:
            data = self._search_raw(keyword)
        except Exception:
            return json.dumps([], indent=2, ensure_ascii=False)
        if data.get("code") != 0:
            return json.dumps([], indent=2, ensure_ascii=False)
        blocks = data.get("data", {}).get("result", []) or []
        videos = []
        for block in blocks:
            if block.get("result_type") == "video":
                videos = block.get("data", []) or []
                break

        # 相关性校验：锚点优先用用户目的地（如「香港屯门」→ 香港/屯门），
        # 仅当目的地缺失时才退回 query 实体词。
        must = self._split_destination(getattr(_CAPTURE, "destination", "")) \
            or self._entity_terms(keyword)
        if must:
            kept = []
            for v in videos:
                hay = ((v.get("title") or "") + " " + (v.get("description") or "")) \
                    .replace('<em class="keyword">', "").replace("</em>", "").lower()
                if any(t.lower() in hay for t in must):
                    kept.append(v)
            videos = kept
            if not videos:
                return json.dumps([], indent=2, ensure_ascii=False)   # 宁缺毋滥

        # 过滤运输 POV（地点对但无旅行价值）与时政内容（合规红线）
        def _is_bad(v):
            text = ((v.get("title") or "") + " " + (v.get("description") or "")).lower()
            return (any(b in text for b in self._TRANSIT_BLACKLIST)
                    or any(p in text for p in self._POLITICS_BLACKLIST))
        videos = [v for v in videos if not _is_bad(v)]
        if not videos:
            return json.dumps([], indent=2, ensure_ascii=False)

        res = []
        for idx, v in enumerate(videos[:max_results], 1):
            title = (v.get("title") or "").replace('<em class="keyword">', "").replace("</em>", "")
            author = v.get("author") or ""
            play = v.get("play") or 0
            dur = v.get("duration") or ""
            pub = self._fmt_time(v.get("pubdate") or 0)
            bvid = v.get("bvid") or v.get("id") or ""
            if not bvid:
                continue
            link = f"https://www.bilibili.com/video/{bvid}"
            abstract = f"UP主：{author}　播放：{play}　时长：{dur}"
            if pub:
                abstract += f"　发布：{pub}"
            item = {"title": title, "url": link, "abstract": abstract, "rank": str(idx)}
            res.append(item)
            # 记录真实来源供前端展示（链接是 bilibili.com 真实地址，非百度跳转链）
            _record_source({"title": title, "url": link, "abstract": abstract}, "B站")
        return json.dumps(res, indent=2, ensure_ascii=False)


# ===== 指定旅行站点搜索工具（带来源记录） =====
# 原理：用百度 site: 语法锁定 携程 等垂直旅行 UGC 站点，
# 拿到一手游记 / 真实攻略，比泛百度知乎更新、更潮、更接地气。
# （注：B站 已独立为 BilibiliSearchTools，直接调官方接口，不走百度。）
class SiteSearchTools(Toolkit):
    def __init__(self, site: str, label: str, fixed_max_results: int = None, fixed_language: str = "zh", **kwargs):
        self.site = site
        self.label = label
        self.fixed_max_results = fixed_max_results
        self.fixed_language = fixed_language
        super().__init__(name=label, tools=[self.search], **kwargs)

    def search(self, query: str, max_results: int = 5, language: str = "zh") -> str:
        """在指定旅行站点搜索高质量的旅行攻略与真实体验分享（含最新一手内容）。"""
        if len(language) != 2:
            try:
                language = pycountry.languages.lookup(language).alpha_2
            except LookupError:
                language = "zh"
        max_results = self.fixed_max_results or max_results
        # 注：不加年份关键词——实测加 "2026" 会让百度 site: 结果归零；
        # B站/携程本身是 UGC 平台，内容天然新鲜，靠站点即可保新。
        site_query = f"{query} 攻略 site:{self.site}"
        results = search(keyword=site_query, num_results=max_results)
        # 兜底：超具体查询（如"泉州 华侨大学附近"）在垂直站点常搜不到，
        # 退回目的地市级查询（用干净的目的地），提高命中率（B站/携程尤其明显）。
        if not results:
            dest = getattr(_CAPTURE, "destination", "").strip()
            if dest:
                fb_query = f"{dest} 攻略 site:{self.site}"
                results = search(keyword=fb_query, num_results=max_results)
        res = []
        for idx, item in enumerate(results, 1):
            res.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "abstract": item.get("abstract", ""),
                "rank": str(idx),
            })
            _record_source(item, self.label)
        return json.dumps(res, indent=2, ensure_ascii=False)


# ===== 百度搜索工具（带来源记录） =====
class CapturingBaiduSearchTools(BaiduSearchTools):
    """在 agno 百度搜索工具基础上记录原始结果，便于前端展示来源。"""

    def baidu_search(self, query: str, max_results: int = 5, language: str = "zh") -> str:
        """百度搜索（事实兜底专用）：仅当 B站/携程 未覆盖官方硬事实（景点介绍、门票价格、交通路线、开放时间、政策）时才调用，用于补充事实缺口，不要作为首选搜索源。"""
        raw = super().baidu_search(query, max_results, language)
        try:
            for it in json.loads(raw):
                _record_source(it, "百度")
        except Exception:
            pass
        return raw


# ===== 中国城市 & 关键词列表（用于智能切换搜索引擎） =====
CHINA_CITIES = {
    "北京", "上海", "广州", "深圳", "成都", "重庆", "杭州", "武汉", "西安", "南京",
    "长沙", "苏州", "郑州", "青岛", "大连", "厦门", "昆明", "贵阳", "拉萨", "桂林",
    "丽江", "三亚", "黄山", "泰山", "洛阳", "开封", "天津", "沈阳", "哈尔滨", "长春",
    "呼和浩特", "乌鲁木齐", "银川", "西宁", "兰州", "福州", "合肥", "南昌", "石家庄",
    "济南", "太原", "无锡", "宁波", "温州", "佛山", "东莞", "珠海", "中山", "惠州",
    "潮汕", "潮州", "汕头", "扬州", "绍兴", "嘉兴", "湖州", "镇江", "常州", "徐州",
    "泉州", "漳州", "龙岩", "景德镇", "九江", "岳阳", "湘潭", "衡阳", "凤凰",
    "大理", "香格里拉", "西双版纳", "九寨沟", "峨眉山", "都江堰", "敦煌", "张掖",
    "拉萨", "林芝", "稻城亚丁", "青海湖", "茶卡盐湖", "纳木错", "珠穆朗玛峰",
    "长城", "故宫", "颐和园", "天坛", "兵马俑", "华清池", "少林寺", "武当山",
    "峨眉山", "青城山", "乐山大佛", "莫高窟", "布达拉宫", "拙政园", "留园",
    "中国", "内地", "大陆", "中华",
}
CHINA_KEYWORDS = {
    "中国", "国内", "内地",
    "川", "粤", "京", "沪", "蓉", "渝", "杭", "苏", "湘", "闽", "滇", "黔", "藏",
    "陕", "豫", "鲁", "赣", "桂", "琼", "甘", "青", "宁", "新", "蒙", "辽", "吉",
    "黑", "冀", "晋", "皖", "鄂", "浙", "苏", "台", "港", "澳",
}


def is_chinese_destination(destination: str) -> bool:
    """判断目的地是否在中国 → 决定用百度/小红书还是 DuckDuckGo 搜索（4 层检测）。"""
    dest_lower = destination.lower().strip()
    for city in CHINA_CITIES:
        if city in dest_lower or dest_lower in city:
            return True
    for kw in CHINA_KEYWORDS:
        if kw in dest_lower:
            return True
    if any('\u4e00' <= c <= '\u9fff' for c in destination):
        return True
    return False


def generate_ics_content(plan_text: str, start_date: datetime = None) -> bytes:
    """将行程文本转换为 .ics 日历文件（标准 iCalendar 格式）。"""
    cal = Calendar()
    cal.add('prodid', '-//AI Travel Planner//github.com//')
    cal.add('version', '2.0')
    if start_date is None:
        start_date = datetime.today()
    day_pattern = re.compile(r'Day (\d+)[:\s]+(.*?)(?=Day \d+|$)', re.DOTALL)
    days = day_pattern.findall(plan_text)
    if not days:
        event = Event()
        event.add('summary', "Travel Itinerary")
        event.add('description', plan_text)
        event.add('dtstart', start_date.date())
        event.add('dtend', start_date.date())
        event.add("dtstamp", datetime.now())
        cal.add_component(event)
    else:
        for day_num, day_content in days:
            day_num = int(day_num)
            current_date = start_date + timedelta(days=day_num - 1)
            event = Event()
            event.add('summary', f"Day {day_num} Itinerary")
            event.add('description', day_content.strip())
            event.add('dtstart', current_date.date())
            event.add('dtend', current_date.date())
            event.add("dtstamp", datetime.now())
            cal.add_component(event)
    return cal.to_ical()


# ===== 结构化 JSON 提取（根治「前端解析 Markdown 易崩」的根因） =====
# 让最终 Planner 直接输出严格 JSON，前端按模板渲染成清爽卡片；
# 这里做稳健提取：剥离 ```json 围栏、截取首个完整 {…}，解析失败返回 None（前端回退 Markdown）。
def _extract_json(text: str):
    if not text:
        return None
    t = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", t, re.I)
    if m:
        t = m.group(1).strip()
    s = t.find("{")
    e = t.rfind("}")
    if s != -1 and e != -1 and e > s:
        t = t[s:e + 1]
    try:
        data = json.loads(t)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


# 追加给最终 Planner 的 JSON 输出指令（与上面 _extract_json 的字段约定一致）
JSON_SCHEMA_INSTRUCTION = dedent(
    """\
    请以上述修改为基础生成【最终行程】，必须以严格的 JSON 格式输出，
    不要输出任何解释性文字，也不要用 Markdown 代码块包裹。结构如下：

    {
      "destination": "目的地名称",
      "summary": "一句话总体建议，涵盖预算区间、节奏、关键贴士（如交通APP、不辣选项），不超过120字",
      "days": [
        {
          "day": 1,
          "theme": "当天主题，如『老城烟火 · 宽窄巷子与盖碗茶』",
          "slots": [
            {
              "period": "morning",
              "items": [
                {"title": "活动/景点名称", "category": "美食", "duration": "2小时", "note": "一句具体说明，含价格/路线/避坑"}
              ]
            },
            {"period": "afternoon", "items": [ {"title": "...", "category": "观光", "duration": "2.5小时", "note": "..."} ]},
            {"period": "evening", "items": [ {"title": "...", "category": "休闲", "duration": "自由", "note": "..."} ]}
          ]
        }
      ],
      "tips": ["实用贴士1", "实用贴士2", "实用贴士3"]
    }

    硬性要求：
    - period 只能是 morning / afternoon / evening 三种之一（分别代表上午/下午/晚上）
    - category 只能是：美食 / 观光 / 拍照 / 交通 / 住宿 / 购物 / 休闲 / 其他（无法归类填『其他』）
    - 每天至少覆盖两个时段，活动数量匹配用户旅行风格（relaxed 少而精，adventure 可更满）
    - note 要具体可信，引用搜索到的真实信息（价格、地铁线路、开放时间），严禁编造不存在的景点或价格
    """
)


# 前端 demo 用的中文兴趣 → 原 Planner 英文约束词 的映射，让偏好约束真正生效
INTEREST_MAP = {
    "美食": "food & cuisine",
    "美食之旅": "food & cuisine",
    "自然风光": "nature & outdoors",
    "自然": "nature & outdoors",
    "历史人文": "history & culture",
    "历史": "history & culture",
    "拍照打卡": "photography",
    "拍照": "photography",
    "购物": "shopping & markets",
    "夜生活": "nightlife & entertainment",
    "艺术": "art & museums",
    "运动": "sports & fitness",
}
BUDGET_MAP = {
    "经济": "budget (backpacker)",
    "舒适": "mid-range",
    "轻奢": "luxury",
    "budget": "budget (backpacker)",
    "mid-range": "mid-range",
    "luxury": "luxury",
}


def _normalize_prefs(prefs: dict) -> dict:
    """把前端/接口传入的偏好标准化成引擎内部使用的字段。"""
    destination = (prefs.get("destination") or prefs.get("dest") or "").strip()
    num_days = int(prefs.get("num_days") or prefs.get("days") or 5)
    num_days = max(1, min(30, num_days))
    raw_budget = prefs.get("budget") or "舒适"
    budget = BUDGET_MAP.get(raw_budget, raw_budget)
    travel_style = prefs.get("travel_style") or "balanced"
    raw_interests = prefs.get("interests") or []
    if isinstance(raw_interests, str):
        raw_interests = [raw_interests]
    interests = [INTEREST_MAP.get(i, i) for i in raw_interests]
    dietary = prefs.get("dietary") or "no restrictions"
    extra_notes = prefs.get("extra_notes") or prefs.get("notes") or ""
    return {
        "destination": destination,
        "num_days": num_days,
        "budget": budget,
        "travel_style": travel_style,
        "interests": interests,
        "dietary": dietary,
        "extra_notes": extra_notes,
    }


def _build_agents(api_key: str, is_china: bool):
    """根据目的地语言构建三个 Agent（researcher/planner/critic）。"""
    if is_china:
        search_tools = [
            BilibiliSearchTools(fixed_max_results=5),                                        # 主力：B站官方接口，真实链接/最新最潮
            SiteSearchTools(site="you.ctrip.com", label="携程", fixed_language="zh"),         # 主力：真实游记攻略
            CapturingBaiduSearchTools(fixed_language="zh"),                                  # 兜底：官方信息/开放时间/票价/交通
        ]
        search_engine_name = "B站 + 携程 + 百度(事实兜底)"
        researcher_instructions = [
            "给定一个中国旅行目的地和旅行天数，首先生成3个中文搜索关键词（如'成都 5日游 攻略'、'成都 美食推荐 本地人'、'成都 住宿 性价比'）。",
            "搜索优先级：先用【B站】和【携程】找真实用户体验（本地人推荐的餐厅、小众景点、避坑指南、拍照机位、最新在地路线、真实游记）；这两类内容最新鲜、最接地气，是主力来源。",
            "【百度】只在需要硬事实时使用：景点官方介绍、门票价格、交通路线、开放时间、政策类信息——且仅当 B站/携程 未覆盖到该事实时才调用，作为兜底补充，不要一上来就调百度。",
            "对每个搜索关键词，优先用 B站/携程 工具搜索并分析结果；若确实缺少官方硬事实，再用百度补全。",
            "从所有搜索结果中，返回10条最相关且最实用的结果，优先选择有具体细节、有真实体验分享、时间较新的内容（B站/携程 优先）。",
            "记住：搜索结果的质量很重要，要确保信息来自真实的本地平台和用户分享，避免过时或泛泛的推广内容。",
        ]
        researcher_description = dedent(
            """\
            你是一位精通中国旅游的资深研究者。给定一个中国旅行目的地和旅行天数，
            生成中文搜索关键词，通过 B站、携程、百度 等工具找到真实旅行信息。
            搜索优先级：【B站】和【携程】是主力来源，用于真实用户分享的餐厅、小众景点、避坑经验、最新在地路线、真实游记；
            【百度】是事实兜底，仅在需要官方信息（景点介绍、门票价格、交通路线、开放时间、政策）且 B站/携程 未覆盖时调用。
            重点关注有具体细节的本地人推荐和较新的内容，而不是翻译的英文旅游博客或泛泛的推广内容。
            """
        )
        planner_china_hint = [
            "CRITICAL: 这是一个中国国内目的地，行程中请使用中文地名和中文描述。推荐具体的餐厅名称、景点中文全名、地铁线路（如'地铁2号线宽窄巷子站'）。",
            "CRITICAL: 价格请用人民币（¥）标注，交通请说明具体的地铁/公交路线和票价。",
            "CRITICAL: 餐饮推荐请优先选择本地特色（如成都的火锅串串、西安的泡馍肉夹馍），而不是泛泛的'当地美食'。",
        ]
    else:
        search_tools = [DuckDuckGoTools()]
        search_engine_name = "DuckDuckGo"
        researcher_instructions = [
            "Given a travel destination and the number of days the user wants to travel for, first generate a list of 3 search terms related to that destination and the number of days.",
            "For each search term, use the search tool and analyze the results.",
            "From the results of all searches, return the 10 most relevant results to the user's preferences.",
            "Remember: the quality of the results is important.",
        ]
        researcher_description = dedent(
            """\
            You are a world-class travel researcher. Given a travel destination and the number of days the user wants to travel for,
            generate a list of search terms for finding relevant travel activities and accommodations.
            Then search the web for each term, analyze the results, and return the 10 most relevant results.
            """
        )
        planner_china_hint = []

    researcher = Agent(
        name="Researcher",
        role="Searches for travel destinations, activities, and accommodations based on user preferences",
        model=DeepSeek(id="deepseek-chat", api_key=api_key),
        description=researcher_description,
        instructions=researcher_instructions,
        tools=search_tools,
        add_datetime_to_context=True,
    )
    planner = Agent(
        name="Planner",
        role="Generates a draft itinerary based on user preferences and research results",
        model=DeepSeek(id="deepseek-chat", api_key=api_key),
        description=dedent(
            """\
            You are a senior travel planner. Given a travel destination, the number of days the user wants to travel for, and a list of research results,
            your goal is to generate a draft itinerary that meets the user's needs and preferences.
            You must strictly respect the user's budget, interests, travel style, and dietary preferences when planning.
            """
        ),
        instructions=[
            "Given a travel destination, the number of days the user wants to travel for, and a list of research results, generate a draft itinerary that includes suggested activities and accommodations.",
            "Ensure the itinerary is well-structured, informative, and engaging.",
            "Ensure you provide a nuanced and balanced itinerary, quoting facts where possible.",
            "CRITICAL: Respect the user's budget level. If they chose 'budget', focus on free/cheap activities and hostels. If 'luxury', suggest premium hotels and fine dining.",
            "CRITICAL: Only suggest activities that match the user's interests. If they selected 'nature', don't suggest shopping malls. If 'food', prioritize restaurant and market visits.",
            "CRITICAL: Match the travel style. If 'relaxed', don't pack too many activities per day. If 'adventure', include hiking, extreme sports, off-the-beaten-path spots.",
            "CRITICAL: Respect dietary preferences. If vegetarian, don't suggest steak houses. If halal, suggest halal-certified restaurants.",
        ] + planner_china_hint + [
            "Never make up facts or plagiarize. Always provide proper attribution.",
        ],
        add_datetime_to_context=True,
    )
    critic = Agent(
        name="Critic",
        role="Reviews the itinerary for quality, consistency, and preference-adherence",
        model=DeepSeek(id="deepseek-chat", api_key=api_key),
        description=dedent(
            """\
            你是一位严格的旅行行程评审专家。你会仔细阅读 Planner 生成的行程，
            对照用户的所有偏好（预算、兴趣、风格、饮食），找出其中不合理、矛盾或低质量的地方，
            并给出具体可执行的修改建议。你只做评审，不生成完整行程。
            """
        ),
        instructions=[
            "逐条检查行程是否严格遵守用户偏好：预算是否匹配、兴趣是否覆盖、风格是否符合、饮食是否满足。",
            "检查行程的合理性：同一天活动之间交通时间是否过长？是否有重复或矛盾？景点开放时间是否冲突？",
            "检查信息质量：是否真实引用了搜索结果？是否有过时或不可信的内容？推荐是否具体可信？",
            "给出具体修改建议，每条说明'问题是什么'和'怎么改'，不要泛泛而谈'请改进'。",
            "如果行程整体质量很高、无明显问题，也明确说明'行程质量良好，无需重大修改'。",
        ],
        add_datetime_to_context=True,
    )
    return researcher, planner, critic, search_engine_name


def generate_itinerary(prefs: dict, api_key: str) -> dict:
    """
    执行「三 Agent 四步」流程，生成最终行程。

    参数:
        prefs: 偏好字典，支持字段 destination/dest, num_days/days, budget,
               interests(列表或字符串), travel_style, dietary, extra_notes/notes
        api_key: DeepSeek API Key（由后端持有，不进前端）

    返回:
        {
          "itinerary": 最终行程原始文本（JSON 或文本，极端兜底用）,
          "itinerary_json": 结构化行程 dict（前端优先渲染；提取失败为 None）,
          "research": Researcher 搜索结果文本,
          "sources": 研究员实际调用的搜索来源（title/url/abstract/source，去重）,
          "draft": Planner 初稿文本,
          "critic": Critic 审查意见文本,
          "is_china": 是否国内目的地,
          "engine": 使用的搜索引擎名,
        }
    """
    p = _normalize_prefs(prefs)
    destination = p["destination"]
    is_china = is_chinese_destination(destination)
    researcher, planner, critic, engine = _build_agents(api_key, is_china)

    _reset_sources()
    _CAPTURE.destination = destination  # 供 SiteSearchTools 兜底查询（市级）使用

    interests_str = ", ".join(p["interests"]) if p["interests"] else "general sightseeing"
    if is_china:
        user_query = (f"研究中国目的地 {destination} 的 {p['num_days']} 天旅行攻略。"
                      f"预算：{p['budget']}。兴趣：{interests_str}。风格：{p['travel_style']}。"
                      f"饮食：{p['dietary']}。额外需求：{p['extra_notes'] or '无'}")
    else:
        user_query = (f"Research {destination} for a {p['num_days']} day trip. "
                      f"Budget: {p['budget']}. Interests: {interests_str}. "
                      f"Travel style: {p['travel_style']}. Dietary: {p['dietary']}. "
                      f"Extra: {p['extra_notes'] or 'none'}")

    # Step 1: Researcher 搜索
    research_results = researcher.run(user_query, stream=False)
    # Step 2: Planner 初稿
    draft_prompt = f"""
    Destination: {destination}
    Duration: {p['num_days']} days
    Budget level: {p['budget']}
    Interests: {interests_str}
    Travel style: {p['travel_style']}
    Dietary preferences: {p['dietary']}
    Extra notes: {p['extra_notes'] or 'none'}
    Search engine used: {engine}

    Research Results: {research_results.content}

    Please create a detailed itinerary draft that STRICTLY respects ALL the user preferences above.
    """
    itinerary_draft = planner.run(draft_prompt, stream=False)
    # Step 3: Critic 审查
    critic_prompt = f"""
    目的地：{destination}
    天数：{p['num_days']} 天
    预算：{p['budget']}
    兴趣：{interests_str}
    风格：{p['travel_style']}
    饮食：{p['dietary']}
    额外需求：{p['extra_notes'] or '无'}

    请审查以下行程初稿，找出问题并给出修改建议：

    {itinerary_draft.content}
    """
    critic_feedback = critic.run(critic_prompt, stream=False)
    # Step 4: Planner 根据审查出终稿
    final_prompt = f"""
    目的地：{destination}
    天数：{p['num_days']} 天
    预算：{p['budget']}
    兴趣：{interests_str}
    风格：{p['travel_style']}
    饮食：{p['dietary']}
    额外需求：{p['extra_notes'] or '无'}

    原始行程（初稿）：
    {itinerary_draft.content}

    审查意见：
    {critic_feedback.content}

    请根据审查意见修改行程，解决所有指出的问题，生成最终版本。
    {JSON_SCHEMA_INSTRUCTION}
    """
    response = planner.run(final_prompt, stream=False)
    raw_itinerary = response.content or ""
    structured = _extract_json(raw_itinerary)

    return {
        "itinerary": raw_itinerary,
        "itinerary_json": structured,
        "research": research_results.content,
        "sources": _get_sources(),
        "draft": itinerary_draft.content,
        "critic": critic_feedback.content,
        "is_china": is_china,
        "engine": engine,
    }
