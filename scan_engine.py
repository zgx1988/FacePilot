import os
import sqlite3
import hashlib
from datetime import datetime
import face_recognition
from PIL import Image
import exifread
import numpy as np
from sklearn.cluster import DBSCAN

DB_FILE = 'gallery.db'
THUMBNAILS_DIR = os.path.join('static', 'thumbnails')
AVATARS_DIR = os.path.join('static', 'avatars')

def init_db_if_needed():
    """智能初始化数据库，支持热更新表结构而不丢失数据"""
    os.makedirs(THUMBNAILS_DIR, exist_ok=True)
    os.makedirs(AVATARS_DIR, exist_ok=True)
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS images (id INTEGER PRIMARY KEY AUTOINCREMENT, file_path TEXT UNIQUE NOT NULL, file_hash TEXT, shot_date DATETIME, thumbnail_path TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS persons (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT DEFAULT '未知人物', cover_face_id INTEGER)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS faces (id INTEGER PRIMARY KEY AUTOINCREMENT, image_id INTEGER, person_id INTEGER, box_top INTEGER, box_right INTEGER, box_bottom INTEGER, box_left INTEGER, encoding BLOB, face_thumbnail_path TEXT, FOREIGN KEY (image_id) REFERENCES images (id), FOREIGN KEY (person_id) REFERENCES persons (id))''')

    # 【热更新 1】增加隐藏字段
    cursor.execute("PRAGMA table_info(persons)")
    if 'is_hidden' not in [column[1] for column in cursor.fetchall()]:
        cursor.execute("ALTER TABLE persons ADD COLUMN is_hidden INTEGER DEFAULT 0")
        
    # 【热更新 2】为 images 表增加“收藏(is_favorite)”字段！
    cursor.execute("PRAGMA table_info(images)")
    if 'is_favorite' not in [column[1] for column in cursor.fetchall()]:
        print("⚙️ 正在升级 images 表 (添加收藏 is_favorite 字段)...")
        cursor.execute("ALTER TABLE images ADD COLUMN is_favorite INTEGER DEFAULT 0")

    conn.commit()
    conn.close()

# ... (中间的 get_file_hash, get_exif_date, create_thumbnail, crop_face 函数保持不变，省略以节省篇幅，请务必保留它们) ...
# 为了确保代码完整性，我还是把它们完整贴出来吧，避免你复制漏了

def get_file_hash(filepath):
    hasher = hashlib.md5()
    with open(filepath, 'rb') as f:
        buf = f.read(65536)
        while len(buf) > 0:
            hasher.update(buf)
            buf = f.read(65536)
    return hasher.hexdigest()

def get_exif_date(filepath):
    try:
        with open(filepath, 'rb') as f:
            tags = exifread.process_file(f, stop_tag="EXIF DateTimeOriginal")
            if "EXIF DateTimeOriginal" in tags:
                return datetime.strptime(str(tags["EXIF DateTimeOriginal"]), '%Y:%m:%d %H:%M:%S').strftime('%Y-%m-%d %H:%M:%S')
    except: pass
    return datetime.fromtimestamp(os.path.getmtime(filepath)).strftime('%Y-%m-%d %H:%M:%S')

def create_thumbnail(filepath, file_hash):
    thumb_path = os.path.join(THUMBNAILS_DIR, f"{file_hash}.jpg")
    if not os.path.exists(thumb_path):
        try:
            with Image.open(filepath) as img:
                if img.mode != 'RGB': img = img.convert('RGB')
                img.thumbnail((600, 600))
                img.save(thumb_path, 'JPEG', quality=85)
        except: return None
    return f"thumbnails/{file_hash}.jpg"

def crop_face(image_path, location, file_hash, face_index):
    top, right, bottom, left = location
    try:
        with Image.open(image_path) as img:
            center_x, center_y = (left + right) // 2, (top + bottom) // 2
            crop_size = int(max(right - left, bottom - top) * 1.8)
            crop_left, crop_top = max(0, center_x - crop_size // 2), max(0, center_y - crop_size // 2)
            face_img = img.crop((crop_left, crop_top, min(img.width, crop_left + crop_size), min(img.height, crop_top + crop_size)))
            if face_img.mode != 'RGB': face_img = face_img.convert('RGB')
            face_img = face_img.resize((200, 200), Image.Resampling.LANCZOS)
            avatar_filename = f"{file_hash}_face_{face_index}.jpg"
            face_img.save(os.path.join(AVATARS_DIR, avatar_filename), 'JPEG', quality=90)
            return f"avatars/{avatar_filename}"
    except: return None
# ... (以上省略函数结束) ...


def run_scan(target_dir, progress):
    init_db_if_needed() # 确保数据库结构最新

    progress['status'] = 'scanning'
    progress['msg'] = '正在查找图片文件...'
    progress['current'] = 0

    files_to_scan = []
    for root, dirs, files in os.walk(target_dir):
        for f in files:
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                files_to_scan.append(os.path.join(root, f))
    
    progress['total'] = len(files_to_scan)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # 1. 增量扫描图片
    for idx, filepath in enumerate(files_to_scan):
        progress['current'] = idx + 1
        progress['msg'] = f'正在提取人脸: {os.path.basename(filepath)}'
        file_hash = get_file_hash(filepath)
        cursor.execute("SELECT id FROM images WHERE file_hash = ?", (file_hash,))
        if cursor.fetchone(): continue
        
        shot_date, thumb_path = get_exif_date(filepath), create_thumbnail(filepath, file_hash)
        cursor.execute("INSERT INTO images (file_path, file_hash, shot_date, thumbnail_path) VALUES (?, ?, ?, ?)", (filepath, file_hash, shot_date, thumb_path))
        image_id = cursor.lastrowid

        try:
            image_np = face_recognition.load_image_file(filepath)
            locations = face_recognition.face_locations(image_np)
            encodings = face_recognition.face_encodings(image_np, locations)
            for i, (loc, enc) in enumerate(zip(locations, encodings)):
                face_thumb = crop_face(filepath, loc, file_hash, i)
                cursor.execute("INSERT INTO faces (image_id, box_top, box_right, box_bottom, box_left, encoding, face_thumbnail_path) VALUES (?, ?, ?, ?, ?, ?, ?)", 
                               (image_id, loc[0], loc[1], loc[2], loc[3], enc.tobytes(), face_thumb))
        except: pass
        conn.commit()

    progress['msg'] = '正在进行AI智能聚类 (将保留已修改的姓名)...'
    
    # 2. 智能聚类
    # 【改动】查询旧名字时，只查询未被隐藏的人
    cursor.execute("SELECT f.id, p.name FROM faces f JOIN persons p ON f.person_id = p.id WHERE p.name NOT LIKE '未知人物%' AND (p.is_hidden = 0 OR p.is_hidden IS NULL)")
    old_face_names = {row[0]: row[1] for row in cursor.fetchall()}

    cursor.execute("SELECT id, encoding FROM faces")
    rows = cursor.fetchall()
    
    if rows:
        face_ids, encodings = [r[0] for r in rows], [np.frombuffer(r[1], dtype=np.float64) for r in rows]
        # 聚类参数保持你觉得好用的设置
        dbscan = DBSCAN(metric="euclidean", eps=0.38, min_samples=1)
        dbscan.fit(encodings)
        labels = dbscan.labels_

        # 【改动】删除旧数据时，保留那些已经被手动隐藏的“假人”记录，防止下次扫描又冒出来
        cursor.execute("DELETE FROM persons WHERE is_hidden = 0 OR is_hidden IS NULL")
        cursor.execute("UPDATE faces SET person_id = NULL WHERE person_id IN (SELECT id FROM persons WHERE is_hidden = 0 OR is_hidden IS NULL)")

        person_count = 0
        for label in set(labels):
            if label == -1: continue
            cluster_faces = [face_ids[i] for i in range(len(labels)) if labels[i] == label]
            
            person_name = next((old_face_names[fid] for fid in cluster_faces if fid in old_face_names), None)
            if not person_name:
                person_count += 1
                person_name = f"未知人物 {person_count}"

            # 新插入的人物默认不隐藏
            cursor.execute("INSERT INTO persons (name, cover_face_id, is_hidden) VALUES (?, ?, 0)", (person_name, cluster_faces[0]))
            person_id = cursor.lastrowid
            for fid in cluster_faces:
                cursor.execute("UPDATE faces SET person_id = ? WHERE id = ?", (person_id, fid))
                
    conn.commit()
    conn.close()
    progress['status'] = 'done'
    progress['msg'] = '扫描与聚类全部完成！'
