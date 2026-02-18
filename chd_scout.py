import sqlite3
import feedparser
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import google.generativeai as genai
import datetime
import time
import os

# --- CONFIGURATION ---
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER") 

# 1. The Broad Search (What we ask Google News for)
SEARCH_TERMS = [
    "Congenital Heart Disease launch", 
    "Congenital Heart Disease partnership",
    "Congenital Heart Disease new foundation", 
    "pediatric cardiology startup funding",
    "CHD non-profit announced"
]

# 2. The Strict Filter (We only ask AI if the title has one of these)
TRIGGER_WORDS = [
    "launch", "new", "start", "found", "creat", "unveil", "partner", 
    "allianc", "invest", "rais", "fund", "donat", "grant", "award"
]

genai.configure(api_key=GOOGLE_API_KEY)
# Using the Lite model because it is free and fast
model = genai.GenerativeModel('gemini-flash-latest') 

DB_NAME = "chd_intelligence.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS seen_articles 
                 (link TEXT PRIMARY KEY, title TEXT, date_added TEXT)''')
    conn.commit()
    conn.close()

def article_exists(link):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT 1 FROM seen_articles WHERE link=?", (link,))
    exists = c.fetchone() is not None
    conn.close()
    return exists

def save_article(link, title):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO seen_articles VALUES (?, ?, ?)", 
              (link, title, datetime.datetime.now()))
    conn.commit()
    conn.close()

def smart_filter(title):
    """
    Returns True if the title looks promising enough to waste an API credit on.
    """
    title_lower = title.lower()
    # Check if any trigger word is in the title
    if any(word in title_lower for word in TRIGGER_WORDS):
        return True
    return False

def analyze_article(title, snippet):
    prompt = f"""
    Title: "{title}"
    Snippet: "{snippet}"
    
    Does this article announce a NEW organization, foundation, alliance, or startup related to Heart Disease? 
    Ignore research papers, obituaries, and generic health advice.
    
    If YES, write a 1-sentence summary.
    If NO, reply "NO".
    """
    
    try:
        response = model.generate_content(prompt)
        answer = response.text.strip()
        if "NO" in answer:
            return None
        return answer
    except Exception as e:
        print(f"Gemini Error: {e}")
        return "QUOTA_HIT" # Signal to stop

def send_email(new_leads):
    if not new_leads:
        return

    subject = f"CHD Investment Scout: {len(new_leads)} New Opportunities Found"
    
    body_html = "<h2>Weekly CHD Intelligence Report</h2>"
    body_html += "<p>The following new organizations or programs were detected:</p><hr>"
    
    for lead in new_leads:
        body_html += f"<h3>{lead['title']}</h3>"
        body_html += f"<p><b>Analysis:</b> {lead['summary']}</p>"
        body_html += f"<p><a href='{lead['link']}'>Read Source Article</a></p><br>"

    msg = MIMEMultipart()
    msg['From'] = EMAIL_SENDER
    msg['To'] = EMAIL_RECEIVER
    msg['Subject'] = subject
    msg.attach(MIMEText(body_html, 'html'))

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmessage(msg)
        server.quit()
        print("Email report sent successfully!")
    except Exception as e:
        print(f"Failed to send email: {e}")

def run_scan():
    print(f"--- Starting Scan: {datetime.datetime.now()} ---")
    new_leads = []
    quota_exhausted = False

    for term in SEARCH_TERMS:
        if quota_exhausted:
            break

        formatted_term = term.replace(" ", "%20")
        rss_url = f"https://news.google.com/rss/search?q={formatted_term}&hl=en-US&gl=US&ceid=US:en"
        feed = feedparser.parse(rss_url)
        
        print(f"Checking term: {term} (Found {len(feed.entries)} articles)")

        for entry in feed.entries:
            if quota_exhausted:
                break

            if not article_exists(entry.link):
                # STEP 1: Smart Filter (Don't use AI yet)
                if smart_filter(entry.title):
                    print(f"Analyzing: {entry.title}")
                    
                    # STEP 2: Ask AI
                    time.sleep(10) # Slow down to 1 request every 10 seconds
                    summary = analyze_article(entry.title, entry.summary if 'summary' in entry else "")
                    
                    if summary == "QUOTA_HIT":
                        print("!!! QUOTA HIT. Stopping scan early and sending what we have.")
                        quota_exhausted = True
                        break
                    
                    if summary:
                        print(f"[MATCH] {entry.title}")
                        new_leads.append({
                            "title": entry.title,
                            "link": entry.link,
                            "summary": summary
                        })
                    else:
                        print(f"[NO MATCH] {entry.title}")
                else:
                    # We skip it without asking AI, saving quota
                    pass 
                
                # Save to DB so we don't check it again
                save_article(entry.link, entry.title)
    
    # --- TEST BLOCK (Delete later) ---
    # new_leads.append({"title": "Test Email", "link": "http://google.com", "summary": "Test Summary"})
    # ---------------------------------

    if new_leads:
        send_email(new_leads)
    else:
        print("No new relevant organizations found this week.")

if __name__ == "__main__":
    init_db()
    run_scan()
