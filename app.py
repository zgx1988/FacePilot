from flask import Flask, render_template, send_from_directory, request, jsonify, send_file
import sqlite3
import os
import sys
import threading
import shutil
from collections import OrderedDict
from scan_engine import run_scan, init_db_if_needed
from urllib.parse import unquote

# ====== 【终极修复】动态获取真正的绝对路径 ======
if getattr(sys, 'frozen', False):
    # 如果是打包后的 exe 运行模式，路径就是 exe 所在的文件夹
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # 如果是开发环境 python 运行模式，路径就是当前代码文件夹
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 强制指定 Flask 去这台电脑的绝对路径下找网页和静态资源
app = Flask(__name__, 
            template_folder=os.path.join(BASE_DIR, 'templates'),
            static_folder=os.path.join(BASE_DIR, 'static'))

DB_FILE = os.path.join(BASE_DIR, 'gallery.db')
# ===============================================

SCAN_PROGRESS = {'status': 'idle', 'current': 0, 'total': 0, 'msg': ''}
init_db_if_needed()

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def index():
    conn = get_db_connection()
    persons = conn.execute('''
        SELECT p.id, p.name, f.face_thumbnail_path 
        FROM persons p JOIN faces f ON p.cover_face_id = f.id
        WHERE p.is_hidden = 0 OR p.is_hidden IS NULL
    ''').fetchall()
    conn.close()
    return render_template('index.html', persons=persons)

@app.route('/person/<int:person_id>')
def timeline(person_id):
    conn = get_db_connection()
    person = conn.execute('SELECT name FROM persons WHERE id = ?', (person_id,)).fetchone()
    if not person: return "Person not found", 404
    
    # 【改动】增加了获取 i.id 和 i.is_favorite 字段
    photos_raw = conn.execute('''
        SELECT i.id, i.file_path, i.thumbnail_path, i.shot_date, i.is_favorite 
        FROM images i JOIN faces f ON i.id = f.image_id
        WHERE f.person_id = ? ORDER BY i.shot_date DESC
    ''', (person_id,)).fetchall()
    conn.close()
    
    grouped_photos = OrderedDict()
    for row in photos_raw:
        year_month = row['shot_date'][:7].replace('-', '年') + '月'
        exact_date = row['shot_date'][:10]
        if year_month not in grouped_photos: grouped_photos[year_month] = {}
        if exact_date not in grouped_photos[year_month]: grouped_photos[year_month][exact_date] = []
        grouped_photos[year_month][exact_date].append(row)
    
    return render_template('timeline.html', person=person, grouped_photos=grouped_photos)

# 【新增】收藏夹专属页面
@app.route('/favorites')
def favorites():
    conn = get_db_connection()
    photos_raw = conn.execute('''
        SELECT id, file_path, thumbnail_path, shot_date, is_favorite 
        FROM images WHERE is_favorite = 1 ORDER BY shot_date DESC
    ''').fetchall()
    conn.close()
    
    grouped_photos = OrderedDict()
    for row in photos_raw:
        year_month = row['shot_date'][:7].replace('-', '年') + '月'
        exact_date = row['shot_date'][:10]
        if year_month not in grouped_photos: grouped_photos[year_month] = {}
        if exact_date not in grouped_photos[year_month]: grouped_photos[year_month][exact_date] = []
        grouped_photos[year_month][exact_date].append(row)
        
    return render_template('favorites.html', grouped_photos=grouped_photos)

# ============ API 区域 ============
@app.route('/api/toggle_favorite', methods=['POST'])
def toggle_favorite():
    """【新增】心心点赞/取消收藏 API"""
    data = request.json
    image_id = data.get('id')
    is_fav = data.get('is_favorite')
    if image_id is not None:
        conn = get_db_connection()
        conn.execute('UPDATE images SET is_favorite = ? WHERE id = ?', (is_fav, image_id))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    return jsonify({'success': False})

@app.route('/api/rename', methods=['POST'])
def rename_person():
    data = request.json
    target_id, new_name = data.get('id'), data.get('name')
    if target_id and new_name:
        conn = get_db_connection()
        existing = conn.execute('SELECT id FROM persons WHERE name = ? AND id != ? AND (is_hidden = 0 OR is_hidden IS NULL)', (new_name, target_id)).fetchone()
        if existing:
            conn.execute('UPDATE faces SET person_id = ? WHERE person_id = ?', (existing['id'], target_id))
            conn.execute('UPDATE persons SET is_hidden = 1 WHERE id = ?', (target_id,))
        else:
            conn.execute('UPDATE persons SET name = ? WHERE id = ?', (new_name, target_id))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'merged': bool(existing)})
    return jsonify({'success': False})

@app.route('/api/hide_person', methods=['POST'])
def hide_person():
    data = request.json
    if data.get('id'):
        conn = get_db_connection()
        conn.execute('UPDATE persons SET is_hidden = 1 WHERE id = ?', (data['id'],))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    return jsonify({'success': False})

@app.route('/api/export_photos', methods=['POST'])
def export_photos():
    data = request.json
    person_ids = data.get('person_ids', [])
    dest_path = data.get('dest_path', '')
    if not person_ids or not dest_path: return jsonify({'success': False, 'msg': '参数不完整'})
    if not os.path.exists(dest_path):
        try: os.makedirs(dest_path)
        except Exception as e: return jsonify({'success': False, 'msg': f'无法创建保存目录: {e}'})

    conn = get_db_connection()
    placeholders = ','.join(['?'] * len(person_ids))
    query = f'SELECT DISTINCT i.file_path FROM images i JOIN faces f ON i.id = f.image_id WHERE f.person_id IN ({placeholders})'
    photos = conn.execute(query, person_ids).fetchall()
    conn.close()

    copied_count = 0
    for photo in photos:
        src = photo['file_path']
        if os.path.exists(src):
            try:
                filename = os.path.basename(src)
                target_file = os.path.join(dest_path, filename)
                base, ext = os.path.splitext(filename)
                counter = 1
                while os.path.exists(target_file):
                    target_file = os.path.join(dest_path, f"{base}_{counter}{ext}")
                    counter += 1
                shutil.copy2(src, target_file)
                copied_count += 1
            except: pass
    return jsonify({'success': True, 'count': copied_count})

@app.route('/api/start_scan', methods=['POST'])
def start_scan():
    if SCAN_PROGRESS['status'] == 'scanning': return jsonify({'success': False, 'msg': '正在扫描中...'})
    target_dir = request.json.get('path', '')
    if not os.path.exists(target_dir): return jsonify({'success': False, 'msg': '找不到该路径，请检查'})
    thread = threading.Thread(target=run_scan, args=(target_dir, SCAN_PROGRESS))
    thread.start()
    return jsonify({'success': True})

@app.route('/api/progress')
def get_progress(): return jsonify(SCAN_PROGRESS)

@app.route('/local_image')
def serve_local_image():
    filepath_encoded = request.args.get('path')
    if filepath_encoded:
        filepath = unquote(filepath_encoded)
        if os.path.exists(filepath): return send_file(filepath)
    return "图片未找到", 404

@app.route('/static/<path:filename>')
def serve_static(filename): return send_from_directory('static', filename)

import webbrowser

if __name__ == '__main__':
    # 【非常重要】打包前，必须将 debug=True 改为 debug=False
    # 否则打包后的程序会因为热重载机制启动两次，导致端口冲突和浏览器弹两次！
    print("🌐 Web 服务器即将启动...")
    
    # 使用定时器延迟 1.5 秒打开浏览器，给服务器留出启动的时间
    threading.Timer(1.5, lambda: webbrowser.open('http://127.0.0.1:5000/')).start()
    
    app.run(debug=False, port=5000)
