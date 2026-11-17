#!/usr/bin/env python3
"""
Modular News & Intelligence Collector
Ingests from RBA, SEC EDGAR, Hacker News, and arXiv into a relational operational store
with entity extraction staging for Neo4j.
"""

import sys
import os
import json
import sqlite3
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import email.utils
import re
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional

DEFAULT_USER_AGENT = "NewsIntelligencePlatform/1.0 (contact@example.com)"

@dataclass
class NormalizedEntity:
    name: str
    entity_type: str  # 'COMPANY', 'INSTITUTION', 'PERSON', 'TOPIC', 'METRIC'
    canonical_id: Optional[str] = None
    confidence: float = 1.0
    extracted_via: str = "rule"

@dataclass
class NormalizedArticle:
    source_id: str
    title: str
    url: str
    published_at: str  # ISO 8601 string
    category: str      # 'tech', 'finance', 'health', 'politics'
    author: Optional[str] = None
    summary: Optional[str] = None
    content_raw: Optional[str] = None
    raw_payload: Dict[str, Any] = field(default_factory=dict)
    entities: List[NormalizedEntity] = field(default_factory=list)

# -----------------------------------------------------------------------------
# Base Adapter Interface
# -----------------------------------------------------------------------------
class BaseAdapter:
    source_id: str
    name: str
    category: str
    feed_url: str
    feed_type: str

    def fetch(self) -> List[NormalizedArticle]:
        raise NotImplementedError

    def _http_get(self, url: str, headers: Optional[Dict[str, str]] = None) -> bytes:
        hdrs = {"User-Agent": DEFAULT_USER_AGENT}
        if headers:
            hdrs.update(headers)
        req = urllib.request.Request(url, headers=hdrs)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read()

# -----------------------------------------------------------------------------
# Sports Filter & Content Classifier
# -----------------------------------------------------------------------------
SPORTS_PATTERNS = [
    # General sports keywords & match language
    r"\b(cricket|afl|nrl|rugby|footy|football|soccer|baseball|basketball|tennis|golf|boxing|ufc|mma|wwe|wrestling)\b",
    r"\b(premier league|champions league|la liga|serie a|bundesliga|fifa|uefa|epl)\b",
    r"\b(nba|nfl|nhl|mlb|mls|wnba|ipl|bbl)\b",
    r"\b(wimbledon|australian open|us open|french open|atp|wta|roland garros)\b",
    r"\b(formula 1|formula one|f1|grand prix|motogp|nascar|supercars)\b",
    r"\b(melbourne cup|horse racing|jockey|derby|spring carnival|cox plate)\b",
    r"\b(olympics|paralympics|commonwealth games)\b",
    r"\b(grand final|semi-final|playoff|playoffs|quarterfinal|touchdown|goalkeeper|striker|red card|yellow card)\b",
    r"\b(innings|wicket|wickets|batsman|bowler|batting|bowling|overs)\b",
    r"\b(head coach|quarterback|pitcher|punt|scrum|try line|homerun)\b",
    # Specific common sports fixtures and teams
    r"\b(melbourne storm|penrith panthers|brisbane broncos|sydney roosters|south sydney|rabbitohs|eels|sea eagles|raiders|cowboys)\b",
    r"\b(collingwood|carlton|richmond|geelong|essendon|hawthorn|swans|st kilda|western bulldogs|adelaide crows|port adelaide|fremantle|dockers|west coast eagles)\b",
    r"\b(manchester united|manchester city|liverpool fc|arsenal fc|chelsea fc|tottenham|real madrid|barcelona|psg|bayern|juventus)\b",
    r"\b(pak vs sl|ind vs aus|aus vs eng|eng vs nz|rsa vs ind)\b",
    r"\b\w+\s+(vs\.?|v)\s+\w+\b",
]

def is_sports_content(text: str) -> bool:
    """Returns True if the text relates to sports, games, or matches."""
    text_lower = text.lower()
    for pattern in SPORTS_PATTERNS:
        if re.search(pattern, text_lower):
            return True
    return False

def classify_content(title: str, query: str = "", snippet: str = "") -> Optional[str]:
    """
    Classifies content into 'tech', 'finance', 'health', 'politics'.
    Returns None if the content is identified as sports (to be discarded).
    """
    full_text = f"{title} {query} {snippet}".lower()
    
    # 1. Sports Filter - Discard sports entirely
    if is_sports_content(full_text):
        return None
        
    # 2. Technology & AI
    tech_patterns = [
        r"\b(ai|artificial intelligence|machine learning|deep learning|llm|gpt|claude|gemini)\b",
        r"\b(tech|technology|software|hardware|computing|cyber|cybersecurity|crypto|bitcoin|ethereum)\b",
        r"\b(nvidia|apple|google|microsoft|meta|amazon|openai|anthropic|tsmc|intel|amd)\b",
        r"\b(semiconductor|chips|microchip|quantum|robot|robotics|autonomous|algorithm)\b"
    ]
    if any(re.search(p, full_text) for p in tech_patterns):
        return "tech"

    # 3. Finance, Markets & Business
    finance_patterns = [
        r"\b(finance|financial|economy|economic|inflation|deflation|recession|gdp|cpi)\b",
        r"\b(market|markets|stock|stocks|shares|trading|investor|investors|wall street|nyse|nasdaq|asx)\b",
        r"\b(rba|reserve bank|federal reserve|fed|central bank|interest rate|rates|cash rate)\b",
        r"\b(earnings|revenue|profit|loss|quarterly|dividend|ipo|merger|acquisition|offshore)\b",
        r"\b(jobs|redundant|redundancies|layoffs|hiring|unemployment|workforce)\b",
        r"\b(mining|commodities|crude|oil|gold|lithium|bunnings|banking|bank|treasury)\b"
    ]
    if any(re.search(p, full_text) for p in finance_patterns):
        return "finance"

    # 4. Health, Medicine & Science
    health_patterns = [
        r"\b(health|medical|medicine|hospital|clinic|doctor|patient|cancer|disease|virus|infection)\b",
        r"\b(vaccine|vaccination|clinical trial|fda|tga|cdc|who|pharma|pharmaceutical|drug)\b",
        r"\b(biotech|genetics|dna|mental health|pandemic|therapy|surgery)\b"
    ]
    if any(re.search(p, full_text) for p in health_patterns):
        return "health"

    # 5. Politics, Policy, Government & Law
    politics_patterns = [
        r"\b(politics|political|policy|government|parliament|senate|congress|legislation|bill|law)\b",
        r"\b(election|poll|voting|vote|prime minister|president|minister|albanese|biden|trump)\b",
        r"\b(court|judge|legal|lawsuit|supreme court|police|investigation|investigating|crime)\b",
        r"\b(foreign affairs|geopolitics|treaty|diplomat|diplomacy|sanctions|military|defense)\b"
    ]
    if any(re.search(p, full_text) for p in politics_patterns):
        return "politics"

    # Default fallback for general non-sports news
    return "politics"

# -----------------------------------------------------------------------------
# 5. Google Trends Realtime Adapter (Search Velocity & Hot Stories)
# -----------------------------------------------------------------------------
class GoogleTrendsAdapter(BaseAdapter):
    def __init__(self, geo: str = "AU"):
        self.geo = geo
        self.source_id = f"google_trends_{geo.lower()}"
        self.name = f"Google Trends ({geo})"
        self.category = "politics"  # Default fallback
        self.feed_url = f"https://trends.google.com/trending/rss?geo={geo}"
        self.feed_type = "rss"

    def fetch(self, limit: int = 15) -> List[NormalizedArticle]:
        raw = self._http_get(self.feed_url)
        root = ET.fromstring(raw)
        articles = []

        ns = {"ht": "https://trends.google.com/trending/rss"}
        items = root.findall(".//item")

        for item in items:
            query = (item.findtext("title") or "").strip()
            traffic = item.findtext("ht:approx_traffic", namespaces=ns) or "1,000+"
            pub_date_str = item.findtext("pubDate")
            
            pub_iso = datetime.now(timezone.utc).isoformat()
            if pub_date_str:
                try:
                    dt = email.utils.parsedate_to_datetime(pub_date_str)
                    pub_iso = dt.isoformat()
                except Exception:
                    pass

            # Attached news item
            news_items = item.findall("ht:news_item", namespaces=ns)
            headline = ""
            news_url = ""
            news_source = ""
            snippet = ""
            if news_items:
                headline = news_items[0].findtext("ht:news_item_title", namespaces=ns) or ""
                news_url = news_items[0].findtext("ht:news_item_url", namespaces=ns) or ""
                news_source = news_items[0].findtext("ht:news_item_source", namespaces=ns) or "News Outlet"
                snippet = news_items[0].findtext("ht:news_item_snippet", namespaces=ns) or ""

            article_title = f"{query.title()}: {headline}" if headline else f"Surging Search: {query.title()}"
            target_url = news_url if news_url else f"https://trends.google.com/trends/explore?q={urllib.parse.quote_plus(query)}"

            # Dynamically classify category & filter out sports
            detected_category = classify_content(article_title, query, snippet)
            if detected_category is None:
                # Discard sports articles entirely
                continue

            # Calculate numerical hotness from traffic (e.g. "50,000+" -> 50000)
            traffic_num = 1000
            m = re.search(r'([\d,]+)', traffic)
            if m:
                try:
                    traffic_num = int(m.group(1).replace(',', ''))
                except ValueError:
                    pass

            entities = [
                NormalizedEntity(name=query.title(), entity_type="TOPIC", canonical_id=f"gtrend:{query}"),
                NormalizedEntity(name="Google Trends", entity_type="INSTITUTION")
            ]
            if news_source and news_source != "News Outlet":
                entities.append(NormalizedEntity(name=news_source, entity_type="SOURCE"))

            articles.append(NormalizedArticle(
                source_id=self.source_id,
                title=article_title,
                url=target_url,
                published_at=pub_iso,
                category=detected_category,
                author=news_source or "Google Trends",
                summary=f"🔥 High Search Velocity: {traffic} searches. {snippet}",
                raw_payload={
                    "trending_query": query,
                    "approx_traffic": traffic,
                    "traffic_num": traffic_num,
                    "hotness_score": min(100, int(traffic_num / 500) + 50),
                    "news_source": news_source,
                    "trends_url": f"https://trends.google.com/trends/explore?q={urllib.parse.quote_plus(query)}"
                },
                entities=entities
            ))
            if len(articles) >= limit:
                break

        return articles

# -----------------------------------------------------------------------------
# 6. Wikimedia Pageviews Top Buzz Ingestion
# -----------------------------------------------------------------------------
def fetch_wikimedia_top_buzz(limit: int = 50) -> Dict[str, int]:
    """Fetches the top viewed Wikipedia articles for the previous day."""
    from datetime import timedelta
    target_date = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y/%m/%d")
    url = f"https://wikimedia.org/api/rest_v1/metrics/pageviews/top/en.wikipedia/all-access/{target_date}"
    
    headers = {"User-Agent": "NewsIntelligencePlatform/1.0 (contact@example.com)"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            items = data.get("items", [])[0].get("articles", [])
            ignore = {"Main_Page", "Special:Search", "-", "Special:CreateAccount", "Special:Watchlist"}
            buzz = {}
            for item in items:
                art_name = item.get("article", "").replace("_", " ")
                if art_name not in ignore and not art_name.startswith("File:") and not art_name.startswith("Wikipedia:"):
                    buzz[art_name.lower()] = item.get("views", 0)
                    if len(buzz) >= limit:
                        break
            return buzz
    except Exception as e:
        print(f"  [Wikimedia] Note: Could not fetch top pageviews ({e})", file=sys.stderr)
        return {}

# -----------------------------------------------------------------------------
# 1. RBA RSS Adapter (Finance / Macro)
# -----------------------------------------------------------------------------
class RBAAdapter(BaseAdapter):
    source_id = "rba_media"
    name = "Reserve Bank of Australia"
    category = "finance"
    feed_url = "https://www.rba.gov.au/rss/rss-cb-media-releases.xml"
    feed_type = "rss"

    def fetch(self) -> List[NormalizedArticle]:
        raw = self._http_get(self.feed_url)
        root = ET.fromstring(raw)
        articles = []

        # Find items regardless of RSS 1.0 / 2.0 RDF namespace
        items = [e for e in root.iter() if e.tag.endswith("item")]
        for item in items:
            title = ""
            link = ""
            desc = ""
            pub_date_str = ""
            
            for child in item:
                tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if tag == "title":
                    title = (child.text or "").strip()
                elif tag == "link":
                    link = (child.text or "").strip()
                elif tag == "description":
                    desc = (child.text or "").strip()
                elif tag in ("pubDate", "date"):
                    pub_date_str = (child.text or "").strip()
            
            # Parse RFC 822 date to ISO
            pub_iso = datetime.now(timezone.utc).isoformat()
            if pub_date_str:
                try:
                    dt = email.utils.parsedate_to_datetime(pub_date_str)
                    pub_iso = dt.isoformat()
                except Exception:
                    pass

            entities = [
                NormalizedEntity(name="Reserve Bank of Australia", entity_type="INSTITUTION", canonical_id="RBA"),
                NormalizedEntity(name="Monetary Policy", entity_type="TOPIC")
            ]
            if "Cash Rate" in title or "interest rate" in title.lower():
                entities.append(NormalizedEntity(name="Cash Rate", entity_type="METRIC"))

            articles.append(NormalizedArticle(
                source_id=self.source_id,
                title=title,
                url=link,
                published_at=pub_iso,
                category=self.category,
                author="RBA",
                summary=desc,
                raw_payload={"source_type": "rss_release"},
                entities=entities
            ))
        return articles

# -----------------------------------------------------------------------------
# 2. Hacker News Firebase Adapter (Tech)
# -----------------------------------------------------------------------------
class HackerNewsAdapter(BaseAdapter):
    source_id = "hacker_news"
    name = "Hacker News (Top Stories)"
    category = "tech"
    feed_url = "https://hacker-news.firebaseio.com/v0/topstories.json"
    feed_type = "rest_json"

    def fetch(self, limit: int = 5) -> List[NormalizedArticle]:
        # Fetch top story IDs
        raw_ids = self._http_get(f"{self.feed_url}?limitToFirst={limit}&orderBy=%22$key%22")
        story_ids = json.loads(raw_ids.decode("utf-8"))[:limit]
        
        articles = []
        for sid in story_ids:
            try:
                story_raw = self._http_get(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json")
                item = json.loads(story_raw.decode("utf-8"))
                if not item or item.get("type") != "story":
                    continue
                
                title = item.get("title", "")
                url = item.get("url") or f"https://news.ycombinator.com/item?id={sid}"
                score = item.get("score", 0)
                by = item.get("by", "anonymous")
                created_ts = item.get("time", int(datetime.now(timezone.utc).timestamp()))
                pub_iso = datetime.fromtimestamp(created_ts, timezone.utc).isoformat()

                entities = [
                    NormalizedEntity(name="Hacker News", entity_type="INSTITUTION", canonical_id="YCombinator"),
                    NormalizedEntity(name=by, entity_type="PERSON", extracted_via="metadata")
                ]

                # Extract domain as entity if external link
                domain_match = re.search(r"https?://(?:www\.)?([^/]+)", url)
                if domain_match and "ycombinator.com" not in domain_match.group(1):
                    entities.append(NormalizedEntity(name=domain_match.group(1), entity_type="DOMAIN"))

                hotness = min(100, int(score / 8) + 30) if score > 50 else 20
                articles.append(NormalizedArticle(
                    source_id=self.source_id,
                    title=title,
                    url=url,
                    published_at=pub_iso,
                    category=self.category,
                    author=by,
                    summary=f"HN Score: {score} | Comments: {len(item.get('kids', []))}",
                    raw_payload={
                        "hn_id": sid,
                        "score": score,
                        "descendants": item.get("descendants", 0),
                        "hotness_score": hotness,
                        "discussion_url": f"https://news.ycombinator.com/item?id={sid}"
                    },
                    entities=entities
                ))
            except Exception as e:
                print(f"  [HN] Error fetching item {sid}: {e}", file=sys.stderr)
        return articles

# -----------------------------------------------------------------------------
# 3. SEC EDGAR Submissions Adapter (Finance / Corporate Disclosures)
# -----------------------------------------------------------------------------
class SECAdapter(BaseAdapter):
    source_id = "sec_edgar"
    name = "U.S. SEC EDGAR Disclosures"
    category = "finance"
    # Testing with Apple Inc. CIK: 0000320193
    feed_url = "https://data.sec.gov/submissions/CIK0000320193.json"
    feed_type = "rest_json"

    def fetch(self, limit: int = 4) -> List[NormalizedArticle]:
        headers = {"User-Agent": "NewsIntelligenceApp user@example.com"}
        raw = self._http_get(self.feed_url, headers=headers)
        data = json.loads(raw.decode("utf-8"))

        company_name = data.get("name", "Unknown Company")
        cik = data.get("cik", "")
        tickers = data.get("tickers", [])
        primary_ticker = tickers[0] if tickers else ""
        
        filings = data.get("filings", {}).get("recent", {})
        forms = filings.get("form", [])
        dates = filings.get("filingDate", [])
        accession_nums = filings.get("accessionNumber", [])
        doc_names = filings.get("primaryDocument", [])
        descriptions = filings.get("primaryDocDescription", [])

        articles = []
        for i in range(min(limit, len(forms))):
            form = forms[i]
            filing_date = dates[i]
            accession = accession_nums[i]
            accession_clean = accession.replace("-", "")
            doc_name = doc_names[i]
            desc = descriptions[i] if i < len(descriptions) else ""
            
            doc_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_clean}/{doc_name}"
            title = f"{company_name} ({primary_ticker}) Files Form {form}: {desc or 'Official Filing'}"
            pub_iso = f"{filing_date}T00:00:00Z"

            entities = [
                NormalizedEntity(name=company_name, entity_type="COMPANY", canonical_id=f"CIK:{cik}"),
                NormalizedEntity(name=f"Form {form}", entity_type="REGULATORY_FORM"),
                NormalizedEntity(name="U.S. SEC", entity_type="INSTITUTION", canonical_id="SEC")
            ]
            if primary_ticker:
                entities.append(NormalizedEntity(name=primary_ticker, entity_type="TICKER", canonical_id=primary_ticker))

            articles.append(NormalizedArticle(
                source_id=self.source_id,
                title=title,
                url=doc_url,
                published_at=pub_iso,
                category=self.category,
                author=company_name,
                summary=f"Official SEC Form {form} filing. Accession: {accession}",
                raw_payload={
                    "cik": cik,
                    "ticker": primary_ticker,
                    "form": form,
                    "accession_number": accession
                },
                entities=entities
            ))
        return articles

# -----------------------------------------------------------------------------
# 4. arXiv API Adapter (Tech / AI / Science Preprints)
# -----------------------------------------------------------------------------
class ArXivAdapter(BaseAdapter):
    source_id = "arxiv_ai"
    name = "arXiv Computer Science & AI"
    category = "tech"
    # By default, arXiv sorts by relevance. We must explicitly set sortBy=submittedDate&sortOrder=descending for new preprints!
    feed_url = "http://export.arxiv.org/api/query?search_query=cat:cs.AI&sortBy=submittedDate&sortOrder=descending&start=0&max_results=5"
    feed_type = "atom"

    def fetch(self) -> List[NormalizedArticle]:
        raw = self._http_get(self.feed_url)
        root = ET.fromstring(raw)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        articles = []

        for entry in root.findall("atom:entry", ns):
            title = (entry.findtext("atom:title", namespaces=ns) or "").strip().replace("\n", " ")
            summary = (entry.findtext("atom:summary", namespaces=ns) or "").strip().replace("\n", " ")
            published = entry.findtext("atom:published", namespaces=ns) or datetime.now(timezone.utc).isoformat()
            
            # Find primary link
            link_elem = entry.find("atom:link[@rel='alternate']", namespaces=ns)
            url = link_elem.get("href") if link_elem is not None else entry.findtext("atom:id", namespaces=ns)
            
            authors = [a.findtext("atom:name", namespaces=ns) for a in entry.findall("atom:author", namespaces=ns)]
            primary_author = authors[0] if authors else "Unknown"

            entities = [
                NormalizedEntity(name="Artificial Intelligence", entity_type="TOPIC", canonical_id="cs.AI"),
                NormalizedEntity(name="arXiv", entity_type="INSTITUTION")
            ]
            for a in authors[:3]:
                if a:
                    entities.append(NormalizedEntity(name=a, entity_type="PERSON"))

            articles.append(NormalizedArticle(
                source_id=self.source_id,
                title=title,
                url=url,
                published_at=published,
                category=self.category,
                author=", ".join(authors[:3]),
                summary=summary[:300] + ("..." if len(summary) > 300 else ""),
                raw_payload={"authors": authors, "primary_category": "cs.AI"},
                entities=entities
            ))
        return articles

# -----------------------------------------------------------------------------
# Database Layer (SQLite local engine, directly compatible with PostgreSQL schema)
# -----------------------------------------------------------------------------
class StorageEngine:
    def __init__(self, db_path: str = "news_platform.db"):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS sources (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                feed_url TEXT NOT NULL,
                feed_type TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                last_fetched_at TEXT
            );

            CREATE TABLE IF NOT EXISTS articles (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL REFERENCES sources(id),
                title TEXT NOT NULL,
                url TEXT UNIQUE NOT NULL,
                published_at TEXT NOT NULL,
                category TEXT NOT NULL,
                author TEXT,
                summary TEXT,
                raw_payload TEXT,
                graph_synced_at TEXT DEFAULT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                canonical_id TEXT,
                UNIQUE (name, entity_type)
            );

            CREATE TABLE IF NOT EXISTS article_entities (
                article_id TEXT NOT NULL REFERENCES articles(id),
                entity_id TEXT NOT NULL REFERENCES entities(id),
                confidence_score REAL DEFAULT 1.0,
                extracted_via TEXT DEFAULT 'rule',
                PRIMARY KEY (article_id, entity_id)
            );

            CREATE INDEX IF NOT EXISTS idx_articles_cat_pub ON articles(category, published_at DESC);
            CREATE INDEX IF NOT EXISTS idx_articles_graph_sync ON articles(published_at DESC) WHERE graph_synced_at IS NULL;
            """)

    def register_sources(self, adapters: List[BaseAdapter]):
        with self._get_conn() as conn:
            for ad in adapters:
                conn.execute("""
                INSERT INTO sources (id, name, category, feed_url, feed_type)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (id) DO UPDATE SET
                    name = excluded.name,
                    feed_url = excluded.feed_url
                """, (ad.source_id, ad.name, ad.category, ad.feed_url, ad.feed_type))

    def save_articles(self, articles: List[NormalizedArticle]) -> int:
        import uuid
        inserted_count = 0
        with self._get_conn() as conn:
            for a in articles:
                art_id = str(uuid.uuid4())
                payload_json = json.dumps(a.raw_payload)
                try:
                    conn.execute("""
                    INSERT INTO articles (id, source_id, title, url, published_at, category, author, summary, raw_payload)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (art_id, a.source_id, a.title, a.url, a.published_at, a.category, a.author, a.summary, payload_json))
                    inserted_count += 1

                    # Save entities and relationships
                    for ent in a.entities:
                        ent_id = str(uuid.uuid4())
                        # Insert or ignore entity
                        conn.execute("""
                        INSERT OR IGNORE INTO entities (id, name, entity_type, canonical_id)
                        VALUES (?, ?, ?, ?)
                        """, (ent_id, ent.name, ent.entity_type, ent.canonical_id))
                        
                        # Fetch the actual entity id (in case it existed already)
                        cur = conn.execute("SELECT id FROM entities WHERE name = ? AND entity_type = ?", (ent.name, ent.entity_type))
                        row = cur.fetchone()
                        actual_ent_id = row[0] if row else ent_id

                        conn.execute("""
                        INSERT OR IGNORE INTO article_entities (article_id, entity_id, confidence_score, extracted_via)
                        VALUES (?, ?, ?, ?)
                        """, (art_id, actual_ent_id, ent.confidence, ent.extracted_via))

                except sqlite3.IntegrityError:
                    # Article URL already exists (deduplicated)
                    pass

            # Update source last_fetched_at
            if articles:
                conn.execute("UPDATE sources SET last_fetched_at = ? WHERE id = ?", 
                             (datetime.now(timezone.utc).isoformat(), articles[0].source_id))

        return inserted_count

    def get_latest_feed(self, limit: int = 15):
        with self._get_conn() as conn:
            cur = conn.execute("""
            SELECT a.title, a.category, s.name as source_name, a.published_at, a.url,
                   (SELECT COUNT(*) FROM article_entities ae WHERE ae.article_id = a.id) as entity_count
            FROM articles a
            JOIN sources s ON a.source_id = s.id
            ORDER BY a.published_at DESC
            LIMIT ?
            """, (limit,))
            return cur.fetchall()

    def get_pending_graph_entities(self, limit: int = 10):
        with self._get_conn() as conn:
            cur = conn.execute("""
            SELECT a.title, e.name, e.entity_type, e.canonical_id
            FROM articles a
            JOIN article_entities ae ON a.id = ae.article_id
            JOIN entities e ON ae.entity_id = e.id
            WHERE a.graph_synced_at IS NULL
            ORDER BY a.published_at DESC
            LIMIT ?
            """, (limit,))
            return cur.fetchall()

    def export_feed_json(self, output_path: str = "feed.json", limit: int = 50):
        with self._get_conn() as conn:
            cur = conn.execute("""
            SELECT a.id, a.title, a.category, s.name as source_name, a.published_at, a.url,
                   a.author, a.summary, a.raw_payload
            FROM articles a
            JOIN sources s ON a.source_id = s.id
            ORDER BY a.published_at DESC
            LIMIT ?
            """, (limit,))
            articles = []
            for row in cur.fetchall():
                art_id = row["id"]
                # Fetch entities for this article
                ent_cur = conn.execute("""
                SELECT e.name, e.entity_type, e.canonical_id, ae.confidence_score
                FROM article_entities ae
                JOIN entities e ON ae.entity_id = e.id
                WHERE ae.article_id = ?
                """, (art_id,))
                entities = [dict(e) for e in ent_cur.fetchall()]
                
                payload = {}
                if row["raw_payload"]:
                    try:
                        payload = json.loads(row["raw_payload"])
                    except Exception:
                        pass

                articles.append({
                    "id": art_id,
                    "title": row["title"],
                    "category": row["category"],
                    "source_name": row["source_name"],
                    "published_at": row["published_at"],
                    "url": row["url"],
                    "author": row["author"],
                    "summary": row["summary"],
                    "payload": payload,
                    "entities": entities
                })
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump({"generated_at": datetime.now(timezone.utc).isoformat(), "articles": articles}, f, indent=2)
        return len(articles)

    def export_db_snapshot(self, output_path: str = "db_snapshot.json"):
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;")
            tables = [row[0] for row in cur.fetchall()]
            snapshot = {}
            for table in tables:
                # Column info
                cur.execute(f"PRAGMA table_info({table});")
                cols = [{"name": c[1], "type": c[2] or "ANY", "notnull": bool(c[3]), "pk": bool(c[5])} for c in cur.fetchall()]
                # Rows
                cur.execute(f"SELECT * FROM {table} LIMIT 100;")
                rows = [dict(r) for r in cur.fetchall()]
                snapshot[table] = {
                    "columns": cols,
                    "rows": rows,
                    "total_count": len(rows)
                }
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2)
        return len(tables)

# -----------------------------------------------------------------------------
# Main Execution Runner
# -----------------------------------------------------------------------------
def run_collection():
    db_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "news_platform.db")
    storage = StorageEngine(db_file)
    
    adapters: List[BaseAdapter] = [
        RBAAdapter(),
        HackerNewsAdapter(),
        SECAdapter(),
        ArXivAdapter(),
        GoogleTrendsAdapter(geo="AU")
    ]
    storage.register_sources(adapters)
    
    print("=" * 75)
    print("  RUNNING NEWS & INTELLIGENCE INGESTION ENGINE")
    print("=" * 75)

    total_inserted = 0
    for ad in adapters:
        print(f"[*] Ingesting from: {ad.name} ({ad.category.upper()})...")
        try:
            articles = ad.fetch()
            count = storage.save_articles(articles)
            print(f"    -> Fetched {len(articles)} items | New stored: {count}")
            total_inserted += count
        except Exception as e:
            print(f"    -> [!] Error collecting from {ad.name}: {e}", file=sys.stderr)

    print("\n" + "-" * 75)
    print(f"  INGESTION COMPLETE: {total_inserted} new stories recorded")
    print("-" * 75)

    # Correlate with real-time Wikimedia Pageviews Top Buzz
    print("[*] Fetching Wikimedia Pageviews Top Buzz to detect surging entities...")
    wiki_buzz = fetch_wikimedia_top_buzz(limit=100)
    if wiki_buzz:
        print(f"    -> Indexed {len(wiki_buzz)} top trending Wikipedia topics globally")
        with storage._get_conn() as conn:
            cur = conn.cursor()
            # Check all entities and enrich matching articles
            cur.execute("SELECT id, name FROM entities;")
            entities = cur.fetchall()
            enriched_articles = 0
            for ent in entities:
                ent_name_clean = ent["name"].lower()
                matched_views = None
                for w_title, w_views in wiki_buzz.items():
                    if ent_name_clean == w_title or (len(ent_name_clean) > 4 and ent_name_clean in w_title):
                        matched_views = w_views
                        break
                
                if matched_views:
                    # Enrich all articles mentioning this entity
                    cur.execute("""
                    SELECT a.id, a.raw_payload FROM articles a
                    JOIN article_entities ae ON a.id = ae.article_id
                    WHERE ae.entity_id = ?
                    """, (ent["id"],))
                    for row in cur.fetchall():
                        try:
                            payload = json.loads(row["raw_payload"] or "{}")
                            payload["wiki_trending"] = True
                            payload["wiki_views"] = matched_views
                            payload["hotness_score"] = max(payload.get("hotness_score", 0), 85)
                            cur.execute("UPDATE articles SET raw_payload = ? WHERE id = ?", (json.dumps(payload), row["id"]))
                            enriched_articles += 1
                        except Exception:
                            pass
            conn.commit()
            if enriched_articles:
                print(f"    -> Enriched {enriched_articles} articles with global Wikipedia buzz spikes!")

    feed_json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "feed.json")
    exported_count = storage.export_feed_json(feed_json_path)
    print(f"[*] Exported {exported_count} articles with entities to {os.path.basename(feed_json_path)}")

    db_snap_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db_snapshot.json")
    table_count = storage.export_db_snapshot(db_snap_path)
    print(f"[*] Exported {table_count} tables snapshot to {os.path.basename(db_snap_path)}")

    print("\n[+] LATEST FEED PREVIEW (Operational Read Layer):")
    feed = storage.get_latest_feed(10)
    for row in feed:
        cat_badge = f"[{row['category'].upper()}]".ljust(11)
        src = f"({row['source_name']})".ljust(30)
        entities = f"({row['entity_count']} entities staged for Neo4j)"
        print(f"  {cat_badge} {src} {row['title'][:45]}... {entities}")

    print("\n[+] STAGED ENTITIES FOR NEO4J SYNC (Sample):")
    staged = storage.get_pending_graph_entities(8)
    for row in staged:
        ent_desc = f"Entity: {row['name']} [{row['entity_type']}]"
        if row['canonical_id']:
            ent_desc += f" (ID: {row['canonical_id']})"
        print(f"  -> Article: '{row['title'][:32]}...' | {ent_desc}")

if __name__ == "__main__":
    run_collection()
