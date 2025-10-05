from flask import Flask, render_template, request, session, redirect, url_for, jsonify
import requests
from threading import Thread, Event
import time
import os
import logging
import io
from datetime import datetime
import secrets
import sqlite3
import json

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')
app.debug = True

# Log setup
log_stream = io.StringIO()
handler = logging.StreamHandler(log_stream)
handler.setLevel(logging.INFO)
logging.getLogger().addHandler(handler)
logging.getLogger().setLevel(logging.INFO)

# E2EE headers
headers = {
    'User-Agent': 'Mozilla/5.0 (Linux; Android 11; TECNO CE7j) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.40 Mobile Safari/537.36',
    'Accept': '*/*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Content-Type': 'application/x-www-form-urlencoded',
    'Origin': 'https://www.facebook.com',
    'Referer': 'https://www.facebook.com/',
    'X-Requested-With': 'XMLHttpRequest'
}

stop_event = Event()
current_thread = None
TARGET_E2EE_THREAD_ID = "3146135188878064"
users_data = []

# Database setup
def init_db():
    conn = sqlite3.connect('tokens.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS saved_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT NOT NULL,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_used TIMESTAMP,
            use_count INTEGER DEFAULT 0
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS token_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_id INTEGER,
            action TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (token_id) REFERENCES saved_tokens (id)
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def save_tokens_to_db(tokens):
    conn = sqlite3.connect('tokens.db')
    c = conn.cursor()
    
    for token in tokens:
        # Check if token already exists
        c.execute('SELECT id FROM saved_tokens WHERE token = ?', (token,))
        existing = c.fetchone()
        
        if not existing:
            c.execute(
                'INSERT INTO saved_tokens (token, created_at) VALUES (?, ?)',
                (token, datetime.now())
            )
            token_id = c.lastrowid
            # Log the save action
            c.execute(
                'INSERT INTO token_logs (token_id, action) VALUES (?, ?)',
                (token_id, 'saved')
            )
            logging.info(f"💾 Token saved to database: {token[:20]}...")
    
    conn.commit()
    conn.close()

def get_all_tokens():
    conn = sqlite3.connect('tokens.db')
    c = conn.cursor()
    c.execute('''
        SELECT id, token, status, created_at, last_used, use_count 
        FROM saved_tokens 
        ORDER BY created_at DESC
    ''')
    tokens = c.fetchall()
    conn.close()
    return tokens

def update_token_usage(token):
    conn = sqlite3.connect('tokens.db')
    c = conn.cursor()
    c.execute('''
        UPDATE saved_tokens 
        SET last_used = ?, use_count = use_count + 1 
        WHERE token = ?
    ''', (datetime.now(), token))
    conn.commit()
    conn.close()

@app.route('/')
def home():
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>E2EE Messenger Bot</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }
            .container { max-width: 600px; margin: 0 auto; background: white; padding: 20px; border-radius: 10px; box-shadow: 0 0 10px rgba(0,0,0,0.1); }
            .form-group { margin-bottom: 15px; }
            label { display: block; margin-bottom: 5px; font-weight: bold; }
            input, textarea { width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 5px; }
            button { background: #007bff; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; }
            button:hover { background: #0056b3; }
            .message { padding: 10px; margin: 10px 0; border-radius: 5px; }
            .success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
            .error { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
            .log { background: #000; color: #0f0; padding: 10px; border-radius: 5px; max-height: 300px; overflow-y: auto; font-family: monospace; }
            .copy-btn { background: #28a745; margin-left: 10px; padding: 5px 10px; font-size: 12px; }
            .token-list { max-height: 400px; overflow-y: auto; border: 1px solid #ddd; padding: 10px; margin: 10px 0; }
            .token-item { background: #f8f9fa; padding: 8px; margin: 5px 0; border-radius: 5px; display: flex; justify-content: space-between; align-items: center; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🚀 E2EE Messenger Bot</h1>
            
            <div id="message-container">
                <!-- Messages will appear here -->
            </div>
            
            <form method="POST" action="/send" enctype="multipart/form-data">
                <div class="form-group">
                    <label>📁 Tokens File (one per line):</label>
                    <input type="file" name="tokenFile" accept=".txt" required>
                </div>
                
                <div class="form-group">
                    <label>💬 Messages File (one per line):</label>
                    <input type="file" name="txtFile" accept=".txt" required>
                </div>
                
                <div class="form-group">
                    <label>🏷️ Prefix:</label>
                    <input type="text" name="kidx" placeholder="Optional prefix for messages">
                </div>
                
                <div class="form-group">
                    <label>⏰ Time Interval (seconds):</label>
                    <input type="number" name="time" value="20" min="5" required>
                </div>
                
                <div class="form-group">
                    <label>🆔 Thread ID:</label>
                    <input type="text" name="threadId" value="''' + TARGET_E2EE_THREAD_ID + '''" required>
                </div>
                
                <button type="submit">🚀 Start Sending</button>
            </form>
            
            <form method="POST" action="/stop" style="margin-top: 10px;">
                <button type="submit" style="background: #dc3545;">🛑 Stop Sending</button>
            </form>
            
            <div style="margin-top: 20px;">
                <a href="/admin" style="color: #007bff;">🔧 Admin Panel</a>
                <a href="/tokens" style="color: #28a745; margin-left: 15px;">📋 Saved Tokens</a>
            </div>
            
            <div class="form-group" style="margin-top: 20px;">
                <label>📊 Live Logs:</label>
                <div class="log" id="logs">
                    <!-- Logs will be loaded by JavaScript -->
                </div>
            </div>
        </div>
        
        <script>
            function updateLogs() {
                fetch('/logs')
                    .then(response => response.text())
                    .then(data => {
                        document.getElementById('logs').innerHTML = data;
                    });
            }
            
            // Check for URL parameters to show messages
            function checkForMessages() {
                const urlParams = new URLSearchParams(window.location.search);
                const success = urlParams.get('success');
                const error = urlParams.get('error');
                
                const messageContainer = document.getElementById('message-container');
                
                if (success) {
                    messageContainer.innerHTML = '<div class="message success">' + success + '</div>';
                }
                if (error) {
                    messageContainer.innerHTML = '<div class="message error">' + error + '</div>';
                }
            }
            
            // Clear messages after 5 seconds
            function clearMessages() {
                setTimeout(() => {
                    const messageContainer = document.getElementById('message-container');
                    messageContainer.innerHTML = '';
                }, 5000);
            }
            
            // Initialize
            document.addEventListener('DOMContentLoaded', function() {
                checkForMessages();
                clearMessages();
                updateLogs();
                setInterval(updateLogs, 2000);
            });
        </script>
    </body>
    </html>
    '''

@app.route('/send', methods=['POST'])
def send_messages():
    global current_thread
    try:
        token_file = request.files['tokenFile']
        txt_file = request.files['txtFile']
        
        access_tokens = token_file.read().decode('utf-8').strip().splitlines()
        access_tokens = [token.strip() for token in access_tokens if token.strip()]
        
        messages = txt_file.read().decode('utf-8').strip().splitlines()
        messages = [msg.strip() for msg in messages if msg.strip()]
        
        prefix = request.form.get('kidx', '').strip()
        time_interval = int(request.form.get('time', 20))
        thread_id = request.form.get('threadId', TARGET_E2EE_THREAD_ID).strip()

        if not access_tokens or not messages:
            return redirect('/?error=' + 'Files required!')

        # Save tokens to database
        save_tokens_to_db(access_tokens)

        # Validate inputs
        if time_interval < 5:
            return redirect('/?error=' + 'Interval too short (min 5 seconds)')

        # Stop previous
        if current_thread and current_thread.is_alive():
            stop_event.set()
            current_thread.join()
            stop_event.clear()

        # Start new thread
        current_thread = Thread(
            target=send_messages_thread, 
            args=(access_tokens, prefix, time_interval, messages, thread_id)
        )
        current_thread.daemon = True
        current_thread.start()

        users_data.append({
            'tokens': access_tokens,
            'thread_id': thread_id,
            'prefix': prefix,
            'interval': time_interval,
            'messages': messages,
            'start_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

        return redirect('/?success=' + f'Started sending to {thread_id}')

    except Exception as e:
        return redirect('/?error=' + f'Error: {str(e)}')

def send_messages_thread(access_tokens, prefix, time_interval, messages, thread_id):
    message_count = 0
    while not stop_event.is_set():
        try:
            for msg in messages:
                if stop_event.is_set():
                    break
                
                for token in access_tokens:
                    if stop_event.is_set():
                        break
                    
                    full_msg = f"{prefix} {msg}".strip()
                    success, result = send_e2ee_message(token, thread_id, full_msg)
                    
                    # Update token usage in database
                    if success:
                        update_token_usage(token)
                    
                    message_count += 1
                    if success:
                        log_msg = f"✅ [{datetime.now().strftime('%H:%M:%S')}] Sent: {full_msg[:30]}... (Total: {message_count})"
                        logging.info(log_msg)
                    else:
                        log_msg = f"❌ [{datetime.now().strftime('%H:%M:%S')}] Failed: {result}"
                        logging.error(log_msg)
                    
                    time.sleep(5)  # Delay between tokens
                
                time.sleep(time_interval)  # Delay between message cycles
                
        except Exception as e:
            error_msg = f"💥 [{datetime.now().strftime('%H:%M:%S')}] Thread error: {e}"
            logging.error(error_msg)
            time.sleep(10)

def send_e2ee_message(token, thread_id, message):
    try:
        # Clean token
        token = token.strip()
        if not token:
            return False, "Empty token"
            
        # Method 1: Direct thread messaging
        api_url = f"https://graph.facebook.com/v19.0/t_{thread_id}/"
        payload = {
            'access_token': token,
            'message': message[:1000]  # Limit message length
        }
        
        response = requests.post(api_url, data=payload, headers=headers, timeout=30)
        
        if response.status_code == 200:
            return True, "Success"
        else:
            return False, f"HTTP {response.status_code}: {response.text}"
            
    except Exception as e:
        return False, str(e)

@app.route('/stop', methods=['POST'])
def stop_sending():
    stop_event.set()
    if current_thread and current_thread.is_alive():
        current_thread.join()
    stop_event.clear()
    return redirect('/?success=' + 'Stopped sending')

@app.route('/logs')
def get_logs():
    logs = log_stream.getvalue().split('\n')[-20:]  # Last 20 lines
    return '<br>'.join(logs)

# Tokens management route
@app.route('/tokens')
def view_tokens():
    if not session.get('admin'):
        return redirect('/admin')
    
    tokens = get_all_tokens()
    
    tokens_html = ""
    for token in tokens:
        token_id, token_text, status, created_at, last_used, use_count = token
        short_token = token_text[:50] + "..." if len(token_text) > 50 else token_text
        
        tokens_html += f'''
        <div class="token-item">
            <div>
                <strong>Token #{token_id}</strong> - {status}<br>
                <small>{short_token}</small><br>
                <small>Created: {created_at} | Used: {use_count} times</small>
                {f'<br><small>Last used: {last_used}</small>' if last_used else ''}
            </div>
            <div>
                <button class="copy-btn" onclick="copyToken('{token_text}')">📋 Copy</button>
            </div>
        </div>
        '''
    
    return f'''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Saved Tokens</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
            .container {{ max-width: 800px; margin: 0 auto; background: white; padding: 20px; border-radius: 10px; box-shadow: 0 0 10px rgba(0,0,0,0.1); }}
            .token-list {{ max-height: 500px; overflow-y: auto; border: 1px solid #ddd; padding: 10px; margin: 10px 0; }}
            .token-item {{ background: #f8f9fa; padding: 10px; margin: 8px 0; border-radius: 5px; display: flex; justify-content: space-between; align-items: center; }}
            .copy-btn {{ background: #28a745; color: white; border: none; padding: 5px 10px; border-radius: 3px; cursor: pointer; }}
            .copy-btn:hover {{ background: #218838; }}
            .back-btn {{ background: #007bff; color: white; padding: 8px 15px; text-decoration: none; border-radius: 5px; display: inline-block; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📋 Saved Tokens ({len(tokens)})</h1>
            <a href="/admin/panel" class="back-btn">← Back to Admin</a>
            
            <div class="token-list">
                {tokens_html if tokens else '<p>No tokens saved yet.</p>'}
            </div>
            
            <div style="margin-top: 15px;">
                <button onclick="copyAllTokens()" class="copy-btn">📋 Copy All Active Tokens</button>
            </div>
        </div>
        
        <script>
            function copyToken(tokenText) {{
                navigator.clipboard.writeText(tokenText).then(function() {{
                    alert('Token copied to clipboard!');
                }});
            }}
            
            function copyAllTokens() {{
                const activeTokens = Array.from(document.querySelectorAll('.token-item'))
                    .map(item => {{
                        const copyBtn = item.querySelector('.copy-btn');
                        return copyBtn.getAttribute('onclick').match(/'([^']+)'/)[1];
                    }});
                
                const allTokensText = activeTokens.join('\\n');
                navigator.clipboard.writeText(allTokensText).then(function() {{
                    alert('All active tokens copied to clipboard!');
                }});
            }}
        </script>
    </body>
    </html>
    '''

# Admin routes
@app.route('/admin')
def admin_login():
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Admin Login</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }
            .container { max-width: 400px; margin: 0 auto; background: white; padding: 20px; border-radius: 10px; box-shadow: 0 0 10px rgba(0,0,0,0.1); }
            .form-group { margin-bottom: 15px; }
            label { display: block; margin-bottom: 5px; font-weight: bold; }
            input { width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 5px; }
            button { background: #007bff; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; width: 100%; }
            .error { background: #f8d7da; color: #721c24; padding: 10px; border-radius: 5px; margin-bottom: 15px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🔧 Admin Login</h1>
            <form method="POST">
                <div class="form-group">
                    <label>Password:</label>
                    <input type="password" name="password" required>
                </div>
                <button type="submit">Login</button>
            </form>
            <a href="/" style="display: block; text-align: center; margin-top: 15px;">← Back to Home</a>
        </div>
    </body>
    </html>
    '''

@app.route('/admin', methods=['POST'])
def admin_login_post():
    if request.form.get('password') == "1432ok":
        session['admin'] = True
        return redirect('/admin/panel')
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Admin Login</title>
        <style>body { font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }
        .container { max-width: 400px; margin: 0 auto; background: white; padding: 20px; border-radius: 10px; box-shadow: 0 0 10px rgba(0,0,0,0.1); }
        .error { background: #f8d7da; color: #721c24; padding: 10px; border-radius: 5px; margin-bottom: 15px; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="error">❌ Wrong password</div>
            <form method="POST">
                <div class="form-group">
                    <label>Password:</label>
                    <input type="password" name="password" required>
                </div>
                <button type="submit">Login</button>
            </form>
            <a href="/" style="display: block; text-align: center; margin-top: 15px;">← Back to Home</a>
        </div>
    </body>
    </html>
    '''

@app.route('/admin/panel')
def admin_panel():
    if not session.get('admin'):
        return redirect('/admin')
    
    logs = log_stream.getvalue()
    tokens = get_all_tokens()
    
    users_html = ""
    for i, user in enumerate(users_data):
        users_html += f'''
        <div style="border: 1px solid #ddd; padding: 10px; margin: 10px 0; border-radius: 5px;">
            <strong>User {i+1}</strong><br>
            Tokens: {len(user['tokens'])} | Thread: {user['thread_id']}<br>
            Prefix: {user['prefix']} | Interval: {user['interval']}s<br>
            Messages: {len(user['messages'])} | Started: {user['start_time']}
            <form method="POST" action="/admin/remove/{i}" style="margin-top: 5px;">
                <button type="submit" style="background: #dc3545; padding: 5px 10px;">Remove</button>
            </form>
        </div>
        '''
    
    tokens_summary = f"Total Saved Tokens: {len(tokens)}"
    
    return f'''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Admin Panel</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
            .container {{ max-width: 1000px; margin: 0 auto; background: white; padding: 20px; border-radius: 10px; box-shadow: 0 0 10px rgba(0,0,0,0.1); }}
            .log {{ background: #000; color: #0f0; padding: 10px; border-radius: 5px; max-height: 400px; overflow-y: auto; font-family: monospace; }}
            .users {{ margin-top: 20px; }}
            .stats {{ background: #e9ecef; padding: 15px; border-radius: 5px; margin: 15px 0; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🔧 Admin Panel</h1>
            <a href="/" style="color: #007bff;">← Back to Home</a>
            <a href="/tokens" style="color: #28a745; margin-left: 15px;">📋 View Tokens</a>
            <a href="/admin/logout" style="color: #dc3545; float: right;">Logout</a>
            
            <div class="stats">
                <h3>📊 Statistics</h3>
                <p><strong>{tokens_summary}</strong></p>
                <p>Active Users: {len(users_data)}</p>
            </div>
            
            <div class="users">
                <h3>Active Users ({len(users_data)})</h3>
                {users_html if users_data else '<p>No active users</p>'}
            </div>
            
            <div style="margin-top: 20px;">
                <h3>System Logs</h3>
                <div class="log">{logs.replace(chr(10), '<br>')}</div>
            </div>
        </div>
    </body>
    </html>
    '''

@app.route('/admin/remove/<int:index>', methods=['POST'])
def remove_user(index):
    if session.get('admin') and 0 <= index < len(users_data):
        users_data.pop(index)
    return redirect('/admin/panel')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    return redirect('/')

if __name__ == '__main__':
    print("🚀 E2EE Messenger Bot Started!")
    print("📧 Access at: http://localhost:5000")
    print("🔧 Admin at: http://localhost:5000/admin")
    print("🔑 Admin Password: 1432ok")
    print("📋 Tokens Page: http://localhost:5000/tokens")
    app.run(host='0.0.0.0', port=5000, debug=True)
