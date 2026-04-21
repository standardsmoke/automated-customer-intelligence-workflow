# 📰 Executive News Monitor

A zero-cost, zero-maintenance weekly news digest that automatically scrapes Google News for your monitored companies and executives, then emails a polished HTML report every **Monday at 7:30 AM PST**.

**No servers. No databases. No API keys. Just GitHub.**

---

## How It Works

```
Every Monday 7:30 AM PST
        ↓
GitHub Actions wakes up
        ↓
Reads companies.csv
        ↓
Scrapes Google News RSS for each company + executive
        ↓
Ranks articles by business importance
(acquisitions, earnings, lawsuits, leadership changes...)
        ↓
Builds polished HTML email with top-priority highlights
        ↓
Sends via Gmail to your mailing list
```

---

## Setup (One-Time, ~10 Minutes)

### Step 1 — Fork or Create the Repository

If you received this as a zip, create a new GitHub repository and push these files to it.

> **Important:** The repository must be **public**, OR you must have GitHub Actions minutes available (free for public repos; 2,000 min/month free for private repos on the free tier).

---

### Step 2 — Edit Your Company List

Open `companies.csv` and replace the example companies with your own:

```csv
company,executives,industry
Acme Corp,Jane Smith,Manufacturing
Globex Inc,John Doe|Mary Jones,Finance
Wayne Enterprises,,Technology
```

**Column guide:**
| Column | Required | Notes |
|--------|----------|-------|
| `company` | ✅ Yes | Company name as it appears in news |
| `executives` | No | Full name(s). Use `|` to separate multiple: `Jane Smith\|Bob Lee` |
| `industry` | No | Used for display in the email only |

**Tips:**
- Use the exact name as it appears in press coverage (e.g., "Meta" not "Facebook Inc.")
- Executive names improve results — the script searches for each exec independently
- Up to ~20 companies works well; beyond that, emails get long

---

### Step 3 — Get a Gmail App Password

You need a **Gmail App Password** — this is different from your regular password.

1. Go to [myaccount.google.com/security](https://myaccount.google.com/security)
2. Enable **2-Step Verification** if not already on
3. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
4. Create a new app password:
   - App name: `Executive News Monitor` (or anything you like)
5. Copy the **16-character password** shown (spaces don't matter)

> ⚠️ This password gives access to your Gmail. Keep it secret — never commit it to the repo.

---

### Step 4 — Add GitHub Secrets

Secrets are encrypted environment variables that GitHub injects at runtime. Your password never touches the repo.

1. Go to your GitHub repository
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret** for each of the following:

| Secret Name | Value | Example |
|-------------|-------|---------|
| `GMAIL_ADDRESS` | Your Gmail address | `you@gmail.com` |
| `GMAIL_APP_PASSWORD` | The 16-char app password from Step 3 | `abcd efgh ijkl mnop` |
| `RECIPIENT_EMAILS` | Comma-separated recipient emails | `boss@company.com, you@company.com` |

---

### Step 5 — Enable GitHub Actions

1. Go to your repository on GitHub
2. Click the **Actions** tab
3. If prompted, click **"I understand my workflows, enable them"**

---

### Step 6 — Test It Manually

Don't wait until Monday — run it now to verify everything works:

1. Go to the **Actions** tab in your repository
2. Click **"Weekly Executive News Digest"** in the left sidebar
3. Click **"Run workflow"** → **"Run workflow"**
4. Watch the logs — it should complete in under 2 minutes
5. Check your inbox!

---

## Updating Your Company List

Just edit `companies.csv` directly on GitHub:

1. Click `companies.csv` in your repository
2. Click the pencil ✏️ icon to edit
3. Add, remove, or change companies
4. Click **Commit changes**

The next Monday run will automatically use the updated list.

---

## Email Format

The weekly email includes:

**⚡ Top Priority This Week** — Up to 5 articles across all companies ranked highest by importance score. Articles are flagged as:
- 🔴 **CRITICAL** — Acquisitions, mergers, bankruptcies, major legal action
- 🟠 **HIGH** — Earnings results, executive changes, regulatory filings
- 🟡 **MEDIUM** — Partnerships, layoffs, general business news
- ⚪ **STANDARD** — General mentions

**Company Briefings** — One section per company with their top articles, source, and publish date. Each article links directly to the original story.

---

## How Articles Are Ranked

Articles are scored automatically based on keywords in the title and description:

| Score | Keywords |
|-------|----------|
| 10 | acquisition, merger, bankruptcy |
| 8–9 | earnings, IPO, resignation, fired, investigation |
| 6–7 | CEO change, lawsuit, SEC/FTC/DOJ, layoffs, quarterly results |
| 4–5 | partnerships, deals, expansion, growth, decline |

This ensures the most business-critical news always surfaces at the top, regardless of company.

---

## Troubleshooting

### Email not arriving on Monday
- Check the Actions tab — look for a failed run (red ✗)
- Click the run to see the error log
- Most common cause: wrong App Password or `GMAIL_ADDRESS` typo

### "Authentication failed" error in logs
- Your `GMAIL_APP_PASSWORD` is incorrect
- Make sure you're using an **App Password**, not your regular Gmail password
- Re-generate the App Password and update the GitHub secret

### "No articles found" for a company
- Try a simpler, shorter company name in `companies.csv`
- Some companies have low media coverage — this is expected
- You'll see "No news this week: [Company]" in the email footer

### Want to change the send time?
Edit `.github/workflows/weekly-digest.yml` and change the cron expression:
```yaml
- cron: "30 15 * * 1"   # 15:30 UTC = 7:30 AM PST (Monday)
```
Use [crontab.guru](https://crontab.guru) to build a new expression.

### Want to send on a different day?
Change the `1` (Monday) in the cron to: `0`=Sunday, `2`=Tuesday, etc.

---

## Files Reference

```
news-monitor/
├── companies.csv                    ← Edit this to manage your watch list
├── .github/
│   └── workflows/
│       └── weekly-digest.yml        ← GitHub Actions schedule & config
└── scripts/
    └── news_monitor.py              ← The main script (no editing needed)
```

---

## Privacy & Security

- **No data is stored** — the script runs, sends the email, and exits. Nothing is persisted.
- **Secrets are encrypted** — GitHub never exposes secret values in logs.
- **No API keys needed** — Google News RSS is public and free.
- **Open source** — you can inspect every line of `news_monitor.py`.

---

## Running Locally (Optional)

If you want to run the script on your own machine for testing:

```bash
# Set environment variables
export GMAIL_ADDRESS="you@gmail.com"
export GMAIL_APP_PASSWORD="your-app-password"
export RECIPIENT_EMAILS="you@gmail.com"

# Run the script
python scripts/news_monitor.py
```

If `GMAIL_ADDRESS` or `GMAIL_APP_PASSWORD` are not set, the script will save an `email_preview.html` file instead of sending — open it in your browser to preview the email layout.

---

*Built for reliability. Zero moving parts. No vendor lock-in.*
