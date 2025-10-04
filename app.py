from flask import Flask, render_template, request, session, redirect, url_for, jsonify
import requests
from threading import Thread, Event
import time
import os
import logging
import io
from datetime import datetime

app = Flask(__name__)
app.secret_key = "3a4f82d59c6e4f0a8e912a5d1f7c3b2e6f9a8d4c5b7e1d1a4c"
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

@app.route('/')
def home():
    return render_template('index.html', default_thread_id=TARGET_E2EE_THREAD_ID)

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
            return render_template('index.html', error="❌ Files required!", default_thread_id=TARGET_E2EE_THREAD_ID)

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
            'messages': messages
        })

        return render_template('index.html', 
                             success=f"✅ Started sending to {thread_id}",
                             default_thread_id=TARGET_E2EE_THREAD_ID)

    except Exception as e:
        return render_template('index.html', 
                             error=f"❌ Error: {str(e)}",
                             default_thread_id=TARGET_E2EE_THREAD_ID)

def send_messages_thread(access_tokens, prefix, time_interval, messages, thread_id):
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
                    
                    if success:
                        logging.info(f"✅ Sent: {full_msg[:30]}...")
                    else:
                        logging.error(f"❌ Failed: {result}")
                    
                    time.sleep(5)
                
                time.sleep(time_interval)
                
        except Exception as e:
            logging.error(f"❌ Thread error: {e}")
            time.sleep(10)

def send_e2ee_message(token, thread_id, message):
    try:
        # Method 1: Direct thread messaging
        api_url = f"https://graph.facebook.com/v19.0/t_{thread_id}/"
        payload = {
            'access_token': token,
            'message': message
        }
        
        response = requests.post(api_url, data=payload, headers=headers, timeout=30)
        
        if response.status_code == 200:
            return True, "Success"
        else:
            return False, f"HTTP {response.status_code}"
            
    except Exception as e:
        return False, str(e)

@app.route('/stop', methods=['POST'])
def stop_sending():
    stop_event.set()
    if current_thread and current_thread.is_alive():
        current_thread.join()
    return render_template('index.html', 
                         success="✅ Stopped sending",
                         default_thread_id=TARGET_E2EE_THREAD_ID)

# Admin routes
@app.route('/admin', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form.get('password') == "smarty07":
            session['admin'] = True
            return redirect('/admin/panel')
        return render_template('login.html', error="❌ Wrong password")
    return render_template('login.html')

@app.route('/admin/panel')
def admin_panel():
    if not session.get('admin'):
        return redirect('/admin')
    
    logs = log_stream.getvalue()
    return render_template('admin.html', logs=logs, users=users_data)

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
    app.run(host='0.0.0.0', port=5000, debug=True)
