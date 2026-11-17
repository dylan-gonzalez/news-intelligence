#!/usr/bin/env python3
"""
Article Content Extractor & Summarizer
Fetches full article text from URLs, generates concise summaries,
and updates news_platform.db.
"""

import sqlite3
import os
import sys
import json
import re
import urllib.request
import urllib.error
from html.parser import HTMLParser

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "news_platform.db")
DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# -----------------------------------------------------------------------------
# 1. Clean HTML Text Extractor (Standard Library, No heavy deps needed)
# -----------------------------------------------------------------------------
class CleanTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text_blocks = []
        self.ignore_tags = {'script', 'style', 'nav', 'header', 'footer', 'aside', 'noscript', 'svg'}
        self.current_tag = None

    def handle_starttag(self, tag, attrs):
        self.current_tag = tag.lower()

    def handle_endtag(self, tag):
        if self.current_tag == tag.lower():
            self.current_tag = None

    def handle_data(self, data):
        if self.current_tag not in self.ignore_tags:
            cleaned = data.strip()
            if cleaned and len(cleaned) > 20:  # Ignore tiny labels/buttons
                self.text_blocks.append(cleaned)

    def get_text(self) -> str:
        return " ".join(self.text_blocks)

def fetch_readable_text(url: str, timeout: int = 8) -> str:
    """Fetches a webpage and extracts its core body text."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_type = resp.headers.get("Content-Type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                return ""
            html_bytes = resp.read()
            html_text = html_bytes.decode('utf-8', errors='ignore')
            
            parser = CleanTextExtractor()
            parser.feed(html_text)
            return parser.get_text()
    except Exception as e:
        return ""

# -----------------------------------------------------------------------------
# 2. Extractive Summarizer (Frequency & Salience Scoring)
# -----------------------------------------------------------------------------
def generate_summary(text: str, max_sentences: int = 3) -> str:
    """Extracts the most salient sentences based on word frequency and positions."""
    if not text or len(text) < 100:
        return text

    # Split into sentences
    sentences = re.split(r'(?<=[.!?])\s+', text)
    if len(sentences) <= max_sentences:
        return " ".join(sentences)

    # Word frequency analysis
    words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
    stopwords = {
        'the', 'and', 'for', 'that', 'this', 'with', 'from', 'have', 'were',
        'which', 'their', 'will', 'would', 'there', 'about', 'they', 'what'
    }
    freq = {}
    for w in words:
        if w not in stopwords:
            freq[w] = freq.get(w, 0) + 1

    # Score each sentence
    sentence_scores = []
    for i, s in enumerate(sentences[:30]):  # Focus on top 30 sentences (journalistic pyramid)
        s_words = re.findall(r'\b[a-zA-Z]{3,}\b', s.lower())
        score = sum(freq.get(w, 0) for w in s_words)
        
        # Boost first 3 sentences slightly (lead paragraph bias in news)
        if i < 3:
            score *= 1.3
        
        sentence_scores.append((score, i, s.strip()))

    # Sort by score descending and take top N
    sentence_scores.sort(key=lambda x: x[0], reverse=True)
    top_sentences = sentence_scores[:max_sentences]
    
    # Restore original reading order
    top_sentences.sort(key=lambda x: x[1])
    
    return " ".join([s[2] for s in top_sentences])

# -----------------------------------------------------------------------------
# 3. Batch Summarization Process
# -----------------------------------------------------------------------------
def summarize_unsummarized_articles():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Find articles with missing or very short summaries
    cursor.execute("""
    SELECT id, title, url, summary, source_id
    FROM articles
    ORDER BY published_at DESC
    LIMIT 10;
    """)
    articles = cursor.fetchall()

    print(f"[*] Checking {len(articles)} recent articles for enhanced summaries...")
    updated_count = 0

    for art in articles:
        current_summary = art["summary"] or ""
        # If it's already an in-depth summary (> 180 chars and not just an HN counter), skip
        if len(current_summary) > 180 and "HN Score:" not in current_summary:
            continue

        print(f"  -> Extracting & summarizing: '{art['title'][:40]}...'")
        body_text = fetch_readable_text(art["url"])
        if body_text and len(body_text) > 150:
            new_summary = generate_summary(body_text, max_sentences=2)
            if new_summary and len(new_summary) > 40:
                cursor.execute("UPDATE articles SET summary = ? WHERE id = ?", (new_summary, art["id"]))
                updated_count += 1
                print(f"     ✓ Summary added ({len(new_summary)} chars)")
            else:
                print("     • Insufficient text extracted")
        else:
            print("     • External page skipped (paywall or non-HTML)")

    conn.commit()
    conn.close()

    # Refresh JSON snapshots for the UI
    import collector
    storage = collector.StorageEngine(DB_FILE)
    storage.export_feed_json(os.path.join(os.path.dirname(os.path.abspath(__file__)), "feed.json"))
    storage.export_db_snapshot(os.path.join(os.path.dirname(os.path.abspath(__file__)), "db_snapshot.json"))
    print(f"\n[+] Completed: {updated_count} article summaries updated.")

if __name__ == "__main__":
    summarize_unsummarized_articles()
