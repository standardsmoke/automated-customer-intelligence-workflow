#!/usr/bin/env python3
"""
Executive News Monitor
----------------------
Scrapes Google News RSS for each company/executive in companies.csv,
ranks articles by importance, and sends a polished HTML email digest.

Required environment variables (set as GitHub Secrets):
  GMAIL_ADDRESS       - your Gmail address (sender)
  GMAIL_APP_PASSWORD  - 16-char Gmail App Password (not your login password)
  RECIPIENT_EMAILS    - comma-separated list of recipient emails
"""

import csv
import os
import re
import smtplib
import sys
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import unescape
from html.parser import HTMLParser

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

COMPANIES_CSV = os.path.join(os.path.dirname(__file__), "..", "companies.csv")
MAX_ARTICLES_PER_COMPANY = 5   # max articles shown per company
MAX_TOTAL_ARTICLES = 40        # hard cap on total articles

# Priority keywords → score boost
PRIORITY_KEYWORDS = {
    # Critical business events
    "acqui": 10, "merger": 10, "acquire": 10, "acquisition": 10,
    "ipo": 9, "bankrupt": 10, "insolvency": 10,
    "earnings": 8, "revenue": 7, "profit": 7, "loss": 7,
    "quarterly results": 8, "annual results": 8,
    # Executive events
    "ceo": 6, "chief executive": 6, "resign": 8, "fired": 8,
    "appoint": 6, "hire": 5, "leadership": 5,
    # Legal / regulatory
    "lawsuit": 7, "sue": 7, "settlement": 7, "fine": 7,
    "investigation": 7, "antitrust": 8, "regulation": 6,
    "sec": 7, "ftc": 7, "doj": 7,
    # Market events
    "layoff": 7, "restructur": 7, "cut": 5, "expansion": 5,
    "partner": 4, "deal": 5, "contract": 5,
    # General positive/negative signals
    "record": 5, "growth": 4, "decline": 5, "surge": 5, "plunge": 6,
}

PRIORITY_LABELS = {
    range(10, 100): ("🔴 CRITICAL", "#dc2626"),
    range(6, 10):   ("🟠 HIGH",     "#ea580c"),
    range(3, 6):    ("🟡 MEDIUM",   "#ca8a04"),
    range(0, 3):    ("⚪ STANDARD", "#6b7280"),
}

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

class MLStripper(HTMLParser):
    """Strip HTML tags from a string."""
    def __init__(self):
        super().__init__()
        self.reset()
        self.fed = []
    def handle_data(self, d):
        self.fed.append(d)
    def get_data(self):
        return " ".join(self.fed)

def strip_html(html: str) -> str:
    s = MLStripper()
    s.feed(html)
    return unescape(s.get_data()).strip()

def get_priority_label(score: int):
    for r, (label, color) in PRIORITY_LABELS.items():
        if score in r:
            return label, color
    return "⚪ STANDARD", "#6b7280"

def score_article(title: str, description: str) -> int:
    text = (title + " " + description).lower()
    score = 0
    for keyword, boost in PRIORITY_KEYWORDS.items():
        if keyword in text:
            score += boost
    return score

def fetch_google_news(query: str) -> list[dict]:
    """Fetch articles from Google News RSS for a query."""
    encoded = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
    articles = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            xml_data = resp.read()
        root = ET.fromstring(xml_data)
        channel = root.find("channel")
        if channel is None:
            return []
        for item in channel.findall("item")[:8]:
            title_el = item.find("title")
            desc_el = item.find("description")
            link_el = item.find("link")
            pub_el = item.find("pubDate")
            source_el = item.find("source")

            title = strip_html(title_el.text or "") if title_el is not None else ""
            description = strip_html(desc_el.text or "") if desc_el is not None else ""
            link = (link_el.text or "").strip() if link_el is not None else ""
            pub_date = (pub_el.text or "").strip() if pub_el is not None else ""
            source = (source_el.text or "").strip() if source_el is not None else "Unknown Source"

            if title:
                articles.append({
                    "title": title,
                    "description": description[:300] + "..." if len(description) > 300 else description,
                    "url": link,
                    "published": pub_date,
                    "source": source,
                    "score": score_article(title, description),
                })
    except Exception as e:
        print(f"  ⚠️  Failed to fetch news for query '{query}': {e}", file=sys.stderr)
    return articles

def deduplicate(articles: list[dict]) -> list[dict]:
    """Remove near-duplicate articles by title similarity."""
    seen = []
    out = []
    for a in articles:
        title_words = set(re.sub(r"[^a-z0-9 ]", "", a["title"].lower()).split())
        is_dup = False
        for s in seen:
            overlap = len(title_words & s) / max(len(title_words | s), 1)
            if overlap > 0.6:
                is_dup = True
                break
        if not is_dup:
            seen.append(title_words)
            out.append(a)
    return out

def load_companies(csv_path: str) -> list[dict]:
    companies = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            company = row.get("company", "").strip()
            executives = row.get("executives", "").strip()
            industry = row.get("industry", "").strip()
            if company:
                companies.append({
                    "company": company,
                    "executives": [e.strip() for e in executives.split("|") if e.strip()],
                    "industry": industry,
                })
    return companies

# ─────────────────────────────────────────────
# EMAIL TEMPLATE
# ─────────────────────────────────────────────

def build_email_html(company_results: list[dict], run_date: str) -> str:
    total_articles = sum(len(r["articles"]) for r in company_results)
    companies_with_news = sum(1 for r in company_results if r["articles"])

    # Build top-priority section (all articles across companies, sorted by score)
    all_articles = []
    for r in company_results:
        for a in r["articles"]:
            all_articles.append({**a, "company": r["company"]})
    all_articles.sort(key=lambda x: x["score"], reverse=True)
    top_articles = [a for a in all_articles if a["score"] >= 6][:5]

    # ── Top Priority Section ──
    top_html = ""
    if top_articles:
        top_rows = ""
        for i, a in enumerate(top_articles, 1):
            label, color = get_priority_label(a["score"])
            top_rows += f"""
            <tr>
              <td style="padding:16px 20px; border-bottom:1px solid #f1f5f9; vertical-align:top;">
                <div style="display:flex; align-items:flex-start; gap:12px;">
                  <span style="font-size:13px; font-weight:700; color:#1e293b; min-width:20px; padding-top:2px;">#{i}</span>
                  <div style="flex:1;">
                    <div style="margin-bottom:6px;">
                      <span style="font-size:11px; font-weight:700; color:{color}; letter-spacing:0.05em;">{label}</span>
                      <span style="font-size:11px; color:#94a3b8; margin-left:8px;">{a['company']}</span>
                    </div>
                    <a href="{a['url']}" style="font-size:14px; font-weight:600; color:#0f172a; text-decoration:none; line-height:1.4;">{a['title']}</a>
                    <p style="margin:6px 0 4px; font-size:13px; color:#64748b; line-height:1.5;">{a['description']}</p>
                    <span style="font-size:12px; color:#94a3b8;">{a['source']} · {a['published'][:16] if a['published'] else ''}</span>
                  </div>
                </div>
              </td>
            </tr>"""
        top_html = f"""
        <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:32px; border:1px solid #e2e8f0; border-radius:8px; overflow:hidden;">
          <tr>
            <td style="background:#0f172a; padding:14px 20px;">
              <span style="font-size:13px; font-weight:700; color:#f8fafc; letter-spacing:0.06em; text-transform:uppercase;">⚡ Top Priority This Week</span>
            </td>
          </tr>
          {top_rows}
        </table>"""

    # ── Per-Company Sections ──
    company_sections = ""
    for r in company_results:
        articles = r["articles"]
        if not articles:
            continue

        exec_str = ", ".join(r["executives"]) if r["executives"] else "—"
        industry = r.get("industry", "")

        article_rows = ""
        for a in articles:
            label, color = get_priority_label(a["score"])
            article_rows += f"""
              <tr>
                <td style="padding:14px 20px; border-bottom:1px solid #f8fafc; vertical-align:top;">
                  <div style="margin-bottom:4px;">
                    <span style="font-size:11px; font-weight:600; color:{color};">{label}</span>
                  </div>
                  <a href="{a['url']}" style="font-size:13px; font-weight:600; color:#0f172a; text-decoration:none; line-height:1.4;">{a['title']}</a>
                  <p style="margin:5px 0 3px; font-size:12px; color:#64748b; line-height:1.5;">{a['description']}</p>
                  <span style="font-size:11px; color:#94a3b8;">{a['source']} · {a['published'][:16] if a['published'] else ''}</span>
                </td>
              </tr>"""

        company_sections += f"""
        <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px; border:1px solid #e2e8f0; border-radius:8px; overflow:hidden;">
          <tr>
            <td style="background:#f8fafc; padding:14px 20px; border-bottom:1px solid #e2e8f0;">
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td>
                    <div style="font-size:15px; font-weight:700; color:#0f172a;">{r['company']}</div>
                    <div style="font-size:12px; color:#64748b; margin-top:2px;">
                      <span>{industry}</span>
                      {"<span style='margin:0 6px; color:#cbd5e1;'>·</span><span>Executives: " + exec_str + "</span>" if exec_str != "—" else ""}
                    </div>
                  </td>
                  <td align="right">
                    <span style="font-size:12px; font-weight:600; color:#475569; background:#e2e8f0; padding:3px 8px; border-radius:12px;">{len(articles)} article{'s' if len(articles) != 1 else ''}</span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          {article_rows}
        </table>"""

    # ── No-news companies ──
    no_news = [r for r in company_results if not r["articles"]]
    no_news_html = ""
    if no_news:
        names = ", ".join(r["company"] for r in no_news)
        no_news_html = f"""
        <p style="font-size:12px; color:#94a3b8; margin-bottom:24px; padding:12px 16px; background:#f8fafc; border-radius:6px; border:1px solid #e2e8f0;">
          <strong>No news this week:</strong> {names}
        </p>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Executive News Digest</title>
</head>
<body style="margin:0; padding:0; background:#f1f5f9; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">

  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9; padding:32px 16px;">
    <tr>
      <td align="center">
        <table width="640" cellpadding="0" cellspacing="0" style="max-width:640px; width:100%;">

          <!-- HEADER -->
          <tr>
            <td style="background:#0f172a; border-radius:8px 8px 0 0; padding:28px 32px 24px;">
              <div style="font-size:11px; font-weight:700; color:#94a3b8; letter-spacing:0.12em; text-transform:uppercase; margin-bottom:8px;">Executive Intelligence Brief</div>
              <div style="font-size:26px; font-weight:800; color:#f8fafc; line-height:1.2;">Weekly News Digest</div>
              <div style="font-size:14px; color:#64748b; margin-top:6px;">{run_date}</div>
              <table cellpadding="0" cellspacing="0" style="margin-top:20px;">
                <tr>
                  <td style="background:#1e293b; border-radius:6px; padding:10px 20px; margin-right:8px; text-align:center;">
                    <div style="font-size:22px; font-weight:800; color:#f8fafc;">{companies_with_news}</div>
                    <div style="font-size:11px; color:#64748b; text-transform:uppercase; letter-spacing:0.05em;">Companies</div>
                  </td>
                  <td style="width:8px;"></td>
                  <td style="background:#1e293b; border-radius:6px; padding:10px 20px; text-align:center;">
                    <div style="font-size:22px; font-weight:800; color:#f8fafc;">{total_articles}</div>
                    <div style="font-size:11px; color:#64748b; text-transform:uppercase; letter-spacing:0.05em;">Articles</div>
                  </td>
                  <td style="width:8px;"></td>
                  <td style="background:#1e293b; border-radius:6px; padding:10px 20px; text-align:center;">
                    <div style="font-size:22px; font-weight:800; color:#f8fafc;">{len(top_articles)}</div>
                    <div style="font-size:11px; color:#64748b; text-transform:uppercase; letter-spacing:0.05em;">High Priority</div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- BODY -->
          <tr>
            <td style="background:#ffffff; border-radius:0 0 8px 8px; padding:32px;">

              {top_html}

              <div style="font-size:12px; font-weight:700; color:#94a3b8; letter-spacing:0.1em; text-transform:uppercase; margin-bottom:16px;">Company Briefings</div>
              {company_sections}
              {no_news_html}

              <!-- FOOTER -->
              <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:32px; border-top:1px solid #e2e8f0; padding-top:20px;">
                <tr>
                  <td>
                    <p style="margin:0; font-size:12px; color:#94a3b8; line-height:1.6;">
                      Generated automatically on {run_date} via Google News RSS.<br>
                      Articles are ranked by relevance to business-critical events.<br>
                      To update monitored companies, edit <code>companies.csv</code> in your repository.
                    </p>
                  </td>
                </tr>
              </table>

            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>

</body>
</html>"""
    return html

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Executive News Monitor")
    print(f"Started: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    # ── Load companies ──
    csv_path = os.path.abspath(COMPANIES_CSV)
    if not os.path.exists(csv_path):
        print(f"❌ companies.csv not found at: {csv_path}", file=sys.stderr)
        sys.exit(1)

    companies = load_companies(csv_path)
    print(f"\n📋 Loaded {len(companies)} companies from companies.csv")

    # ── Fetch news ──
    company_results = []
    total_found = 0

    for entry in companies:
        company = entry["company"]
        executives = entry["executives"]
        print(f"\n🔍 Searching: {company}...")

        # Build search queries: company name + each executive
        queries = [company]
        for exec_name in executives[:2]:  # limit to 2 execs per company
            queries.append(f'"{exec_name}"')

        all_articles = []
        for q in queries:
            articles = fetch_google_news(q)
            print(f"   '{q}' → {len(articles)} articles")
            all_articles.extend(articles)

        # Deduplicate and sort by score
        unique = deduplicate(all_articles)
        unique.sort(key=lambda x: x["score"], reverse=True)
        top = unique[:MAX_ARTICLES_PER_COMPANY]
        total_found += len(top)

        company_results.append({
            "company": company,
            "executives": executives,
            "industry": entry["industry"],
            "articles": top,
        })

        if total_found >= MAX_TOTAL_ARTICLES:
            print(f"⚠️  Hit max article cap ({MAX_TOTAL_ARTICLES}), stopping early.")
            break

    print(f"\n✅ Total articles collected: {total_found}")

    # ── Build email ──
    run_date = datetime.now(timezone.utc).strftime("%A, %B %d, %Y")
    html_body = build_email_html(company_results, run_date)

    # ── Send email ──
    gmail_address = os.environ.get("GMAIL_ADDRESS", "").strip()
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD", "").strip()
    recipients_raw = os.environ.get("RECIPIENT_EMAILS", "").strip()

    if not gmail_address or not gmail_password:
        print("\n⚠️  GMAIL_ADDRESS or GMAIL_APP_PASSWORD not set.")
        print("    Saving email preview to email_preview.html instead.")
        with open("email_preview.html", "w", encoding="utf-8") as f:
            f.write(html_body)
        print("    ✅ Saved to email_preview.html")
        return

    recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]
    if not recipients:
        print("❌ RECIPIENT_EMAILS is empty — no one to send to.", file=sys.stderr)
        sys.exit(1)

    subject = f"Executive News Digest — {run_date}"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_address
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html"))

    print(f"\n📧 Sending to {len(recipients)} recipient(s)...")
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_address, gmail_password)
            server.sendmail(gmail_address, recipients, msg.as_string())
        print(f"✅ Email sent successfully to: {', '.join(recipients)}")
    except smtplib.SMTPAuthenticationError:
        print("❌ Gmail authentication failed.", file=sys.stderr)
        print("   Make sure GMAIL_APP_PASSWORD is a 16-char App Password,", file=sys.stderr)
        print("   NOT your regular Gmail password.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"❌ Failed to send email: {e}", file=sys.stderr)
        sys.exit(1)

    print("\n" + "=" * 60)
    print("Done.")

if __name__ == "__main__":
    main()
