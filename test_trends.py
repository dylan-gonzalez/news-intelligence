import urllib.request
import xml.etree.ElementTree as ET

urls = {
    "Google Trends (AU)": "https://trends.google.com/trending/rss?geo=AU",
    "Google Trends (US)": "https://trends.google.com/trending/rss?geo=US",
}

for name, url in urls.items():
    print(f"\n--- {name} ---")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
            root = ET.fromstring(data)
            items = root.findall(".//item")
            for item in items[:4]:
                title = item.findtext("title")
                approx = item.findtext("{https://trends.google.com/trending/rss}approx_traffic") or "N/A"
                pub = item.findtext("pubDate")
                news_items = item.findall("{https://trends.google.com/trending/rss}news_item")
                headline = ""
                if news_items:
                    headline = news_items[0].findtext("{https://trends.google.com/trending/rss}news_item_title")
                print(f"• Query: {title} | Traffic: {approx}")
                if headline:
                    print(f"  Headline: {headline[:70]}...")
    except Exception as e:
        print(f"Error: {e}")
