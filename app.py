from flask import Flask, render_template, request, redirect, url_for, session
import os
import random
import string
import sqlite3
from flask_socketio import SocketIO, emit
import base64
from io import BytesIO
from PIL import Image

app = Flask(__name__)
socketio = SocketIO(app)

app.secret_key = os.urandom(24) 

db_folder = 'datas'
os.makedirs(db_folder, exist_ok=True)
db_path = os.path.join(db_folder, 'forum.db')

with sqlite3.connect(db_path) as conn:
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS topics (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        content TEXT NOT NULL,
                        public INTEGER NOT NULL,
                        password TEXT,
                        image_base64 TEXT)
                   ''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS comments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        topic_id TEXT NOT NULL,
                        author TEXT NOT NULL,
                        comment TEXT NOT NULL,
                        image_base64 TEXT,
                        FOREIGN KEY (topic_id) REFERENCES topics (id))
                   ''')

def image_to_base64(image_file):
    image = Image.open(image_file)
    buffered = BytesIO()
    image.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

@app.route('/')
def index():
    search_query = request.args.get('search', '').strip()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        if search_query:
            cursor.execute('SELECT id, title, public FROM topics WHERE title LIKE ?', (f'%{search_query}%',))
        else:
            cursor.execute('SELECT id, title, public FROM topics')
        all_topics = cursor.fetchall()
    return render_template('index.html', topics=all_topics, search_query=search_query)

@app.route('/create', methods=['GET', 'POST'])
def create_topic():
    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content']
        is_public = 'public' in request.form
        password = request.form['password'] if request.form['password'] else None

        image_base64 = None
        if 'image' in request.files:
            image_file = request.files['image']
            if image_file and image_file.filename:
                image_base64 = image_to_base64(image_file)

        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM topics WHERE title = ?', (title,))
            existing_topic = cursor.fetchone()

            if existing_topic:
                return render_template('create_topic.html', error="A topic with this title already exists.")

        topic_id = ''.join(random.choices(string.ascii_lowercase, k=8))
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT INTO topics (id, title, content, public, password, image_base64) VALUES (?, ?, ?, ?, ?, ?) ',
                           (topic_id, title, content, int(is_public), password, image_base64))
        return redirect(url_for('index'))

    return render_template('create_topic.html')

@app.route('/topic/<topic_id>', methods=['GET', 'POST'])
def view_topic(topic_id):
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT id, title, content, public, password FROM topics WHERE id = ?', (topic_id,))
        topic = cursor.fetchone()

        if not topic:
            return "Topic not found", 404

        if not topic['public']:
            if 'access_granted' not in session or session['access_granted'] != topic_id:
                if request.method == 'POST':
                    input_password = request.form.get('password')
                    if input_password != topic['password']:
                        return render_template('password_prompt.html', error="Invalid password")
                    else:
                        session['access_granted'] = topic_id  
                else:
                    return render_template('password_prompt.html')

        if request.method == 'POST' and 'comment' in request.form:
            author = request.form['author'] or 'Anon'
            comment = request.form['comment']

            comment_image_base64 = None
            if 'image' in request.files:
                image_file = request.files['image']
                if image_file and image_file.filename:
                    comment_image_base64 = image_to_base64(image_file)

            cursor.execute('INSERT INTO comments (topic_id, author, comment, image_base64) VALUES (?, ?, ?, ?)',
                           (topic_id, author, comment, comment_image_base64))

            return redirect(url_for('view_topic', topic_id=topic_id))

        cursor.execute('SELECT author, comment, image_base64 FROM comments WHERE topic_id = ?', (topic_id,))
        comments = cursor.fetchall()

    return render_template('topic.html', topic=dict(topic), comments=comments)

@socketio.on('new_comment')
def handle_new_comment(data):
    topic_id = data['topic_id']
    author = data['author'] or 'Anon'
    comment = data['comment']

    comment_image_base64 = data.get('image_base64')

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('INSERT INTO comments (topic_id, author, comment, image_base64) VALUES (?, ?, ?, ?)',
                       (topic_id, author, comment, comment_image_base64))

    emit('comment_added', {'author': author, 'comment': comment, 'image_base64': comment_image_base64}, broadcast=True)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=4502, debug=True)

