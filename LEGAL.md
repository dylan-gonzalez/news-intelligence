# Legal & Regulatory Compliance Framework
## Automated News & Intelligence Aggregation (Australia & United States)

> **Disclaimer:** This document provides a structural analysis of statutory frameworks, relevant case law, and operational best practices for software engineering teams building content aggregation and intelligence platforms. It is for informational and architectural guidance and does not constitute formal legal counsel.

---

## 1. United States Legal Framework

### A. The Copyright Act of 1976 (17 U.S.C. §§ 101 et seq.)

#### 1. The Fact / Expression Dichotomy (17 U.S.C. § 102(b))
* **The Rule:** Copyright protects original artistic or literary *expression*, but expressly excludes ideas, procedures, systems, methods of operation, concepts, principles, or **factual discoveries**.
* **Application to News:** The facts of a breaking event (e.g., that a merger occurred, an interest rate changed, or a trial concluded) cannot be copyrighted. Only the specific sentences and prose used by the journalist are protected.
* **Relevant Precedent:** *Feist Publications, Inc. v. Rural Telephone Service Co.*, 499 U.S. 340 (1991) confirmed that raw facts and data lack the requisite originality for copyright protection.

#### 2. Fair Use Doctrine (17 U.S.C. § 107)
News aggregators rely on the four-factor Fair Use statutory balancing test:
1. **Purpose and Character of Use:** Transformative uses that index, catalog, summarize, or provide analytical metadata for news consumption are strongly favored (*Authors Guild v. Google, Inc.*, 804 F.3d 201 (2d Cir. 2015)).
2. **Nature of the Copyrighted Work:** Informational, factual news reporting is granted narrower copyright protection than creative fiction.
3. **Amount and Substantiality Used:** Using only headlines, metadata, and 1–3 sentence summaries is deemed minimal and proportionate. Re-hosting entire article bodies without a license violates this prong (*Associated Press v. Meltwater U.S. Holdings, Inc.*, 931 F. Supp. 2d 537 (S.D.N.Y. 2013)).
4. **Effect upon the Potential Market:** An aggregator must act as a **pointer** that drives traffic to the primary publisher. If the aggregator serves as a full-text substitute that obviates the need to visit the original site, fair use fails.

#### 3. Hyperlinking and Thumbnail Precedents
* Simply providing a hypertext link (`<a href="...">`) to a publicly accessible webpage does not constitute direct copyright infringement under U.S. law (*Perfect 10, Inc. v. Amazon.com, Inc.*, 508 F.3d 1146 (9th Cir. 2007)).

#### 4. U.S. Government Works (17 U.S.C. § 105)
* Works created by officers or employees of the United States Government as part of their official duties are in the **public domain**.
* **Application:** Filings on **SEC EDGAR** (Forms 8-K, 10-K, 10-Q), data from the Federal Reserve, and government agency releases are exempt from copyright claims and free to redistribute.

---

### B. Computer Fraud and Abuse Act (CFAA - 18 U.S.C. § 1030)

* **The Rule:** Prohibits intentionally accessing a computer "without authorization" or "exceeding authorized access."
* **Application to Web Scraping:** 
  * The U.S. Supreme Court in *Van Buren v. United States*, 141 S. Ct. 1648 (2021) and the Ninth Circuit in *hiQ Labs, Inc. v. LinkedIn Corp.*, 31 F.4th 1180 (9th Cir. 2022) affirmed that **scraping publicly available information from websites without authenticating or bypassing access controls does not violate the CFAA**.
  * Mere violation of a website's Terms of Service (ToS) does not constitute a criminal violation of the CFAA.

---

### C. Digital Millennium Copyright Act (DMCA - 17 U.S.C. § 512 & § 1201)

#### 1. Safe Harbor for Information Location Tools (§ 512(d))
* Aggregators, search engines, and directories that link or refer users to online locations containing infringing material are shielded from monetary liability if they:
  * Do not have actual knowledge of infringement;
  * Do not receive direct financial benefit directly attributable to infringing activity where they have the right to control it;
  * Expeditiously remove or disable access to linked material upon receiving a compliant DMCA takedown notice.

#### 2. Anti-Circumvention Rule (§ 1201)
* **Crucial Restriction:** It is illegal to circumvent technical protection measures (TPMs) that effectively control access to a copyrighted work.
* **Application:** You **must never** write code to defeat paywalls (e.g. bypassing meter scripts, cookie blockers, token injection, or password authentication).

---

## 2. Australian Legal Framework

### A. The Copyright Act 1968 (Cth)

Unlike the open-ended U.S. Fair Use doctrine, Australia operates under a system of **specific statutory exceptions** known as **Fair Dealing**.

#### 1. Fair Dealing for Reporting of News (Section 42)
* **The Exception:** A fair dealing with a literary, dramatic, musical, or artistic work does not constitute an infringement of copyright if it is done **for the purpose of, or associated with, the reporting of news** in a newspaper, magazine, or by means of communication (including online digital platforms).
* **Mandatory Requirement:** You **must provide sufficient acknowledgement** of the original work (identifying the title of the article, publisher/source, and author where known).

#### 2. Fair Dealing for Criticism or Review (Section 41)
* Protects analytical commentary, evaluation, and comparative summaries of published articles, provided sufficient acknowledgement is given.

#### 3. Fact vs. Expression in Australia
* In *IceTV Pty Ltd v Nine Network Australia Pty Ltd* [2009] HCA 14, the High Court of Australia established that purely factual information (such as broadcast times, dates, and titles) lacks the requisite authorial originality to sustain copyright infringement claims.

#### 4. Crown Copyright & Government Data
* Commonwealth of Australia public releases (including **Reserve Bank of Australia (RBA)** media releases and **Australian Bureau of Statistics (ABS)** data) are routinely published under standard **Creative Commons Attribution 4.0 International (CC BY 4.0)** licenses. You may freely republish, aggregate, and compute statistics from them, provided attribution to the Commonwealth/RBA is retained.

---

### B. News Media and Digital Platforms Mandatory Bargaining Code (2021)
*(Treasury Laws Amendment (News Media and Digital Platforms Mandatory Bargaining Code) Act 2021 (Cth))*

* **Scope:** Passed by the Australian Federal Parliament to compel tech companies to negotiate commercial payments with Australian news media organizations for indexing snippets.
* **Applicability:** The Code applies **strictly and exclusively to "designated digital platform services"** formally designated by the Australian Federal Treasurer (intended for massive multi-billion-dollar gatekeeper platforms like Google and Meta).
* **Application to Independent Aggregators:** **Does NOT apply** to small, independent, or third-party web developers, startups, or non-designated publishers.

---

### C. Australian Consumer Law (Competition and Consumer Act 2010 - Schedule 2)

#### Section 18: Misleading or Deceptive Conduct
* A corporation or website must not, in trade or commerce, engage in conduct that is misleading or deceptive or likely to mislead or deceive.
* **Application:**
  * You must clearly label the origin of all aggregated content.
  * You must not mislead users into believing that third-party news outlets (e.g. ABC, AFR, Reuters) are affiliated with, sponsor, or endorse your platform.
  * Use clear source badges (e.g., `"Source: Reserve Bank of Australia"`) rather than claiming ownership of the reports.

---

## 3. Operational Rules of Architecture & Engineering

To ensure your platform remains strictly compliant under both U.S. and Australian jurisdictions, design your systems according to these five engineering rules:

| Rule | Technical Specification | Legal Justification |
| :--- | :--- | :--- |
| **1. Headline + Snippet + Link Only** | Display title, source attribution, and at most a 1–3 sentence summary. Open the canonical article in a new tab (`target="_blank"`). | Satisfies 17 U.S.C. § 107 (US Fair Use) and Section 42 (AU Fair Dealing). Prevents market substitution. |
| **2. Zero Framing / Embedding** | Never load third-party articles inside an `<iframe>` on your domain. Always redirect the user out to the original URL. | Avoids trademark dilution, false affiliation claims under ACL § 18, and copyright framing disputes. |
| **3. Strict Paywall Non-Circumvention** | Do not script paywall bypasses, user-agent spoofing (e.g., claiming to be `Googlebot` to evade meters), or token tampering. | Prevents civil and criminal liability under DMCA 17 U.S.C. § 1201 and international equivalents. |
| **4. Structured User-Agent Header** | Every outbound HTTP request in `collector.py` must declare: `User-Agent: PlatformName/1.0 (+https://yoursite.com; contact@yoursite.com)` | Mandatory for U.S. SEC EDGAR compliance and good-faith scraping standards. |
| **5. Respect `robots.txt`** | Check `robots.txt` for disallow directives before scraping full article bodies for summarization. | Demonstrates authorized access and compliance under CFAA (*hiQ v. LinkedIn* standards). |

---

## 4. Required Public Pages on Your Website

When launching your site, include these three policy components in your footer:

1. **Terms of Service & Disclaimer:**
   > *"This platform is an automated news and intelligence index. All headlines, excerpts, and trademarks belong to their respective original publishers. Outbound links direct users to the authoritative source."*
2. **Attribution Notices:**
   > Clearly state licensing for open datasets (e.g., *"Statistical releases from the Reserve Bank of Australia used under CC BY 4.0; US SEC filings public domain"*).
3. **DMCA / Copyright Takedown Contact:**
   > Provide a designated email address (e.g. `legal@yoursite.com`) where publishers can request that their RSS feed or domain be excluded from indexing. Complying immediately with legitimate opt-out requests guarantees protection under statutory safe harbors.
