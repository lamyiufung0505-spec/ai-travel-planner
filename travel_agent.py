"""
AI Travel Planner — 基于 DeepSeek 的智能旅行规划 Agent
=========================================================

架构：双 Agent 协作（Researcher + Planner）
- Researcher Agent：负责搜索真实旅行信息（百度/DuckDuckGo）
- Planner Agent：负责基于搜索结果生成个性化行程

改良自 awesome-llm-apps 项目的 ai_travel_agent 模板
原作者：Shubhamsaboo (https://github.com/Shubhamsaboo/awesome-llm-apps)

改良点：
1. DeepSeek 替代 OpenAI（更便宜、中文能力更强）
2. 百度搜索替代 SerpAPI（中国目的地接地气、免费无额度限制）
3. 智能搜索引擎切换（中国→百度，海外→DuckDuckGo）
4. 5 个个性化输入（预算、风格、兴趣、饮食、备注）
5. 多格式下载（.ics 日历、.md Markdown、.txt 纯文本）
"""

# ===== 导入依赖 =====
from textwrap import dedent                  # 去除多行字符串的公共前导空格，让缩进不影响 Prompt 内容
from agno.agent import Agent                 # agno 框架的核心类：创建 AI Agent（定义身份、指令、工具）
from agno.run.agent import RunOutput         # Agent.run() 的返回类型，包含 Agent 的输出文本 (.content)
from agno.tools.duckduckgo import DuckDuckGoTools   # DuckDuckGo 搜索工具（海外目的地使用，无需 API Key）
from agno.tools.baidusearch import BaiduSearchTools  # 百度搜索工具（中国目的地使用，无需 API Key，中文索引更全）
import streamlit as st                       # Web UI 框架：把 Python 脚本变成交互式网页应用
import re                                    # 正则表达式：用于从行程文本中提取 "Day 1/Day 2" 等结构
from agno.models.deepseek import DeepSeek    # agno 内置的 DeepSeek 模型适配器（自动处理 base_url 和 system role）
from icalendar import Calendar, Event        # 日历文件生成库：输出标准 .ics 格式，可导入 Google/Apple 日历
from datetime import datetime, timedelta     # 日期处理：计算行程每一天对应的实际日期


# ===== 中国城市 & 关键词列表（用于智能切换搜索引擎） =====
# 覆盖 80+ 个热门旅游城市、景点、省份简称
# 如果用户输入匹配到任何一个，就自动切换到百度搜索（更接地气）
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

# 省份简称 + 常见关键词（"川"=四川、"滇"=云南 等）
CHINA_KEYWORDS = {
    "中国", "国内", "内地",
    "川", "粤", "京", "沪", "蓉", "渝", "杭", "苏", "湘", "闽", "滇", "黔", "藏",
    "陕", "豫", "鲁", "赣", "桂", "琼", "甘", "青", "宁", "新", "蒙", "辽", "吉",
    "黑", "冀", "晋", "皖", "鄂", "浙", "苏", "台", "港", "澳"
}


def is_chinese_destination(destination: str) -> bool:
    """
    判断目的地是否在中国 → 决定用百度还是 DuckDuckGo 搜索

    检测逻辑（4层，任一层匹配即返回 True）：
    1. 输入是否包含 CHINA_CITIES 中的城市/景点名
    2. 输入是否包含 CHINA_KEYWORDS 中的省份简称/关键词
    3. 输入是否包含中文字符（Unicode CJK 范围 \u4e00-\u9fff）
    4. 以上都不匹配 → 返回 False（海外目的地）

    示例：
    - "成都" → True（匹配城市列表）
    - "Tokyo" → False（不匹配任何层）
    - "大理古城" → True（包含中文字符）
    """
    dest_lower = destination.lower().strip()

    # 第1层：匹配中国城市名（双向匹配，"京"能匹配"北京"，"成都"能匹配"成都"）
    for city in CHINA_CITIES:
        if city in dest_lower or dest_lower in city:
            return True

    # 第2层：匹配省份简称和中国关键词
    for kw in CHINA_KEYWORDS:
        if kw in dest_lower:
            return True

    # 第3层：检测中文字符（CJK Unified Ideographs 范围）
    if any('\u4e00' <= c <= '\u9fff' for c in destination):
        return True

    # 第4层：都没匹配，判定为海外目的地
    return False


def generate_ics_content(plan_text: str, start_date: datetime = None) -> bytes:
    """
    将行程文本转换为 .ics 日历文件（标准 iCalendar 格式）

    原理：
    1. 用正则表达式从文本中提取 "Day 1: xxx / Day 2: xxx" 的结构
    2. 每个 Day 创建一个全天日历事件，日期从 start_date 开始递增
    3. 如果文本没有 "Day X" 格式，整个行程作为单个事件

    Args:
        plan_text:  LLM 生成的行程文本（通常包含 "Day 1/Day 2..." 结构）
        start_date: 行程起始日期（默认为今天）

    Returns:
        bytes: 标准 .ics 文件内容，可直接下载或导入日历应用
    """
    # 创建 Calendar 对象，设置元信息
    cal = Calendar()
    cal.add('prodid', '-//AI Travel Planner//github.com//')  # 产品标识
    cal.add('version', '2.0')                                  # iCalendar 版本

    # 默认从今天开始计算行程日期
    if start_date is None:
        start_date = datetime.today()

    # 正则提取行程结构：
    # Day (\d+)    → 匹配 "Day 1"、"Day 2" 等，捕获天数编号
    # [:\s]+       → 匹配冒号和空格（如 "Day 1: " 或 "Day 1 "）
    # (.*?)        → 懒惰匹配，捕获这一天所有的行程内容
    # (?=Day \d+|$) → 预判：遇到下一个 "Day X" 或文本结尾就停止
    # re.DOTALL    → 让 . 也能匹配换行符（行程内容可能跨多行）
    day_pattern = re.compile(r'Day (\d+)[:\s]+(.*?)(?=Day \d+|$)', re.DOTALL)
    days = day_pattern.findall(plan_text)

    # 兜底处理：如果 LLM 输出没有 "Day X" 格式（格式异常）
    if not days:
        event = Event()
        event.add('summary', "Travel Itinerary")         # 日历事件标题
        event.add('description', plan_text)               # 全部行程内容作为描述
        event.add('dtstart', start_date.date())           # 起始日期
        event.add('dtend', start_date.date())             # 结束日期（全天事件）
        event.add("dtstamp", datetime.now())              # 创建时间戳
        cal.add_component(event)
    else:
        # 正常处理：每个 Day 生成一个独立的日历事件
        # Day 1 = start_date，Day 2 = start_date + 1天，Day 3 = start_date + 2天 ...
        for day_num, day_content in days:
            day_num = int(day_num)
            current_date = start_date + timedelta(days=day_num - 1)  # Day N 对应的日期

            event = Event()
            event.add('summary', f"Day {day_num} Itinerary")  # 事件标题：如 "Day 1 Itinerary"
            event.add('description', day_content.strip())      # 这一天的行程内容

            # 设为全天事件（dtstart 和 dtend 同一天，不带具体时间）
            event.add('dtstart', current_date.date())
            event.add('dtend', current_date.date())
            event.add("dtstamp", datetime.now())
            cal.add_component(event)

    # 序列化为标准 iCalendar 格式的 bytes（可直接作为文件下载）
    return cal.to_ical()


# ===== 页面标题 & 会话状态初始化 =====
st.title("AI Travel Planner 🧳")
st.caption("智能旅行规划 — DeepSeek 驱动 · 百度/DuckDuckGo 搜索 · 个性化定制")

# session_state 是 Streamlit 的跨刷新持久化机制
# 用户点按钮后页面会重新渲染，但 session_state 里的数据不会丢失
# 这里用它保存生成的行程，防止刷新后消失
if 'itinerary' not in st.session_state:
    st.session_state.itinerary = None

# API Key 输入（type="password" 让输入显示为掩码 ●●●●，防止旁观者看到）
deepseek_api_key = st.text_input("输入 DeepSeek API Key", type="password")


# ===== 只有填了 API Key 才显示后续内容 =====
if deepseek_api_key:
    # ===== 基本信息输入 =====
    st.subheader("基本信息")
    destination = st.text_input("你想去哪里？", placeholder="例如：成都、大理、Tokyo、Barcelona")
    num_days = st.number_input("旅行几天？", min_value=1, max_value=30, value=5)

    # ===== 智能搜索引擎切换 =====
    # 根据目的地自动选择最接地气的搜索源
    # 中国目的地 → 百度搜索（中文索引全，搜出来的是马蜂窝/携程/大众点评）
    # 海外目的地 → DuckDuckGo（全球英文索引，搜出来的是 TripAdvisor/英文博客）
    is_china = is_chinese_destination(destination) if destination else False
    search_tools = BaiduSearchTools(fixed_language="zh") if is_china else DuckDuckGoTools()
    search_engine_name = "百度搜索 🔴" if is_china else "DuckDuckGo 🔵"

    # 在页面上显示当前使用的搜索引擎，让用户知道系统做了智能判断
    if destination:
        st.info(f"🔍 检测到：**{destination}** → 使用 **{search_engine_name}** 获取更相关的结果")

    # ===== 根据目的地语言调整 Researcher 的搜索策略 =====
    # 中国目的地：搜索关键词和 instructions 都是中文，优先选本地平台
    # 海外目的地：搜索关键词和 instructions 都是英文
    if is_china:
        # Researcher 的中文指令：生成中文搜索词 → 百度搜索 → 筛选本地平台结果
        researcher_instructions = [
            "给定一个中国旅行目的地和旅行天数，首先生成3个中文搜索关键词（如'成都 5日游 攻略'、'成都 美食推荐 本地人'、'成都 住宿 性价比'）。",
            "对每个搜索关键词，使用百度搜索工具搜索并分析结果。",
            "从所有搜索结果中，返回10条最相关且最实用的结果，优先选择来自马蜂窝、携程、大众点评、小红书等中国本地平台的真实信息。",
            "记住：搜索结果的质量很重要，要确保信息来自真实的中国旅游平台和本地经验分享。",
        ]
        # Researcher 的中文身份描述（dedent 去除缩进，让传给模型的字符串干净）
        researcher_description = dedent(
            """\
            你是一位精通中国旅游的资深研究者。给定一个中国旅行目的地和旅行天数，
            生成中文搜索关键词，通过百度搜索找到来自马蜂窝、携程、大众点评等中国本地平台的真实旅行攻略和信息。
            重点关注本地人推荐的餐厅、性价比住宿、真实景点评价，而不是翻译的英文旅游博客。
            """
        )
        # Planner 的中国专属约束：人民币价格、地铁线路、本地菜名
        planner_china_hint = [
            "CRITICAL: 这是一个中国国内目的地，行程中请使用中文地名和中文描述。推荐具体的餐厅名称、景点中文全名、地铁线路（如'地铁2号线宽窄巷子站'）。",
            "CRITICAL: 价格请用人民币（¥）标注，交通请说明具体的地铁/公交路线和票价。",
            "CRITICAL: 餐饮推荐请优先选择本地特色（如成都的火锅串串、西安的泡馍肉夹馍），而不是泛泛的'当地美食'。",
        ]
    else:
        # Researcher 的英文指令：生成英文搜索词 → DuckDuckGo 搜索 → 筛选全球结果
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
        planner_china_hint = []  # 海外目的地不需要中国专属约束

    # ===== 创建 Agent 1：Researcher（搜索者） =====
    # 职责：根据目的地 + 偏好生成搜索关键词 → 调用搜索工具 → 返回真实搜索结果
    # 关键参数说明：
    #   name        — Agent 名字（主要用于日志，不影响行为）
    #   role        — 一句话角色定义（"搜索旅行信息的研究者"）
    #   model       — 用的语言模型（DeepSeek，agno 自动处理 base_url 和 system role）
    #   description — 完整的身份说明书（"你是世界级旅行研究者..."）
    #   instructions — 分步执行指令（最影响 Agent 行为的参数！有序步骤列表）
    #   tools       — Agent 可调用的外部工具（百度/DuckDuckGo 搜索）
    #   add_datetime_to_context — 自动注入当前日期时间，防止推荐过时信息
    researcher = Agent(
        name="Researcher",
        role="Searches for travel destinations, activities, and accommodations based on user preferences",
        model=DeepSeek(id="deepseek-chat", api_key=deepseek_api_key),
        description=researcher_description,
        instructions=researcher_instructions,
        tools=[search_tools],
        add_datetime_to_context=True,
    )

    # ===== 创建 Agent 2：Planner（规划者） =====
    # 职责：拿到 Researcher 的搜索结果 → 结合用户偏好 → 生成结构化行程
    # 注意：Planner 没有 tools 参数！它不需要搜索，只负责写作
    # 4 条 CRITICAL 指令是我们加的改良——强制模型遵守用户偏好
    # "CRITICAL:" 开头会让 LLM 把这些指令的优先级提到最高
    planner = Agent(
        name="Planner",
        role="Generates a draft itinerary based on user preferences and research results",
        model=DeepSeek(id="deepseek-chat", api_key=deepseek_api_key),
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
            # ↓↓↓ 4 条 CRITICAL 级约束（我们加的改良）↓↓↓
            "CRITICAL: Respect the user's budget level. If they chose 'budget', focus on free/cheap activities and hostels. If 'luxury', suggest premium hotels and fine dining.",
            "CRITICAL: Only suggest activities that match the user's interests. If they selected 'nature', don't suggest shopping malls. If 'food', prioritize restaurant and market visits.",
            "CRITICAL: Match the travel style. If 'relaxed', don't pack too many activities per day. If 'adventure', include hiking, extreme sports, off-the-beaten-path spots.",
            "CRITICAL: Respect dietary preferences. If vegetarian, don't suggest steak houses. If halal, suggest halal-certified restaurants.",
        ] + planner_china_hint + [  # 中国目的地会追加 3 条本地化约束
            "Never make up facts or plagiarize. Always provide proper attribution.",
        ],
        add_datetime_to_context=True,
    )

    # ===== 个性化偏好输入 =====
    st.subheader("你的偏好")
    col_pref1, col_pref2 = st.columns(2)  # 两列布局，让界面不那么长

    with col_pref1:
        # selectbox: 下拉单选，index=1 表示默认选中第二个（mid-range / balanced）
        budget = st.selectbox("预算水平", ["budget (backpacker)", "mid-range", "luxury"], index=1)
        travel_style = st.selectbox("旅行风格", ["relaxed (slow pace)", "balanced", "adventure (packed schedule)"], index=1)

    with col_pref2:
        # multiselect: 下拉多选，用户可以选多个兴趣（返回列表）
        interests = st.multiselect("你感兴趣什么？", ["nature & outdoors", "food & cuisine", "history & culture", "shopping & markets", "nightlife & entertainment", "art & museums", "sports & fitness", "photography"])
        dietary = st.selectbox("饮食偏好", ["no restrictions", "vegetarian", "halal", "vegan", "gluten-free"])

    # text_area: 大文本框，适合自由输入额外需求（带小孩、恐高等）
    extra_notes = st.text_area("还有其他需求吗？（可选）", placeholder="例如：我想去看大熊猫、不喜欢太拥挤的景点、带小孩出行...")

    # ===== 生成按钮 + 下载区域（两列布局） =====
    col1, col2 = st.columns(2)

    with col1:
        if st.button("生成行程", type="primary"):
            # 把所有偏好拼成查询字符串，传给 Researcher
            # interests 是列表，用逗号连接成字符串；如果没选则默认 "general sightseeing"
            interests_str = ", ".join(interests) if interests else "general sightseeing"

            # 中国目的地用中文查询，海外目的地用英文查询
            if is_china:
                user_query = f"研究中国目的地 {destination} 的 {num_days} 天旅行攻略。预算：{budget}。兴趣：{interests_str}。风格：{travel_style}。饮食：{dietary}。额外需求：{extra_notes if extra_notes else '无'}"
            else:
                user_query = f"Research {destination} for a {num_days} day trip. Budget: {budget}. Interests: {interests_str}. Travel style: {travel_style}. Dietary: {dietary}. Extra: {extra_notes if extra_notes else 'none'}"

            # ===== Step 1: Researcher Agent 执行搜索 =====
            # researcher.run() 会让 Agent 自动：生成搜索词 → 调用搜索工具 → 筛选结果
            # stream=False 表示等完整执行完再返回（配合 st.spinner 显示加载动画）
            with st.spinner(f"正在通过 {search_engine_name} 搜索你的目的地..."):
                research_results: RunOutput = researcher.run(user_query, stream=False)
                st.write("搜索完成 ✅")

            # ===== Step 2: Planner Agent 生成行程 =====
            # 把用户偏好 + Researcher 的搜索结果拼成完整的 Prompt
            # 关键：research_results.content 包含了真实搜索数据（不是模型编的）
            # Planner 没有搜索工具，它只能基于这个 Prompt 里的信息来写行程
            with st.spinner("正在生成你的个性化行程..."):
                prompt = f"""
                Destination: {destination}
                Duration: {num_days} days
                Budget level: {budget}
                Interests: {interests_str}
                Travel style: {travel_style}
                Dietary preferences: {dietary}
                Extra notes: {extra_notes if extra_notes else 'none'}
                Search engine used: {search_engine_name}

                Research Results: {research_results.content}

                Please create a detailed itinerary that STRICTLY respects ALL the user preferences above.
                """
                # planner.run() 让 Planner 基于上面的 Prompt 生成行程
                response: RunOutput = planner.run(prompt, stream=False)
                # 存到 session_state（防止页面刷新丢失行程内容）
                st.session_state.itinerary = response.content
                st.write(response.content)

    # ===== 下载区域（只在行程生成后显示） =====
    with col2:
        if st.session_state.itinerary:
            st.subheader("保存你的行程")
            st.markdown("选择不同格式下载：")

            # 📅 .ics 日历文件 — 可导入 Google Calendar / Apple Calendar / Outlook
            # 每个Day变成一个全天日历事件，手机上也能看
            ics_content = generate_ics_content(st.session_state.itinerary)
            st.download_button(
                label="📅 Calendar (.ics) — 导入到 Google/Apple 日历",
                data=ics_content,
                file_name=f"{destination}_itinerary.ics",
                mime="text/calendar"
            )

            # 📝 .md Markdown 文件 — 适合发博客、做笔记、贴到 GitHub
            # 包含标题、偏好摘要、行程正文
            md_content = f"# {destination} {num_days}-Day Travel Itinerary\n\n"
            md_content += f"**Budget:** {budget} | **Style:** {travel_style} | **Interests:** {interests_str} | **Dietary:** {dietary}\n\n"
            md_content += f"---\n\n{st.session_state.itinerary}\n"
            st.download_button(
                label="📝 Markdown (.md) — 适合博客和笔记",
                data=md_content,
                file_name=f"{destination}_itinerary.md",
                mime="text/markdown"
            )

            # 📄 .txt 纯文本文件 — 最通用，任何设备都能打开
            # 包含偏好摘要和分隔线
            txt_content = f"{destination} {num_days}-Day Travel Itinerary\n"
            txt_content += f"Budget: {budget} | Style: {travel_style} | Interests: {interests_str} | Dietary: {dietary}\n"
            txt_content += f"{'=' * 50}\n\n{st.session_state.itinerary}\n"
            st.download_button(
                label="📄 Plain Text (.txt) — 最通用格式",
                data=txt_content,
                file_name=f"{destination}_itinerary.txt",
                mime="text/plain"
            )
