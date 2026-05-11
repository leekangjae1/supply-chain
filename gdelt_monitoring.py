import requests
import pandas as pd
from pathlib import Path
from urllib.parse import quote

DATA_PATH = Path("gdelt_monitoring.csv")

queries = [
    '"Hyundai" "supplier" disruption',
    '"Kia" "supplier" shortage',
    '"automotive" "semiconductor shortage"',
    '"port strike" "supply chain"',
    '"Red Sea" "shipping" "supply chain"',
    '"Suez Canal" "supply chain"',
    '"battery" "supplier" disruption'
]

all_articles = []

for q in queries:
    url = (
        "https://api.gdeltproject.org/api/v2/doc/doc"
        f"?query={quote(q)}"
        "&mode=artlist"
        "&format=json"
        "&maxrecords=50"
        "&timespan=1d"
        "&sort=datedesc"
    )

    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        data = response.json()

        for article in data.get("articles", []):
            all_articles.append({
                "query": q,
                "title": article.get("title"),
                "url": article.get("url"),
                "domain": article.get("domain"),
                "source_country": article.get("sourceCountry"),
                "language": article.get("language"),
                "published": article.get("seendate"),
            })

    except Exception as e:
        print(f"Error in query: {q}")
        print(e)

new_df = pd.DataFrame(all_articles)

if DATA_PATH.exists():
    old_df = pd.read_csv(DATA_PATH)
    df = pd.concat([old_df, new_df], ignore_index=True)
else:
    df = new_df

if not df.empty:
    df = df.drop_duplicates(subset=["url"])
    df = df.drop_duplicates(subset=["title"])
    df = df.sort_values("published", ascending=False)

df.to_csv(DATA_PATH, index=False, encoding="utf-8-sig")

print(f"Saved {len(df)} GDELT articles")
