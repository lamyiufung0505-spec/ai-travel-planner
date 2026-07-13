# AI Travel Planner

Plan your next adventure with AI — a personalized travel itinerary generator powered by DeepSeek and DuckDuckGo search.

Built on top of [awesome-llm-apps](https://github.com/Shubhamsaboo/awesome-llm-apps) by Shubhamsaboo, with significant enhancements to personalization and model compatibility.

## What It Does

Tell it where you want to go, how many days, and your preferences — it will:

1. **Search the web** for real, up-to-date travel info via DuckDuckGo
2. **Generate a personalized itinerary** that respects your budget, interests, and dietary needs
3. **Export to calendar** — download a `.ics` file and import directly into Google Calendar or Apple Calendar

## Features

- **Dual-Agent Architecture**: A Researcher Agent searches the web, a Planner Agent writes the itinerary
- **Personalized Preferences**: Budget level, travel style, interests, dietary restrictions, custom notes
- **DeepSeek Powered**: Uses DeepSeek's API (cheaper than OpenAI, excellent Chinese support)
- **No SerpAPI Required**: Uses free DuckDuckGo search instead of paid SerpAPI
- **Calendar Export**: One-click download of `.ics` calendar file

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_USERNAME/ai-travel-planner.git
cd ai-travel-planner

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the app
streamlit run travel_agent.py
```

The app will open at `http://localhost:8501`.

## Get Your DeepSeek API Key

1. Go to [platform.deepseek.com](https://platform.deepseek.com)
2. Sign up / log in
3. Navigate to API Keys and create a new key
4. Paste it into the app's input field

New users get free credits. DeepSeek-chat costs approximately 1 RMB per million tokens — extremely affordable.

## How It Works

```
User Input (destination, days, preferences)
        |
        v
+------------------+     DuckDuckGo Search
| Researcher Agent | -----> Real web results
+------------------+
        |
        v  (search results passed to Planner)
        |
+------------------+
| Planner Agent    | -----> Structured itinerary
+------------------+
        |
        v
+------------------+
| ICS Generator    | -----> .ics calendar file
+------------------+
```

### Why Two Agents?

- **Researcher** has access to web search tools — it decides what to search, analyzes results, and filters the best 10
- **Planner** has no tools — it focuses purely on writing a great itinerary based on the research data

This separation of concerns mirrors real-world AI applications where different agents handle different tasks.

## Customization

The app supports the following personalization options:

| Option | Choices |
|--------|---------|
| Budget | budget / mid-range / luxury |
| Travel Style | relaxed / balanced / adventure |
| Interests | nature, food, history, shopping, nightlife, art, sports, photography |
| Dietary | no restrictions / vegetarian / halal / vegan / gluten-free |
| Extra Notes | Free text — anything you want the AI to consider |

## Tech Stack

- **[DeepSeek](https://www.deepseek.com)** — LLM for reasoning and generation
- **[agno](https://github.com/agno-agi/agno)** — Agent orchestration framework
- **[DuckDuckGo](https://duckduckgo.com)** — Free web search (no API key needed)
- **[Streamlit](https://streamlit.io)** — Python web UI framework
- **[icalendar](https://pypi.org/project/icalendar/)** — Calendar file generation

## What I Changed from the Original

| Change | Reason |
|--------|--------|
| OpenAI GPT-4o -> DeepSeek | Cheaper, better Chinese support, no overseas account needed |
| SerpAPI -> DuckDuckGo | Free, no API key, unlimited searches |
| Added 5 personalization inputs | Budget, style, interests, dietary, notes |
| Added 4 CRITICAL prompt constraints | Force the model to strictly respect user preferences |

## Credits

- Original project: [awesome-llm-apps](https://github.com/Shubhamsaboo/awesome-llm-apps) by Shubhamsaboo
- Agent framework: [agno](https://github.com/agno-agi/agno)

## License

MIT License — see [LICENSE](LICENSE) for details.
