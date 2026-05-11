import feedparser
import pandas as pd
from urllib.parse import quote
from datetime import datetime
import os

KEYWORDS = [
    "Toyota supply chain disruption",
    "Bosch factory fire",
    "Taiwan earthquake semiconductor",
    "China export restriction battery",
    "Suez Canal blockage"
]

SAVE_FILE = "news_monitoring.csv"

def make_url(query):
    query = quote(query)
    return f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

results = []

for keyword in KEYWORDS:
    feed = feedparser.parse(make_url(keyword))

    for entry in feed.entries:
        results.append({
            "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "keyword": keyword,
            "title": entry.get("title", ""),
            "link": entry.get("link", ""),
            "published": entry.get("published", ""),
            "source": entry.get("source", {}).get("title", "")
        })

new_df = pd.DataFrame(results)

if os.path.exists(SAVE_FILE):
    old_df = pd.read_csv(SAVE_FILE)
    df = pd.concat([old_df, new_df], ignore_index=True)
else:
    df = new_df

df = df.drop_duplicates(subset=["title"])
df = df.drop_duplicates(subset=["link"])

df.to_csv(SAVE_FILE, index=False, encoding="utf-8-sig")

print(f"이번 실행 수집 기사 수: {len(new_df)}")
print(f"총 저장 기사 수: {len(df)}")
