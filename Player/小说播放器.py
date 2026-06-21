#!/usr/bin/env python3
"""
听小说 + 网页音频探测器 - 单文件版
功能：
  1. 📖 听小说 - 从 i275.com 等网站播放小说音频，自动保存进度
  2. 🔍 音频探测 - 检测任意网页中的音频/视频资源
启动: python3 app.py
"""

import re
import json
import os
import io
import logging
import threading
import zipfile
import tempfile
from urllib.parse import urljoin, urlparse, quote
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from flask import Flask, Response, jsonify, request as flask_request

# ============================================================
# 配置
# ============================================================
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TIMEOUT = 15
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
}

DATA_DIR = Path(__file__).parent / 'data'
DATA_DIR.mkdir(exist_ok=True)
PROGRESS_FILE = DATA_DIR / 'progress.json'
CATALOG_CACHE_FILE = DATA_DIR / 'catalog_cache.json'

# ============================================================
# 音频/视频 URL 正则
# ============================================================
AUDIO_EXTS = re.compile(r'\.(mp3|m4a|aac|ogg|oga|wav|flac|wma|opus|amr|mid|midi|ape|alac|wv)(\?[^#\s]*)?$', re.I)
VIDEO_EXTS = re.compile(r'\.(mp4|m4v|webm|mkv|avi|mov|flv|wmv|3gp|ts|f4v)(\?[^#\s]*)?$', re.I)
STREAM_EXTS = re.compile(r'\.(m3u8|m3u|mpd|ism|ismc|isml)(\?[^#\s]*)?$', re.I)
MEDIA_EXTS = re.compile(r'|'.join([AUDIO_EXTS.pattern, VIDEO_EXTS.pattern, STREAM_EXTS.pattern]), re.I)
IMAGE_EXTS = re.compile(r'\.(jpg|jpeg|png|gif|bmp|ico|svg|webp|avif)(\?[^#\s]*)?$', re.I)

# ============================================================
# 进度管理
# ============================================================
_progress_lock = threading.Lock()

def load_progress():
    """加载所有书籍的播放进度"""
    try:
        if PROGRESS_FILE.exists():
            with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f'加载进度失败: {e}')
    return {}

def save_progress(progress):
    """保存所有书籍的播放进度"""
    try:
        with _progress_lock:
            with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
                json.dump(progress, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f'保存进度失败: {e}')

def get_book_progress(book_id):
    """获取指定书籍的播放进度"""
    all_progress = load_progress()
    return all_progress.get(str(book_id), {'chapter_id': None, 'position': 0, 'last_chapter': None})

def update_book_progress(book_id, chapter_id, position=0):
    """更新指定书籍的播放进度"""
    all_progress = load_progress()
    key = str(book_id)
    if key not in all_progress:
        all_progress[key] = {}
    all_progress[key]['chapter_id'] = chapter_id
    all_progress[key]['position'] = position
    all_progress[key]['last_chapter'] = chapter_id
    all_progress[key]['updated'] = __import__('time').strftime('%Y-%m-%d %H:%M:%S')
    save_progress(all_progress)

# ============================================================
# 目录缓存
# ============================================================
def load_catalog_cache():
    try:
        if CATALOG_CACHE_FILE.exists():
            with open(CATALOG_CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except:
        pass
    return {}

def save_catalog_cache(cache):
    try:
        with open(CATALOG_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f'保存目录缓存失败: {e}')

# ============================================================
# i275.com 专用功能
# ============================================================
def i275_get_session(book_id):
    """获取 i275.com 的 session（需要先访问 book 页面建立 PHP session）"""
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        session.get(f'https://m.i275.com/book/{book_id}.html', timeout=TIMEOUT, verify=False)
    except:
        pass
    return session

def i275_get_chapter_list(book_id):
    """从书籍页面获取章节列表"""
    cache = load_catalog_cache()
    cache_key = f'i275_{book_id}'

    # 检查缓存（有效期 1 小时）
    if cache_key in cache:
        import time
        cached = cache[cache_key]
        if time.time() - cached.get('timestamp', 0) < 3600:
            return cached['chapters']

    try:
        session = i275_get_session(book_id)
        resp = session.get(f'https://m.i275.com/book/{book_id}.html', timeout=TIMEOUT, verify=False)
        resp.encoding = resp.apparent_encoding or 'utf-8'
        soup = BeautifulSoup(resp.text, 'html.parser')

        chapters = []
        # 查找章节链接
        for a in soup.find_all('a', href=True):
            href = a['href']
            m = re.match(r'/play/(\d+)/(\d+)', href)
            if m and m.group(1) == str(book_id):
                ch_id = m.group(2)
                title = a.get_text(strip=True)
                if title and len(title) > 1:
                    chapters.append({'id': ch_id, 'title': title})

        # 去重并保持顺序
        seen = set()
        unique_chapters = []
        for ch in chapters:
            if ch['id'] not in seen:
                seen.add(ch['id'])
                unique_chapters.append(ch)

        # 缓存
        cache[cache_key] = {
            'chapters': unique_chapters,
            'timestamp': __import__('time').time(),
            'total': len(unique_chapters)
        }
        save_catalog_cache(cache)

        return unique_chapters
    except Exception as e:
        logger.error(f'获取章节列表失败: {e}')
        return []

def i275_get_audio_url(book_id, chapter_id):
    """获取指定章节的音频 URL"""
    try:
        session = i275_get_session(book_id)
        url = f'https://m.i275.com/play/{book_id}/{chapter_id}.html'
        resp = session.get(url, timeout=TIMEOUT, verify=False)
        resp.encoding = resp.apparent_encoding or 'utf-8'

        # 检查是否被重定向到首页
        if '/play/' not in resp.url:
            return None, '无法获取章节页面，可能需要重新建立会话'

        # 使用 APlayer 正则提取音频 URL
        m = re.search(r"url\s*:\s*['\"`]([^'\"`\s]+?)['\"`]", resp.text)
        if m:
            audio_url = m.group(1)
            if audio_url.startswith('//'):
                audio_url = 'https:' + audio_url
            return audio_url, None

        return None, '未找到音频地址'
    except Exception as e:
        return None, str(e)

def i275_get_book_info(book_id):
    """获取书籍基本信息"""
    try:
        session = i275_get_session(book_id)
        resp = session.get(f'https://m.i275.com/book/{book_id}.html', timeout=TIMEOUT, verify=False)
        resp.encoding = resp.apparent_encoding or 'utf-8'
        soup = BeautifulSoup(resp.text, 'html.parser')

        title = ''
        # 尝试从页面标题获取
        title_tag = soup.find('title')
        if title_tag:
            title = title_tag.get_text(strip=True)
            # 清理标题中的网站名称
            title = re.sub(r'[-_|].*i275.*$', '', title).strip()
            title = re.sub(r'[-_|].*听书.*$', '', title).strip()

        # 尝试获取封面
        cover = ''
        img = soup.find('img', class_=re.compile(r'cover|book|img', re.I))
        if not img:
            img = soup.find('img', src=re.compile(r'cover|book', re.I))
        if img and img.get('src'):
            cover = img['src']
            if cover.startswith('//'):
                cover = 'https:' + cover

        return {'title': title or f'书籍 {book_id}', 'cover': cover}
    except Exception as e:
        return {'title': f'书籍 {book_id}', 'cover': ''}

# ============================================================
# 通用页面抓取
# ============================================================
def fetch_page(url):
    try:
        session = requests.Session()
        session.headers.update(HEADERS)

        # i275.com 特殊处理
        i275_match = re.match(r'https?://(?:m\.)?i275\.com/play/(\d+)/(\d+)', url)
        if i275_match:
            book_id = i275_match.group(1)
            session.get(f'https://m.i275.com/book/{book_id}.html', timeout=TIMEOUT, verify=False)

        resp = session.get(url, timeout=TIMEOUT, allow_redirects=True, verify=False)
        resp.encoding = resp.apparent_encoding or 'utf-8'
        soup = BeautifulSoup(resp.text, 'html.parser')
        js_urls = set()
        for tag in soup.find_all('script', src=True):
            src = tag['src']
            if src.endswith('.js') or 'javascript' in tag.get('type', '').lower() or not tag.get('type'):
                js_urls.add(urljoin(resp.url, src))
        return {'html': resp.text, 'final_url': resp.url, 'js_urls': list(js_urls), 'error': None}
    except requests.exceptions.Timeout:
        return {'html': '', 'final_url': url, 'js_urls': [], 'error': '请求超时'}
    except requests.exceptions.ConnectionError:
        return {'html': '', 'final_url': url, 'js_urls': [], 'error': '连接失败，请检查URL'}
    except Exception as e:
        return {'html': '', 'final_url': url, 'js_urls': [], 'error': str(e)}

def fetch_js_content(js_url):
    try:
        resp = requests.get(js_url, headers=HEADERS, timeout=TIMEOUT, verify=False)
        resp.encoding = resp.apparent_encoding or 'utf-8'
        return resp.text
    except:
        return ''

# ============================================================
# 音频检测引擎
# ============================================================
def detect_media(html, base_url='', js_contents=None):
    results = []
    seen = set()

    def add_result(url, source, title=''):
        if not url or len(url) < 10 or len(url) > 2000:
            return
        url = url.strip().strip("'\"`")
        if url.startswith('//'):
            url = 'https:' + url
        if url.startswith('data:') or IMAGE_EXTS.search(url):
            return
        if not url.startswith('http'):
            if base_url:
                url = urljoin(base_url, url)
            else:
                return
        if url in seen:
            return
        seen.add(url)

        media_type, ext = 'unknown', ''
        try:
            parsed = urlparse(url)
            path, qs = parsed.path.lower(), parsed.query.lower()
            if AUDIO_EXTS.search(path) or AUDIO_EXTS.search(qs):
                media_type, ext = 'audio', (AUDIO_EXTS.search(path) or AUDIO_EXTS.search(qs)).group(1)
            elif VIDEO_EXTS.search(path) or VIDEO_EXTS.search(qs):
                media_type, ext = 'video', (VIDEO_EXTS.search(path) or VIDEO_EXTS.search(qs)).group(1)
            elif STREAM_EXTS.search(path) or STREAM_EXTS.search(qs):
                media_type, ext = 'stream', (STREAM_EXTS.search(path) or STREAM_EXTS.search(qs)).group(1)
            else:
                host = (parsed.hostname or '').lower()
                path_lower = path.lower()
                if any(kw in host for kw in ['audio', 'music', 'sound', 'mp3', 'media', 'stream', 'radio', 'podcast']):
                    media_type = 'audio'
                elif any(kw in host for kw in ['video', 'movie', 'film', 'tv']):
                    media_type = 'video'
                if any(kw in path_lower for kw in ['/audio/', '/music/', '/sound/', '/mp3/', '/media/', '/stream/']):
                    media_type = 'audio' if media_type == 'unknown' else media_type
        except Exception:
            pass

        results.append({'url': url, 'source': source, 'type': media_type, 'ext': ext, 'title': title})

    # 策略1: HTML标签
    try:
        soup = BeautifulSoup(html, 'html.parser')
        for tag in soup.find_all(['audio', 'video']):
            t = tag.name
            title = tag.get('title', '')
            if tag.get('src'):
                add_result(tag['src'], f'HTML <{t}> 标签', title)
            for s in tag.find_all('source'):
                if s.get('src'):
                    add_result(s['src'], f'HTML <source> 标签', title)
        for a in soup.find_all('a', href=True):
            if MEDIA_EXTS.search(a['href']):
                add_result(a['href'], 'HTML <a> 链接', a.get_text(strip=True)[:100])
        for tag in soup.find_all(['embed', 'iframe']):
            src = tag.get('src', '') or tag.get('data-src', '')
            if src and (MEDIA_EXTS.search(src) or re.search(r'player|audio|video|music', src, re.I)):
                add_result(src, f'HTML <{tag.name}> 标签')
        for meta in soup.find_all('meta', property=True):
            prop = meta.get('property', '').lower()
            if prop in ('og:audio', 'og:audio:url', 'og:video', 'og:video:url'):
                if meta.get('content'):
                    add_result(meta['content'], f'Meta OG ({prop})')
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                _extract_json(json.loads(script.string), 'JSON-LD', add_result)
            except:
                pass
        for script in soup.find_all('script'):
            if script.string and len(script.string) > 5:
                _extract_js(script.string, '内联JS', add_result)
    except Exception as e:
        logger.warning(f'HTML解析错误: {e}')

    _regex_scan(html, '全局正则', add_result)

    if js_contents:
        for js in js_contents:
            if js.get('content'):
                _extract_js(js['content'], f"JS:{js['url'].split('/')[-1]}", add_result)
                _regex_scan(js['content'], f"JS正则:{js['url'].split('/')[-1]}", add_result)

    return results


def _extract_json(obj, source, add_result):
    if not obj or not isinstance(obj, (dict, list)):
        return
    if isinstance(obj, list):
        for item in obj:
            _extract_json(item, source, add_result)
        return
    for key in ['url', 'src', 'source', 'file', 'path', 'audio', 'mp3', 'stream',
                'playUrl', 'audioUrl', 'musicUrl', 'mediaUrl', 'videoUrl',
                'audio_url', 'mp3_url', 'source_url', 'stream_url', 'play_url']:
        val = obj.get(key)
        if isinstance(val, str) and val.startswith('http') and len(val) > 10:
            if MEDIA_EXTS.search(val) or re.search(r'audio|music|sound|mp3|media|stream', val, re.I):
                add_result(val, source, obj.get('title', obj.get('name', '')))
    for v in obj.values():
        if isinstance(v, (dict, list)):
            _extract_json(v, source, add_result)


def _extract_js(text, source, add_result):
    for regex, label in [
        (re.compile(r"url\s*:\s*['\"`]([^'\"`\s]+?)['\"`]", re.I), 'APlayer'),
        (re.compile(r"""['"`](?:src|source|url|file|audio|mp3|stream|playUrl|audioUrl|musicUrl|mediaUrl)['"`]\s*:\s*['"`](https?://[^'"`\s]+?)['"`]""", re.I), 'JS属性'),
        (re.compile(r"""['"`](?:url|src|file|path|stream|play_url|audio_url|mp3_url|source_url)['"`]\s*:\s*['"`](https?://[^'"`\s]+?)['"`]""", re.I), 'JSON键值'),
    ]:
        for m in regex.finditer(text):
            if m.group(1):
                add_result(m.group(1), f'{source}-{label}')
    for block in re.findall(r'\{[^{}]*(?:url|src|audio|mp3|stream|playUrl)[^{}]*\}', text, re.I):
        try:
            fixed = re.sub(r'(\w+)\s*:', r'"\1":', block.replace("'", '"'))
            _extract_json(json.loads(fixed), source, add_result)
        except:
            pass


def _regex_scan(text, source, add_result):
    for regex in [
        re.compile(r'https?://[^\s\'"`<>)\]\}]+?\.(mp3|m4a|aac|ogg|wav|flac|opus|wma|webm|mp4|m3u8|mpd)(\?[^\s\'"`<>)\]\}]*)?', re.I),
        re.compile(r'https?://[a-z0-9\-\.]*xmcdn\.com/[^\s\'"`<>)\]\}]*?\.(mp3|m4a|aac|ogg|wav|flac|opus)[^\s\'"`<>)\]\}]*', re.I),
        re.compile(r'https?://[^\s\'"`<>)\]\}]*?(?:audio|music|sound|media|stream|podcast|radio|mp3|cdn)[^\s\'"`<>)\]\}]*?\.(mp3|m4a|aac|ogg|wav|flac|webm|mp4|m3u8)[^\s\'"`<>)\]\}]*', re.I),
        re.compile(r'https?://[^\s\'"`<>)\]\}]+?\.m3u8[^\s\'"`<>)\]\}]*', re.I),
        re.compile(r'https?://[^\s\'"`<>)\]\}]+?\.mpd[^\s\'"`<>)\]\}]*', re.I),
        re.compile(r'data-(?:src|url|audio|mp3|source|stream)\s*=\s*[\'"`]([^\'"`\s]+?)[\'"`]', re.I),
    ]:
        for m in regex.finditer(text):
            url = m.group(1) if m.lastindex and m.group(1) else m.group(0)
            if url:
                add_result(url, source)


# ============================================================
# 前端 HTML（内嵌）
# ============================================================
HTML_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>📖 听小说</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--primary:#6c5ce7;--primary-dark:#5a4bd1;--bg:#0a0a1a;--bg2:#12122a;--bg3:#1a1a3e;--text:#e8e8f0;--text2:#9999bb;--border:rgba(255,255,255,.08);--accent:#a29bfe;--success:#00b894;--danger:#e17055}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Noto Sans SC','PingFang SC',sans-serif;background:var(--bg);min-height:100vh;color:var(--text);overflow-x:hidden}
.app{max-width:480px;margin:0 auto;min-height:100vh;position:relative;background:var(--bg)}

/* 顶部导航 */
.top-bar{display:flex;align-items:center;justify-content:space-between;padding:16px 20px;background:var(--bg2);border-bottom:1px solid var(--border);position:sticky;top:0;z-index:100;backdrop-filter:blur(20px)}
.top-bar h1{font-size:1.2em;font-weight:700;background:linear-gradient(135deg,var(--primary),var(--accent));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.top-bar .menu-btn{background:none;border:none;color:var(--text2);font-size:1.3em;cursor:pointer;padding:4px 8px}

/* 标签页 */
.tabs{display:flex;background:var(--bg2);padding:0 16px 12px;gap:4px;position:sticky;top:56px;z-index:99}
.tab-btn{flex:1;padding:8px 12px;border:none;background:transparent;color:var(--text2);font-size:.88em;border-radius:8px;cursor:pointer;transition:all .3s;font-weight:500}
.tab-btn.active{background:var(--primary);color:#fff;box-shadow:0 2px 12px rgba(108,92,231,.4)}

/* 面板 */
.page{display:none;padding:16px 20px 100px}
.page.active{display:block}

/* 输入区域 */
.input-card{background:var(--bg2);border:1px solid var(--border);border-radius:16px;padding:20px;margin-bottom:16px}
.input-card h3{font-size:.95em;color:var(--accent);margin-bottom:12px;font-weight:600}
.input-card label{display:block;font-size:.82em;color:var(--text2);margin-bottom:6px}
.input-card input,.input-card textarea{width:100%;padding:12px 14px;background:var(--bg);border:1px solid var(--border);border-radius:10px;color:var(--text);font-size:.92em;outline:none;transition:border-color .3s}
.input-card input:focus,.input-card textarea:focus{border-color:var(--primary)}
.input-card textarea{resize:vertical;min-height:120px;font-family:monospace;font-size:.82em}

/* 按钮 */
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:12px 24px;border:none;border-radius:10px;font-size:.92em;font-weight:600;cursor:pointer;transition:all .3s}
.btn-primary{background:linear-gradient(135deg,var(--primary),#8b5cf6);color:#fff;box-shadow:0 4px 15px rgba(108,92,231,.3)}
.btn-primary:hover{transform:translateY(-1px);box-shadow:0 6px 20px rgba(108,92,231,.5)}
.btn-primary:disabled{opacity:.5;cursor:not-allowed;transform:none}
.btn-ghost{background:rgba(255,255,255,.06);color:var(--text2);border:1px solid var(--border)}
.btn-ghost:hover{background:rgba(255,255,255,.1)}
.btn-sm{padding:6px 14px;font-size:.82em;border-radius:8px}
.btn-block{width:100%}
.btn-group{display:flex;gap:8px;margin-top:12px}

/* 播放器区域 */
.player-section{display:none}
.player-section.active{display:block}
.book-header{display:flex;gap:16px;align-items:center;margin-bottom:20px;padding:16px;background:var(--bg2);border-radius:16px;border:1px solid var(--border)}
.book-cover{width:80px;height:100px;border-radius:10px;object-fit:cover;background:var(--bg3);flex-shrink:0}
.book-info{flex:1;min-width:0}
.book-info h2{font-size:1.05em;margin-bottom:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.book-info .chapter-title{font-size:.88em;color:var(--accent);margin-bottom:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.book-info .meta{font-size:.78em;color:var(--text2)}

/* 播放控制 */
.player-card{background:var(--bg2);border:1px solid var(--border);border-radius:16px;padding:20px;margin-bottom:16px}
.progress-wrap{margin-bottom:16px}
.progress-bar{width:100%;height:6px;background:var(--bg3);border-radius:3px;cursor:pointer;position:relative;overflow:hidden}
.progress-fill{height:100%;background:linear-gradient(90deg,var(--primary),var(--accent));border-radius:3px;transition:width .3s linear;width:0}
.progress-bar:hover .progress-fill{height:8px;margin-top:-1px}
.progress-time{display:flex;justify-content:space-between;font-size:.78em;color:var(--text2);margin-top:6px;font-variant-numeric:tabular-nums}

.controls{display:flex;align-items:center;justify-content:center;gap:20px;margin-bottom:12px}
.ctrl-btn{background:none;border:none;color:var(--text);font-size:1.6em;cursor:pointer;transition:all .2s;padding:8px;border-radius:50%}
.ctrl-btn:hover{color:var(--accent);background:rgba(255,255,255,.05)}
.ctrl-btn.play-btn{width:56px;height:56px;background:linear-gradient(135deg,var(--primary),#8b5cf6);color:#fff;font-size:1.4em;border-radius:50%;display:flex;align-items:center;justify-content:center;box-shadow:0 4px 20px rgba(108,92,231,.4)}
.ctrl-btn.play-btn:hover{transform:scale(1.05);box-shadow:0 6px 25px rgba(108,92,231,.6)}

.extra-controls{display:flex;align-items:center;justify-content:center;gap:16px;padding-top:8px;border-top:1px solid var(--border)}
.speed-btn{background:rgba(255,255,255,.06);border:1px solid var(--border);color:var(--text2);padding:4px 10px;border-radius:6px;font-size:.78em;cursor:pointer;transition:all .2s}
.speed-btn.active,.speed-btn:hover{background:var(--primary);color:#fff;border-color:var(--primary)}

/* 章节列表 */
.chapter-list-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}
.chapter-list-header h3{font-size:.95em;color:var(--accent);font-weight:600}
.chapter-search{padding:8px 12px;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:.85em;outline:none;width:100%;margin-bottom:12px}
.chapter-list{max-height:400px;overflow-y:auto;border-radius:12px;background:var(--bg2);border:1px solid var(--border)}
.chapter-item{display:flex;align-items:center;gap:10px;padding:12px 16px;border-bottom:1px solid var(--border);cursor:pointer;transition:background .2s;font-size:.88em}
.chapter-item:last-child{border-bottom:none}
.chapter-item:hover{background:rgba(108,92,231,.1)}
.chapter-item.active{background:rgba(108,92,231,.15);color:var(--accent)}
.chapter-item .ch-num{color:var(--text2);font-size:.78em;min-width:36px;text-align:right}
.chapter-item .ch-title{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.chapter-item .ch-playing{color:var(--success);font-size:.75em;display:none}
.chapter-item.active .ch-playing{display:inline}

/* 加载状态 */
.loading-overlay{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(10,10,26,.85);z-index:200;align-items:center;justify-content:center;flex-direction:column;gap:16px}
.loading-overlay.active{display:flex}
.spinner{width:40px;height:40px;border:3px solid var(--border);border-top-color:var(--primary);border-radius:50%;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.loading-text{color:var(--text2);font-size:.9em}

/* 提示 */
.toast{position:fixed;bottom:80px;left:50%;transform:translateX(-50%) translateY(100px);background:var(--bg3);color:var(--text);padding:10px 20px;border-radius:10px;font-size:.88em;z-index:300;transition:transform .3s;box-shadow:0 4px 20px rgba(0,0,0,.5);border:1px solid var(--border)}
.toast.show{transform:translateX(-50%) translateY(0)}

/* 音频探测页面样式 */
.detect-card{background:var(--bg2);border:1px solid var(--border);border-radius:16px;padding:20px;margin-bottom:16px}
.detect-card h3{font-size:.95em;color:var(--accent);margin-bottom:12px;font-weight:600}
.detect-card label{display:block;font-size:.82em;color:var(--text2);margin-bottom:6px}
.detect-card input,.detect-card textarea{width:100%;padding:12px 14px;background:var(--bg);border:1px solid var(--border);border-radius:10px;color:var(--text);font-size:.92em;outline:none;transition:border-color .3s}
.detect-card input:focus,.detect-card textarea:focus{border-color:var(--primary)}
.detect-card textarea{resize:vertical;min-height:150px;font-family:monospace;font-size:.82em}
.checkbox-row{display:flex;align-items:center;gap:8px;margin:10px 0;font-size:.85em;color:var(--text2)}
.checkbox-row input{width:16px;height:16px;accent-color:var(--primary)}
.media-item{background:var(--bg);border:1px solid var(--border);border-radius:12px;padding:14px;margin-bottom:10px}
.media-item-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.media-type{display:inline-block;padding:2px 8px;border-radius:5px;font-size:.72em;font-weight:600}
.type-audio{background:#2d6a4f;color:#95d5b2}
.type-video{background:#7b2cbf;color:#c77dff}
.type-stream{background:#e76f51;color:#f4a261}
.type-unknown{background:#555;color:#aaa}
.media-source{font-size:.72em;color:var(--text2);background:rgba(255,255,255,.05);padding:2px 6px;border-radius:4px}
.media-url{word-break:break-all;font-family:monospace;font-size:.78em;color:#8ecae6;background:var(--bg2);padding:8px 10px;border-radius:8px;margin-bottom:10px;cursor:pointer;user-select:all}
.media-player{width:100%;border-radius:8px;outline:none}
.media-actions{display:flex;gap:6px;flex-wrap:wrap}
.filter-bar{display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap}
.filter-chip{padding:5px 12px;border-radius:16px;border:1px solid var(--border);background:transparent;color:var(--text2);font-size:.82em;cursor:pointer;transition:all .2s}
.filter-chip.active{background:var(--primary);border-color:var(--primary);color:#fff}
.results-count{background:var(--primary);padding:3px 10px;border-radius:12px;font-size:.8em;font-weight:600}
.results-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;gap:8px}
.empty-state{text-align:center;padding:40px 20px;color:var(--text2)}
.empty-state .icon{font-size:2.5em;margin-bottom:12px}
.error-msg{background:rgba(225,112,85,.15);border:1px solid rgba(225,112,85,.3);color:#fca5a5;padding:10px 14px;border-radius:10px;margin-bottom:12px;font-size:.88em}

/* 批量下载 */
.download-bar{display:flex;align-items:center;gap:8px;margin-bottom:12px;flex-wrap:wrap}
.download-bar input[type="number"]{width:70px;padding:6px 8px;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:.85em;outline:none;text-align:center}
.download-bar input[type="number"]:focus{border-color:var(--primary)}
.download-bar span{color:var(--text2);font-size:.85em}
.download-progress{width:100%;margin-top:8px;display:none}
.download-progress.active{display:block}
.download-progress .prog-bar{width:100%;height:8px;background:var(--bg3);border-radius:4px;overflow:hidden}
.download-progress .prog-fill{height:100%;background:linear-gradient(90deg,var(--primary),var(--success));border-radius:4px;transition:width .5s;width:0}
.download-progress .prog-text{font-size:.78em;color:var(--text2);margin-top:4px;text-align:center}

/* 隐藏的 audio 元素 */
#hidden-audio{display:none}

/* 滚动条 */
::-webkit-scrollbar{width:4px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:rgba(255,255,255,.1);border-radius:2px}

/* 响应式 */
@media(min-width:481px){.app{border-left:1px solid var(--border);border-right:1px solid var(--border)}}
</style>
</head>
<body>
<div class="app">
  <!-- 顶部栏 -->
  <div class="top-bar">
    <h1 id="top-title">📖 听小说</h1>
    <button class="menu-btn" onclick="showPage('home')" title="返回首页">🏠</button>
  </div>

  <!-- 标签页 -->
  <div class="tabs" id="main-tabs">
    <button class="tab-btn active" onclick="switchMainTab('novel',this)">📖 听小说</button>
    <button class="tab-btn" onclick="switchMainTab('detect',this)">🔍 音频探测</button>
  </div>

  <!-- ====== 听小说页面 ====== -->
  <div class="page active" id="page-novel">
    <!-- 首页：输入URL -->
    <div id="novel-home">
      <div class="input-card">
        <h3>📖 输入小说播放地址</h3>
        <label>支持 i275.com 等小说网站</label>
        <input type="text" id="novel-url-input" placeholder="https://m.i275.com/play/101/132611.html"/>
        <div class="btn-group">
          <button class="btn btn-primary btn-block" onclick="startNovel()">▶ 开始播放</button>
        </div>
        <p style="font-size:.78em;color:var(--text2);margin-top:10px">💡 提示：输入任意章节地址即可，程序会自动加载目录并支持上下章切换</p>
      </div>
      <div id="recent-books"></div>
    </div>

    <!-- 播放器 -->
    <div class="player-section" id="novel-player">
      <div class="book-header">
        <img class="book-cover" id="book-cover" src="" alt="封面" onerror="this.style.display='none'"/>
        <div class="book-info">
          <h2 id="book-title">加载中...</h2>
          <div class="chapter-title" id="current-chapter-title">--</div>
          <div class="meta" id="book-meta">--</div>
        </div>
      </div>

      <div class="player-card">
        <div class="progress-wrap">
          <div class="progress-bar" id="progress-bar" onclick="seekAudio(event)">
            <div class="progress-fill" id="progress-fill"></div>
          </div>
          <div class="progress-time">
            <span id="time-current">00:00</span>
            <span id="time-total">00:00</span>
          </div>
        </div>
        <div class="controls">
          <button class="ctrl-btn" onclick="prevChapter()" title="上一章">⏮</button>
          <button class="ctrl-btn" onclick="seekBack()" title="后退15秒">⏪</button>
          <button class="ctrl-btn play-btn" id="play-btn" onclick="togglePlay()">▶</button>
          <button class="ctrl-btn" onclick="seekForward()" title="快进15秒">⏩</button>
          <button class="ctrl-btn" onclick="nextChapter()" title="下一章">⏭</button>
        </div>
        <div class="extra-controls">
          <button class="speed-btn" onclick="setSpeed(0.75)">0.75x</button>
          <button class="speed-btn active" onclick="setSpeed(1)">1x</button>
          <button class="speed-btn" onclick="setSpeed(1.25)">1.25x</button>
          <button class="speed-btn" onclick="setSpeed(1.5)">1.5x</button>
          <button class="speed-btn" onclick="setSpeed(2)">2x</button>
        </div>
      </div>

      <!-- 章节列表 -->
      <div class="chapter-list-header">
        <h3>📚 章节列表 (<span id="chapter-count">0</span>)</h3>
      </div>
      <div class="download-bar" id="download-bar">
        <button class="btn btn-ghost btn-sm" onclick="toggleDownloadBar()" id="dl-toggle-btn">📥 批量下载</button>
        <div id="dl-range" style="display:none;align-items:center;gap:6px;flex-wrap:wrap">
          <span>从第</span>
          <input type="number" id="dl-start" min="1" value="1"/>
          <span>章到第</span>
          <input type="number" id="dl-end" min="1" value="10"/>
          <span>章</span>
          <button class="btn btn-primary btn-sm" onclick="startBatchDownload()" id="dl-start-btn">⬇ 开始下载</button>
          <button class="btn btn-ghost btn-sm" onclick="document.getElementById('dl-range').style.display='none'">取消</button>
        </div>
      </div>
      <div class="download-progress" id="download-progress">
        <div class="prog-bar"><div class="prog-fill" id="dl-prog-fill"></div></div>
        <div class="prog-text" id="dl-prog-text">准备下载...</div>
      </div>
      <input class="chapter-search" id="chapter-search" placeholder="搜索章节..." oninput="filterChapters()"/>
      <div class="chapter-list" id="chapter-list"></div>
    </div>
  </div>

  <!-- ====== 音频探测页面 ====== -->
  <div class="page" id="page-detect">
    <div class="detect-card">
      <h3>🔗 通过 URL 抓取</h3>
      <label>输入网页地址</label>
      <input type="text" id="detect-url-input" placeholder="https://example.com/page.html"/>
      <div class="checkbox-row"><input type="checkbox" id="analyze-js" checked/><label for="analyze-js">分析外部 JS 文件</label></div>
      <div class="btn-group">
        <button class="btn btn-primary" id="btn-detect-url" onclick="detectFromUrl()">🔍 检测</button>
        <button class="btn btn-ghost" onclick="document.getElementById('detect-url-input').value=''">清空</button>
      </div>
    </div>
    <div class="detect-card">
      <h3>📋 粘贴源码</h3>
      <p style="color:var(--text2);font-size:.82em;margin-bottom:8px">Ctrl+U 查看源码，复制粘贴到下方</p>
      <textarea id="detect-source-input" placeholder="粘贴 HTML 源码..."></textarea>
      <div class="btn-group">
        <button class="btn btn-primary" onclick="detectFromSource()">🔍 检测</button>
        <button class="btn btn-ghost" onclick="document.getElementById('detect-source-input').value=''">清空</button>
      </div>
    </div>
    <div id="detect-warning" style="display:none"></div>
    <div id="detect-results" style="display:none">
      <div class="detect-card">
        <div class="results-header">
          <h3>检测结果</h3>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
            <span class="results-count" id="detect-count">0</span>
            <button class="btn btn-ghost btn-sm" onclick="exportResults()">📥 导出</button>
          </div>
        </div>
        <div class="filter-bar">
          <button class="filter-chip active" onclick="filterDetect('all',this)">全部</button>
          <button class="filter-chip" onclick="filterDetect('audio',this)">🎵 音频</button>
          <button class="filter-chip" onclick="filterDetect('video',this)">🎬 视频</button>
          <button class="filter-chip" onclick="filterDetect('stream',this)">📡 流</button>
        </div>
        <div id="detect-list"></div>
      </div>
    </div>
    <div class="empty-state" id="detect-empty"><div class="icon">🎧</div><p>输入 URL 或粘贴源码检测音频</p></div>
  </div>
</div>

<!-- 加载遮罩 -->
<div class="loading-overlay" id="loading-overlay">
  <div class="spinner"></div>
  <div class="loading-text" id="loading-text">加载中...</div>
</div>

<!-- 提示 -->
<div class="toast" id="toast"></div>

<!-- 隐藏音频 -->
<audio id="hidden-audio" preload="auto"></audio>

<script>
// ====== 全局状态 ======
const audio = document.getElementById('hidden-audio');
let novelState = {
  bookId: null,
  bookTitle: '',
  bookCover: '',
  chapters: [],       // [{id, title}]
  currentIndex: -1,   // 当前章节在 chapters 中的索引
  playing: false,
  speed: 1,
  savingTimer: null
};
let allDetectResults = [];
let currentDetectFilter = 'all';

// ====== 工具函数 ======
function showLoading(show, text) {
  document.getElementById('loading-overlay').classList.toggle('active', show);
  if (text) document.getElementById('loading-text').textContent = text;
}
function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2500);
}
function formatTime(sec) {
  if (!sec || isNaN(sec)) return '00:00';
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return String(m).padStart(2,'0') + ':' + String(s).padStart(2,'0');
}
function esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

// ====== 页面切换 ======
function switchMainTab(name, el) {
  document.querySelectorAll('.tab-btn').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.getElementById('page-' + name).classList.add('active');
  document.getElementById('top-title').textContent = name === 'novel' ? '📖 听小说' : '🔍 音频探测';
}

function showPage(name) {
  if (name === 'home') {
    // 停止播放，回到首页
    audio.pause();
    novelState.playing = false;
    updatePlayBtn();
    document.getElementById('novel-home').style.display = 'block';
    document.getElementById('novel-player').classList.remove('active');
    document.getElementById('main-tabs').style.display = 'flex';
    loadRecentBooks();
  }
}

// ====== 听小说功能 ======
async function startNovel() {
  const url = document.getElementById('novel-url-input').value.trim();
  if (!url) { showToast('请输入播放地址'); return; }

  // 解析 URL
  const m = url.match(/i275\.com\/play\/(\d+)\/(\d+)/);
  if (!m) { showToast('请输入有效的 i275.com 播放地址'); return; }

  const bookId = m[1];
  const chapterId = m[2];

  showLoading(true, '正在加载书籍信息...');
  novelState.bookId = bookId;

  try {
    // 并行加载书籍信息和章节列表
    const [infoRes, chaptersRes] = await Promise.all([
      fetch('/api/novel/info?book_id=' + bookId),
      fetch('/api/novel/chapters?book_id=' + bookId)
    ]);

    const info = await infoRes.json();
    const chaptersData = await chaptersRes.json();

    if (chaptersData.error) {
      showLoading(false);
      showToast('加载失败: ' + chaptersData.error);
      return;
    }

    novelState.bookTitle = info.title || ('书籍 ' + bookId);
    novelState.bookCover = info.cover || '';
    novelState.chapters = chaptersData.chapters || [];

    // 找到当前章节的索引
    let idx = novelState.chapters.findIndex(c => c.id === chapterId);
    if (idx === -1) {
      // 如果目录中没有该章节，尝试加载进度中的章节
      const progress = await (await fetch('/api/novel/progress?book_id=' + bookId)).json();
      if (progress.chapter_id) {
        idx = novelState.chapters.findIndex(c => c.id === progress.chapter_id);
      }
      if (idx === -1) idx = 0; // 默认第一章
    }

    novelState.currentIndex = idx;

    // 更新UI
    document.getElementById('book-title').textContent = novelState.bookTitle;
    document.getElementById('book-cover').src = novelState.bookCover;
    document.getElementById('book-meta').textContent = '共 ' + novelState.chapters.length + ' 章';
    document.getElementById('chapter-count').textContent = novelState.chapters.length;

    renderChapterList();

    // 切换到播放器界面
    document.getElementById('novel-home').style.display = 'none';
    document.getElementById('novel-player').classList.add('active');
    document.getElementById('main-tabs').style.display = 'none';

    // 播放当前章节
    await playChapter(idx);

  } catch (e) {
    showLoading(false);
    showToast('加载失败: ' + e.message);
  }
}

function renderChapterList() {
  const list = document.getElementById('chapter-list');
  const chapters = novelState.chapters;
  list.innerHTML = chapters.map((ch, i) => {
    const active = i === novelState.currentIndex ? ' active' : '';
    return '<div class="chapter-item' + active + '" data-idx="' + i + '" onclick="jumpToChapter(' + i + ')">' +
      '<span class="ch-num">' + (i + 1) + '</span>' +
      '<span class="ch-title">' + esc(ch.title) + '</span>' +
      '<span class="ch-playing">♪</span></div>';
  }).join('');
}

function filterChapters() {
  const keyword = document.getElementById('chapter-search').value.trim().toLowerCase();
  const items = document.querySelectorAll('.chapter-item');
  items.forEach(item => {
    const idx = parseInt(item.dataset.idx);
    const title = novelState.chapters[idx].title.toLowerCase();
    const num = String(idx + 1);
    item.style.display = (!keyword || title.includes(keyword) || num.includes(keyword)) ? '' : 'none';
  });
}

async function jumpToChapter(idx) {
  if (idx < 0 || idx >= novelState.chapters.length) return;
  novelState.currentIndex = idx;
  await playChapter(idx);
}

async function playChapter(idx) {
  if (idx < 0 || idx >= novelState.chapters.length) return;

  const chapter = novelState.chapters[idx];
  novelState.currentIndex = idx;

  // 更新UI
  document.getElementById('current-chapter-title').textContent = '第 ' + (idx + 1) + ' 章：' + chapter.title;
  document.getElementById('progress-fill').style.width = '0%';
  document.getElementById('time-current').textContent = '00:00';
  document.getElementById('time-total').textContent = '加载中...';

  // 高亮当前章节
  document.querySelectorAll('.chapter-item').forEach((el, i) => {
    el.classList.toggle('active', i === idx);
  });

  // 滚动到当前章节
  const activeItem = document.querySelector('.chapter-item.active');
  if (activeItem) activeItem.scrollIntoView({ behavior: 'smooth', block: 'center' });

  showLoading(true, '正在加载音频...');

  try {
    const res = await fetch('/api/novel/audio', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ book_id: novelState.bookId, chapter_id: chapter.id })
    });
    const data = await res.json();

    if (data.error) {
      showLoading(false);
      showToast('加载音频失败: ' + data.error);
      return;
    }

    // 设置音频源
    audio.src = data.audio_url;
    audio.playbackRate = novelState.speed;

    // 检查是否有保存的进度
    const progressRes = await fetch('/api/novel/progress?book_id=' + novelState.bookId);
    const progress = await progressRes.json();
    if (progress.chapter_id === chapter.id && progress.position > 0) {
      audio.addEventListener('loadedmetadata', function onLoaded() {
        audio.removeEventListener('loadedmetadata', onLoaded);
        audio.currentTime = progress.position;
        showToast('已恢复播放进度 ' + formatTime(progress.position));
      });
    }

    audio.play().then(() => {
      novelState.playing = true;
      updatePlayBtn();
    }).catch(e => {
      showToast('播放失败，请重试');
    });

    showLoading(false);
  } catch (e) {
    showLoading(false);
    showToast('请求失败: ' + e.message);
  }
}

function togglePlay() {
  if (!audio.src) return;
  if (audio.paused) {
    audio.play().then(() => {
      novelState.playing = true;
      updatePlayBtn();
    });
  } else {
    audio.pause();
    novelState.playing = false;
    updatePlayBtn();
  }
}

function updatePlayBtn() {
  document.getElementById('play-btn').textContent = novelState.playing ? '⏸' : '▶';
}

function seekAudio(e) {
  if (!audio.duration) return;
  const bar = document.getElementById('progress-bar');
  const rect = bar.getBoundingClientRect();
  const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
  audio.currentTime = pct * audio.duration;
}

function seekBack() { if (audio.src) audio.currentTime = Math.max(0, audio.currentTime - 15); }
function seekForward() { if (audio.src) audio.currentTime = Math.min(audio.duration || 0, audio.currentTime + 15); }

function setSpeed(s) {
  novelState.speed = s;
  audio.playbackRate = s;
  document.querySelectorAll('.speed-btn').forEach(b => {
    b.classList.toggle('active', parseFloat(b.textContent) === s);
  });
}

async function prevChapter() {
  if (novelState.currentIndex > 0) {
    saveCurrentProgress();
    await playChapter(novelState.currentIndex - 1);
  } else {
    showToast('已经是第一章了');
  }
}

async function nextChapter() {
  if (novelState.currentIndex < novelState.chapters.length - 1) {
    saveCurrentProgress();
    await playChapter(novelState.currentIndex + 1);
  } else {
    showToast('已经是最后一章了');
  }
}

// 自动播放下一章（使用多种检测方式确保后台也能工作）
audio.addEventListener('ended', handleAudioEnded);

// 后台播放检测：定时器检测播放结束（解决息屏时 ended 事件不触发的问题）
let bgCheckTimer = null;
let lastCheckTime = 0;
let lastCheckPos = 0;

function startBgCheck() {
  stopBgCheck();
  lastCheckTime = Date.now();
  lastCheckPos = audio.currentTime || 0;
  bgCheckTimer = setInterval(() => {
    if (!audio.src || audio.paused) return;
    const now = Date.now();
    const pos = audio.currentTime || 0;
    const duration = audio.duration || 0;
    
    // 检测1：播放位置接近结尾（剩余小于1秒）
    if (duration > 0 && pos > 0 && (duration - pos) < 1) {
      console.log('[BG] 检测到即将播放结束，准备切换下一章');
      handleAudioEnded();
      return;
    }
    
    // 检测2：播放位置没有变化超过5秒（可能已结束但事件未触发）
    if (pos === lastCheckPos && !audio.paused) {
      const elapsed = (now - lastCheckTime) / 1000;
      if (elapsed > 5 && duration > 0 && pos >= duration - 2) {
        console.log('[BG] 播放位置停滞，可能已结束');
        handleAudioEnded();
        return;
      }
    } else {
      lastCheckTime = now;
      lastCheckPos = pos;
    }
  }, 2000); // 每2秒检测一次
}

function stopBgCheck() {
  if (bgCheckTimer) {
    clearInterval(bgCheckTimer);
    bgCheckTimer = null;
  }
}

async function handleAudioEnded() {
  // 防止重复触发
  if (audio._endingHandled) return;
  audio._endingHandled = true;
  setTimeout(() => { audio._endingHandled = false; }, 3000);
  
  if (novelState.currentIndex < novelState.chapters.length - 1) {
    saveCurrentProgress();
    try {
      await playChapter(novelState.currentIndex + 1);
    } catch (e) {
      console.error('[BG] 自动切换下一章失败:', e);
    }
  } else {
    novelState.playing = false;
    updatePlayBtn();
    showToast('本书已听完！');
  }
}

// 播放时启动后台检测
audio.addEventListener('play', () => {
  startBgCheck();
});

// 暂停时停止后台检测
audio.addEventListener('pause', () => {
  stopBgCheck();
});

// 更新进度条
audio.addEventListener('timeupdate', () => {
  if (!audio.duration) return;
  const pct = (audio.currentTime / audio.duration) * 100;
  document.getElementById('progress-fill').style.width = pct + '%';
  document.getElementById('time-current').textContent = formatTime(audio.currentTime);
});

audio.addEventListener('loadedmetadata', () => {
  document.getElementById('time-total').textContent = formatTime(audio.duration);
});

audio.addEventListener('error', () => {
  showToast('音频加载失败');
});

// 定时保存进度
function saveCurrentProgress() {
  if (!novelState.bookId || novelState.currentIndex < 0) return;
  const chapter = novelState.chapters[novelState.currentIndex];
  if (!chapter) return;

  const position = audio.currentTime || 0;
  fetch('/api/novel/progress', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      book_id: novelState.bookId,
      chapter_id: chapter.id,
      position: Math.floor(position)
    })
  });
}

// 每 5 秒自动保存进度
setInterval(() => {
  if (novelState.playing && audio.src) {
    saveCurrentProgress();
  }
}, 5000);

// 页面关闭时保存
window.addEventListener('beforeunload', () => {
  saveCurrentProgress();
});

// 加载最近播放的书籍
async function loadRecentBooks() {
  try {
    const res = await fetch('/api/novel/progress');
    const data = await res.json();
    const container = document.getElementById('recent-books');
    const entries = Object.entries(data).filter(([k, v]) => v.chapter_id);

    if (!entries.length) {
      container.innerHTML = '';
      return;
    }

    let html = '<div class="input-card"><h3>📖 最近播放</h3>';
    entries.forEach(([bookId, progress]) => {
      html += '<div style="display:flex;align-items:center;justify-content:space-between;padding:10px 0;border-bottom:1px solid var(--border);cursor:pointer" onclick="resumeBook(\'' + bookId + '\')">' +
        '<div><div style="font-size:.9em;font-weight:500">书籍 ' + bookId + '</div>' +
        '<div style="font-size:.78em;color:var(--text2)">上次播放：' + (progress.updated || '未知') + '</div></div>' +
        '<span style="color:var(--accent);font-size:.85em">继续 ▶</span></div>';
    });
    html += '</div>';
    container.innerHTML = html;
  } catch (e) {
    console.error('加载最近播放失败', e);
  }
}

async function resumeBook(bookId) {
  showLoading(true, '正在恢复播放...');
  novelState.bookId = bookId;

  try {
    const [infoRes, chaptersRes, progressRes] = await Promise.all([
      fetch('/api/novel/info?book_id=' + bookId),
      fetch('/api/novel/chapters?book_id=' + bookId),
      fetch('/api/novel/progress?book_id=' + bookId)
    ]);

    const info = await infoRes.json();
    const chaptersData = await chaptersRes.json();
    const progress = await progressRes.json();

    if (chaptersData.error) {
      showLoading(false);
      showToast('加载失败: ' + chaptersData.error);
      return;
    }

    novelState.bookTitle = info.title || ('书籍 ' + bookId);
    novelState.bookCover = info.cover || '';
    novelState.chapters = chaptersData.chapters || [];

    let idx = 0;
    if (progress.chapter_id) {
      idx = novelState.chapters.findIndex(c => c.id === progress.chapter_id);
      if (idx === -1) idx = 0;
    }

    novelState.currentIndex = idx;

    document.getElementById('book-title').textContent = novelState.bookTitle;
    document.getElementById('book-cover').src = novelState.bookCover;
    document.getElementById('book-meta').textContent = '共 ' + novelState.chapters.length + ' 章';
    document.getElementById('chapter-count').textContent = novelState.chapters.length;

    renderChapterList();

    document.getElementById('novel-home').style.display = 'none';
    document.getElementById('novel-player').classList.add('active');
    document.getElementById('main-tabs').style.display = 'none';

    await playChapter(idx);
  } catch (e) {
    showLoading(false);
    showToast('恢复失败: ' + e.message);
  }
}

// ====== 音频探测功能 ======
async function detectFromUrl() {
  const url = document.getElementById('detect-url-input').value.trim();
  if (!url) { showToast('请输入网页地址'); return; }
  const aj = document.getElementById('analyze-js').checked;
  showLoading(true, '正在抓取网页...');
  allDetectResults = [];
  try {
    const r = await fetch('/api/detect', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ url, analyze_js: aj })
    });
    const d = await r.json();
    if (d.error) { showLoading(false); showToast('抓取失败: ' + d.error); return; }
    allDetectResults = d.results || [];
    const w = document.getElementById('detect-warning');
    if (d.spa_warning) { w.style.display = 'block'; w.className = 'error-msg'; w.textContent = '⚠️ ' + d.spa_warning; }
    else { w.style.display = 'none'; }
    renderDetectResults();
  } catch (e) { showToast('请求失败: ' + e.message); }
  showLoading(false);
}

async function detectFromSource() {
  const html = document.getElementById('detect-source-input').value.trim();
  if (!html) { showToast('请粘贴网页源码'); return; }
  showLoading(true, '正在分析源码...');
  allDetectResults = [];
  try {
    const r = await fetch('/api/detect', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ html })
    });
    const d = await r.json();
    allDetectResults = d.results || [];
    document.getElementById('detect-warning').style.display = 'none';
    renderDetectResults();
  } catch (e) { showToast('分析失败: ' + e.message); }
  showLoading(false);
}

function renderDetectResults(f) {
  f = f || currentDetectFilter;
  const list = document.getElementById('detect-list');
  const sec = document.getElementById('detect-results');
  const emp = document.getElementById('detect-empty');
  const cnt = document.getElementById('detect-count');
  let fl = allDetectResults;
  if (f !== 'all') fl = allDetectResults.filter(r => r.type === f);
  if (!fl.length) {
    sec.style.display = 'none';
    emp.style.display = 'block';
    return;
  }
  sec.style.display = 'block';
  emp.style.display = 'none';
  cnt.textContent = fl.length;
  list.innerHTML = fl.map((item, i) => {
    const bc = item.type === 'audio' ? 'type-audio' : item.type === 'video' ? 'type-video' : item.type === 'stream' ? 'type-stream' : 'type-unknown';
    const tl = item.type === 'audio' ? '🎵 音频' : item.type === 'video' ? '🎬 视频' : item.type === 'stream' ? '📡 流' : '❓';
    const isA = item.type === 'audio' || /^(mp3|m4a|aac|ogg|wav|flac|opus|wma)$/i.test(item.ext || '');
    let p = '';
    if (isA) p = '<audio class="media-player" controls preload="metadata"><source src="' + esc(item.url) + '"></audio>';
    return '<div class="media-item"><div class="media-item-header"><div><span class="media-type ' + bc + '">' + tl + '</span> <span class="media-source">' + esc(item.source) + '</span></div></div>' +
      '<div class="media-url" onclick="copyText(this.textContent)" title="点击复制">' + esc(item.url) + '</div>' + p +
      '<div class="media-actions"><button class="btn btn-ghost btn-sm" onclick="window.open(\'' + esc(item.url) + '\')">🔗 新窗口</button>' +
      '<button class="btn btn-ghost btn-sm" onclick="copyText(\'' + esc(item.url) + '\')">📋 复制</button></div></div>';
  }).join('');
}

function filterDetect(t, el) {
  currentDetectFilter = t;
  document.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
  el.classList.add('active');
  renderDetectResults(t);
}

function copyText(t) {
  navigator.clipboard.writeText(t).then(() => showToast('已复制')).catch(() => {
    const a = document.createElement('textarea');
    a.value = t;
    document.body.appendChild(a);
    a.select();
    document.execCommand('copy');
    document.body.removeChild(a);
    showToast('已复制');
  });
}

function exportResults() {
  if (!allDetectResults.length) { showToast('无结果'); return; }
  let t = '音频检测结果\n时间: ' + new Date().toLocaleString() + '\n共 ' + allDetectResults.length + ' 个资源\n\n';
  allDetectResults.forEach((r, i) => {
    t += '#' + (i + 1) + ' [' + r.type + ']\n' + r.url + '\n\n';
  });
  const b = new Blob([t], { type: 'text/plain;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(b);
  a.download = 'audio-' + Date.now() + '.txt';
  a.click();
  showToast('导出成功');
}

// ====== 批量下载 ======
function toggleDownloadBar() {
  const range = document.getElementById('dl-range');
  const total = novelState.chapters.length;
  if (!total) { showToast('请先加载书籍'); return; }
  if (range.style.display === 'none') {
    range.style.display = 'flex';
    document.getElementById('dl-end').value = total;
    document.getElementById('dl-end').max = total;
    document.getElementById('dl-start').max = total;
  } else {
    range.style.display = 'none';
  }
}

async function startBatchDownload() {
  const startIdx = parseInt(document.getElementById('dl-start').value) - 1;
  const endIdx = parseInt(document.getElementById('dl-end').value) - 1;
  const total = novelState.chapters.length;

  if (isNaN(startIdx) || isNaN(endIdx)) { showToast('请输入有效的章节范围'); return; }
  if (startIdx < 0 || endIdx >= total || startIdx > endIdx) {
    showToast('章节范围无效'); return;
  }

  const count = endIdx - startIdx + 1;
  if (count > 500) { showToast('单次最多下载500章'); return; }

  const progDiv = document.getElementById('download-progress');
  const progFill = document.getElementById('dl-prog-fill');
  const progText = document.getElementById('dl-prog-text');
  const dlBtn = document.getElementById('dl-start-btn');

  progDiv.classList.add('active');
  progFill.style.width = '0%';
  progText.textContent = '正在打包 ' + count + ' 章音频，请耐心等待...';
  dlBtn.disabled = true;
  dlBtn.textContent = '⏳ 打包中...';

  try {
    const res = await fetch('/api/novel/batch-download', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        book_id: novelState.bookId,
        start_idx: startIdx,
        end_idx: endIdx,
        book_title: novelState.bookTitle
      })
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || '下载失败');
    }

    // 获取文件名
    const cd = res.headers.get('Content-Disposition') || '';
    const fm = cd.match(/filename\*?=(?:UTF-8''|"?)([^";]+)/i);
    const filename = fm ? decodeURIComponent(fm[1].replace(/"/g, '')) : 'novel.zip';

    // 流式读取并显示进度
    const contentLength = res.headers.get('Content-Length');
    const reader = res.body.getReader();
    const chunks = [];
    let received = 0;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
      received += value.length;
      if (contentLength) {
        const pct = Math.round((received / parseInt(contentLength)) * 100);
        progFill.style.width = pct + '%';
        progText.textContent = '下载中... ' + (received / 1024 / 1024).toFixed(1) + 'MB / ' + (parseInt(contentLength) / 1024 / 1024).toFixed(1) + 'MB';
      } else {
        progText.textContent = '下载中... ' + (received / 1024 / 1024).toFixed(1) + 'MB';
      }
    }

    progFill.style.width = '100%';
    progText.textContent = '下载完成！正在保存...';

    // 创建 Blob 并下载
    const blob = new Blob(chunks, { type: 'application/zip' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);

    progText.textContent = '✅ 下载完成！共 ' + count + ' 章';
    showToast('下载完成！');
  } catch (e) {
    progText.textContent = '❌ ' + e.message;
    showToast('下载失败: ' + e.message);
  } finally {
    dlBtn.disabled = false;
    dlBtn.textContent = '⬇ 开始下载';
    setTimeout(() => { progDiv.classList.remove('active'); }, 5000);
  }
}

// ====== 初始化 ======
document.getElementById('novel-url-input').addEventListener('keydown', e => { if (e.key === 'Enter') startNovel(); });
document.getElementById('detect-url-input').addEventListener('keydown', e => { if (e.key === 'Enter') detectFromUrl(); });
loadRecentBooks();

// ====== Wake Lock（防止息屏冻结） ======
let wakeLock = null;

async function requestWakeLock() {
  if ('wakeLock' in navigator) {
    try {
      wakeLock = await navigator.wakeLock.request('screen');
      console.log('[WakeLock] 已获取屏幕唤醒锁');
      wakeLock.addEventListener('release', () => {
        console.log('[WakeLock] 屏幕唤醒锁已释放');
      });
    } catch (e) {
      console.log('[WakeLock] 无法获取唤醒锁:', e.message);
    }
  }
}

function releaseWakeLock() {
  if (wakeLock) {
    wakeLock.release();
    wakeLock = null;
  }
}

// 页面可见性变化时重新获取 Wake Lock
document.addEventListener('visibilitychange', async () => {
  if (document.visibilityState === 'visible' && novelState.playing) {
    await requestWakeLock();
  }
});

// 播放时请求 Wake Lock
audio.addEventListener('play', async () => {
  await requestWakeLock();
});

// 暂停时释放 Wake Lock
audio.addEventListener('pause', () => {
  releaseWakeLock();
});

// 媒体会话 API（锁屏/通知栏控制）
if ('mediaSession' in navigator) {
  navigator.mediaSession.setActionHandler('play', () => togglePlay());
  navigator.mediaSession.setActionHandler('pause', () => togglePlay());
  navigator.mediaSession.setActionHandler('previoustrack', () => prevChapter());
  navigator.mediaSession.setActionHandler('nexttrack', () => nextChapter());
  navigator.mediaSession.setActionHandler('seekbackward', () => seekBack());
  navigator.mediaSession.setActionHandler('seekforward', () => seekForward());
}

audio.addEventListener('play', () => {
  if ('mediaSession' in navigator) {
    navigator.mediaSession.metadata = new MediaMetadata({
      title: novelState.chapters[novelState.currentIndex]?.title || '未知章节',
      artist: novelState.bookTitle,
      album: '听小说'
    });
  }
});
</script>
</body>
</html>"""

# ============================================================
# Flask 路由
# ============================================================
@app.route('/')
def index():
    return Response(HTML_PAGE, content_type='text/html; charset=utf-8')


# ====== 听小说 API ======
@app.route('/api/novel/info')
def api_novel_info():
    """获取书籍信息"""
    book_id = flask_request.args.get('book_id', '').strip()
    if not book_id:
        return jsonify({'error': '缺少 book_id'}), 400
    info = i275_get_book_info(book_id)
    return jsonify(info)


@app.route('/api/novel/chapters')
def api_novel_chapters():
    """获取章节列表"""
    book_id = flask_request.args.get('book_id', '').strip()
    if not book_id:
        return jsonify({'error': '缺少 book_id'}), 400
    chapters = i275_get_chapter_list(book_id)
    return jsonify({'chapters': chapters, 'total': len(chapters)})


@app.route('/api/novel/audio', methods=['POST'])
def api_novel_audio():
    """获取章节音频 URL"""
    data = flask_request.get_json(force=True)
    book_id = data.get('book_id', '').strip()
    chapter_id = data.get('chapter_id', '').strip()
    if not book_id or not chapter_id:
        return jsonify({'error': '缺少参数'}), 400

    audio_url, error = i275_get_audio_url(book_id, chapter_id)
    if error:
        return jsonify({'error': error, 'audio_url': None})
    return jsonify({'audio_url': audio_url, 'error': None})


@app.route('/api/novel/progress', methods=['GET'])
def api_novel_progress_get():
    """获取播放进度"""
    book_id = flask_request.args.get('book_id', '').strip()
    if book_id:
        progress = get_book_progress(book_id)
        return jsonify(progress)
    else:
        # 返回所有书籍的进度
        all_progress = load_progress()
        return jsonify(all_progress)


@app.route('/api/novel/progress', methods=['POST'])
def api_novel_progress_save():
    """保存播放进度"""
    data = flask_request.get_json(force=True)
    book_id = data.get('book_id', '').strip()
    chapter_id = data.get('chapter_id', '').strip()
    position = data.get('position', 0)

    if not book_id or not chapter_id:
        return jsonify({'error': '缺少参数'}), 400

    update_book_progress(book_id, chapter_id, position)
    return jsonify({'status': 'ok'})


# ====== 音频探测 API ======
@app.route('/api/detect', methods=['POST'])
def api_detect():
    data = flask_request.get_json(force=True)
    url = data.get('url', '').strip()
    html = data.get('html', '').strip()
    analyze_js = data.get('analyze_js', True)

    if not url and not html:
        return jsonify({'error': '请提供 URL 或 HTML 源码', 'results': []}), 400

    if url:
        page = fetch_page(url)
        if page['error']:
            return jsonify({'error': page['error'], 'results': [], 'final_url': url})

        html = page['html']
        base_url = page['final_url']

        original_path = urlparse(url).path.rstrip('/')
        final_path = urlparse(base_url).path.rstrip('/')
        spa_warning = ''
        if original_path != final_path and final_path in ('', '/'):
            spa_warning = '该网站可能是 SPA（单页应用），服务端返回了首页。建议：1) 勾选"分析JS文件"；2) 使用"粘贴源码"模式。'

        js_contents = []
        if analyze_js and page['js_urls']:
            for js_url in page['js_urls'][:20]:
                content = fetch_js_content(js_url)
                if content:
                    js_contents.append({'url': js_url, 'content': content})

        results = detect_media(html, base_url, js_contents)
        return jsonify({
            'error': None, 'results': results, 'final_url': base_url,
            'js_analyzed': len(js_contents), 'js_total': len(page['js_urls']),
            'spa_warning': spa_warning,
        })
    else:
        results = detect_media(html)
        return jsonify({'error': None, 'results': results, 'final_url': '', 'js_analyzed': 0, 'js_total': 0})


# ====== 批量下载 API ======
@app.route('/api/novel/batch-download', methods=['POST'])
def api_novel_batch_download():
    """批量下载章节音频，打包为 ZIP"""
    data = flask_request.get_json(force=True)
    book_id = data.get('book_id', '').strip()
    start_idx = data.get('start_idx', 0)
    end_idx = data.get('end_idx', 0)
    book_title = data.get('book_title', '小说')

    if not book_id:
        return jsonify({'error': '缺少 book_id'}), 400

    # 获取章节列表
    chapters = i275_get_chapter_list(book_id)
    if not chapters:
        return jsonify({'error': '无法获取章节列表'}), 400

    # 校验范围
    start_idx = max(0, min(start_idx, len(chapters) - 1))
    end_idx = max(0, min(end_idx, len(chapters) - 1))
    if start_idx > end_idx:
        start_idx, end_idx = end_idx, start_idx

    selected = chapters[start_idx:end_idx + 1]
    total = len(selected)

    if total > 500:
        return jsonify({'error': f'单次最多下载500章，当前选择了{total}章'}), 400

    # 生成 ZIP（流式）
    safe_title = re.sub(r'[\\/:*?"<>|]', '_', book_title)[:50]
    zip_filename = f'{safe_title}_第{start_idx+1}-{end_idx+1}章.zip'

    def generate_zip():
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for i, ch in enumerate(selected):
                try:
                    audio_url, err = i275_get_audio_url(book_id, ch['id'])
                    if err or not audio_url:
                        logger.warning(f'跳过章节 {ch["id"]}: {err}')
                        continue

                    # 下载音频
                    resp = requests.get(audio_url, headers=HEADERS, timeout=60, stream=True, verify=False)
                    if resp.status_code != 200:
                        logger.warning(f'下载失败 {ch["id"]}: HTTP {resp.status_code}')
                        continue

                    # 确定文件扩展名
                    ext = '.m4a'
                    path_lower = urlparse(audio_url).path.lower()
                    for e in ['.mp3', '.m4a', '.aac', '.ogg', '.wav', '.flac']:
                        if e in path_lower:
                            ext = e
                            break

                    # 文件名：序号_章节标题.ext（清理特殊字符）
                    safe_ch_title = re.sub(r'[\\/:*?"<>|]', '_', ch['title'])[:80]
                    fname = f'{start_idx + i + 1:04d}_{safe_ch_title}{ext}'

                    # 写入 ZIP
                    audio_data = resp.content
                    zf.writestr(fname, audio_data)
                    logger.info(f'已添加 {fname} ({len(audio_data)//1024}KB) [{i+1}/{total}]')

                except Exception as e:
                    logger.warning(f'处理章节 {ch["id"]} 失败: {e}')
                    continue

        buf.seek(0)
        yield buf.read()

    return Response(
        generate_zip(),
        content_type='application/zip',
        headers={
            'Content-Disposition': f'attachment; filename="{quote(zip_filename)}"',
            'Cache-Control': 'no-cache',
        }
    )


@app.route('/api/proxy-download')
def proxy_download():
    url = flask_request.args.get('url', '')
    if not url:
        return 'Missing URL', 400
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30, stream=True, verify=False)
        ct = resp.headers.get('Content-Type', 'application/octet-stream')
        fn = url.split('/')[-1].split('?')[0] or 'download'
        def gen():
            for chunk in resp.iter_content(chunk_size=8192):
                yield chunk
        return Response(gen(), content_type=ct, headers={'Content-Disposition': f'attachment; filename="{fn}"'})
    except Exception as e:
        return f'Download failed: {e}', 500


# ============================================================
# 启动
# ============================================================
if __name__ == '__main__':
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    print('=' * 50)
    print('📖 听小说 + 🎵 音频探测器 已启动')
    print('📍 访问地址: http://localhost:8080')
    print('=' * 50)
    app.run(host='0.0.0.0', port=8080, debug=True)