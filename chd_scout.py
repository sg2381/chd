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
# We use os.environ.get to pull the secrets from GitHub
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER") 

SEARCH_TERMS = [
    "Congenital Heart Disease launch", 
    "Congenital Heart Disease partnership",
    "Congenital Heart Disease new foundation", 
    "pediatric cardiology startup funding",
    "CHD non-profit announced"
]

# Configure Google Gemini
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

DB_NAME = "chd_intelligence.db"

# --- PART 1: THE DATABASE ---
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

# --- PART 2: THE INTELLIGENCE (GOOGLE GEMINI) ---
def analyze_article(title, snippet):
    prompt = f"""
    I am an investor looking for NEW organizations, foundations, alliances, or startups in the Congenital Heart Disease space.
    
    Look at this news headline and snippet: 
    Title: "{title}"
    Snippet: "{snippet}"
    
    Task:
    1. Decide if this announces a NEW entity, a NEW program launch, or a NEW investment/partnership.
    2. Ignore general health advice, "awareness month" posts, or generic research papers.
    
    If it is relevant, write a 1-sentence summary of what the new entity does.
    If it is NOT relevant, reply with exactly "NO".
    """
    
    try:
        response = model.generate_content(prompt)
        answer = response.text.strip()
        
        if answer == "NO" or "NO." in answer:
            return None
        return answer
    except Exception as e:
        print(f"Gemini Error: {e}")
        return None

# --- PART 3: THE REPORTER (EMAIL) ---
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

# --- PART 4: THE MAIN LOOP ---
def run_scan():
    print(f"--- Starting Scan: {datetime.datetime.now()} ---")
    new_leads = []

    for term in SEARCH_TERMS:
        formatted_term = term.replace(" ", "%20")
        rss_url = f"https://news.google.com/rss/search?q={formatted_term}&hl=en-US&gl=US&ceid=US:en"
        feed = feedparser.parse(rss_url)
        
        print(f"Checking term: {term} (Found {len(feed.entries)} articles)")

        for entry in feed.entries:
            if not article_exists(entry.link):
                # We haven't seen this before. Ask Gemini.
                # Introduce a small delay so Google doesn't think we are spamming
                time.sleep(1) 
                
                summary = analyze_article(entry.title, entry.summary if 'summary' in entry else "")
                
                if summary:
                    print(f"[MATCH] {entry.title}")
                    new_leads.append({
                        "title": entry.title,
                        "link": entry.link,
                        "summary": summary
                    })
                else:
                    print(f"[SKIP] {entry.title}")
                
                save_article(entry.link, entry.title)
    
    if new_leads:
        send_email(new_leads)
    else:
        print("No new relevant organizations found this week.")

if __name__ == "__main__":
    init_db()
    run_scan()
