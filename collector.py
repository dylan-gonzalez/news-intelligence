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
def fetch_wikimedia_top_buzz(limit: int = 1000) -> Dict[str, Dict[str, Any]]:
    """Fetches the top viewed Wikipedia articles for the previous day with full URLs and view counts."""
    from datetime import timedelta
    target_date = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y/%m/%d")
    url = f"https://wikimedia.org/api/rest_v1/metrics/pageviews/top/en.wikipedia/all-access/{target_date}"
    
    headers = {"User-Agent": "NewsIntelligencePlatform/1.0 (contact@example.com)"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            items = data.get("items", [])[0].get("articles", [])
            ignore = {
                "main_page", "main page", "special:search", "-", 
                "special:createaccount", "special:watchlist", "404.php", 
                "portal:current_events", "portal:current events", "index.html"
            }
            buzz = {}
            for item in items:
                raw_slug = item.get("article", "")
                if not raw_slug:
                    continue
                clean_title = raw_slug.replace("_", " ").strip()
                clean_lower = clean_title.lower()
                
                if (clean_lower in ignore or 
                    raw_slug.lower() in ignore or 
                    raw_slug.startswith("File:") or 
                    raw_slug.startswith("Wikipedia:") or 
                    raw_slug.startswith("Special:") or 
                    raw_slug.startswith("Portal:") or
                    clean_lower.startswith("list of ")):
                    continue

                if is_sports_content(clean_title):
                    continue

                buzz[clean_lower] = {
                    "views": item.get("views", 0),
                    "article": raw_slug,
                    "title": clean_title,
                    "wiki_url": f"https://en.wikipedia.org/wiki/{urllib.parse.quote(raw_slug)}"
                }
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
# Mortgage Broking & Australian Finance Entity Extractor
# -----------------------------------------------------------------------------
def extract_mortgage_entities(text: str) -> List[NormalizedEntity]:
    entities = []
    text_lower = text.lower()
    
    # Major Lenders & Banks
    banks = [
        ("Commonwealth Bank", "CBA", [r"\bcba\b", r"\bcommonwealth bank\b"]),
        ("Westpac", "WBC", [r"\bwestpac\b"]),
        ("National Australia Bank", "NAB", [r"\bnab\b", r"\bnational australia bank\b"]),
        ("ANZ Bank", "ANZ", [r"\banz\b", r"\banz bank\b"]),
        ("Macquarie Bank", "MQG", [r"\bmacquarie\b", r"\bmacquarie bank\b"]),
        ("Bankwest", "BWA", [r"\bbankwest\b"]),
        ("ING Bank", "ING", [r"\bing\b", r"\bing bank\b", r"\bing australia\b"]),
        ("Suncorp Bank", "SUN", [r"\bsuncorp\b"]),
        ("Bendigo Bank", "BEN", [r"\bbendigo\b", r"\bbendigo bank\b"]),
        ("AMP Bank", "AMP", [r"\bamp\b", r"\bamp bank\b"])
    ]
    for name, code, triggers in banks:
        if any(re.search(tr, text_lower) for tr in triggers):
            entities.append(NormalizedEntity(name=name, entity_type="INSTITUTION", canonical_id=code))
            
    # Regulators & Industry Bodies
    bodies = [
        ("MFAA", "MFAA", [r"\bmfaa\b", r"mortgage & finance association"]),
        ("FBAA", "FBAA", [r"\bfbaa\b", r"finance brokers association"]),
        ("APRA", "APRA", [r"\bapra\b", r"prudential regulation authority"]),
        ("ASIC", "ASIC", [r"\basic\b", r"securities and investments commission"]),
        ("RBA", "RBA", [r"\brba\b", r"reserve bank of australia"]),
        ("AFCA", "AFCA", [r"\bafca\b", r"financial complaints authority"])
    ]
    for name, code, triggers in bodies:
        if any(re.search(tr, text_lower) for tr in triggers):
            entities.append(NormalizedEntity(name=name, entity_type="REGULATOR", canonical_id=code))

    # Aggregators
    aggregators = [
        ("LMG", [r"\blmg\b", r"loan market group", r"loan market"]),
        ("AFG", [r"\bafg\b", r"australian finance group"]),
        ("Finsure", [r"\bfinsure\b"]),
        ("Connective", [r"\bconnective\b"])
    ]
    for name, triggers in aggregators:
        if any(re.search(tr, text_lower) for tr in triggers):
            entities.append(NormalizedEntity(name=name, entity_type="AGGREGATOR"))
            
    # Core Mortgage Industry Topics
    concepts = [
        ("Mortgage Broking", [r"mortgage broker", r"mortgage broking", r"brokers", r"brokerage"]),
        ("Serviceability Buffer", [r"serviceability", r"3% buffer", r"serviceability buffer", r"borrowing capacity"]),
        ("Cash Rate", [r"cash rate", r"interest rate", r"rate hike", r"rate cut", r"monetary policy"]),
        ("First Home Buyers", [r"first home buyer", r"first-home buyer", r"\bfhb\b"]),
        ("Refinancing", [r"refinance", r"refinancing", r"clawback", r"clawbacks"]),
        ("Credit Policy", [r"credit policy", r"lending policy", r"lending criteria", r"lending barriers"]),
        ("Mortgage Fraud", [r"mortgage fraud", r"loan fraud"]),
        ("Negative Equity", [r"negative equity", r"\blvr\b", r"loan to value"]),
        ("Property Investment", [r"property investor", r"property investment", r"rental yield", r"housing shortage"])
    ]
    for name, triggers in concepts:
        if any(re.search(tr, text_lower) for tr in triggers):
            entities.append(NormalizedEntity(name=name, entity_type="TOPIC"))
            
    return entities

# -----------------------------------------------------------------------------
# 5. Australian Broker Adapter (Premier Broking Industry News)
# -----------------------------------------------------------------------------
class AustralianBrokerAdapter(BaseAdapter):
    source_id = "australian_broker"
    name = "Australian Broker"
    category = "finance"
    feed_url = "https://www.brokernews.com.au/rss/"
    feed_type = "atom"

    def fetch(self, limit: int = 15) -> List[NormalizedArticle]:
        raw = self._http_get(self.feed_url)
        root = ET.fromstring(raw)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        articles = []
        for entry in root.findall("atom:entry", namespaces=ns)[:limit]:
            title = (entry.findtext("atom:title", namespaces=ns) or "").strip()
            updated = (entry.findtext("atom:updated", namespaces=ns) or "").strip()
            link_elem = entry.find("atom:link", namespaces=ns)
            link = link_elem.attrib.get("href", "") if link_elem is not None else ""
            content = entry.findtext("atom:content", namespaces=ns) or ""
            clean_desc = re.sub(r"<[^<]+?>", "", content).strip()
            if len(clean_desc) > 300:
                clean_desc = clean_desc[:297] + "..."
                
            entities = [
                NormalizedEntity(name="Australian Broker", entity_type="SOURCE"),
                NormalizedEntity(name="Mortgage Industry", entity_type="TOPIC")
            ]
            entities.extend(extract_mortgage_entities(f"{title} {clean_desc}"))
            
            articles.append(NormalizedArticle(
                source_id=self.source_id,
                title=title,
                url=link,
                published_at=updated or datetime.now(timezone.utc).isoformat(),
                category=self.category,
                author="Australian Broker",
                summary=clean_desc,
                raw_payload={"source_type": "atom_feed", "industry": "mortgage_broking"},
                entities=entities
            ))
        return articles

# -----------------------------------------------------------------------------
# 6. MPA Magazine Adapter (Mortgage Professional Australia)
# -----------------------------------------------------------------------------
class MPAAdapter(BaseAdapter):
    source_id = "mpa_australia"
    name = "Mortgage Professional Australia"
    category = "finance"
    feed_url = "https://www.mpamag.com/au/rss"
    feed_type = "atom"

    def fetch(self, limit: int = 15) -> List[NormalizedArticle]:
        raw = self._http_get(self.feed_url)
        root = ET.fromstring(raw)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        articles = []
        for entry in root.findall("atom:entry", namespaces=ns)[:limit]:
            title = (entry.findtext("atom:title", namespaces=ns) or "").strip()
            updated = (entry.findtext("atom:updated", namespaces=ns) or "").strip()
            link_elem = entry.find("atom:link", namespaces=ns)
            link = link_elem.attrib.get("href", "") if link_elem is not None else ""
            content = entry.findtext("atom:content", namespaces=ns) or ""
            clean_desc = re.sub(r"<[^<]+?>", "", content).strip()
            if len(clean_desc) > 300:
                clean_desc = clean_desc[:297] + "..."
                
            entities = [
                NormalizedEntity(name="Mortgage Professional Australia", entity_type="SOURCE"),
                NormalizedEntity(name="Mortgage Broking", entity_type="TOPIC")
            ]
            entities.extend(extract_mortgage_entities(f"{title} {clean_desc}"))
            
            articles.append(NormalizedArticle(
                source_id=self.source_id,
                title=title,
                url=link,
                published_at=updated or datetime.now(timezone.utc).isoformat(),
                category=self.category,
                author="MPA Magazine",
                summary=clean_desc,
                raw_payload={"source_type": "atom_feed", "industry": "mortgage_broking"},
                entities=entities
            ))
        return articles

# -----------------------------------------------------------------------------
# 7. APRA Adapter (Prudential Regulation Authority)
# -----------------------------------------------------------------------------
class APRAAdapter(BaseAdapter):
    source_id = "apra_media"
    name = "APRA Banking Regulation"
    category = "finance"
    feed_url = "https://www.apra.gov.au/rss.xml"
    feed_type = "rss"

    def fetch(self, limit: int = 10) -> List[NormalizedArticle]:
        raw = self._http_get(self.feed_url)
        root = ET.fromstring(raw)
        articles = []
        for item in root.findall(".//item")[:limit]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            desc = (item.findtext("description") or "").strip()
            pub_date_str = item.findtext("pubDate")
            
            pub_iso = datetime.now(timezone.utc).isoformat()
            if pub_date_str:
                try:
                    dt = email.utils.parsedate_to_datetime(pub_date_str)
                    pub_iso = dt.isoformat()
                except Exception:
                    pass
                    
            clean_desc = re.sub(r"<[^<]+?>", "", desc).strip()
            if len(clean_desc) > 300:
                clean_desc = clean_desc[:297] + "..."
                
            entities = [
                NormalizedEntity(name="APRA", entity_type="REGULATOR", canonical_id="APRA"),
                NormalizedEntity(name="Banking Regulation", entity_type="TOPIC")
            ]
            entities.extend(extract_mortgage_entities(f"{title} {clean_desc}"))
            
            articles.append(NormalizedArticle(
                source_id=self.source_id,
                title=title,
                url=link,
                published_at=pub_iso,
                category=self.category,
                author="APRA",
                summary=clean_desc,
                raw_payload={"source_type": "rss", "industry": "banking_prudential"},
                entities=entities
            ))
        return articles

# -----------------------------------------------------------------------------
# 8. Property Update Adapter (Michael Yardney Housing & Property Economics)
# -----------------------------------------------------------------------------
class PropertyUpdateAdapter(BaseAdapter):
    source_id = "property_update_au"
    name = "Property Update Australia"
    category = "finance"
    feed_url = "https://propertyupdate.com.au/feed/"
    feed_type = "rss"

    def fetch(self, limit: int = 10) -> List[NormalizedArticle]:
        raw = self._http_get(self.feed_url)
        root = ET.fromstring(raw)
        articles = []
        for item in root.findall(".//item")[:limit]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            desc = (item.findtext("description") or "").strip()
            pub_date_str = item.findtext("pubDate")
            
            pub_iso = datetime.now(timezone.utc).isoformat()
            if pub_date_str:
                try:
                    dt = email.utils.parsedate_to_datetime(pub_date_str)
                    pub_iso = dt.isoformat()
                except Exception:
                    pass
                    
            clean_desc = re.sub(r"<[^<]+?>", "", desc).strip()
            if len(clean_desc) > 300:
                clean_desc = clean_desc[:297] + "..."
                
            entities = [
                NormalizedEntity(name="Property Update", entity_type="SOURCE"),
                NormalizedEntity(name="Housing Market", entity_type="TOPIC")
            ]
            entities.extend(extract_mortgage_entities(f"{title} {clean_desc}"))
            
            articles.append(NormalizedArticle(
                source_id=self.source_id,
                title=title,
                url=link,
                published_at=pub_iso,
                category=self.category,
                author="Property Update",
                summary=clean_desc,
                raw_payload={"source_type": "rss", "industry": "property_economics"},
                entities=entities
            ))
        return articles

# -----------------------------------------------------------------------------
# 9. MacroBusiness Australia Adapter (Macro, Housing Debt & Rates)
# -----------------------------------------------------------------------------
class MacrobusinessAdapter(BaseAdapter):
    source_id = "macrobusiness_au"
    name = "MacroBusiness Australia"
    category = "finance"
    feed_url = "https://www.macrobusiness.com.au/feed/"
    feed_type = "rss"

    def fetch(self, limit: int = 10) -> List[NormalizedArticle]:
        raw = self._http_get(self.feed_url)
        root = ET.fromstring(raw)
        articles = []
        for item in root.findall(".//item")[:limit]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            desc = (item.findtext("description") or "").strip()
            pub_date_str = item.findtext("pubDate")
            
            pub_iso = datetime.now(timezone.utc).isoformat()
            if pub_date_str:
                try:
                    dt = email.utils.parsedate_to_datetime(pub_date_str)
                    pub_iso = dt.isoformat()
                except Exception:
                    pass
                    
            clean_desc = re.sub(r"<[^<]+?>", "", desc).strip()
            if len(clean_desc) > 300:
                clean_desc = clean_desc[:297] + "..."
                
            entities = [
                NormalizedEntity(name="MacroBusiness", entity_type="SOURCE"),
                NormalizedEntity(name="Macroeconomics", entity_type="TOPIC")
            ]
            entities.extend(extract_mortgage_entities(f"{title} {clean_desc}"))
            
            articles.append(NormalizedArticle(
                source_id=self.source_id,
                title=title,
                url=link,
                published_at=pub_iso,
                category=self.category,
                author="MacroBusiness",
                summary=clean_desc,
                raw_payload={"source_type": "rss", "industry": "macro_finance"},
                entities=entities
            ))
        return articles

# -----------------------------------------------------------------------------
# 10. RBA Speeches & Statements Adapter
# -----------------------------------------------------------------------------
class RBASpeechesAdapter(BaseAdapter):
    source_id = "rba_speeches"
    name = "RBA Speeches & Statements"
    category = "finance"
    feed_url = "https://www.rba.gov.au/rss/rss-cb-speeches.xml"
    feed_type = "rss"

    def fetch(self, limit: int = 5) -> List[NormalizedArticle]:
        raw = self._http_get(self.feed_url)
        root = ET.fromstring(raw)
        articles = []
        for item in root.findall(".//item")[:limit]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            desc = (item.findtext("description") or "").strip()
            pub_date_str = item.findtext("pubDate")
            
            pub_iso = datetime.now(timezone.utc).isoformat()
            if pub_date_str:
                try:
                    dt = email.utils.parsedate_to_datetime(pub_date_str)
                    pub_iso = dt.isoformat()
                except Exception:
                    pass
                    
            clean_desc = re.sub(r"<[^<]+?>", "", desc).strip()
            entities = [
                NormalizedEntity(name="Reserve Bank of Australia", entity_type="INSTITUTION", canonical_id="RBA"),
                NormalizedEntity(name="Monetary Policy", entity_type="TOPIC")
            ]
            entities.extend(extract_mortgage_entities(f"{title} {clean_desc}"))
            
            articles.append(NormalizedArticle(
                source_id=self.source_id,
                title=f"RBA Speech: {title}",
                url=link,
                published_at=pub_iso,
                category=self.category,
                author="Reserve Bank of Australia",
                summary=clean_desc,
                raw_payload={"source_type": "rss", "type": "speech"},
                entities=entities
            ))
        return articles

# -----------------------------------------------------------------------------
# 11. YouTube Channel RSS Adapter
# -----------------------------------------------------------------------------
class YouTubeChannelAdapter(BaseAdapter):
    def __init__(self, channel_id: str, channel_name: str, category: str = "tech", handle: str = ""):
        self.channel_id = channel_id
        self.name = f"YouTube: {channel_name}"
        self.source_id = f"yt_{channel_id.lower()}"
        self.category = category
        self.handle = handle
        self.feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        self.feed_type = "youtube_rss"

    def fetch(self, limit: int = 6) -> List[NormalizedArticle]:
        raw = self._http_get(self.feed_url)
        root = ET.fromstring(raw)
        ns = {
            "atom": "http://www.w3.org/2005/Atom",
            "media": "http://search.yahoo.com/mrss/",
            "yt": "http://www.youtube.com/xml/schemas/2015"
        }
        articles = []
        for entry in root.findall("atom:entry", namespaces=ns)[:limit]:
            title = (entry.findtext("atom:title", namespaces=ns) or "").strip()
            pub_date = (entry.findtext("atom:published", namespaces=ns) or "").strip()
            link_elem = entry.find("atom:link", namespaces=ns)
            video_url = link_elem.attrib.get("href", "") if link_elem is not None else ""
            
            media_group = entry.find("media:group", namespaces=ns)
            description = ""
            thumbnail_url = ""
            if media_group is not None:
                description = (media_group.findtext("media:description", namespaces=ns) or "").strip()
                thumb_elem = media_group.find("media:thumbnail", namespaces=ns)
                if thumb_elem is not None:
                    thumbnail_url = thumb_elem.attrib.get("url", "")

            # Discard any accidental sports video
            if is_sports_content(f"{title} {description}"):
                continue

            summary = description[:280] + ("..." if len(description) > 280 else "")

            entities = [
                NormalizedEntity(name=self.name.replace("YouTube: ", ""), entity_type="CREATOR"),
                NormalizedEntity(name="YouTube", entity_type="PLATFORM")
            ]
            if self.category == "finance":
                entities.extend(extract_mortgage_entities(f"{title} {description}"))

            articles.append(NormalizedArticle(
                source_id=self.source_id,
                title=f"📺 {title}",
                url=video_url,
                published_at=pub_date or datetime.now(timezone.utc).isoformat(),
                category=self.category,
                author=self.name.replace("YouTube: ", ""),
                summary=summary,
                raw_payload={
                    "source_type": "youtube_rss",
                    "channel_id": self.channel_id,
                    "handle": self.handle,
                    "thumbnail": thumbnail_url,
                    "is_video": True
                },
                entities=entities
            ))
        return articles

# -----------------------------------------------------------------------------
# Headline Deduplication Utilities
# -----------------------------------------------------------------------------
def normalize_headline(title: str) -> str:
    """Strips leading emojis, labels, punctuation, and lowercases for deduplication."""
    t = re.sub(r'^[📺🔥\s]+', '', title)
    t = re.sub(r'^(breaking|exclusive|analysis|watch|podcast|speech|special report)[\s:\-]+', '', t, flags=re.IGNORECASE)
    t = re.sub(r'[^a-zA-Z0-9\s]', ' ', t.lower())
    words = [w for w in t.split() if len(w) > 2]
    return ' '.join(words)

def is_title_duplicate(title1: str, title2: str) -> bool:
    """Returns True if two headlines share >= 75% significant words."""
    norm1 = normalize_headline(title1)
    norm2 = normalize_headline(title2)
    if norm1 == norm2:
        return True
    words1 = set(norm1.split())
    words2 = set(norm2.split())
    if not words1 or not words2:
        return False
    similarity = len(words1.intersection(words2)) / len(words1.union(words2))
    return similarity >= 0.75

def determine_news_type(url: str, source_id: str = "", title: str = "", raw_payload: dict = None) -> str:
    """
    Classifies an article into:
    - 'youtube_short': Vertical video (<60s, /shorts/ URL, or #shorts tag)
    - 'youtube_video': Standard horizontal YouTube video / long-form
    - 'blog_post': Long-form blogs, essays, Substacks, and market commentaries
    - 'official_filing': SEC filings, arXiv preprints, RBA speeches, APRA regulatory disclosures
    - 'news_post': Standard news reporting, wire reports, and media articles
    """
    url_lower = (url or "").lower()
    title_lower = (title or "").lower()
    source_lower = (source_id or "").lower()
    payload = raw_payload or {}

    # YouTube Shorts
    if "/shorts/" in url_lower or "#shorts" in title_lower or "#short" in title_lower:
        return "youtube_short"

    # YouTube Standard Videos
    if source_lower.startswith("yt_") or "youtube.com" in url_lower or "youtu.be" in url_lower or payload.get("is_video"):
        return "youtube_video"

    # Official Filings, Central Banks, Academic Preprints
    if source_lower in ("sec_edgar", "arxiv_ai", "apra_media", "rba_media", "rba_speeches") or "arxiv.org" in url_lower or "sec.gov" in url_lower:
        return "official_filing"

    # Blogs & Analytical Commentaries
    if source_lower in ("macrobusiness_au", "property_update_au", "hacker_news") or "substack.com" in url_lower or "/blog" in url_lower:
        return "blog_post"

    # Default News Post
    return "news_post"

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

        # Restore from existing snapshot if starting on a clean database (e.g. CI/CD runners)
        snapshot_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db_snapshot.json")
        if os.path.exists(snapshot_file):
            with self._get_conn() as conn:
                cur = conn.execute("SELECT COUNT(*) FROM articles")
                if cur.fetchone()[0] == 0:
                    try:
                        with open(snapshot_file, "r", encoding="utf-8") as f:
                            snap = json.load(f)
                        for tbl in ["sources", "articles", "entities", "article_entities"]:
                            if tbl in snap and "rows" in snap[tbl]:
                                for row in snap[tbl]["rows"]:
                                    cols = list(row.keys())
                                    placeholders = ", ".join(["?"] * len(cols))
                                    col_names = ", ".join(cols)
                                    conn.execute(f"INSERT OR IGNORE INTO {tbl} ({col_names}) VALUES ({placeholders})", list(row.values()))
                        conn.commit()
                        print(f"[*] Restored {os.path.basename(snapshot_file)} into fresh database")
                    except Exception as e:
                        print(f"[!] Note: Could not restore snapshot ({e})")

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
            # Pre-load recent article titles for fuzzy deduplication
            cur = conn.execute("SELECT id, title, url FROM articles ORDER BY published_at DESC LIMIT 500")
            recent_articles = list(cur.fetchall())

            for a in articles:
                # Check for duplicate headline against existing recent articles
                if any(is_title_duplicate(a.title, existing["title"]) for existing in recent_articles):
                    continue

                art_id = str(uuid.uuid4())
                payload_json = json.dumps(a.raw_payload)
                try:
                    conn.execute("""
                    INSERT INTO articles (id, source_id, title, url, published_at, category, author, summary, raw_payload)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (art_id, a.source_id, a.title, a.url, a.published_at, a.category, a.author, a.summary, payload_json))
                    inserted_count += 1
                    recent_articles.append({"id": art_id, "title": a.title, "url": a.url})

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

    def export_feed_json(self, output_path: str = "feed.json", limit: int = 150):
        with self._get_conn() as conn:
            cur = conn.execute("""
            SELECT a.id, a.source_id, a.title, a.category, s.name as source_name, a.published_at, a.url,
                   a.author, a.summary, a.raw_payload
            FROM articles a
            JOIN sources s ON a.source_id = s.id
            ORDER BY a.published_at DESC
            LIMIT ?
            """, (limit,))
            articles = []
            seen_titles = []
            for row in cur.fetchall():
                title = row["title"]
                if any(is_title_duplicate(title, st) for st in seen_titles):
                    continue
                seen_titles.append(title)

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

                news_type = determine_news_type(
                    url=row["url"],
                    source_id=row["source_id"],
                    title=row["title"],
                    raw_payload=payload
                )

                articles.append({
                    "id": art_id,
                    "title": row["title"],
                    "category": row["category"],
                    "news_type": news_type,
                    "source_id": row["source_id"],
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

    def export_sources_json(self, output_path: str = "sources.json"):
        with self._get_conn() as conn:
            cur = conn.execute("""
            SELECT s.id, s.name, s.category, s.feed_url, s.feed_type, s.is_active,
                   COUNT(a.id) as article_count,
                   MAX(a.published_at) as latest_article_at
            FROM sources s
            LEFT JOIN articles a ON s.id = a.source_id
            GROUP BY s.id
            ORDER BY s.category, s.name
            """)
            sources = [dict(r) for r in cur.fetchall()]
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump({
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_count": len(sources),
                "sources": sources
            }, f, indent=2)
        return len(sources)

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
        AustralianBrokerAdapter(),
        MPAAdapter(),
        APRAAdapter(),
        PropertyUpdateAdapter(),
        MacrobusinessAdapter(),
        RBAAdapter(),
        RBASpeechesAdapter(),
        HackerNewsAdapter(),
        SECAdapter(),
        ArXivAdapter(),
        GoogleTrendsAdapter(geo="AU"),
        # YouTube Channels
        YouTubeChannelAdapter("UCONWr2M0moA8wsGHb3zUn_w", "AI Engineer", category="tech", handle="@aiDotEngineer"),
        YouTubeChannelAdapter("UC8cc4pVKVHG7A9fbNsRNrLQ", "IBM Technology", category="tech", handle="@IBMTechnology"),
        YouTubeChannelAdapter("UCZa18YV7qayTh-MRIrBhDpA", "Dwarkesh Patel", category="tech", handle="@DwarkeshPatel"),
        YouTubeChannelAdapter("UCMliswJ7oukCeW35GSayhRA", "The Wall Street Journal", category="finance", handle="@wsj"),
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
    wiki_buzz = fetch_wikimedia_top_buzz(limit=1000)
    if wiki_buzz:
        print(f"    -> Indexed {len(wiki_buzz)} top trending Wikipedia topics globally")
        with storage._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, title, raw_payload FROM articles;")
            all_articles = cur.fetchall()

            ignore_entities = {
                "youtube", "arxiv", "sec", "google", "platform", "institution", 
                "u.s. sec", "google trends", "hacker news", "australian broker",
                "mortgage professional australia", "video", "news", "topic"
            }

            enriched_articles = 0
            for art in all_articles:
                art_id = art["id"]
                title = art["title"]
                payload = json.loads(art["raw_payload"] or "{}")

                # Fetch entities for this article
                cur.execute("""
                SELECT e.name, e.entity_type FROM article_entities ae
                JOIN entities e ON ae.entity_id = e.id
                WHERE ae.article_id = ?
                """, (art_id,))
                entities = cur.fetchall()

                matched_buzz = None

                # 1. Match against specific entities
                for ent in entities:
                    ent_name = ent["name"].strip()
                    ent_lower = ent_name.lower()
                    if ent_lower in ignore_entities or ent["entity_type"] in ("PLATFORM", "REGULATORY_FORM"):
                        continue
                    
                    if ent_lower in wiki_buzz:
                        matched_buzz = wiki_buzz[ent_lower]
                        break
                    
                    # Partial match if length >= 5
                    for w_key, info in wiki_buzz.items():
                        if len(ent_lower) >= 5 and (ent_lower == w_key or ent_lower in w_key):
                            matched_buzz = info
                            break
                    if matched_buzz:
                        break

                # 2. Match against title keywords
                if not matched_buzz:
                    clean_title = re.sub(r'^[📺🔥\s]+', '', title).lower()
                    for w_key, info in wiki_buzz.items():
                        if len(w_key) >= 5 and re.search(r'\b' + re.escape(w_key) + r'\b', clean_title):
                            matched_buzz = info
                            break

                if matched_buzz:
                    payload["wiki_trending"] = True
                    payload["wiki_views"] = matched_buzz["views"]
                    payload["wiki_topic"] = matched_buzz["title"]
                    payload["wiki_url"] = matched_buzz["wiki_url"]
                    payload["hotness_score"] = max(payload.get("hotness_score", 0), 85)
                    cur.execute("UPDATE articles SET raw_payload = ? WHERE id = ?", (json.dumps(payload), art_id))
                    enriched_articles += 1
                else:
                    # Clear out any previous generic matches (like accidental YouTube platform match)
                    if payload.get("wiki_trending") and not payload.get("wiki_url"):
                        payload.pop("wiki_trending", None)
                        payload.pop("wiki_views", None)
                        payload.pop("wiki_topic", None)
                        cur.execute("UPDATE articles SET raw_payload = ? WHERE id = ?", (json.dumps(payload), art_id))

            conn.commit()
            if enriched_articles:
                print(f"    -> Enriched {enriched_articles} articles with genuine Wikipedia buzz spikes!")

    feed_json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "feed.json")
    exported_count = storage.export_feed_json(feed_json_path)
    print(f"[*] Exported {exported_count} articles with entities to {os.path.basename(feed_json_path)}")

    db_snap_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db_snapshot.json")
    table_count = storage.export_db_snapshot(db_snap_path)
    print(f"[*] Exported {table_count} tables snapshot to {os.path.basename(db_snap_path)}")

    sources_json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources.json")
    sources_count = storage.export_sources_json(sources_json_path)
    print(f"[*] Exported {sources_count} sources registry to {os.path.basename(sources_json_path)}")

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
