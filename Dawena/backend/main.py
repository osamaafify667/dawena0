"""
Dawena Downloader Backend - FastAPI
- POST /api/info  : يحلل أي لينك ويرجع فيديوهات + صور + ملفات + جودات
- GET  /api/download : يجيب رابط التحميل المباشر لجودة معينة (redirect)
- POST /api/mp3 : يحول الفيديو لصوت mp3 ويرجعه
- POST /api/scan : يفحص الرابط عبر VirusTotal
يدعم: YouTube, TikTok, Instagram, Facebook, X, وأي موقع عام
"""

import os
import re
import base64
import tempfile
import subprocess
import requests
from urllib.parse import urljoin, urlparse
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, FileResponse, JSONResponse
from pydantic import BaseModel
from bs4 import BeautifulSoup

try:
    import yt_dlp
    HAS_YTDLP = True
except ImportError:
    HAS_YTDLP = False

app = FastAPI(title="Dawena Downloader API")

# السماح للفرونت إند (Vercel + localhost) بالوصول
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

VIRUSTOTAL_API_KEY = os.getenv("VIRUSTOTAL_API_KEY", "")

FILE_EXTS = (".pdf", ".zip", ".rar", ".7z", ".doc", ".docx", ".xls", ".xlsx",
             ".ppt", ".pptx", ".txt", ".csv", ".apk", ".exe", ".mp4", ".mp3",
             ".avi", ".mkv", ".mov")


class InfoRequest(BaseModel):
    url: str


class ScanRequest(BaseModel):
    url: str


def _is_valid_url(url: str) -> bool:
    try:
        p = urlparse(url.strip())
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False


def _cookie_file() -> str | None:
    """دعم الكوكيز لفيسبوك/انستا: حط محتوى ملف cookies.txt في متغير البيئة YTDLP_COOKIES على Render."""
    data = os.getenv("YTDLP_COOKIES", "").strip()
    if not data:
        return None
    try:
        # يدعم نص خام أو base64
        try:
            decoded = base64.b64decode(data).decode("utf-8", "ignore")
            if "Netscape" in decoded or "facebook" in decoded.lower() or "#HttpOnly" in decoded:
                data = decoded
        except Exception:
            pass
        fd, path = tempfile.mkstemp(prefix="cookies_", suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        return path
    except Exception:
        return None


def extract_with_ytdlp(url: str) -> dict | None:
    """يحاول استخراج معلومات الفيديو عبر yt-dlp. يرجع None لو الموقع مش فيديو مدعوم."""
    if not HAS_YTDLP:
        return None
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "extract_flat": False,
        "socket_timeout": 20,
        "retries": 2,
        "fragment_retries": 2,
        # عميل أندرويد بيتخطى صفحة الحماية google/sorry اللي بتحظر سيرفرات الاستضافة
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    }
    ck = _cookie_file()
    if ck:
        ydl_opts["cookiefile"] = ck
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return None
            # لو بلاي ليست، خد أول عنصر فقط في الـ MVP
            if info.get("_type") == "playlist" and info.get("entries"):
                info = next((e for e in info["entries"] if e), info)

            title = info.get("title", "بدون عنوان")
            thumbnail = info.get("thumbnail", "")
            duration = info.get("duration")
            uploader = info.get("uploader") or info.get("channel") or ""

            videos = []
            audios = []
            seen_res = set()

            for f in (info.get("formats") or []):
                f_url = f.get("url")
                if not f_url:
                    continue
                ext = (f.get("ext") or "").lower()
                vcodec = f.get("vcodec", "")
                acodec = f.get("acodec", "")
                height = f.get("height")
                filesize = f.get("filesize") or f.get("filesize_approx")

                # فيديو (فيه صورة) — يشمل بث HLS/DASH بتاع فيسبوك (m3u8)
                protocol = (f.get("protocol") or "")
                if vcodec and vcodec != "none" and (ext in ("mp4", "webm", "mkv", "mov", "m3u8", "mpd") or "m3u8" in protocol or "dash" in protocol):
                    label = f"{height}p" if height else (f.get("format_note") or ext)
                    if height and height in seen_res and filesize is None:
                        pass
                    videos.append({
                        "format_id": f.get("format_id", ""),
                        "quality": label,
                        "height": height or 0,
                        "ext": ext,
                        "filesize": filesize,
                        "fps": f.get("fps"),
                        "direct_url": f_url,
                        "has_audio": acodec not in (None, "none"),
                    })
                    if height:
                        seen_res.add(height)
                # صوت فقط
                elif (vcodec in (None, "none")) and acodec not in (None, "none"):
                    audios.append({
                        "format_id": f.get("format_id", ""),
                        "ext": ext,
                        "abr": f.get("abr"),
                        "filesize": filesize,
                        "direct_url": f_url,
                    })

            # رتب الفيديوهات من الأعلى جودة للأقل
            videos = sorted(videos, key=lambda x: x["height"], reverse=True)
            # احتفظ بأفضل نسخة لكل جودة لتقليل الزحمة
            uniq = {}
            for v in videos:
                key = (v["quality"], v["ext"])
                if key not in uniq:
                    uniq[key] = v
            videos = list(uniq.values())

            # صور: الثامبنيل + أي صور إضافية
            images = []
            if thumbnail:
                images.append({"url": thumbnail, "alt": title})
            for th in (info.get("thumbnails") or [])[-3:]:
                if th.get("url") and th["url"] != thumbnail:
                    images.append({"url": th["url"], "alt": title})

            if not videos and not audios:
                return None

            return {
                "source": "ytdlp",
                "platform": info.get("extractor_key") or info.get("extractor") or "video",
                "title": title,
                "thumbnail": thumbnail,
                "uploader": uploader,
                "duration": duration,
                "original_url": url,
                "videos": videos,
                "audios": audios,
                "images": images,
                "files": [],
            }
    except Exception:
        return None


def extract_tiktok_fallback(url: str) -> dict | None:
    """حل بديل لتيك توك عبر tikwm (مجاني وبدون مفتاح) — لأن سيرفرات الاستضافة بتتحظر من TikTok مباشرة."""
    if "tiktok.com" not in url.lower():
        return None
    try:
        r = requests.get("https://www.tikwm.com/api/", params={"url": url},
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=25)
        r.raise_for_status()
        j = r.json()
        if j.get("code") != 0:
            return None
        d = j.get("data") or {}
        title = d.get("title", "TikTok video")
        cover = d.get("cover", "")
        videos, audios, images = [], [], []
        if d.get("play"):  # بدون علامة مائية
            videos.append({"format_id": "tiktok-nowm", "quality": "بدون علامة مائية", "height": 1080,
                           "ext": "mp4", "filesize": d.get("size"), "direct_url": d["play"], "has_audio": True})
        if d.get("wmplay"):  # بعلامة مائية
            videos.append({"format_id": "tiktok-wm", "quality": "بعلامة مائية", "height": 720,
                           "ext": "mp4", "filesize": None, "direct_url": d["wmplay"], "has_audio": True})
        if d.get("hdplay"):
            videos.append({"format_id": "tiktok-hd", "quality": "جودة عالية HD", "height": 1080,
                           "ext": "mp4", "filesize": None, "direct_url": d["hdplay"], "has_audio": True})
        if d.get("music"):
            audios.append({"format_id": "tiktok-music", "ext": "mp3", "abr": None,
                           "filesize": d.get("music_size"), "direct_url": d["music"]})
        for im in (d.get("images") or [])[:10]:  # بوست صور
            images.append({"url": im, "alt": title})
        if cover:
            images.insert(0, {"url": cover, "alt": title})
        if not videos and not audios and not images:
            return None
        return {"source": "tiktok-api", "platform": "tiktok.com", "title": title,
                "thumbnail": cover, "uploader": (d.get("author") or {}).get("nickname", ""),
                "duration": d.get("duration"), "original_url": url,
                "videos": videos, "audios": audios, "images": images, "files": []}
    except Exception:
        return None


def _youtube_id(url: str) -> str | None:
    """يستخرج ID فيديو يوتيوب من أي شكل لينك (watch / youtu.be / shorts / embed)."""
    try:
        p = urlparse(url)
        host = (p.hostname or "").lower()
        if "youtu.be" in host:
            vid = p.path.strip("/").split("/")[0]
            return vid or None
        if "youtube.com" in host or "youtube-nocookie.com" in host:
            import urllib.parse as _up
            q = _up.parse_qs(p.query)
            if q.get("v"):
                return q["v"][0]
            m = re.match(r"^/(shorts|embed|live|v)/([^/?#]+)", p.path)
            if m:
                return m.group(2)
    except Exception:
        pass
    return None


PIPED_INSTANCES = [
    "https://pipedapi.adminforge.de",
    "https://pipedapi.reallyaweso.me",
    "https://api.piped.private.coffee",
]


def extract_youtube_fallback(url: str) -> dict | None:
    """حل بديل ليوتيوب عبر Piped (سيرفرات وسيطة بعناوين مختلفة مش محظورة).
    يشتغل لما yt-dlp يتخنق من حظر الـ IP."""
    vid = _youtube_id(url)
    if not vid:
        return None
    for base in PIPED_INSTANCES:
        try:
            r = requests.get(f"{base}/streams/{vid}",
                             headers={"User-Agent": "Mozilla/5.0"}, timeout=25)
            if r.status_code != 200:
                continue
            d = r.json()
            if "videoStreams" not in d:
                continue
            title = d.get("title", "YouTube video")
            thumb = d.get("thumbnailUrl", "")
            videos, audios = [], []
            for s in (d.get("videoStreams") or []):
                if not s.get("url"):
                    continue
                # المدمج (صوت+صورة) الأول عشان يشتغل تحميل مباشر
                if s.get("videoOnly"):
                    continue
                q = str(s.get("quality") or "")
                h = int("".join(filter(str.isdigit, q)) or 0)
                videos.append({"format_id": f"piped-{s.get('itag', q)}", "quality": f"{q}p" if h else q,
                               "height": h, "ext": "mp4", "filesize": s.get("contentLength"),
                               "direct_url": s["url"], "has_audio": True})
            # لو مفيش مدمج، خد أعلى فيديو منفصل + صوت (للتحويل)
            if not videos:
                best_v = None
                for s in (d.get("videoStreams") or []):
                    if s.get("url"):
                        best_v = s
                        break
                if best_v:
                    q = str(best_v.get("quality") or "")
                    videos.append({"format_id": f"piped-{best_v.get('itag', q)}", "quality": f"{q} (بدون صوت)",
                                   "height": 0, "ext": "mp4", "filesize": None,
                                   "direct_url": best_v["url"], "has_audio": False})
            for s in (d.get("audioStreams") or [])[:4]:
                if s.get("url"):
                    audios.append({"format_id": f"piped-a{s.get('itag', '')}", "ext": "m4a",
                                   "abr": s.get("bitrate"), "filesize": s.get("contentLength"),
                                   "direct_url": s["url"]})
            if not videos and not audios:
                continue
            videos = sorted(videos, key=lambda x: x["height"], reverse=True)[:8]
            return {"source": "youtube-piped", "platform": "youtube.com", "title": title,
                    "thumbnail": thumb, "uploader": d.get("uploader", ""),
                    "duration": d.get("duration"), "original_url": url,
                    "videos": videos, "audios": audios,
                    "images": [{"url": thumb, "alt": title}] if thumb else [], "files": []}
        except Exception:
            continue
    return None


def scrape_generic_site(url: str) -> dict:
    """كشط أي موقع عام: يجمع <video> و <img> وروابط الملفات."""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DawenaBot/1.0"}
    try:
        r = requests.get(url, headers=headers, timeout=20)
        r.raise_for_status()
    except Exception as e:
        msg = str(e)
        # روابط google/sorry الطويلة بتخوف المستخدم، اختصرها لرسالة مفهومة
        if "429" in msg or "sorry" in msg or "Too Many Requests" in msg:
            raise HTTPException(status_code=429, detail="يوتيوب حظر الطلب مؤقتا من سيرفر الاستضافة المجانية (حماية ضد السيرفرات). جرب: 1) رابط تيك توك أو انستا 2) استنى 10 دقايق وجرب تاني 3) جرب فيديو آخر")
        raise HTTPException(status_code=400, detail=f"تعذر فتح الرابط: {msg[:150]}")

    soup = BeautifulSoup(r.text, "lxml")
    title = (soup.title.string.strip() if soup.title and soup.title.string else url)

    # og:image / og:video (الأدق)
    images = []
    videos = []
    files = []

    for meta in soup.find_all("meta"):
        prop = (meta.get("property") or meta.get("name") or "").lower()
        content = meta.get("content", "")
        if not content:
            continue
        full = urljoin(url, content)
        if prop in ("og:image", "twitter:image"):
            images.append({"url": full, "alt": title})
        elif prop in ("og:video", "og:video:url", "twitter:player:stream"):
            videos.append({
                "format_id": "og-video",
                "quality": "مباشر",
                "height": 0,
                "ext": full.split(".")[-1].split("?")[0][:4] or "mp4",
                "filesize": None,
                "direct_url": full,
                "has_audio": True,
            })

    # <video> و <source>
    for v in soup.find_all("video"):
        src = v.get("src")
        if src:
            videos.append({"format_id": "html5", "quality": "مباشر", "height": 0,
                           "ext": "mp4", "filesize": None,
                           "direct_url": urljoin(url, src), "has_audio": True})
        for s in v.find_all("source"):
            if s.get("src"):
                videos.append({"format_id": "html5-source", "quality": s.get("label") or s.get("size") or "مباشر",
                               "height": 0, "ext": "mp4", "filesize": None,
                               "direct_url": urljoin(url, s["src"]), "has_audio": True})

    # <img>
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if not src or src.startswith("data:"):
            continue
        full = urljoin(url, src)
        # تجاهل الأيقونات الصغيرة
        if any(x in full.lower() for x in ("logo", "icon", "sprite", "1x1")):
            continue
        images.append({"url": full, "alt": img.get("alt", title)})

    # روابط ملفات مباشرة
    for a in soup.find_all("a", href=True):
        href = a["href"]
        full = urljoin(url, href)
        low = full.lower().split("?")[0]
        if low.endswith(FILE_EXTS):
            files.append({"url": full, "name": a.get_text(strip=True)[:80] or full.split("/")[-1]})

    # إزالة التكرار
    images = list({i["url"]: i for i in images}.values())[:30]
    videos = list({v["direct_url"]: v for v in videos}.values())[:20]
    files = list({f["url"]: f for f in files}.values())[:30]

    return {
        "source": "generic",
        "platform": urlparse(url).netloc,
        "title": title,
        "thumbnail": images[0]["url"] if images else "",
        "uploader": "",
        "duration": None,
        "original_url": url,
        "videos": videos,
        "audios": [],
        "images": images,
        "files": files,
    }


@app.get("/")
def health():
    return {"status": "ok", "service": "Dawena Downloader API", "ytdlp": HAS_YTDLP}


@app.get("/api/diag")
def diag(url: str = ""):
    """صفحة تشخيص مؤقتة: تبين نسخة yt-dlp وهل الكوكيز متفعلة وإيرور الاستخراج الحقيقي."""
    import yt_dlp as _ydl
    out = {"ytdlp_version": getattr(_ydl.version, "__version__", "?"),
           "cookies_env": bool(os.getenv("YTDLP_COOKIES", "").strip())}
    if url and _is_valid_url(url):
        ck = _cookie_file()
        out["cookie_file"] = bool(ck)
        out["clients"] = {}
        for client in (None, ["web"], ["android"], ["ios"], ["tv"], ["web_creator"]):
            name = "default" if client is None else "+".join(client)
            try:
                opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True,
                        "socket_timeout": 25}
                if client:
                    opts["extractor_args"] = {"youtube": {"player_client": client}}
                if ck:
                    opts["cookiefile"] = ck
                with _ydl.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    out["clients"][name] = {"title": (info or {}).get("title"),
                                            "formats": len((info or {}).get("formats") or [])}
            except Exception as e:
                out["clients"][name] = {"error": str(e)[:200]}
    return JSONResponse(out)


@app.post("/api/info")
def api_info(body: InfoRequest):
    url = (body.url or "").strip()
    if not _is_valid_url(url):
        raise HTTPException(status_code=400, detail="الرابط غير صالح. الصق رابط يبدأ بـ http")
    # 1) جرب yt-dlp (يوتيوب/تيك توك/انستا/فيسبوك/X)
    data = extract_with_ytdlp(url)
    if data:
        return JSONResponse(data)
    # 2) حل بديل مخصص لتيك توك (محظور من سيرفرات الاستضافة)
    tk = extract_tiktok_fallback(url)
    if tk:
        return JSONResponse(tk)
    # 2ب) حل بديل ليوتيوب عبر Piped لما الـ IP يتحظر
    if "youtu" in url.lower():
        yp = extract_youtube_fallback(url)
        if yp:
            return JSONResponse(yp)
    # 3) fallback: كشط عام
    return JSONResponse(scrape_generic_site(url))


@app.get("/api/download")
def api_download(url: str = Query(...), format_id: str = Query(default="best")):
    """يرجع redirect لرابط التحميل المباشر بأفضل جودة مطلوبة."""
    if not _is_valid_url(url):
        raise HTTPException(status_code=400, detail="الرابط غير صالح")
    # صيغ Piped البديلة ليوتيوب (piped-*) يجلبها مباشرة بدون yt-dlp
    if (format_id or "").startswith("piped-"):
        yp = extract_youtube_fallback(url)
        if yp:
            for v in (yp.get("videos") or []) + (yp.get("audios") or []):
                if v.get("format_id") == format_id and v.get("direct_url"):
                    return RedirectResponse(v["direct_url"])
            if yp.get("videos"):
                return RedirectResponse(yp["videos"][0]["direct_url"])
        raise HTTPException(status_code=400, detail="تعذر تجهيز رابط يوتيوب. حلل اللينك من جديد (الروابط المباشرة بتنتهي بسرعة)")
    # صيغ التيك توك البديلة (tiktok-nowm/wm/hd) يجلبها مباشرة بدون yt-dlp
    if (format_id or "").startswith("tiktok-"):
        tk = extract_tiktok_fallback(url)
        if tk:
            for v in (tk.get("videos") or []):
                if v.get("format_id") == format_id and v.get("direct_url"):
                    return RedirectResponse(v["direct_url"])
            if tk.get("videos"):
                return RedirectResponse(tk["videos"][0]["direct_url"])
        raise HTTPException(status_code=400, detail="تعذر تجهيز رابط التيك توك. جرب تحديث الصفحة واطلب التحليل من جديد (الروابط المباشرة بتنتهي بسرعة)")
    if HAS_YTDLP:
        try:
            ydl_opts = {"quiet": True, "no_warnings": True, "noplaylist": True,
                          "extractor_args": {"youtube": {"player_client": ["android", "web"]}}}
            _ck2 = _cookie_file()
            if _ck2:
                ydl_opts["cookiefile"] = _ck2
            fmt = "best"
            if format_id and format_id not in ("best", "og-video", "html5", "html5-source"):
                fmt = format_id
            elif format_id == "best":
                fmt = "best[ext=mp4]/best"
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info and info.get("_type") == "playlist" and info.get("entries"):
                    info = next((e for e in info["entries"] if e), info)
                # لو المستخدم اختار format_id معين، هاته
                if format_id not in ("best",):
                    for f in (info.get("formats") or []):
                        if f.get("format_id") == format_id and f.get("url"):
                            return RedirectResponse(f["url"])
                # وإلا استخرج أفضل رابط بالصيغة المطلوبة
                ydl2_opts = {"quiet": True, "format": fmt, "noplaylist": True}
                with yt_dlp.YoutubeDL(ydl2_opts) as ydl2:
                    info2 = ydl2.extract_info(url, download=False)
                    if info2 and info2.get("url"):
                        return RedirectResponse(info2["url"])
                    if info2 and info2.get("requested_downloads"):
                        return RedirectResponse(info2["requested_downloads"][0]["url"])
                # fallback: أول فورمات
                for f in (info.get("formats") or []):
                    if f.get("url"):
                        return RedirectResponse(f["url"])
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"تعذر تجهيز التحميل: {e}")
    # لو رابط مباشر أصلا
    return RedirectResponse(url)


@app.post("/api/mp3")
def api_mp3(body: InfoRequest):
    """يحول الفيديو إلى mp3 ويرجعه كملف. يحتاج ffmpeg على السيرفر."""
    url = (body.url or "").strip()
    if not _is_valid_url(url):
        raise HTTPException(status_code=400, detail="الرابط غير صالح")
    if not HAS_YTDLP:
        raise HTTPException(status_code=500, detail="yt-dlp غير مثبت على السيرفر")
    tmpdir = tempfile.mkdtemp(prefix="dawena_")
    out_tpl = os.path.join(tmpdir, "%(title).50s.%(ext)s")
    try:
        subprocess.run(
            ["yt-dlp", "-x", "--audio-format", "mp3", "--audio-quality", "0",
             "-o", out_tpl, "--no-playlist", url],
            check=True, timeout=300, capture_output=True,
        )
        mp3s = [f for f in os.listdir(tmpdir) if f.lower().endswith(".mp3")]
        if not mp3s:
            raise HTTPException(status_code=500, detail="فشل التحويل إلى mp3")
        path = os.path.join(tmpdir, mp3s[0])
        return FileResponse(path, media_type="audio/mpeg", filename=mp3s[0])
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="التحويل أخذ وقتا طويلا، جرب فيديو أقصر")
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=400, detail=f"تعذر تحويل الفيديو: {e.stderr.decode()[:300]}")


@app.post("/api/scan")
def api_scan(body: ScanRequest):
    """يفحص الرابط عبر VirusTotal. يحتاج VIRUSTOTAL_API_KEY."""
    url = (body.url or "").strip()
    if not _is_valid_url(url):
        raise HTTPException(status_code=400, detail="الرابط غير صالح")
    if not VIRUSTOTAL_API_KEY:
        return JSONResponse({
            "scanned": False,
            "verdict": "unknown",
            "message": "لم يتم ضبط مفتاح VirusTotal (VIRUSTOTAL_API_KEY). الفحص معطل حاليا.",
        })
    try:
        # 1) إرسال الرابط للفحص
        headers = {"x-apikey": VIRUSTOTAL_API_KEY}
        r = requests.post("https://www.virustotal.com/api/v3/urls",
                          data={"url": url}, headers=headers, timeout=20)
        r.raise_for_status()
        analysis_id = r.json()["data"]["id"]
        # 2) جلب النتيجة
        r2 = requests.get(f"https://www.virustotal.com/api/v3/analyses/{analysis_id}",
                          headers=headers, timeout=20)
        r2.raise_for_status()
        stats = r2.json()["data"]["attributes"].get("stats", {})
        malicious = stats.get("malicious", 0)
        suspicious = stats.get("suspicious", 0)
        verdict = "clean" if (malicious == 0 and suspicious == 0) else ("suspicious" if malicious == 0 else "malicious")
        return JSONResponse({
            "scanned": True,
            "verdict": verdict,
            "stats": stats,
            "message": "نظيف ✅" if verdict == "clean" else ("مشبوه ⚠️" if verdict == "suspicious" else "خطير ⛔"),
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"فشل الفحص: {e}")


# للتشغيل المحلي: uvicorn main:app --reload
