'use client';
import { useState } from 'react';
import './globals.css';

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export default function Home() {
  const [url, setUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [mp3Loading, setMp3Loading] = useState(false);
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [scan, setScan] = useState(null);
  const [quality, setQuality] = useState('best');

  async function handleFetch() {
    setError(''); setData(null); setScan(null);
    if (!url.startsWith('http')) { setError('الصق رابط صحيح يبدأ بـ http'); return; }
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/info`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url })
      });
      const j = await res.json();
      if (!res.ok) throw new Error(j.detail || 'تعذر تحليل الرابط');
      setData(j);
      if (j.videos?.length) setQuality(j.videos[0].format_id);
      handleScan(url);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }

  async function handleScan(targetUrl) {
    try {
      const res = await fetch(`${API}/api/scan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: targetUrl })
      });
      setScan(await res.json());
    } catch { setScan(null); }
  }

  async function handleMp3() {
    if (data && data.audios && data.audios[0] && data.audios[0].direct_url) {
      const a = document.createElement('a');
      a.href = data.audios[0].direct_url; a.download = 'dawena-audio.mp3'; a.target = '_blank'; a.click();
      return;
    }
    setMp3Loading(true); setError('');
    try {
      const res = await fetch(`${API}/api/mp3`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url })
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j.detail || 'فشل تحويل MP3');
      }
      const blob = await res.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'dawena-audio.mp3';
      a.click();
    } catch (e) { setError(e.message); }
    finally { setMp3Loading(false); }
  }

  function getDlLink() {
    if (data && data.source && data.source !== 'ytdlp') {
      const v = (data.videos || []).find(x => x.format_id === quality);
      return v ? v.direct_url : '#';
    }
    return `${API}/api/download?url=${encodeURIComponent(url)}&format_id=${encodeURIComponent(quality)}`;
  }
  const dlLink = getDlLink();

  return (
    <div className="container">
      <div className="hero">
        <h1>🚀 <span>Dawena</span> downloader</h1>
        <p>الصق لينك من يوتيوب / تيك توك / انستا / فيسبوك / X أو أي موقع — وهنطلعلك الصور والفيديوهات والملفات بجودة عالية + MP3 + فحص فيروسات</p>
      </div>

      <div className="search-box">
        <input value={url} onChange={e => setUrl(e.target.value)} placeholder="https://..." />
        <button onClick={handleFetch} disabled={loading}>{loading ? 'جاري التحليل...' : 'عرض المحتوى'}</button>
      </div>

      {error && <div className="error">{error}</div>}

      {scan && (
        <div className="card">
          🛡️ فحص VirusTotal: {' '}
          {scan.scanned
            ? <b className={scan.verdict === 'clean' ? 'scan-clean' : 'scan-bad'}>{scan.message}</b>
            : <span className="meta">{scan.message}</span>}
        </div>
      )}

      {data && (
        <>
          <div className="card">
            <h2>{data.title}</h2>
            <div className="meta">{data.platform} {data.uploader ? `• ${data.uploader}` : ''} {data.duration ? `• ${Math.floor(data.duration / 60)}:${String(data.duration % 60).padStart(2, '0')} دقيقة` : ''}</div>
            {data.thumbnail && <img className="thumb" src={data.thumbnail} alt="thumbnail" />}

            {data.videos?.length > 0 && (
              <>
                <h2 style={{ marginTop: 16 }}>🎬 الفيديو — اختار الجودة</h2>
                <div className="row">
                  <select value={quality} onChange={e => setQuality(e.target.value)}>
                    <option value="best">أعلى جودة تلقائية</option>
                    {data.videos.map((v, i) => (
                      <option key={i} value={v.format_id}>
                        {v.quality} • {v.ext} {v.has_audio ? '' : '(بدون صوت)'}
                      </option>
                    ))}
                  </select>
                  <a className="btn" href={dlLink} target="_blank" rel="noreferrer">⬇️ تحميل الفيديو</a>
                  <button className="btn btn-mp3" onClick={handleMp3} disabled={mp3Loading}>
                    {mp3Loading ? 'جاري التحويل...' : '🎵 تحميل MP3 فقط'}
                  </button>
                </div>
              </>
            )}
          </div>

          {data.images?.length > 0 && (
            <div className="card">
              <h2>🖼️ الصور ({data.images.length})</h2>
              <div className="grid">
                {data.images.map((img, i) => (
                  <div key={i}>
                    <img src={img.url} alt={img.alt || ''} loading="lazy" />
                    <div className="row">
                      <a className="btn btn-secondary" href={img.url} download target="_blank" rel="noreferrer">تحميل</a>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {data.files?.length > 0 && (
            <div className="card">
              <h2>📁 ملفات أخرى ({data.files.length})</h2>
              {data.files.map((f, i) => (
                <div className="file-item" key={i}>
                  <span>{f.name}</span>
                  <a href={f.url} target="_blank" rel="noreferrer">تحميل ⬇️</a>
                </div>
              ))}
            </div>
          )}

          {(!data.videos?.length && !data.images?.length && !data.files?.length) && (
            <div className="error">لم نجد محتوى قابل للتحميل في هذا الرابط. جرب رابط مباشر آخر.</div>
          )}
        </>
      )}

      <p className="note">
        ⚠️ تنبيه: حمّل فقط المحتوى الذي تملكه أو المسموح بتحميله. بعض المنصات تمنع التحميل في شروط الاستخدام.<br />
        للنشر المجاني: الفرونت على Vercel والباك على Render. ضيف مفتاح VirusTotal في متغيرات البيئة لتفعيل الفحص.
      </p>
    </div>
  );
}
