from textwrap import dedent
from agno.agent import Agent
from agno.run.agent import RunOutput
from agno.tools.duckduckgo import DuckDuckGoTools
import streamlit as st
import re
from agno.models.deepseek import DeepSeek
from icalendar import Calendar, Event
from datetime import datetime, timedelta


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
st.caption("Plan your next adventure with AI — powered by DeepSeek, fully customizable")

# Initialize session state to store the generated itinerary
if 'itinerary' not in st.session_state:
    st.session_state.itinerary = None

# Get DeepSeek API key from user
deepseek_api_key = st.text_input("Enter DeepSeek API Key", type="password")

if deepseek_api_key:
    researcher = Agent(
        name="Researcher",
        role="Searches for travel destinations, activities, and accommodations based on user preferences",
        model=DeepSeek(id="deepseek-chat", api_key=deepseek_api_key),
        description=dedent(
            """\
            You are a world-class travel researcher. Given a travel destination and the number of days the user wants to travel for,
            generate a list of search terms for finding relevant travel activities and accommodations.
            Then search the web for each term, analyze the results, and return the 10 most relevant results.
            """
        ),
        instructions=[
            "Given a travel destination and the number of days the user wants to travel for, first generate a list of 3 search terms related to that destination and the number of days.",
            "For each search term, use the search tool and analyze the results.",
            "From the results of all searches, return the 10 most relevant results to the user's preferences.",
            "Remember: the quality of the results is important.",
        ],
        tools=[DuckDuckGoTools()],
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
            "Never make up facts or plagiarize. Always provide proper attribution.",
        ],
        add_datetime_to_context=True,
    )

    # ===== Personalization inputs =====
    st.subheader("Basic Info")
    destination = st.text_input("Where do you want to go?", placeholder="e.g. Tokyo, Barcelona, Chengdu")
    num_days = st.number_input("How many days do you want to travel for?", min_value=1, max_value=30, value=5)

    st.subheader("Your Preferences")
    col_pref1, col_pref2 = st.columns(2)

    with col_pref1:
        budget = st.selectbox("Budget level", ["budget ( backpacker)", "mid-range", "luxury"], index=1)
        travel_style = st.selectbox("Travel style", ["relaxed ( slow pace)", "balanced", "adventure ( packed schedule)"], index=1)

    with col_pref2:
        interests = st.multiselect("What interests you?", ["nature & outdoors", "food & cuisine", "history & culture", "shopping & markets", "nightlife & entertainment", "art & museums", "sports & fitness", "photography"])
        dietary = st.selectbox("Dietary preferences", ["no restrictions", "vegetarian", "halal", "vegan", "gluten-free"])

    extra_notes = st.text_area("Anything else? (optional)", placeholder="e.g. I want to visit a specific temple, or I'm traveling with kids, or I hate crowded places...")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Generate Itinerary", type="primary"):
            # Build a rich query that includes all preferences
            interests_str = ", ".join(interests) if interests else "general sightseeing"
            user_query = f"Research {destination} for a {num_days} day trip. Budget: {budget}. Interests: {interests_str}. Travel style: {travel_style}. Dietary: {dietary}. Extra: {extra_notes if extra_notes else 'none'}"

            with st.spinner("Researching your destination..."):
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
