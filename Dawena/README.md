# Dawena Downloader 🚀
موقع تحميل فيديوهات وصور وملفات من أي لينك بجودة عالية + تحويل MP3 + فحص فيروسات عبر VirusTotal.

## المكونات
- `backend/` → FastAPI + yt-dlp (يدعم YouTube, TikTok, Instagram, Facebook, X + كشط عام لأي موقع)
- `frontend/` → Next.js واجهة عربية RTL

## التشغيل محليا (بعد تسطيب Node و Python)

### 1) سطّب الأدوات (مرة واحدة)
- Node.js LTS من: https://nodejs.org
- Python 3.11 من: https://www.python.org/downloads/
- ffmpeg من: https://ffmpeg.org/download.html (مهم لتحويل MP3)

### 2) شغّل الباك إند
```powershell
cd backend
pip install -r requirements.txt
# لو عندك مفتاح VirusTotal حطه هنا:
# $env:VIRUSTOTAL_API_KEY="your_key"
uvicorn main:app --reload --port 8000
```
جرّب: http://localhost:8000

### 3) شغّل الفرونت إند (ترمينال جديد)
```powershell
cd frontend
cp .env.example .env.local
npm install
npm run dev
```
افتح: http://localhost:3000

## النشر المجاني

### الباك إند على Render
1. ارفع المشروع على GitHub
2. ادخل Render → New Web Service → اختار repo → Root Directory = `backend`
3. Build: `pip install -r requirements.txt` — Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. ضيف Environment Variable: `VIRUSTOTAL_API_KEY` (مفتاح مجاني من virustotal.com)
5. انسخ رابط الخدمة، مثال: `https://dawena-backend.onrender.com`

### الفرونت على Vercel
1. ادخل Vercel → New Project → اختار نفس الـ repo → Root Directory = `frontend`
2. ضيف Environment Variable: `NEXT_PUBLIC_API_URL` = رابط Render اللي نسخته
3. Deploy ✅

## ملاحظات مهمة
- الاستضافة المجانية بطيئة أول مرة (Render بينام) + تحويل MP3 لفيديوهات طويلة قد ياخد وقت.
- للاستخدام التقيل الأفضل VPS (مثل Hetzner بـ 4€) مع ffmpeg ومساحة تخزين.
- حمّل فقط المحتوى المسموح به قانونيا.
