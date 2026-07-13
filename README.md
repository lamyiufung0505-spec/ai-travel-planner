# AI Travel Planner 🧳

Plan your next adventure with AI — a personalized travel itinerary generator powered by DeepSeek, with smart search switching between Baidu (for China) and DuckDuckGo (for overseas).

Built on top of [awesome-llm-apps](https://github.com/Shubhamsaboo/awesome-llm-apps) by Shubhamsaboo, with significant enhancements to personalization, model compatibility, and China-localized search.

## What It Does

Tell it where you want to go, how many days, and your preferences — it will:

1. **Auto-detect your destination** — Chinese cities use Baidu, overseas use DuckDuckGo
2. **Search the web** for real, up-to-date travel info (马蜂窝/携程/大众点评 for China, global sources for overseas)
3. **Generate a personalized itinerary** that respects your budget, interests, and dietary needs
4. **Export in 3 formats** — `.ics` (calendar), `.md` (blog/notes), `.txt` (universal)

## Features

- **Smart Search Engine**: Auto-switches between Baidu (中国 🔴) and DuckDuckGo (海外 🔵) based on destination
- **China-Localized**: Chinese destinations get Chinese search keywords, ¥ prices, subway routes, local dish names
- **Dual-Agent Architecture**: A Researcher Agent searches the web, a Planner Agent writes the itinerary
- **Personalized Preferences**: Budget level, travel style, interests, dietary restrictions, custom notes
- **DeepSeek Powered**: Uses DeepSeek's API (cheaper than OpenAI, excellent Chinese support)
- **No API Key for Search**: Both Baidu and DuckDuckGo are free, no registration needed
- **Multi-format Export**: `.ics` (calendar), `.md` (Markdown), `.txt` (plain text)

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/lamyiufung0505-spec/ai-travel-planner.git
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

New users get free credits. DeepSeek-chat costs approximately ¥1 per million tokens — extremely affordable.

## How It Works

```
User Input (destination, days, preferences)
        |
        v
  [Destination Detection]
        |
   +----+----+
   |         |
China 🔴   Overseas 🔵
   |         |
Baidu      DuckDuckGo
   |         |
   +----+----+
        |
        v
+------------------+     Search Results
| Researcher Agent | -----> (马蜂窝/携程/点评 or global sources)
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
| Export           | -----> .ics / .md / .txt
+------------------+
```

### Why Two Agents?

- **Researcher** has access to web search tools — it decides what to search, analyzes results, and filters the best 10
- **Planner** has no tools — it focuses purely on writing a great itinerary based on the research data

This separation of concerns mirrors real-world AI applications where different agents handle different tasks.

### Smart Search Detection

The app uses `is_chinese_destination()` to auto-detect:
- 80+ Chinese city names (北京, 成都, 丽江, 九寨沟...)
- Province abbreviations (川, 粤, 滇...)
- Chinese keywords (中国, 国内, 内地...)
- Chinese characters (any CJK Unicode range input)

When a Chinese destination is detected:
- Search engine switches to **Baidu** (default language: zh)
- Researcher generates **Chinese search keywords** (e.g. "成都 5日游 攻略")
- Planner adds **China-specific constraints** (¥ prices, subway lines, local dish names)

## Customization

The app supports the following personalization options:

| Option | Choices |
|--------|---------|
| Budget | budget (backpacker) / mid-range / luxury |
| Travel Style | relaxed (slow pace) / balanced / adventure (packed schedule) |
| Interests | nature, food, history, shopping, nightlife, art, sports, photography |
| Dietary | no restrictions / vegetarian / halal / vegan / gluten-free |
| Extra Notes | Free text — anything you want the AI to consider |

## Tech Stack

- **[DeepSeek](https://www.deepseek.com)** — LLM for reasoning and generation
- **[agno](https://github.com/agno-agi/agno)** — Agent orchestration framework
- **[Baidu Search](https://www.baidu.com)** — Chinese web search (free, no API key)
- **[DuckDuckGo](https://duckduckgo.com)** — Global web search (free, no API key)
- **[Streamlit](https://streamlit.io)** — Python web UI framework
- **[icalendar](https://pypi.org/project/icalendar/)** — Calendar file generation

## What I Changed from the Original

| Change | Reason |
|--------|--------|
| OpenAI GPT-4o → DeepSeek | Cheaper, better Chinese support, no overseas account needed |
| SerpAPI → Baidu (China) + DuckDuckGo (overseas) | Free, no API key, auto-switch for best local results |
| Added smart destination detection | Chinese cities get real local info from 马蜂窝/携程/大众点评 |
| Added 5 personalization inputs | Budget, style, interests, dietary, notes |
| Added 4 CRITICAL prompt constraints | Force the model to strictly respect user preferences |
| Added China-specific Planner constraints | ¥ prices, subway routes, local dish names for Chinese destinations |
| Added .md and .txt export | Not just calendar — also blog-friendly and universal formats |
| Removed local_travel_agent.py | Only keeping the enhanced version |

## Credits

- Original project: [awesome-llm-apps](https://github.com/Shubhamsaboo/awesome-llm-apps) by Shubhamsaboo
- Agent framework: [agno](https://github.com/agno-agi/agno)

## License

MIT License — see [LICENSE](LICENSE) for details.
