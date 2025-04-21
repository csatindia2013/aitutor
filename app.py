from flask import Flask, render_template, request, session, send_from_directory
from PIL import Image
import pytesseract
import os
import sqlite3
from datetime import datetime
from uuid import uuid4
from openai import OpenAI
from googleapiclient.discovery import build
import cv2
import numpy as np

# ✅ Ensure Tesseract is available
pytesseract.pytesseract.tesseract_cmd = r"C:\\Program Files\\Tesseract-OCR\\tesseract.exe"

app = Flask(__name__)
app.secret_key = str(uuid4())
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

DB_PATH = "answers.db"
OPENAI_API_KEY = "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"
YOUTUBE_API_KEY = "AIzaSyAwQitt1pq0k-z6Qfw_JJHqYDvqG2bJGB8"

client = OpenAI(api_key=OPENAI_API_KEY)

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT UNIQUE,
                answer TEXT,
                youtube_embed TEXT,
                timestamp TEXT
            )
        """)

def auto_crop_math_region(image_path):
    image = cv2.imread(image_path)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    _, thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if w > 50 and h > 20:
            preview_path = image_path.replace(".png", "_preview.png")
            cropped_path = image_path.replace(".png", "_cropped.png")
            cropped = image[y:y + h, x:x + w]
            cv2.imwrite(preview_path, image.copy())
            cv2.imwrite(cropped_path, cropped)
            return cropped_path, preview_path
    return image_path, None

def ask_gpt(conversation):
    system_prompt = """
You are a helpful AI tutor. Do the following:
1. Identify the subject (Math, Physics, Chemistry).
2. Extract and clean math expressions.
3. Convert to LaTeX format.
4. Solve step-by-step with explanation.
Use $$ for math LaTeX blocks.
"""
    messages = [{"role": "system", "content": system_prompt}] + conversation
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0.5,
    )
    return response.choices[0].message.content

def get_youtube_video_embed(topic):
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    request = youtube.search().list(part="snippet", q=topic, maxResults=1, type="video")
    response = request.execute()
    if response['items']:
        video = response['items'][0]
        video_id = video['id']['videoId']
        title = video['snippet']['title']
        thumbnail = video['snippet']['thumbnails']['high']['url']
        return f"""
        <div style='background: #f3f3f3; padding: 16px; border-radius: 12px;'>
        <strong>🎥 Top Video:</strong><br>
        <img src='{thumbnail}' alt='{title}' style='width:100%; max-width:480px; border-radius:12px;' />
        <p><strong>{title}</strong></p>
        <a href='https://www.youtube.com/watch?v={video_id}' target='_blank'>▶️ Watch on YouTube</a></div>"""
    return "<div style='color:red'>❌ No video found.</div>"

def get_cached_answer(question):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT answer, youtube_embed FROM answers WHERE question = ?", (question,)).fetchone()
        return row if row else None

def save_answer_to_db(question, answer, youtube_embed):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT OR IGNORE INTO answers (question, answer, youtube_embed, timestamp) VALUES (?, ?, ?, ?)",
                     (question, answer, youtube_embed, datetime.now().isoformat()))

@app.route('/', methods=['GET', 'POST'])
def chat():
    if 'conversation' not in session:
        session['conversation'] = []
    thinking = False
    if request.method == 'POST':
        thinking = True
        user_input = ""
        file = request.files.get('image')
        if 'question' in request.form and request.form['question']:
            user_input = request.form['question']
        elif file and file.filename:
            filepath = os.path.join(UPLOAD_FOLDER, file.filename)
            file.save(filepath)
            cropped_path, preview_path = auto_crop_math_region(filepath)
            image = Image.open(cropped_path)
            user_input = pytesseract.image_to_string(image)
            if preview_path:
                preview_html = f"<strong>📸 Auto-detected Math Region:</strong><br><img src='/uploads/{os.path.basename(preview_path)}' style='width:100%; max-width:400px;' />"
                session['conversation'].append({"role": "assistant", "content": preview_html})
        if user_input:
            session['conversation'].append({"role": "user", "content": user_input})
            cached = get_cached_answer(user_input)
            if cached:
                gpt_reply, youtube_embed = cached
            else:
                gpt_reply = ask_gpt(session['conversation'])
                youtube_embed = get_youtube_video_embed(user_input)
                save_answer_to_db(user_input, gpt_reply, youtube_embed)
            session['conversation'].append({"role": "assistant", "content": gpt_reply})
            session['conversation'].append({"role": "assistant", "content": youtube_embed})
        thinking = False
    return render_template("chat.html", conversation=session['conversation'], thinking=thinking)

@app.route('/clear')
def clear_conversation():
    session.pop('conversation', None)
    return render_template("cleared.html")

@app.route('/uploads/<path:filename>')
def serve_uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route('/admin')
def admin_panel():
    with sqlite3.connect(DB_PATH) as conn:
        records = conn.execute("SELECT id, question, answer, youtube_embed, timestamp FROM answers ORDER BY timestamp DESC").fetchall()
    return render_template("admin.html", records=records)

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get("PORT", 10000))
    app.run(debug=True, host="0.0.0.0", port=port)
