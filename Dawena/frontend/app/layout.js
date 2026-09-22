export const metadata = {
  title: 'Dawena | تحميل فيديوهات وصور بجودة عالية',
  description: 'الصق أي لينك وحمّل الفيديوهات والصور والملفات بجودة عالية + تحويل MP3 + فحص فيروسات'
};

export default function RootLayout({ children }) {
  return (
    <html lang="ar" dir="rtl">
      <body>{children}</body>
    </html>
  );
}
