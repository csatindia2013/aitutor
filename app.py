from flask import Flask, render_template, request, session
from PIL import Image
import pytesseract
import os
from openai import OpenAI
from uuid import uuid4
from googleapiclient.discovery import build

# ✅ Replace with secure environment variable use in production
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "your-openai-api-key")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "your-youtube-api-key")

client = OpenAI(api_key=OPENAI_API_KEY)
pytesseract.pytesseract.tesseract_cmd = r'/usr/bin/tesseract'  # Linux Render path

app = Flask(__name__)
app.secret_key = str(uuid4())

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def ask_gpt(conversation, custom_instruction=None):
    base_prompt = """
You are a helpful AI tutor. Do the following:
1. Identify the subject (Math, Physics, Chemistry, or Word Problem).
2. Extract and clean math expressions or questions.
3. Convert them to LaTeX format.
4. Solve step-by-step with explanation.
At the end, include: 📚 Subject: <subject>
Use $$ for LaTeX formatting.
"""
    if custom_instruction:
        base_prompt += f"\n\n{custom_instruction}"

    messages = [{"role": "system", "content": base_prompt}] + conversation
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0.5,
    )
    return response.choices[0].message.content

def get_youtube_video_embed(topic):
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    request = youtube.search().list(
        part="snippet",
        q=topic,
        maxResults=1,
        type="video"
    )
    response = request.execute()

    if response['items']:
        video = response['items'][0]
        video_id = video['id']['videoId']
        title = video['snippet']['title']
        thumbnail = video['snippet']['thumbnails']['high']['url']
        watch_url = f"https://www.youtube.com/watch?v={video_id}"
        return f"""
        <div style="margin-top: 15px; background: #f3f3f3; padding: 16px; border-radius: 12px;">
            <strong>🎥 Top Video:</strong><br>
            <div style="margin-top: 10px;">
                <img src="{thumbnail}" alt="{title}" style="width:100%; max-width:480px; border-radius:12px;" />
                <p style="font-weight: bold; margin: 10px 0;">{title}</p>
                <a href="{watch_url}" target="_blank" style="padding: 10px 18px; background: #007bff; color: white; text-decoration: none; border-radius: 8px;">▶️ Watch on YouTube</a>
            </div>
        </div>
        """
    else:
        return "<div style='color: red;'>❌ No video found for this topic.</div>"

@app.route('/', methods=['GET', 'POST'])
def chat():
    if 'conversation' not in session:
        session['conversation'] = []

    user_input = ""
    gpt_reply = ""
    youtube_embed = ""
    thinking = False

    if request.method == 'POST':
        thinking = True
        custom_instruction = None

        if 'question' in request.form and request.form['question']:
            user_input = request.form['question']
        elif 'image' in request.files:
            file = request.files['image']
            if file and file.filename:
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
                file.save(filepath)
                image = Image.open(filepath)
                user_input = pytesseract.image_to_string(image)
        elif 'retry' in request.form:
            user_input = request.form['retry']
            custom_instruction = "Explain this again in a fresh way."
        elif 'simplify' in request.form:
            user_input = request.form['simplify']
            custom_instruction = "Explain this in simpler words for a younger student."

        if user_input:
            session['conversation'].append({"role": "user", "content": user_input})
            gpt_reply = ask_gpt(session['conversation'], custom_instruction)
            session['conversation'].append({"role": "assistant", "content": gpt_reply})

            if not custom_instruction:  # Only search YouTube if it’s a new query
                youtube_embed = get_youtube_video_embed(user_input)
                session['conversation'].append({"role": "assistant", "content": youtube_embed})

        thinking = False

    return render_template("chat.html", conversation=session['conversation'], thinking=thinking)

# ✅ Required for Render: Bind to 0.0.0.0 and PORT env var
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
