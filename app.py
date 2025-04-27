from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from openai import OpenAI
from googleapiclient.discovery import build
from textblob import TextBlob
import os
from fuzzywuzzy import fuzz
from werkzeug.utils import secure_filename  # Added for safe file uploads

app = Flask(__name__)
app.secret_key = 'supersecretkey'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chat_history.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'  # Image upload folder
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

# --- DB Model ---
class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(10))
    subject = db.Column(db.String(100), default='Auto')
    question = db.Column(db.Text)
    answer = db.Column(db.Text)
    video_url = db.Column(db.String(300))
    keywords = db.Column(db.String(300))
    views = db.Column(db.Integer, default=0)
    edit_count = db.Column(db.Integer, default=0)

with app.app_context():
    db.create_all()

# --- API Keys ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "sk-proj-your-key")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "AIza-your-key")
client = OpenAI(api_key=OPENAI_API_KEY)

# --- Helper Functions ---
def detect_subject(question):
    q = (question or "").lower()
    if any(w in q for w in ["solve", "equation", "integral", "geometry", "trigonometry", "math"]): return "📚 Math"
    if any(w in q for w in ["force", "energy", "motion", "velocity", "gravity", "friction"]): return "🔬 Physics"
    if any(w in q for w in ["atom", "molecule", "reaction", "acid", "base"]): return "🧪 Chemistry"
    if any(w in q for w in ["cell", "photosynthesis", "virus", "bacteria", "genetics"]): return "🧬 Biology"
    if any(w in q for w in ["python", "html", "algorithm", "programming", "code"]): return "💻 Computer Science"
    return "📚 General"

def clean_text(text):
    if not text:
        return ""
    blob = TextBlob(text)
    return str(blob.correct())

def ask_gpt(conversation):
    system_prompt = """
You are a helpful AI tutor. Provide step-by-step math or science explanations.
Use Markdown and LaTeX (\\( ... \\), \\[ ... \\]) formatting where appropriate.
Friendly tone. No $$ symbols.
"""
    messages = [{"role": "system", "content": system_prompt}] + conversation
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0.5
    )
    return response.choices[0].message.content

def get_youtube_video_embed(query):
    try:
        youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
        request = youtube.search().list(part="snippet", q=query, maxResults=1, type="video")
        response = request.execute()
        if response['items']:
            video_id = response['items'][0]['id']['videoId']
            return f"https://www.youtube.com/watch?v={video_id}"
    except Exception as e:
        print("YouTube API Error:", e)
    return ""

def search_database(question):
    all_questions = ChatMessage.query.all()
    question_clean = clean_text(question).lower()

    for q in all_questions:
        db_question = (q.question or "").lower()
        if fuzz.partial_ratio(question_clean, db_question) > 85:
            q.views = (q.views or 0) + 1
            db.session.commit()
            return q
    return None

# --- Serve Uploaded Images ---
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# --- Student Chat Route ---
@app.route('/', methods=['GET', 'POST'])
def chat():
    if 'conversation' not in session:
        session['conversation'] = []

    if request.method == 'POST':
        user_input = request.form.get('question')
        image_file = request.files.get('image')  # Check for uploaded image

        image_preview_html = ""

        if image_file and image_file.filename != '':
            filename = secure_filename(image_file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            image_file.save(filepath)
            image_url = url_for('uploaded_file', filename=filename)
            image_preview_html = f"<br><img src='{image_url}' style='max-width:250px;border-radius:10px;' />"
            user_input = (user_input or '') + " [Image uploaded]"

        if user_input:
            subject = detect_subject(user_input)

            session['conversation'].append({"role": "user", "content": user_input + image_preview_html, "subject": subject})

            # First check DB
            db_answer = search_database(user_input)
            if db_answer:
                gpt_reply = db_answer.answer
                youtube_link = db_answer.video_url
            else:
                gpt_reply = ask_gpt(session['conversation'])
                youtube_link = get_youtube_video_embed(user_input)
                db.session.add(ChatMessage(
                    role='assistant',
                    subject=subject,
                    question=user_input,
                    answer=gpt_reply,
                    video_url=youtube_link
                ))
                db.session.commit()

            session['conversation'].append({"role": "assistant", "content": gpt_reply, "subject": subject})

    recent_qna = ChatMessage.query.order_by(ChatMessage.id.desc()).limit(25).all()
    return render_template('chat.html', conversation=session.get('conversation', []), sessions=recent_qna)

# --- Clear Chat ---
@app.route('/clear', methods=['POST'])
def clear_chat():
    session.pop('conversation', None)
    return redirect(url_for('chat'))

# --- Admin Login ---
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username == 'admin' and password == 'password':
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid Credentials')
    return render_template('login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

# --- Admin Dashboard ---
@app.route('/admin')
def admin_dashboard():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    return render_template('admin.html')

# --- Admin: View Questions ---
@app.route('/admin/questions')
def view_questions():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    search_query = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)
    per_page = 10

    query = ChatMessage.query
    if search_query:
        query = query.filter(
            ChatMessage.question.ilike(f"%{search_query}%") |
            ChatMessage.answer.ilike(f"%{search_query}%")
        )

    pagination = query.order_by(ChatMessage.id.desc()).paginate(page=page, per_page=per_page)
    return render_template('questions.html', questions=pagination.items, page=page, total_pages=pagination.pages, search_query=search_query)

# --- Admin: Add Question ---
@app.route('/admin/add', methods=['GET', 'POST'])
def add_question():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    if request.method == 'POST':
        question = request.form['question']
        answer = request.form['answer']
        video_url = request.form['video_url']

        new_question = ChatMessage(
            role='assistant',
            subject='Manual',
            question=question,
            answer=answer,
            video_url=video_url
        )
        db.session.add(new_question)
        db.session.commit()
        return redirect(url_for('view_questions'))

    return render_template('add_question.html')

# --- Admin: Edit Question ---
@app.route('/admin/edit/<int:id>', methods=['GET', 'POST'])
def edit_question(id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    question = ChatMessage.query.get_or_404(id)

    if request.method == 'POST':
        question.question = request.form['question']
        question.answer = request.form['answer']
        question.video_url = request.form['video_url']
        question.edit_count = (question.edit_count or 0) + 1
        db.session.commit()

        if request.form.get('stay_on_page') == 'yes':
            return redirect(url_for('edit_question', id=id))
        else:
            return redirect(url_for('view_questions'))

    return render_template('edit_question.html', question=question)

# --- Admin: Delete Question ---
@app.route('/admin/delete/<int:id>')
def delete_question(id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    question = ChatMessage.query.get_or_404(id)
    db.session.delete(question)
    db.session.commit()
    return redirect(url_for('view_questions'))

# --- Run App ---
if __name__ == '__main__':
    app.run(debug=True)
