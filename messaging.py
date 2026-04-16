"""
消息平台 API — 文本/图片/视频/文件/链接/GIF/语音发送 + CDN 上传/下载

所有与消息平台的交互都在此文件中。其他模块只需调用这里的函数。

功能模块:
1. 初始化配置 (init)
2. 底层 API 调用 (api) — 自动重试机制
3. 文本发送 (send_text)
4. CDN 上传 (upload) — 支持 URL 和本地文件
5. 媒体发送 (send_image/send_video/send_file/send_gif/send_voice/send_link)
6. 上传 + 发送一体化 (upload_and_send)
7. 媒体下载 (download_media/download_wx/download_wx_work)
8. 联系人信息 (get_contact_info)
9. 位置发送 (send_location)
10. 名片发送 (send_namecard)

依赖：标准库 (json, urllib, os, time, logging, http.client)

设计原则:
- 零外部依赖
- 自动重试（3 次，指数退避）
- 流式上传（恒定内存占用）
- 智能文件类型识别
- 统一的错误处理
"""

import http.client
import json
import logging
import os
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

log = logging.getLogger("agent")

# ============================================================
#  Initialization (called by main entry point)
# ============================================================

_config = {}  # messaging config dict
_file_api_url = ""


def init(messaging_config):
    """Initialize messaging platform config. Called once at startup."""
    global _config, _file_api_url
    _config = messaging_config
    _file_api_url = messaging_config.get("file_api_url",
                                          "https://api.messaging-platform.example.com/doFileApi")


# ============================================================
#  Low-level API Call
# ============================================================

def api(method, params):
    """调用消息平台 API（网络错误时自动重试 3 次，指数退避）
    
    所有消息平台 API 调用的统一入口。
    处理认证、重试、错误日志等通用逻辑。
    
    参数:
        method: API 方法名（如 "/msg/sendText"）
        params: 方法参数（会自动添加 guid）
    
    返回:
        dict: API 响应结果，包含 code 和 msg/data 等字段
    
    重试机制:
        - 最大重试次数：3 次
        - 退避延迟：2s -> 4s -> 8s（指数增长）
        - 仅对网络错误重试（URLError, OSError, TimeoutError）
        - 其他错误直接返回
    
    认证处理:
        - 自动添加 guid 到参数
        - X-API-TOKEN 请求头认证
    
    错误处理:
        - 网络错误：重试后返回 code=-1
        - API 错误：记录日志并返回原始结果
        - 未知错误：记录日志并返回 code=-1
    
    日志记录:
        - 警告：重试时的网络错误
        - 错误：最终失败或 API 返回非 0 code
    """
    params["guid"] = _config["guid"]
    body = json.dumps({"method": method, "params": params}).encode("utf-8")

    max_retries = 3
    backoff_delays = [2, 4, 8]  # 指数退避延迟序列

    for attempt in range(max_retries + 1):
        req = urllib.request.Request(
            _config["api_url"],
            data=body,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "X-API-TOKEN": _config["token"],
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
                if result.get("code") != 0:
                    log.error(f"[messaging] {method} failed: {result}")
                return result
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            if attempt < max_retries:
                delay = backoff_delays[attempt]
                log.warning("[messaging] %s network error (attempt %d/%d), retry in %ds: %s",
                            method, attempt + 1, max_retries, delay, e)
                time.sleep(delay)
                continue
            log.error(f"[messaging] {method} error after {max_retries} retries: {e}")
            return {"code": -1, "msg": str(e)}
        except Exception as e:
            log.error(f"[messaging] {method} error: {e}")
            return {"code": -1, "msg": str(e)}


# ============================================================
#  Text Send
# ============================================================

def send_text(to_id, content):
    result = api("/msg/sendText", {"toId": str(to_id), "content": content})
    if result.get("code") == 0:
        log.info(f"[messaging] sent to {to_id}: {content[:80]}")
    return result


# ============================================================
#  CDN Upload
# ============================================================

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".avi"}
GIF_EXTS = {".gif"}
VOICE_EXTS = {".amr", ".mp3", ".wav", ".silk"}


def get_ext(filepath):
    """Extract extension from filepath or URL"""
    if filepath.startswith("http://") or filepath.startswith("https://"):
        return os.path.splitext(urlparse(filepath).path)[1].lower()
    return os.path.splitext(filepath)[1].lower()


def _get_file_type(ext):
    """File type for CDN: 1=image, 4=video, 5=file/voice"""
    if ext in IMAGE_EXTS or ext in GIF_EXTS:
        return 1
    if ext in VIDEO_EXTS:
        return 4
    return 5


def _cdn_upload_url(file_url, filename, file_type):
    """Upload to CDN via URL"""
    result = api("/cloud/cdnBigUploadByUrl", {
        "filename": filename, "fileUrl": file_url, "fileType": file_type
    })
    if result.get("code") == 0 and result.get("data", {}).get("fileId"):
        log.info(f"[cdn] URL upload OK: {filename}")
        return result["data"]
    log.error(f"[cdn] URL upload failed: {result}")
    return None


def _cdn_upload_binary(filepath, file_type):
    """流式上传本地文件到 CDN（multipart/form-data）
    
    使用 http.client 实现真正的流式上传：
    - 先计算 Content-Length（表单字段 + 文件头 + 文件大小 + 结尾）
    - 然后分块从磁盘读取文件内容发送到 socket，恒定约 64KB 内存占用
    - 200MB 视频和 200KB 图片使用相同的内存量
    
    参数:
        filepath: 本地文件路径
        file_type: 文件类型（1=图片，4=视频，5=文件/语音）
    
    返回:
        dict: CDN 返回的文件信息（fileId, fileKey 等），失败返回 None
    
    流式上传原理:
        1. 构建 multipart 表单的各个部分（字段、文件头、文件尾）
        2. 计算总 Content-Length（需要精确值）
        3. 建立 HTTP 连接，发送请求头
        4. 发送表单字段和文件头
        5. 分块读取文件内容并发送（64KB/块）
        6. 发送结尾标记
        7. 读取响应并解析
    
    内存优化:
        - 不一次性加载整个文件到内存
        - 使用固定大小的缓冲区（64KB）
        - 适合大文件上传（视频等）
    
    连接管理:
        - HTTPS 使用 SSL 上下文
        - 超时设置 300 秒（5 分钟）
        - 上传完成后关闭连接
    
    日志记录:
        - 大于 50MB 的文件记录流式上传提示
        - 成功记录文件大小
        - 失败记录错误信息
    """
    filename = os.path.basename(filepath)
    file_size = os.path.getsize(filepath)
    boundary = f"----AgentBoundary{int(time.time() * 1000)}"
    CHUNK_SIZE = 65536  # 64KB 分块大小

    # Build multipart parts (构建 multipart 表单各部分)
    field_parts = b""
    for key, val in [("method", "/cloud/cdnBigUpload"), ("guid", _config["guid"]), ("fileType", str(file_type))]:
        field_parts += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{val}\r\n".encode()
    file_header = f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\nContent-Type: application/octet-stream\r\n\r\n".encode()
    file_footer = f"\r\n--{boundary}--\r\n".encode()

    content_length = len(field_parts) + len(file_header) + file_size + len(file_footer)

    if file_size > 50 * 1024 * 1024:
        log.info(f"[cdn] streaming upload: {filename} ({file_size // 1024 // 1024}MB)")

    parsed = urlparse(_file_api_url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"

    try:
        if parsed.scheme == "https":
            import ssl
            conn = http.client.HTTPSConnection(host, port, timeout=300,
                                                context=ssl.create_default_context())
        else:
            conn = http.client.HTTPConnection(host, port, timeout=300)

        conn.putrequest("POST", path)
        conn.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
        conn.putheader("Content-Length", str(content_length))
        conn.putheader("X-API-TOKEN", _config["token"])
        conn.endheaders()

        # Stream: form fields -> file header -> file content (chunked) -> footer
        # 流式发送：表单字段 -> 文件头 -> 文件内容（分块） -> 结尾
        conn.send(field_parts)
        conn.send(file_header)
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                conn.send(chunk)
        conn.send(file_footer)

        resp = conn.getresponse()
        body = resp.read()
        conn.close()

        result = json.loads(body)
        if result.get("code") == 0 and result.get("data", {}).get("fileId"):
            log.info(f"[cdn] upload OK: {filename} ({file_size // 1024}KB)")
            return result["data"]
        log.error(f"[cdn] upload failed: {result}")
        return None
    except Exception as e:
        log.error(f"[cdn] upload error: {e}")
        return None


def upload(filepath, workspace=""):
    """智能上传：URL 使用 URL 上传（失败时降级为下载 + 二进制），本地文件使用二进制上传。
    
    根据文件路径类型自动选择最优上传策略。
    
    参数:
        filepath: 文件路径或 URL
        workspace: 工作区路径（用于解析相对路径）
    
    返回:
        dict: CDN 文件信息，失败返回 None
    
    上传策略:
        1. URL 文件:
           - 优先使用 URL 直接上传（CDN 拉取）
           - 失败时下载到临时文件，再二进制上传
           - 视频上传失败时尝试降级为文件类型
        
        2. 本地文件:
           - 解析相对路径（相对于 workspace）
           - 检查文件存在性
           - 二进制流式上传
           - 视频上传失败时尝试降级为文件类型
    
    文件类型识别:
        - 图片：.jpg, .jpeg, .png, .webp, .bmp, .gif -> type=1
        - 视频：.mp4, .mov, .avi -> type=4
        - 其他：.amr, .mp3, .wav, .silk 及所有其他文件 -> type=5
    
    错误处理:
        - URL 下载失败：记录错误，返回 None
        - 文件不存在：记录错误，返回 None
        - 上传失败：尝试降级类型（视频->文件）
        - 临时文件：上传后自动清理
    
    使用场景:
        - 发送网络图片/视频
        - 发送本地生成的文件
        - 发送用户下载的资源
    """
    ext = get_ext(filepath)
    file_type = _get_file_type(ext)
    is_url = filepath.startswith("http://") or filepath.startswith("https://")

    if is_url:
        # URL 上传流程
        filename = os.path.basename(urlparse(filepath).path) or f"file{ext}"
        cdn = _cdn_upload_url(filepath, filename, file_type)
        if not cdn:
            log.info("[cdn] URL upload failed, downloading to local...")
            try:
                tmp_path = f"/tmp/agent-dl-{int(time.time())}{ext}"
                urllib.request.urlretrieve(filepath, tmp_path)
                cdn = _cdn_upload_binary(tmp_path, file_type)
                if not cdn and file_type == 4:
                    cdn = _cdn_upload_binary(tmp_path, 5)  # 视频降级为文件类型
                try:
                    os.unlink(tmp_path)  # 清理临时文件
                except Exception:
                    pass
            except Exception as e:
                log.error(f"[cdn] download failed: {e}")
                cdn = None
        return cdn
    else:
        # 本地文件上传流程
        if not os.path.isabs(filepath) and workspace:
            filepath = os.path.join(workspace, filepath)
        if not os.path.exists(filepath):
            log.error(f"[cdn] file not found: {filepath}")
            return None
        cdn = _cdn_upload_binary(filepath, file_type)
        if not cdn and file_type == 4:
            cdn = _cdn_upload_binary(filepath, 5)  # 视频降级为文件类型
        return cdn


# ============================================================
#  Media Send (requires CDN upload first)
# ============================================================

def send_image(to_id, cdn, filename="image.jpg"):
    return api("/msg/sendImage", {
        "toId": str(to_id),
        "fileAesKey": cdn.get("fileAesKey", ""),
        "fileId": cdn.get("fileId", ""),
        "fileKey": cdn.get("fileKey", cdn.get("fileAesKey", "")),
        "fileMd5": cdn.get("fileMd5", ""),
        "fileSize": cdn.get("fileSize", 0),
        "filename": filename,
    })


def send_file(to_id, cdn, filename="file"):
    return api("/msg/sendFile", {
        "toId": str(to_id),
        "fileAesKey": cdn.get("fileAesKey", ""),
        "fileId": cdn.get("fileId", ""),
        "fileSize": cdn.get("fileSize", 0),
        "filename": filename,
    })


def send_video(to_id, cdn, filename="video.mp4"):
    return api("/msg/sendVideo", {
        "toId": str(to_id),
        "fileAesKey": cdn.get("fileAesKey", ""),
        "fileId": cdn.get("fileId", ""),
        "fileMd5": cdn.get("fileMd5", ""),
        "fileSize": cdn.get("fileSize", 0),
        "filename": filename,
        "coverImageSize": cdn.get("fileThumbSize", 0),
        "duration": cdn.get("durationTime", 0),
    })


def send_gif(to_id, cdn):
    if cdn.get("cloudUrl"):
        return api("/msg/sendGif", {"toId": str(to_id), "wxFileUrl": cdn["cloudUrl"]})
    return send_image(to_id, cdn, "image.gif")


def send_voice(to_id, cdn, voice_time=0):
    return api("/msg/sendVoice", {
        "toId": str(to_id),
        "fileAesKey": cdn.get("fileAesKey", ""),
        "fileId": cdn.get("fileId", ""),
        "fileSize": cdn.get("fileSize", 0),
        "voiceTime": voice_time,
    })


def send_link(to_id, title, desc, link_url, icon_url=""):
    return api("/msg/sendLink", {
        "toId": str(to_id),
        "title": title,
        "desc": desc,
        "linkUrl": link_url,
        "iconUrl": icon_url,
    })


def upload_and_send(to_id, filepath, caption="", workspace=""):
    """Upload + auto-send by type (image/video/GIF/voice/file)"""
    cdn = upload(filepath, workspace)
    if not cdn:
        return {"code": -1, "msg": "CDN upload failed"}

    ext = get_ext(filepath)
    is_url = filepath.startswith("http")
    filename = os.path.basename(urlparse(filepath).path if is_url else filepath) or f"file{ext}"

    if ext in GIF_EXTS:
        result = send_gif(to_id, cdn)
    elif ext in IMAGE_EXTS:
        result = send_image(to_id, cdn, filename)
    elif ext in VIDEO_EXTS:
        result = send_video(to_id, cdn, filename)
    elif ext in VOICE_EXTS:
        result = send_voice(to_id, cdn)
    else:
        result = send_file(to_id, cdn, filename)

    if caption and result.get("code") == 0:
        send_text(to_id, caption)

    return result


# ============================================================
#  Media Download (receive user-sent images/videos/files)
# ============================================================

def download_media(file_id, file_aes_key=""):
    """Download media file to /tmp/, return local path or None"""
    result = api("/cloud/cdnDownload", {"fileId": file_id, "fileAesKey": file_aes_key})
    if result.get("code") == 0 and result.get("data", {}).get("fileUrl"):
        url = result["data"]["fileUrl"]
        ext = get_ext(url) or ".bin"
        tmp_path = f"/tmp/agent-recv-{int(time.time())}{ext}"
        try:
            urllib.request.urlretrieve(url, tmp_path)
            log.info(f"[cdn] downloaded media to {tmp_path}")
            return tmp_path
        except Exception as e:
            log.error(f"[cdn] download error: {e}")
    else:
        log.error(f"[cdn] download failed: {result}")
    return None


def download_wx(file_aes_key, file_auth_key, file_url, file_size, file_type=1):
    """Download personal WeChat format media (when callback has no fileId)

    file_type: 1=full image 2=small image 3=thumbnail 4=video 5=file/voice
    Returns local path or None
    """
    result = api("/cloud/wxDownload", {
        "fileAeskey": file_aes_key,
        "fileAuthkey": file_auth_key,
        "fileUrl": file_url,
        "fileSize": file_size,
        "fileType": file_type,
    })
    if result.get("code") == 0 and result.get("data", {}).get("cloudUrl"):
        cloud_url = result["data"]["cloudUrl"]
        ext = get_ext(cloud_url) or ".jpg"
        tmp_path = f"/tmp/agent-recv-{int(time.time())}{ext}"
        try:
            urllib.request.urlretrieve(cloud_url, tmp_path)
            log.info(f"[cdn] wxDownload OK -> {tmp_path}")
            return tmp_path
        except Exception as e:
            log.error(f"[cdn] wxDownload fetch error: {e}")
    else:
        log.error(f"[cdn] wxDownload failed: {result}")
    return None


def download_wx_work(file_id, file_aes_key, file_size, file_type=1):
    """Download Work WeChat format media (when callback has fileId)

    file_type: 1=full image 2=small image 3=thumbnail 4=video 5=file/voice
    Returns local path or None
    """
    result = api("/cloud/wxWorkDownload", {
        "fileAeskey": file_aes_key,
        "fileId": file_id,
        "fileSize": file_size,
        "fileType": file_type,
    })
    if result.get("code") == 0 and result.get("data", {}).get("cloudUrl"):
        cloud_url = result["data"]["cloudUrl"]
        ext = get_ext(cloud_url) or ".jpg"
        tmp_path = f"/tmp/agent-recv-{int(time.time())}{ext}"
        try:
            urllib.request.urlretrieve(cloud_url, tmp_path)
            log.info(f"[cdn] wxWorkDownload OK -> {tmp_path}")
            return tmp_path
        except Exception as e:
            log.error(f"[cdn] wxWorkDownload fetch error: {e}")
    else:
        log.error(f"[cdn] wxWorkDownload failed: {result}")
    return None


# ============================================================
#  Contact Info
# ============================================================

def get_contact_info(user_id_list):
    """Batch get contact basic info (nickname/avatar/gender etc.). Returns list[dict] or empty list."""
    result = api("/contact/batchGetUserinfo", {"userIdList": [str(uid) for uid in user_id_list]})
    if result.get("code") == 0:
        contacts = result.get("data", {}).get("contactList", [])
        log.info(f"[messaging] got {len(contacts)} contact info")
        return contacts
    log.error(f"[messaging] get_contact_info failed: {result}")
    return []


# ============================================================
#  Location Send
# ============================================================

def send_location(to_id, latitude, longitude, label, address=""):
    """Send location message. label=POI name (card title), address=detailed address (below title)"""
    return api("/msg/sendLocation", {
        "toId": str(to_id),
        "latitude": float(latitude),
        "longitude": float(longitude),
        "title": label,
        "label": address or label,
        "poiname": label,
        "address": address or label,
    })


# ============================================================
#  Namecard Send
# ============================================================

def send_namecard(to_id, contact_user_id):
    """Send contact namecard"""
    return api("/msg/sendPersonalCard", {
        "toId": str(to_id),
        "sharedId": str(contact_user_id),
    })
