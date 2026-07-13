from textwrap import dedent
from agno.agent import Agent
from agno.run.agent import RunOutput
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.baidusearch import BaiduSearchTools
import streamlit as st
import re
from agno.models.deepseek import DeepSeek
from icalendar import Calendar, Event
from datetime import datetime, timedelta

# ===== 中国城市列表（用于智能切换搜索引擎） =====
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

CHINA_KEYWORDS = {"中国", "国内", "内地", "川", "粤", "京", "沪", "蓉", "渝", "杭", "苏", "湘", "闽", "滇", "黔", "藏", "陕", "豫", "鲁", "赣", "桂", "琼", "甘", "青", "宁", "新", "蒙", "辽", "吉", "黑", "冀", "晋", "皖", "鄂", "浙", "苏", "台", "港", "澳"}


def is_chinese_destination(destination: str) -> bool:
    """判断目的地是否在中国，用于智能切换搜索引擎"""
    dest_lower = destination.lower().strip()

    # 检查是否包含中国城市名
    for city in CHINA_CITIES:
        if city in dest_lower or dest_lower in city:
            return True

    # 检查是否包含中国相关关键词
    for kw in CHINA_KEYWORDS:
        if kw in dest_lower:
            return True

    # 检查是否包含中文字符（Unicode CJK range）
    if any('\u4e00' <= c <= '\u9fff' for c in destination):
        return True

    return False


def generate_ics_content(plan_text: str, start_date: datetime = None) -> bytes:
    """
    Generate an ICS calendar file from a travel itinerary text.

    Args:
        plan_text: The travel itinerary text
        start_date: Optional start date for the itinerary (defaults to today)

    Returns:
        bytes: The ICS file content as bytes
    """
    cal = Calendar()
    cal.add('prodid', '-//AI Travel Planner//github.com//')
    cal.add('version', '2.0')

    if start_date is None:
        start_date = datetime.today()

    # Split the plan into days
    day_pattern = re.compile(r'Day (\d+)[:\s]+(.*?)(?=Day \d+|$)', re.DOTALL)
    days = day_pattern.findall(plan_text)

    if not days:  # If no day pattern found, create a single all-day event with the entire content
        event = Event()
        event.add('summary', "Travel Itinerary")
        event.add('description', plan_text)
        event.add('dtstart', start_date.date())
        event.add('dtend', start_date.date())
        event.add("dtstamp", datetime.now())
        cal.add_component(event)
    else:
        # Process each day
        for day_num, day_content in days:
            day_num = int(day_num)
            current_date = start_date + timedelta(days=day_num - 1)

            # Create a single event for the entire day
            event = Event()
            event.add('summary', f"Day {day_num} Itinerary")
            event.add('description', day_content.strip())

            # Make it an all-day event
            event.add('dtstart', current_date.date())
            event.add('dtend', current_date.date())
            event.add("dtstamp", datetime.now())
            cal.add_component(event)

    return cal.to_ical()


# Set up the Streamlit app
st.title("AI Travel Planner 🧳")
st.caption("Plan your next adventure with AI — powered by DeepSeek, smart search for China & overseas")

# Initialize session state to store the generated itinerary
if 'itinerary' not in st.session_state:
    st.session_state.itinerary = None

# Get DeepSeek API key from user
deepseek_api_key = st.text_input("Enter DeepSeek API Key", type="password")

if deepseek_api_key:
    # ===== Personalization inputs =====
    st.subheader("Basic Info")
    destination = st.text_input("Where do you want to go?", placeholder="e.g. 成都、大理、Tokyo、Barcelona")
    num_days = st.number_input("How many days do you want to travel for?", min_value=1, max_value=30, value=5)

    # ===== 智能选择搜索引擎 =====
    is_china = is_chinese_destination(destination) if destination else False
    search_tools = BaiduSearchTools(fixed_language="zh") if is_china else DuckDuckGoTools()
    search_engine_name = "百度搜索 🔴" if is_china else "DuckDuckGo 🔵"

    # 显示当前使用的搜索引擎
    if destination:
        st.info(f"🔍 Detected: **{destination}** → using **{search_engine_name}** for more relevant results")

    # ===== 根据目的地语言调整 Researcher 的搜索策略 =====
    if is_china:
        researcher_instructions = [
            "给定一个中国旅行目的地和旅行天数，首先生成3个中文搜索关键词（如'成都 5日游 攻略'、'成都 美食推荐 本地人'、'成都 住宿 性价比'）。",
            "对每个搜索关键词，使用百度搜索工具搜索并分析结果。",
            "从所有搜索结果中，返回10条最相关且最实用的结果，优先选择来自马蜂窝、携程、大众点评、小红书等中国本地平台的真实信息。",
            "记住：搜索结果的质量很重要，要确保信息来自真实的中国旅游平台和本地经验分享。",
        ]
        researcher_description = dedent(
            """\
            你是一位精通中国旅游的资深研究者。给定一个中国旅行目的地和旅行天数，
            生成中文搜索关键词，通过百度搜索找到来自马蜂窝、携程、大众点评等中国本地平台的真实旅行攻略和信息。
            重点关注本地人推荐的餐厅、性价比住宿、真实景点评价，而不是翻译的英文旅游博客。
            """
        )
        planner_china_hint = [
            "CRITICAL: 这是一个中国国内目的地，行程中请使用中文地名和中文描述。推荐具体的餐厅名称、景点中文全名、地铁线路（如'地铁2号线宽窄巷子站'）。",
            "CRITICAL: 价格请用人民币（¥）标注，交通请说明具体的地铁/公交路线和票价。",
            "CRITICAL: 餐饮推荐请优先选择本地特色（如成都的火锅串串、西安的泡馍肉夹馍），而不是泛泛的'当地美食'。",
        ]
    else:
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
        model=DeepSeek(id="deepseek-chat", api_key=deepseek_api_key),
        description=researcher_description,
        instructions=researcher_instructions,
        tools=[search_tools],
        add_datetime_to_context=True,
    )

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
            "CRITICAL: Respect the user's budget level. If they chose 'budget', focus on free/cheap activities and hostels. If 'luxury', suggest premium hotels and fine dining.",
            "CRITICAL: Only suggest activities that match the user's interests. If they selected 'nature', don't suggest shopping malls. If 'food', prioritize restaurant and market visits.",
            "CRITICAL: Match the travel style. If 'relaxed', don't pack too many activities per day. If 'adventure', include hiking, extreme sports, off-the-beaten-path spots.",
            "CRITICAL: Respect dietary preferences. If vegetarian, don't suggest steak houses. If halal, suggest halal-certified restaurants.",
        ] + planner_china_hint + [
            "Never make up facts or plagiarize. Always provide proper attribution.",
        ],
        add_datetime_to_context=True,
    )

    # ===== Preferences =====
    st.subheader("Your Preferences")
    col_pref1, col_pref2 = st.columns(2)

    with col_pref1:
        budget = st.selectbox("Budget level", ["budget (backpacker)", "mid-range", "luxury"], index=1)
        travel_style = st.selectbox("Travel style", ["relaxed (slow pace)", "balanced", "adventure (packed schedule)"], index=1)

    with col_pref2:
        interests = st.multiselect("What interests you?", ["nature & outdoors", "food & cuisine", "history & culture", "shopping & markets", "nightlife & entertainment", "art & museums", "sports & fitness", "photography"])
        dietary = st.selectbox("Dietary preferences", ["no restrictions", "vegetarian", "halal", "vegan", "gluten-free"])

    extra_notes = st.text_area("Anything else? (optional)", placeholder="e.g. 我想去看大熊猫、不喜欢太拥挤的景点、带小孩出行...")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Generate Itinerary", type="primary"):
            # Build a rich query that includes all preferences
            interests_str = ", ".join(interests) if interests else "general sightseeing"
            if is_china:
                user_query = f"研究中国目的地 {destination} 的 {num_days} 天旅行攻略。预算：{budget}。兴趣：{interests_str}。风格：{travel_style}。饮食：{dietary}。额外需求：{extra_notes if extra_notes else '无'}"
            else:
                user_query = f"Research {destination} for a {num_days} day trip. Budget: {budget}. Interests: {interests_str}. Travel style: {travel_style}. Dietary: {dietary}. Extra: {extra_notes if extra_notes else 'none'}"

            with st.spinner(f"Researching your destination via {search_engine_name}..."):
                research_results: RunOutput = researcher.run(user_query, stream=False)
                st.write("Research completed ✅")

            with st.spinner("Creating your personalized itinerary..."):
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
                response: RunOutput = planner.run(prompt, stream=False)
                st.session_state.itinerary = response.content
                st.write(response.content)

    # Only show download buttons if there's an itinerary
    with col2:
        if st.session_state.itinerary:
            st.subheader("Save Your Itinerary")
            st.markdown("Download in different formats for different uses:")

            # .ics — 导入日历（Google Calendar / Apple Calendar）
            ics_content = generate_ics_content(st.session_state.itinerary)
            st.download_button(
                label="📅 Calendar (.ics) — import to Google/Apple Calendar",
                data=ics_content,
                file_name=f"{destination}_itinerary.ics",
                mime="text/calendar"
            )

            # .md — Markdown 格式（适合发博客、做笔记、贴到 GitHub）
            md_content = f"# {destination} {num_days}-Day Travel Itinerary\n\n"
            md_content += f"**Budget:** {budget} | **Style:** {travel_style} | **Interests:** {interests_str} | **Dietary:** {dietary}\n\n"
            md_content += f"---\n\n{st.session_state.itinerary}\n"
            st.download_button(
                label="📝 Markdown (.md) — for blogs & notes",
                data=md_content,
                file_name=f"{destination}_itinerary.md",
                mime="text/markdown"
            )

            # .txt — 纯文本（最通用，任何设备都能打开）
            txt_content = f"{destination} {num_days}-Day Travel Itinerary\n"
            txt_content += f"Budget: {budget} | Style: {travel_style} | Interests: {interests_str} | Dietary: {dietary}\n"
            txt_content += f"{'=' * 50}\n\n{st.session_state.itinerary}\n"
            st.download_button(
                label="📄 Plain Text (.txt) — universal format",
                data=txt_content,
                file_name=f"{destination}_itinerary.txt",
                mime="text/plain"
            )
