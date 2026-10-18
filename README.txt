PDFImageKit - setup

Local:
  pip install -r requirements.txt
  python app.py

Production (Render etc.):
  Build: pip install -r requirements.txt
  Start: gunicorn app:app --timeout 120

Environment variables:
  SITE_NAME       your brand name (default PDFImageKit)
  SITE_URL        https://www.yourdomain.com   (no trailing slash)
  CONTACT_EMAIL   your real email (shown on Contact/Privacy pages)
  ADSENSE_CLIENT  ca-pub-XXXXXXXXXXXXXXXX  (after AdSense approval)
  ADSENSE_SLOT    optional ad unit id
  GA_ID           G-XXXXXXXXXX  (Google Analytics, optional)
