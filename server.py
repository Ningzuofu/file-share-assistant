from flask import Flask, render_template_string, send_from_directory, request, abort, redirect, url_for, make_response, session, jsonify, send_file, Response
from config import verify_password
import os
import tempfile
import threading
import signal
import sys
import zipfile
import io
import json
import uuid
import datetime
from urllib.parse import unquote
import secrets

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)  # 每次启动生成新的64位随机密钥
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Strict'
app.config['PERMANENT_SESSION_LIFETIME'] = 3600

@app.after_request
def add_no_cache_headers(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/logout')
def logout():
    client_ip = request.remote_addr
    log_operation('LOGOUT', '用户退出登录', client_ip)
    session.clear()
    response = redirect('/login')
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

ALLOWED_EXTENSIONS = None

config = {}
server_thread = None
server = None

class UploadRecord:
    def __init__(self, upload_id, filename, file_path, total_size, folder=''):
        self.upload_id = upload_id
        self.filename = filename
        self.file_path = file_path
        self.total_size = total_size
        self.folder = folder
        self.uploaded_size = 0
        self.status = 'pending'
        self.start_time = None
        self.end_time = None
        self.error_message = ''

    def to_dict(self):
        return {
            'upload_id': self.upload_id,
            'filename': self.filename,
            'file_path': self.file_path,
            'total_size': self.total_size,
            'uploaded_size': self.uploaded_size,
            'status': self.status,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'error_message': self.error_message,
            'folder': self.folder
        }


class UploadManager:
    def __init__(self):
        self._records = {}
        self._cancel_events = {}
        self._lock = threading.Lock()
        self._load_records()

    def create_record(self, filename, file_path, total_size, folder=''):
        upload_id = str(uuid.uuid4())[:8]
        record = UploadRecord(upload_id, filename, file_path, total_size, folder)
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        record.start_time = now
        record.status = 'uploading'
        with self._lock:
            self._records[upload_id] = record
            self._cancel_events[upload_id] = threading.Event()
            self._save_records_locked()
        return upload_id

    def get_record(self, upload_id):
        with self._lock:
            record = self._records.get(upload_id)
            return record.to_dict() if record else None

    def update_record(self, upload_id, **kwargs):
        with self._lock:
            record = self._records.get(upload_id)
            if record:
                for k, v in kwargs.items():
                    setattr(record, k, v)
                self._save_records_locked()

    def get_records(self, limit=50):
        with self._lock:
            records = [r.to_dict() for r in self._records.values()]
            records.sort(key=lambda x: x.get('start_time') or '', reverse=True)
            return records[:limit]

    def cancel_upload(self, upload_id):
        with self._lock:
            if upload_id in self._cancel_events:
                self._cancel_events[upload_id].set()
            record = self._records.get(upload_id)
            if record and record.status in ('pending', 'uploading'):
                record.status = 'cancelled'
                record.end_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                record.error_message = '用户取消上传'
                self._save_records_locked()
                return True
        return False

    def is_cancelled(self, upload_id):
        with self._lock:
            cancel_event = self._cancel_events.get(upload_id)
            if cancel_event:
                return cancel_event.is_set()
            return False

    def retry_prepare(self, upload_id):
        with self._lock:
            record = self._records.get(upload_id)
            if record and record.status in ('failed', 'cancelled'):
                record.status = 'pending'
                record.uploaded_size = 0
                record.error_message = ''
                record.start_time = None
                record.end_time = None
                self._cancel_events[upload_id] = threading.Event()
                self._save_records_locked()
                return record.to_dict()
        return None

    def mark_retry_start(self, upload_id):
        with self._lock:
            record = self._records.get(upload_id)
            if record:
                record.status = 'uploading'
                record.start_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                record.end_time = None
                self._save_records_locked()

    def _save_records_locked(self):
        records_dir = self._get_records_dir()
        os.makedirs(records_dir, exist_ok=True)
        records_file = os.path.join(records_dir, 'upload_records.json')
        data = {uid: r.to_dict() for uid, r in self._records.items()}
        with open(records_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _load_records(self):
        records_dir = self._get_records_dir()
        records_file = os.path.join(records_dir, 'upload_records.json')
        if os.path.exists(records_file):
            try:
                with open(records_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for uid, d in data.items():
                    record = UploadRecord(
                        upload_id=d['upload_id'],
                        filename=d['filename'],
                        file_path=d['file_path'],
                        total_size=d['total_size'],
                        folder=d.get('folder', '')
                    )
                    record.uploaded_size = d.get('uploaded_size', 0)
                    record.status = d.get('status', 'pending')
                    record.start_time = d.get('start_time')
                    record.end_time = d.get('end_time')
                    record.error_message = d.get('error_message', '')
                    if record.status in ('uploading', 'pending'):
                        record.status = 'failed'
                        record.error_message = '服务器重启，上传中断'
                        record.end_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    self._records[uid] = record
                    self._cancel_events[uid] = threading.Event()
            except Exception as e:
                print(f"Failed to load upload records: {e}")

    def _get_records_dir(self):
        if getattr(sys, 'frozen', False):
            exe_dir = os.path.dirname(sys.executable)
        else:
            exe_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(exe_dir, 'records')


upload_manager = UploadManager()


def log_operation(operation_type, message, ip_address='unknown', user='anonymous', status='success', details=''):
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
    else:
        exe_dir = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(exe_dir, 'log')
    os.makedirs(log_dir, exist_ok=True)
    
    now = datetime.datetime.now()
    today = now.strftime('%Y-%m-%d')
    log_file = os.path.join(log_dir, f'{today}.log')
    
    timestamp = now.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    log_entry = f"[{timestamp}] [{operation_type}] [{status}] IP={ip_address} User={user} - {message}"
    if details:
        log_entry += f" | Details: {details}"
    log_entry += "\n"
    
    try:
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry)
    except Exception as e:
        print(f"Failed to write log: {e}")

def allowed_file(filename):
    return True

def secure_filename(filename):
    import re
    filename = re.sub(r'[^\w\-. ]', '_', filename)
    return filename[:255]

def init_server(cfg):
    global config
    config = cfg
    
    upload_size = cfg.get('max_upload_size', 1024)
    upload_unit = cfg.get('max_upload_unit', 'MB')
    
    if upload_unit == 'KB':
        max_bytes = upload_size * 1024
    elif upload_unit == 'GB':
        max_bytes = upload_size * 1024 * 1024 * 1024
    else:
        max_bytes = upload_size * 1024 * 1024
    
    app.config['MAX_CONTENT_LENGTH'] = max_bytes

def run_server(port):
    global server
    from werkzeug.serving import make_server
    server = make_server('0.0.0.0', port, app, threaded=True)
    server.serve_forever()

def stop_server():
    global server
    if server:
        try:
            server.shutdown()
        except Exception:
            pass
        try:
            server.server_close()
        except Exception:
            pass
        server = None

@app.route('/login', methods=['GET', 'POST'])
def login():
    if config.get('password_hash', '') and session.get('authenticated'):
        return redirect('/')
    if not config.get('password_hash', ''):
        return redirect('/')

    error = ''
    client_ip = request.remote_addr
    if request.method == 'POST':
        password = request.form.get('password', '')
        if verify_password(password, config.get('password_hash', '')):
            session['authenticated'] = True
            log_operation('LOGIN', '用户登录成功', client_ip)
            return redirect('/')
        else:
            error = '密码错误，请重试'
            log_operation('LOGIN', '用户登录失败', client_ip)
    
    return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>文件共享 - 登录</title>
            <style>
                body { font-family: 'Microsoft YaHei', Arial, sans-serif; max-width: 400px; margin: 100px auto; padding: 20px; background: #FFF5F7; }
                .container { background: white; padding: 30px; border-radius: 15px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
                h2 { color: #FF69B4; text-align: center; margin-bottom: 20px; }
                .error { color: #e74c3c; margin-bottom: 15px; text-align: center; }
                .form-group { margin-bottom: 20px; }
                label { display: block; margin-bottom: 8px; color: #FF69B4; }
                input { width: 100%; padding: 12px; box-sizing: border-box; border: 2px solid #FFB6C1; border-radius: 8px; font-size: 14px; }
                button { width: 100%; padding: 12px; background: #FF69B4; color: white; border: none; border-radius: 8px; font-size: 14px; cursor: pointer; }
                button:hover { background: #FF1493; }
            </style>
        </head>
        <body>
            <div class="container">
                <h2>🔒 请输入访问密码</h2>
                {% if error %}<div class="error">❌ {{ error }}</div>{% endif %}
                <form method="post">
                    <div class="form-group">
                        <label>密码:</label>
                        <input type="password" name="password" required placeholder="请输入密码">
                    </div>
                    <button type="submit">登录</button>
                </form>
            </div>
        </body>
        </html>
    ''', error=error)

@app.route('/')
def index():
    if config.get('password_hash', '') and not session.get('authenticated'):
        return redirect('/login')
    
    error = request.args.get('error', '')
    success = request.args.get('success', '')
    subpath = request.args.get('subpath', '')
    
    base_folder = config.get('folder', os.path.expanduser('~'))
    if not os.path.isdir(base_folder):
        return render_template_string('''
            <!DOCTYPE html>
            <html>
            <head>
                <title>错误</title>
                <style>
                    body { font-family: 'Microsoft YaHei', Arial, sans-serif; text-align: center; padding-top: 100px; background: #FFF5F7; }
                    .error { color: #e74c3c; font-size: 18px; }
                </style>
            </head>
            <body>
                <div class="error">❌ 错误: 文件夹 "{{ folder }}" 不存在</div>
            </body>
            </html>
        ''', folder=base_folder), 404
    
    if subpath:
        subpath = unquote(subpath)
        folder = os.path.normpath(os.path.join(base_folder, subpath))
        if not folder.startswith(os.path.normpath(base_folder)):
            return render_template_string('''
                <!DOCTYPE html>
                <html>
                <head>
                    <title>访问被拒绝</title>
                    <style>
                        body { font-family: 'Microsoft YaHei', Arial, sans-serif; text-align: center; padding-top: 100px; background: #FFF5F7; }
                        .error { color: #e74c3c; font-size: 18px; }
                    </style>
                </head>
                <body>
                    <div class="error">❌ 访问被拒绝：非法路径访问</div>
                </body>
                </html>
            '''), 403
    else:
        folder = base_folder
    
    if not os.path.isdir(folder):
        return render_template_string('''
            <!DOCTYPE html>
            <html>
            <head>
                <title>错误</title>
                <style>
                    body { font-family: 'Microsoft YaHei', Arial, sans-serif; text-align: center; padding-top: 100px; background: #FFF5F7; }
                    .error { color: #e74c3c; font-size: 18px; }
                </style>
            </head>
            <body>
                <div class="error">❌ 错误: 目录 "{{ folder }}" 不存在</div>
            </body>
            </html>
        ''', folder=folder), 404
    
    try:
        items = []
        for item in os.listdir(folder):
            item_path = os.path.join(folder, item)
            if os.path.isdir(item_path):
                items.append({
                    'name': item,
                    'type': 'folder',
                    'size': '-',
                    'mtime': os.path.getmtime(item_path)
                })
            else:
                items.append({
                    'name': item,
                    'type': 'file',
                    'size': format_size(os.path.getsize(item_path)),
                    'mtime': os.path.getmtime(item_path)
                })
        
        items.sort(key=lambda x: (x['type'], x['name'].lower()))
        
        if subpath:
            parent_path = os.path.dirname(subpath)
            if parent_path == '.' or parent_path == '/' or parent_path == '\\':
                parent_path = ''
        else:
            parent_path = ''
        
        return render_template_string('''
            <!DOCTYPE html>
            <html>
            <head>
                <title>文件共享 - {{ folder }}</title>
                <style>
                    body { font-family: 'Microsoft YaHei', 'PingFang SC', Arial, sans-serif; max-width: 960px; margin: 30px auto; background: #FFF5F7; color: #5D4E5A; padding: 0 16px; }
                    h1 { color: #FF8FAB; text-align: center; margin-bottom: 20px; font-size: 24px; letter-spacing: 1px; }
                    .path-bar { background: white; padding: 14px 20px; border-radius: 12px; margin-bottom: 14px; box-shadow: 0 2px 8px rgba(255, 143, 171, 0.1); border: 1px solid #F5E4E8; }
                    .path-bar span { color: #A8949E; }
                    .path-bar strong { color: #E8607D; }
                    .action-bar { background: white; padding: 18px 20px; border-radius: 12px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(255, 143, 171, 0.1); border: 1px solid #F5E4E8; display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }
                    .nav-btn { background: #F0F4FF; color: #7EC8E3; padding: 10px 20px; border: none; border-radius: 10px; cursor: pointer; font-size: 14px; text-decoration: none; display: inline-flex; align-items: center; gap: 6px; transition: all 0.2s ease; }
                    .nav-btn:hover { background: #DCE8FA; transform: translateY(-1px); box-shadow: 0 3px 8px rgba(126, 200, 227, 0.2); }
                    .upload-btn { background: linear-gradient(135deg, #FF8FAB, #FFB6C8); color: white; padding: 10px 22px; border: none; border-radius: 10px; cursor: pointer; font-size: 14px; display: inline-flex; align-items: center; gap: 6px; transition: all 0.2s ease; }
                    .upload-btn:hover { background: linear-gradient(135deg, #E8607D, #FF8FAB); transform: translateY(-1px); box-shadow: 0 3px 10px rgba(255, 143, 171, 0.3); }
                    .download-selected-btn { background: linear-gradient(135deg, #7BC8A4, #A8E6CF); color: white; padding: 10px 22px; border: none; border-radius: 10px; cursor: pointer; font-size: 14px; display: inline-flex; align-items: center; gap: 6px; transition: all 0.2s ease; }
                    .download-selected-btn:hover { background: linear-gradient(135deg, #6AB894, #7BC8A4); transform: translateY(-1px); box-shadow: 0 3px 10px rgba(123, 200, 164, 0.3); }
                    .download-selected-btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; box-shadow: none; }
                    .divider { width: 1px; height: 24px; background: #F0E4E8; }
                    #file-input { display: none; }
                    .hint-text { color: #C8B4BE; font-size: 13px; }
                    .error { color: #E8847D; margin-top: 8px; }
                    .success { color: #7BC8A4; margin-top: 8px; }
                    table { width: 100%; border-collapse: separate; border-spacing: 0; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 8px rgba(255, 143, 171, 0.1); border: 1px solid #F5E4E8; }
                    th, td { padding: 12px 15px; text-align: left; }
                    th { background: linear-gradient(135deg, #FFB6C8, #FFD6E0); color: white; font-weight: 600; font-size: 14px; }
                    th:first-child { border-top-left-radius: 12px; }
                    th:last-child { border-top-right-radius: 12px; }
                    tr:not(:last-child) td { border-bottom: 1px solid #F8EEF0; }
                    tr:hover td { background-color: #FFF8FA; }
                    a { text-decoration: none; color: #7EC8E3; }
                    a:hover { text-decoration: underline; color: #5AB0D0; }
                    .folder { color: #F7C873; font-weight: 500; }
                    .folder:hover { color: #E7B863; }
                    .file { color: #7EC8E3; }
                    .file:hover { color: #5AB0D0; }
                    .size-col { width: 120px; color: #A8949E; font-size: 13px; }
                    .time-col { width: 180px; color: #A8949E; font-size: 13px; }
                    .action-col { width: 140px; }
                    .checkbox-col { width: 40px; }
                    .action-btn { display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px; border-radius: 10px; text-decoration: none; font-size: 16px; transition: all 0.2s ease; margin-right: 4px; border: 0; outline: 0; box-shadow: none; background-clip: padding-box; -webkit-appearance: none; -moz-appearance: none; appearance: none; }
                    .action-btn:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.12); }
                    .download-btn { background: linear-gradient(135deg, #7EC8E3, #A8D8EA); color: white; }
                    .download-btn:hover { background: linear-gradient(135deg, #6DB8D3, #7EC8E3); box-shadow: 0 4px 12px rgba(126, 200, 227, 0.4); }
                    .action-btn:active { transform: translateY(0); }
                    input[type="checkbox"] { width: 16px; height: 16px; border-radius: 5px; border: 2px solid #FFD6E0; background: white; cursor: pointer; accent-color: #FF8FAB; transition: all 0.2s ease; }
                    input[type="checkbox"]:hover { border-color: #FF8FAB; }
                </style>
            </head>
            <body>
                <h1>📁 文件共享</h1>
                <div class="path-bar">
                    <strong>当前目录:</strong> <span>{{ folder }}</span>
                </div>
                <div class="action-bar">
                    <a href="/" class="nav-btn">📂 返回根目录</a>
                    {% if subpath %}
                    <a href="/?subpath={{ parent_path | urlencode if parent_path else '' }}" class="nav-btn">⬆️ 返回上级</a>
                    {% endif %}
                    <div class="divider"></div>
                    <form id="upload-form" action="/upload?subpath={{ subpath | urlencode }}" method="post" enctype="multipart/form-data">
                        <label for="file-input" class="upload-btn">📤 上传文件</label>
                        <input type="file" id="file-input" name="files" multiple>
                    </form>
                    <div id="upload-progress" style="display: none; margin: 10px 0; padding: 15px; background: #FFF8F0; border-radius: 10px; border: 1px solid #FFE4CC;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                            <div id="progress-status" style="font-size: 14px; color: #666;">📤 准备上传...</div>
                            <button id="cancel-upload-btn" style="display: none; padding: 6px 16px; background: #e74c3c; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 13px;">⏹ 取消上传</button>
                        </div>
                        <div style="width: 100%; height: 20px; background: #FFF0F0; border-radius: 10px; overflow: hidden; box-shadow: inset 0 2px 4px rgba(0,0,0,0.1);">
                            <div id="progress-bar" style="height: 100%; background: linear-gradient(90deg, #FF6B9D, #FF8E53); width: 0%; transition: width 0.3s ease; border-radius: 10px;"></div>
                        </div>
                        <div id="progress-text" style="font-size: 12px; color: #999; margin-top: 6px;">0%</div>
                        <div id="file-progress-list" style="margin-top: 10px; max-height: 200px; overflow-y: auto;"></div>
                    </div>
                    <button id="show-history-btn" class="nav-btn" style="background: #E8F5E9; color: #388E3C;" onclick="toggleUploadHistory()" type="button">📋 上传记录</button>
                    <form id="download-form" action="/download/selected?subpath={{ subpath | urlencode }}" method="post">
                        <button type="submit" class="download-selected-btn" id="download-selected-btn" disabled>📦 下载选中</button>
                    </form>
                    <div class="divider"></div>
                    <a href="/logout" class="nav-btn" style="background: #FFF3E0; color: #E65100;">🚪 退出登录</a>
                    <span class="hint-text">💡 支持多文件上传，单个文件最大{{ config.get('max_upload_size', 1024) }}{{ config.get('max_upload_unit', 'MB') }}</span>
                    {% if error %}<div class="error" style="margin-left: auto;">❌ {{ error }}</div>{% endif %}
                    {% if success %}<div class="success" style="margin-left: auto;">✅ {{ success }}</div>{% endif %}
                </div>
                <table>
                    <tr>
                        <th class="checkbox-col"><input type="checkbox" id="select-all" onchange="toggleSelectAll()"></th>
                        <th>名称</th>
                        <th class="size-col">大小</th>
                        <th class="time-col">修改时间</th>
                        <th class="action-col">操作</th>
                    </tr>
                    {% for item in items %}
                    <tr>
                        <td><input type="checkbox" class="file-checkbox" name="files" value="{{ item.name }}"></td>
                        <td>
                            {% if item.type == 'folder' %}
                            <a href="?subpath={{ (subpath + '/' + item.name) if subpath else item.name | urlencode }}" class="folder">📂 {{ item.name }}</a>
                            {% else %}
                            <a href="/download/{{ item.name }}?subpath={{ subpath | urlencode }}" class="file">📄 {{ item.name }}</a>
                            {% endif %}
                        </td>
                        <td>{{ item.size }}</td>
                        <td>{{ item.mtime | format_time }}</td>
                        <td>
                            {% if item.type == 'file' %}
                            <a href="/download/{{ item.name }}?subpath={{ subpath | urlencode }}" title="下载文件" class="action-btn download-btn">📥</a>
                            {% else %}
                            <a href="/download/folder/{{ item.name }}?subpath={{ subpath | urlencode }}" title="下载文件夹" class="action-btn download-btn">📥</a>
                            {% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                </table>
                <div id="upload-history" style="display: none; margin-top: 20px; background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                    <div style="background: #E8F5E9; padding: 12px 15px; display: flex; justify-content: space-between; align-items: center;">
                        <span style="color: #388E3C; font-weight: bold; font-size: 15px;">📋 上传记录</span>
                        <button onclick="toggleUploadHistory()" style="background: none; border: none; color: #999; cursor: pointer; font-size: 18px;">✕</button>
                    </div>
                    <div id="history-list" style="padding: 10px; max-height: 400px; overflow-y: auto;">
                        <div style="text-align: center; padding: 30px; color: #ccc;">加载中...</div>
                    </div>
                </div>
                <script>
                    var currentXHR = null;
                    var historyVisible = false;

                    document.getElementById('file-input').addEventListener('change', function(e) {
                        var files = e.target.files;
                        if (files.length === 0) return;

                        var form = document.getElementById('upload-form');
                        var progressDiv = document.getElementById('upload-progress');
                        var progressBar = document.getElementById('progress-bar');
                        var progressText = document.getElementById('progress-text');
                        var progressStatus = document.getElementById('progress-status');
                        var cancelBtn = document.getElementById('cancel-upload-btn');
                        var fileProgressList = document.getElementById('file-progress-list');

                        fileProgressList.innerHTML = '';
                        for (var i = 0; i < files.length; i++) {
                            var item = document.createElement('div');
                            item.style.cssText = 'display:flex;align-items:center;padding:4px 0;font-size:13px;';
                            item.innerHTML = '<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + files[i].name + '</span>' +
                                '<span id="fs-' + i + '" style="color:#999;font-size:12px;width:80px;text-align:right;">等待中...</span>';
                            fileProgressList.appendChild(item);
                        }

                        progressDiv.style.display = 'block';
                        progressBar.style.width = '0%';
                        progressBar.style.background = 'linear-gradient(90deg, #FF6B9D, #FF8E53)';
                        progressText.textContent = '0% - 共 ' + files.length + ' 个文件';
                        progressStatus.innerHTML = '📤 正在上传...';
                        progressStatus.style.color = '#666';
                        cancelBtn.style.display = 'inline-block';

                        var xhr = new XMLHttpRequest();
                        currentXHR = xhr;
                        var formData = new FormData(form);

                        xhr.upload.addEventListener('progress', function(ev) {
                            if (ev.lengthComputable) {
                                var pct = Math.round((ev.loaded / ev.total) * 100);
                                progressBar.style.width = pct + '%';
                                progressText.textContent = pct + '% - ' + formatSize(ev.loaded) + ' / ' + formatSize(ev.total);
                            } else {
                                progressStatus.innerHTML = '📤 正在上传... (无法估算进度)';
                            }
                        });

                        xhr.addEventListener('load', function() {
                            cancelBtn.style.display = 'none';
                            var respText = xhr.responseText;
                            if (!respText) {
                                progressStatus.innerHTML = '❌ 上传失败：服务器无响应';
                                progressStatus.style.color = '#e74c3c';
                                return;
                            }
                            try {
                                var resp = JSON.parse(respText);
                                if (resp && resp.results) {
                                    resp.results.forEach(function(r, idx) {
                                        var el = document.getElementById('fs-' + idx);
                                        if (el) {
                                            if (r.success) {
                                                el.textContent = '✅ 成功';
                                                el.style.color = '#4CAF50';
                                            } else {
                                                el.textContent = '❌ 失败';
                                                el.style.color = '#e74c3c';
                                                el.title = r.error || '未知错误';
                                            }
                                        }
                                    });
                                    var failCount = resp.results.filter(function(r) { return !r.success; }).length;
                                    if (failCount === 0) {
                                        progressBar.style.width = '100%';
                                        progressText.textContent = '100% - 全部完成';
                                        progressStatus.innerHTML = '✅ 全部上传成功！';
                                        progressStatus.style.color = '#4CAF50';
                                    } else {
                                        var okCount = resp.results.length - failCount;
                                        progressStatus.innerHTML = '⚠️ ' + okCount + ' 个成功，' + failCount + ' 个失败';
                                        progressStatus.style.color = '#e67e22';
                                        progressBar.style.background = 'linear-gradient(90deg, #FFB347, #FF8E53)';
                                    }
                                } else {
                                    progressStatus.innerHTML = '❌ 上传失败：返回数据异常';
                                    progressStatus.style.color = '#e74c3c';
                                }
                                setTimeout(function() {
                                    location.href = location.pathname + location.search;
                                }, 2000);
                            } catch (err) {
                                progressStatus.innerHTML = '❌ 上传失败：响应解析错误';
                                progressStatus.style.color = '#e74c3c';
                                console.error('Parse error:', err, 'Response:', respText);
                            }
                        });

                        xhr.addEventListener('error', function() {
                            cancelBtn.style.display = 'none';
                            progressStatus.innerHTML = '❌ 上传失败，请检查网络连接后重试';
                            progressStatus.style.color = '#e74c3c';
                            progressBar.style.background = 'linear-gradient(90deg, #e74c3c, #c0392b)';
                        });

                        xhr.addEventListener('abort', function() {
                            cancelBtn.style.display = 'none';
                            progressStatus.innerHTML = '⏹️ 上传已取消';
                            progressStatus.style.color = '#999';
                            for (var i = 0; i < files.length; i++) {
                                var el = document.getElementById('fs-' + i);
                                if (el && el.textContent === '等待中...') {
                                    el.textContent = '⏹ 已取消';
                                    el.style.color = '#999';
                                }
                            }
                        });

                        xhr.open('POST', form.action);
                        xhr.send(formData);
                        e.target.value = '';
                    });

                    document.getElementById('cancel-upload-btn').addEventListener('click', function() {
                        if (currentXHR) {
                            currentXHR.abort();
                        }
                    });

                    function toggleSelectAll() {
                        var cbs = document.querySelectorAll('.file-checkbox');
                        var sel = document.getElementById('select-all');
                        cbs.forEach(function(cb) { cb.checked = sel.checked; });
                        updateDownloadBtn();
                    }

                    document.querySelectorAll('.file-checkbox').forEach(function(cb) {
                        cb.addEventListener('change', updateDownloadBtn);
                    });

                    function updateDownloadBtn() {
                        var cbs = document.querySelectorAll('.file-checkbox');
                        var n = Array.from(cbs).filter(function(cb) { return cb.checked; }).length;
                        var btn = document.getElementById('download-selected-btn');
                        btn.disabled = n === 0;
                        btn.innerHTML = n > 0 ? '📦 下载选中 (' + n + ')' : '📦 下载选中';
                    }

                    document.getElementById('download-form').addEventListener('submit', function(e) {
                        e.preventDefault();
                        var files = Array.from(document.querySelectorAll('.file-checkbox:checked')).map(function(cb) { return cb.value; });
                        var fd = new FormData();
                        files.forEach(function(f) { fd.append('files[]', f); });
                        var xhr = new XMLHttpRequest();
                        xhr.open('POST', this.action);
                        xhr.responseType = 'blob';
                        xhr.onload = function() {
                            if (xhr.status === 200) {
                                var a = document.createElement('a');
                                a.href = URL.createObjectURL(xhr.response);
                                a.download = 'selected_files.zip';
                                document.body.appendChild(a);
                                a.click();
                                document.body.removeChild(a);
                                URL.revokeObjectURL(a.href);
                            }
                        };
                        xhr.send(fd);
                    });

                    function toggleUploadHistory() {
                        historyVisible = !historyVisible;
                        document.getElementById('upload-history').style.display = historyVisible ? 'block' : 'none';
                        if (historyVisible) loadUploadHistory();
                    }

                    function loadUploadHistory() {
                        var list = document.getElementById('history-list');
                        list.innerHTML = '<div style="text-align:center;padding:20px;color:#ccc;">🔄 加载中...</div>';
                        var xhr = new XMLHttpRequest();
                        xhr.open('GET', '/api/upload/records', true);
                        xhr.onload = function() {
                            if (xhr.status === 200) {
                                renderHistory(JSON.parse(xhr.responseText).records);
                            } else {
                                list.innerHTML = '<div style="text-align:center;padding:20px;color:#e74c3c;">❌ 加载失败</div>';
                            }
                        };
                        xhr.onerror = function() {
                            list.innerHTML = '<div style="text-align:center;padding:20px;color:#e74c3c;">❌ 加载失败</div>';
                        };
                        xhr.send();
                    }

                    function renderHistory(records) {
                        var list = document.getElementById('history-list');
                        if (!records || records.length === 0) {
                            list.innerHTML = '<div style="text-align:center;padding:30px;color:#ccc;">暂无上传记录</div>';
                            return;
                        }
                        var html = '';
                        records.forEach(function(r) {
                            var icon = '', color = '', actions = '';
                            if (r.status === 'completed') { icon = '✅'; color = '#4CAF50'; }
                            else if (r.status === 'failed') { icon = '❌'; color = '#e74c3c'; actions = '<button onclick="retryUpload(\\'' + r.upload_id + '\\')" style="padding:4px 12px;background:#FF9800;color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:12px;">🔄 重传</button>'; }
                            else if (r.status === 'cancelled') { icon = '⏹️'; color = '#999'; actions = '<button onclick="retryUpload(\\'' + r.upload_id + '\\')" style="padding:4px 12px;background:#FF9800;color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:12px;">🔄 重传</button>'; }
                            else { icon = '📤'; color = '#2196F3'; }
                            var label = r.status === 'completed' ? '成功' : r.status === 'failed' ? '失败' : r.status === 'cancelled' ? '已取消' : '上传中';
                            html += '<div style="display:flex;align-items:center;padding:8px 10px;border-bottom:1px solid #f0f0f0;">' +
                                '<span style="margin-right:8px;font-size:16px;">' + icon + '</span>' +
                                '<div style="flex:1;min-width:0;">' +
                                '<div style="font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + r.filename + '">' + r.filename + '</div>' +
                                '<div style="font-size:11px;color:#999;margin-top:2px;">' + (r.start_time || '') +
                                (r.error_message ? ' <span style="color:#e74c3c;">' + r.error_message + '</span>' : '') +
                                '</div></div>' +
                                '<span style="font-size:12px;color:' + color + ';margin:0 10px;white-space:nowrap;">' + label + '</span>' +
                                actions + '</div>';
                        });
                        list.innerHTML = html;
                    }

                    function retryUpload(uploadId) {
                        var xhr = new XMLHttpRequest();
                        xhr.open('POST', '/api/upload/retry/' + uploadId, true);
                        xhr.onload = function() {
                            if (xhr.status === 200) {
                                var resp = JSON.parse(xhr.responseText);
                                if (resp.success) {
                                    document.getElementById('file-input').click();
                                    document.getElementById('file-input').onchange = function(ev) {
                                        if (ev.target.files.length === 0) return;
                                        var form = document.getElementById('upload-form');
                                        var fd = new FormData(form);
                                        var x2 = new XMLHttpRequest();
                                        currentXHR = x2;
                                        var pd = document.getElementById('upload-progress');
                                        var pb = document.getElementById('progress-bar');
                                        var pt = document.getElementById('progress-text');
                                        var ps = document.getElementById('progress-status');
                                        var cb = document.getElementById('cancel-upload-btn');
                                        pd.style.display = 'block';
                                        pb.style.width = '0%';
                                        pb.style.background = 'linear-gradient(90deg, #FF6B9D, #FF8E53)';
                                        pt.textContent = '0%';
                                        ps.innerHTML = '📤 正在重传...';
                                        ps.style.color = '#666';
                                        cb.style.display = 'inline-block';
                                        x2.upload.addEventListener('progress', function(e) {
                                            if (e.lengthComputable) {
                                                var p = Math.round((e.loaded / e.total) * 100);
                                                pb.style.width = p + '%';
                                                pt.textContent = p + '% - ' + formatSize(e.loaded) + ' / ' + formatSize(e.total);
                                            }
                                        });
                                        x2.addEventListener('load', function() {
                                            cb.style.display = 'none';
                                            try {
                                                var r = JSON.parse(x2.responseText);
                                                ps.innerHTML = r.success ? '✅ 重传成功！' : '❌ 重传失败';
                                                ps.style.color = r.success ? '#4CAF50' : '#e74c3c';
                                                if (r.success) pb.style.width = '100%';
                                            } catch (err) {
                                                ps.innerHTML = '❌ 重传失败';
                                                ps.style.color = '#e74c3c';
                                            }
                                            setTimeout(function() { location.href = location.pathname + location.search; }, 2000);
                                        });
                                        x2.addEventListener('error', function() {
                                            cb.style.display = 'none';
                                            ps.innerHTML = '❌ 重传失败';
                                            ps.style.color = '#e74c3c';
                                        });
                                        x2.addEventListener('abort', function() {
                                            cb.style.display = 'none';
                                            ps.innerHTML = '⏹️ 重传已取消';
                                            ps.style.color = '#999';
                                        });
                                        x2.open('POST', form.action);
                                        x2.send(fd);
                                        this.onchange = null;
                                    };
                                } else {
                                    alert(resp.error || '重传准备失败');
                                }
                            } else {
                                alert('重传准备失败');
                            }
                        };
                        xhr.send();
                    }

                    function formatSize(bytes) {
                        if (bytes === 0) return '0 B';
                        var units = ['B', 'KB', 'MB', 'GB'];
                        var i = Math.floor(Math.log(bytes) / Math.log(1024));
                        return (bytes / Math.pow(1024, i)).toFixed(i > 0 ? 2 : 0) + ' ' + units[i];
                    }
                </script>
            </body>
            </html>
        ''', folder=folder, items=items, subpath=subpath, parent_path=parent_path, error=error, success=success, config=config)
    except Exception as e:
        return render_template_string('''
            <!DOCTYPE html>
            <html>
            <head>
                <title>错误</title>
                <style>
                    body { font-family: 'Microsoft YaHei', Arial, sans-serif; text-align: center; padding-top: 100px; background: #FFF5F7; }
                    .error { color: #e74c3c; font-size: 18px; }
                </style>
            </head>
            <body>
                <div class="error">❌ 服务器内部错误，请稍后重试</div>
            </body>
            </html>
        '''), 500

@app.errorhandler(413)
def request_entity_too_large(error):
    max_size = config.get('max_upload_size', 1024)
    max_unit = config.get('max_upload_unit', 'MB')
    return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>文件过大</title>
            <style>
                body { font-family: 'Microsoft YaHei', Arial, sans-serif; text-align: center; padding-top: 100px; background: #FFF5F7; }
                .error { color: #e74c3c; font-size: 18px; }
                .btn { display: inline-block; padding: 10px 20px; background: #FF69B4; color: white; text-decoration: none; border-radius: 5px; margin-top: 20px; }
            </style>
        </head>
        <body>
            <div class="error">❌ 上传文件超过大小限制！</div>
            <div style="color: #666; margin-top: 10px;">最大允许上传：{{ max_size }}{{ max_unit }}</div>
            <a href="/" class="btn">返回</a>
        </body>
        </html>
        ''', max_size=max_size, max_unit=max_unit), 413

def save_file_with_cancel(file_stream, file_path, upload_id, chunk_size=8192):
    with open(file_path, 'wb') as f:
        while True:
            if upload_manager.is_cancelled(upload_id):
                f.close()
                if os.path.exists(file_path):
                    os.remove(file_path)
                return False
            chunk = file_stream.read(chunk_size)
            if not chunk:
                break
            f.write(chunk)
    return True


@app.route('/upload', methods=['POST'])
def upload():
    if config.get('password_hash', '') and not session.get('authenticated'):
        return redirect('/login')
    
    subpath = request.args.get('subpath', '')
    
    base_folder = config.get('folder', os.path.expanduser('~'))
    
    if subpath:
        subpath = unquote(subpath)
        folder = os.path.normpath(os.path.join(base_folder, subpath))
        if not folder.startswith(os.path.normpath(base_folder)):
            return render_template_string('''
                <!DOCTYPE html>
                <html>
                <head>
                    <title>访问被拒绝</title>
                    <style>
                        body { font-family: 'Microsoft YaHei', Arial, sans-serif; text-align: center; padding-top: 100px; background: #FFF5F7; }
                        .error { color: #e74c3c; font-size: 18px; }
                    </style>
                </head>
                <body>
                    <div class="error">❌ 访问被拒绝：非法路径访问</div>
                </body>
                </html>
            '''), 403
    else:
        folder = base_folder
    
    if not os.path.isdir(folder):
        return jsonify({'success': False, 'error': '目录不存在'})
    
    if 'files' not in request.files:
        return jsonify({'success': False, 'error': '请选择要上传的文件'})
    
    files = request.files.getlist('files')
    results = []
    all_success = True
    cancelled = False
    
    upload_size = config.get('max_upload_size', 1024)
    upload_unit = config.get('max_upload_unit', 'MB')
    if upload_unit == 'KB':
        max_bytes = upload_size * 1024
    elif upload_unit == 'GB':
        max_bytes = upload_size * 1024 * 1024 * 1024
    else:
        max_bytes = upload_size * 1024 * 1024
    
    for file in files:
        if cancelled:
            break
        
        if file.filename == '':
            continue
        
        if not allowed_file(file.filename):
            results.append({'filename': file.filename, 'success': False, 'error': '文件类型不允许'})
            all_success = False
            continue
        
        filename = secure_filename(file.filename)
        if not filename:
            results.append({'filename': file.filename, 'success': False, 'error': '无效的文件名'})
            all_success = False
            continue
        
        actual_path = os.path.join(folder, filename)
        
        if os.path.exists(actual_path):
            base, ext = os.path.splitext(filename)
            counter = 1
            while os.path.exists(os.path.join(folder, f"{base}_{counter}{ext}")):
                counter += 1
                if counter > 100:
                    results.append({'filename': filename, 'success': False, 'error': '文件已存在且重命名失败'})
                    all_success = False
                    continue
            filename = f"{base}_{counter}{ext}"
            actual_path = os.path.join(folder, filename)
        
        upload_id = upload_manager.create_record(filename, actual_path, 0, subpath)
        
        try:
            file.save(actual_path)
            client_ip = request.remote_addr
            file_size = os.path.getsize(actual_path) if os.path.exists(actual_path) else 0
            upload_manager.update_record(upload_id, status='completed', uploaded_size=file_size,
                                        end_time=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            log_operation('UPLOAD', f'上传文件: {filename} ({file_size} bytes)', client_ip)
            results.append({'filename': filename, 'success': True, 'upload_id': upload_id})
        except Exception as e:
            upload_manager.update_record(upload_id, status='failed', error_message=str(e),
                                        end_time=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            results.append({'filename': filename, 'success': False, 'error': str(e), 'upload_id': upload_id})
            all_success = False
    
    return jsonify({
        'success': all_success,
        'cancelled': cancelled,
        'results': results
    })


@app.route('/api/upload/records', methods=['GET'])
def api_upload_records():
    if config.get('password_hash', '') and not session.get('authenticated'):
        return jsonify({'error': '未授权'}), 403
    records = upload_manager.get_records()
    return jsonify({'records': records})


@app.route('/api/upload/cancel/<upload_id>', methods=['POST'])
def api_cancel_upload(upload_id):
    if config.get('password_hash', '') and not session.get('authenticated'):
        return jsonify({'error': '未授权'}), 403
    result = upload_manager.cancel_upload(upload_id)
    if result:
        return jsonify({'success': True, 'message': '上传已取消'})
    return jsonify({'success': False, 'error': '未找到上传记录或上传已完成'})


@app.route('/api/upload/retry/<upload_id>', methods=['POST'])
def api_retry_upload(upload_id):
    if config.get('password_hash', '') and not session.get('authenticated'):
        return jsonify({'error': '未授权'}), 403
    record = upload_manager.retry_prepare(upload_id)
    if record:
        return jsonify({'success': True, 'record': record})
    return jsonify({'success': False, 'error': '未找到上传记录或上传状态不允许重传'})


def zip_filename(prefix):
    return f'{prefix}_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.zip'


@app.route('/download/selected', methods=['POST'])
def download_selected():
    if config.get('password_hash', '') and not session.get('authenticated'):
        abort(403)
    
    client_ip = request.remote_addr
    subpath = request.args.get('subpath', '')
    
    base_folder = config.get('folder', os.path.expanduser('~'))
    
    if subpath:
        subpath = unquote(subpath)
        folder = os.path.join(base_folder, subpath)
    else:
        folder = base_folder
    
    selected_files = request.form.getlist('files[]')
    if not selected_files:
        return redirect(f'/?subpath={subpath}&error=请选择要下载的文件')
    
    if len(selected_files) == 1:
        filename = selected_files[0]
        file_path = os.path.join(folder, filename)
        if os.path.isfile(file_path):
            file_size = os.path.getsize(file_path)
            log_operation('DOWNLOAD', f'下载文件: {filename} ({file_size} bytes)', client_ip)
            return send_from_directory(folder, filename, as_attachment=True)
        else:
            log_operation('DOWNLOAD', f'下载文件失败: {filename} - 文件不存在', client_ip, status='failed')
            return redirect(f'/?subpath={subpath}&error=文件不存在')
    
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
    tmp_path = tmp.name
    tmp.close()
    
    total_size = 0
    file_count = 0
    try:
        with zipfile.ZipFile(tmp_path, 'w', zipfile.ZIP_STORED) as zf:
            for filename in selected_files:
                file_path = os.path.join(folder, filename)
                if os.path.isfile(file_path):
                    zf.write(file_path, filename)
                    total_size += os.path.getsize(file_path)
                    file_count += 1
        
        def generate():
            with open(tmp_path, 'rb') as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    yield chunk
            try:
                os.unlink(tmp_path)
            except:
                pass
        
        log_operation('DOWNLOAD', f'批量下载 {file_count} 个文件 ({total_size} bytes)', client_ip)
        return Response(generate(), mimetype='application/zip',
                        headers={'Content-Disposition': f'attachment; filename={zip_filename("download")}'})
    except:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

@app.route('/download/folder/<foldername>')
def download_folder(foldername):
    if config.get('password_hash', '') and not session.get('authenticated'):
        abort(403)
    
    client_ip = request.remote_addr
    subpath = request.args.get('subpath', '')
    
    base_folder = config.get('folder', os.path.expanduser('~'))
    
    if subpath:
        subpath = unquote(subpath)
        parent_folder = os.path.join(base_folder, subpath)
    else:
        parent_folder = base_folder
    
    folder_path = os.path.join(parent_folder, foldername)
    
    if not os.path.isdir(folder_path):
        log_operation('FOLDER_PACKAGE', f'打包文件夹失败: {foldername} - 文件夹不存在', client_ip, status='failed')
        abort(404)
    
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
    tmp_path = tmp.name
    tmp.close()
    
    total_size = 0
    file_count = 0
    try:
        with zipfile.ZipFile(tmp_path, 'w', zipfile.ZIP_STORED) as zf:
            for root, dirs, files in os.walk(folder_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, parent_folder)
                    zf.write(file_path, arcname)
                    total_size += os.path.getsize(file_path)
                    file_count += 1
        
        def generate():
            with open(tmp_path, 'rb') as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    yield chunk
            try:
                os.unlink(tmp_path)
            except:
                pass
        
        log_operation('FOLDER_PACKAGE', f'打包文件夹: {foldername} ({file_count} 个文件, {total_size} bytes)', client_ip)
        return Response(generate(), mimetype='application/zip',
                        headers={'Content-Disposition': f'attachment; filename={zip_filename(foldername)}'})
    except:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

@app.route('/download/<filename>')
def download(filename):
    if config.get('password_hash', '') and not session.get('authenticated'):
        abort(403)
    
    client_ip = request.remote_addr
    subpath = request.args.get('subpath', '')
    
    base_folder = config.get('folder', os.path.expanduser('~'))
    
    if subpath:
        subpath = unquote(subpath)
        folder = os.path.join(base_folder, subpath)
    else:
        folder = base_folder
    
    file_path = os.path.join(folder, filename)
    
    if not os.path.isfile(file_path):
        log_operation('DOWNLOAD', f'下载文件失败: {filename} - 文件不存在', client_ip, status='failed')
        abort(404)
    
    file_size = os.path.getsize(file_path)
    log_operation('DOWNLOAD', f'下载文件: {filename} ({file_size} bytes)', client_ip)
    return send_from_directory(folder, filename, as_attachment=True)

def format_size(size):
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.2f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.2f} MB"
    else:
        return f"{size / (1024 * 1024 * 1024):.2f} GB"

@app.template_filter('format_time')
def format_time_filter(timestamp):
    import datetime
    return datetime.datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')