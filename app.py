"""
PDFImageKit - free online PDF and image converter (Flask)

Settings come from environment variables (see README section in chat):
    SITE_NAME, SITE_URL, CONTACT_EMAIL, ADSENSE_CLIENT, ADSENSE_SLOT, GA_ID

Run locally:  python app.py
Production:   gunicorn app:app --timeout 120
"""
import datetime
import io
import os
import subprocess
import tempfile
import zipfile

import fitz  # PyMuPDF
from flask import Flask, Response, abort, render_template, request, send_file
from markupsafe import Markup
from PIL import Image, ImageOps
from pypdf import PdfReader, PdfWriter

from tools_data import MAIN_TOOLS, TOOLS, TOOLS_BY_SLUG, VARIANT_TOOLS

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB upload limit

SITE_NAME = os.getenv("SITE_NAME", "PDFImageKit")
SITE_URL = os.getenv("SITE_URL", "https://www.pdfimagekit.com").rstrip("/")  # e.g. https://www.yourdomain.com
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "contact@example.com")
ADSENSE_CLIENT = os.getenv("ADSENSE_CLIENT", "")  # e.g. ca-pub-1234567890123456
ADSENSE_SLOT = os.getenv("ADSENSE_SLOT", "")      # optional manual ad unit id
GA_ID = os.getenv("GA_ID", "")                    # e.g. G-XXXXXXXXXX

IMAGE_EXT = {"png", "jpg", "jpeg", "webp", "bmp", "gif", "tiff", "tif"}
OFFICE_EXT = {"doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "txt", "rtf"}


# ---------------------------------------------------------------- helpers
def ext(filename):
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def get_files(allowed, min_files=1):
    files = [f for f in request.files.getlist("files") if f and f.filename]
    if len(files) < min_files:
        abort(400, f"Please add at least {min_files} file(s).")
    for f in files:
        if ext(f.filename) not in allowed:
            abort(400, f"'{f.filename}' is not supported. Allowed types: {', '.join(sorted(allowed))}")
    return files


def open_image(file_storage):
    img = Image.open(file_storage.stream)
    img = ImageOps.exif_transpose(img)  # fix phone-camera rotation
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        return bg
    return img.convert("RGB")


def parse_pages(spec, total):
    """'1-3,5,8-' -> [0,1,2,4,7,...] (0-indexed)"""
    pages = []
    for part in spec.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            start = int(a) if a else 1
            end = int(b) if b else total
        else:
            start = end = int(part)
        if start < 1 or end > total or start > end:
            abort(400, f"Invalid page range. This PDF has {total} pages.")
        pages.extend(range(start - 1, end))
    if not pages:
        abort(400, "Enter the pages to keep, for example 1-3, 5")
    return pages


def send_bytes(data, name, mime):
    return send_file(io.BytesIO(data), as_attachment=True, download_name=name, mimetype=mime)


def zip_response(items, name):
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, d in items:
            z.writestr(n, d)
    return send_bytes(zbuf.getvalue(), name, "application/zip")


# ------------------------------------------------------------- converters
def img_to_pdf():
    files = get_files(IMAGE_EXT)
    images = [open_image(f) for f in files]
    out = io.BytesIO()
    images[0].save(out, format="PDF", save_all=True, append_images=images[1:], resolution=100.0)
    return send_bytes(out.getvalue(), "images.pdf", "application/pdf")


def pdf_to_img():
    f = get_files({"pdf"})[0]
    fmt = request.form.get("format", "png").lower()
    if fmt not in ("png", "jpg", "webp"):
        abort(400, "Format must be png, jpg or webp.")
    dpi = max(50, min(int(request.form.get("dpi", 150) or 150), 400))
    doc = fitz.open(stream=f.read(), filetype="pdf")
    save_fmt = {"png": "PNG", "jpg": "JPEG", "webp": "WEBP"}[fmt]
    results = []
    for i, page in enumerate(doc, 1):
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        buf = io.BytesIO()
        img.save(buf, format=save_fmt, quality=90)
        results.append((f"page_{i}.{fmt}", buf.getvalue()))
    if len(results) == 1:
        name, data = results[0]
        return send_bytes(data, name, f"image/{'jpeg' if fmt == 'jpg' else fmt}")
    return zip_response(results, "pdf_pages.zip")


def img_convert():
    files = get_files(IMAGE_EXT)
    fmt = request.form.get("format", "png").lower()
    if fmt not in ("png", "jpg", "webp", "bmp", "gif", "tiff"):
        abort(400, "Unsupported output format.")
    save_fmt = {"jpg": "JPEG", "tiff": "TIFF"}.get(fmt, fmt.upper())
    outs = []
    for f in files:
        img = open_image(f)
        buf = io.BytesIO()
        img.save(buf, format=save_fmt)
        outs.append((f"{f.filename.rsplit('.', 1)[0]}.{fmt}", buf.getvalue()))
    if len(outs) == 1:
        return send_bytes(outs[0][1], outs[0][0], "application/octet-stream")
    return zip_response(outs, "converted.zip")


def img_compress():
    files = get_files(IMAGE_EXT)
    quality = max(10, min(int(request.form.get("quality", 70) or 70), 95))
    max_w = int(request.form.get("max_width", 0) or 0)
    outs = []
    for f in files:
        img = open_image(f)
        if max_w and img.width > max_w:
            img = img.resize((max_w, int(img.height * max_w / img.width)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        outs.append((f"{f.filename.rsplit('.', 1)[0]}_compressed.jpg", buf.getvalue()))
    if len(outs) == 1:
        return send_bytes(outs[0][1], outs[0][0], "image/jpeg")
    return zip_response(outs, "compressed.zip")


def pdf_merge():
    files = get_files({"pdf"}, min_files=2)
    writer = PdfWriter()
    for f in files:
        for page in PdfReader(f.stream).pages:
            writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return send_bytes(out.getvalue(), "merged.pdf", "application/pdf")


def pdf_split():
    f = get_files({"pdf"})[0]
    reader = PdfReader(f.stream)
    pages = parse_pages(request.form.get("pages", ""), len(reader.pages))
    writer = PdfWriter()
    for p in pages:
        writer.add_page(reader.pages[p])
    out = io.BytesIO()
    writer.write(out)
    return send_bytes(out.getvalue(), "extracted.pdf", "application/pdf")


def pdf_to_text():
    f = get_files({"pdf"})[0]
    doc = fitz.open(stream=f.read(), filetype="pdf")
    text = "\n\n".join(f"--- Page {i} ---\n{p.get_text()}" for i, p in enumerate(doc, 1))
    return send_bytes(text.encode("utf-8"), "text.txt", "text/plain")


def office_to_pdf():
    """Needs LibreOffice on the server (soffice in PATH)."""
    f = get_files(OFFICE_EXT)[0]
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "input." + ext(f.filename))
        f.save(src)
        try:
            subprocess.run(
                ["soffice", "--headless", "--convert-to", "pdf", "--outdir", tmp, src],
                check=True, timeout=120, capture_output=True,
            )
        except FileNotFoundError:
            abort(500, "Office conversion is not available on this server right now.")
        except subprocess.SubprocessError:
            abort(500, "Conversion failed. Please check the file and try again.")
        with open(os.path.join(tmp, "input.pdf"), "rb") as fh:
            data = fh.read()
    return send_bytes(data, f"{f.filename.rsplit('.', 1)[0]}.pdf", "application/pdf")


CONVERTERS = {
    "img-to-pdf": img_to_pdf,
    "pdf-to-img": pdf_to_img,
    "img-convert": img_convert,
    "img-compress": img_compress,
    "pdf-merge": pdf_merge,
    "pdf-split": pdf_split,
    "pdf-to-text": pdf_to_text,
    "office-to-pdf": office_to_pdf,
}


@app.post("/api/<tool>")
def api(tool):
    if tool not in CONVERTERS:
        abort(404)
    try:
        return CONVERTERS[tool]()
    except (ValueError, OSError) as e:
        abort(400, f"This file could not be processed: {e}")


# ------------------------------------------------------------------ pages
def abs_url(path="/"):
    return (SITE_URL or request.url_root.rstrip("/")) + path


@app.context_processor
def inject():
    return dict(
        SITE_NAME=SITE_NAME, ADSENSE_CLIENT=ADSENSE_CLIENT, ADSENSE_SLOT=ADSENSE_SLOT,
        GA_ID=GA_ID, CONTACT_EMAIL=CONTACT_EMAIL, MAIN_TOOLS=MAIN_TOOLS,
        canonical=abs_url(request.path), abs_url=abs_url, year=datetime.date.today().year,
    )


@app.get("/")
def home():
    return render_template("home.html", main=MAIN_TOOLS, variants=VARIANT_TOOLS)


@app.get("/<slug>")
def tool_page(slug):
    t = TOOLS_BY_SLUG.get(slug)
    if not t:
        abort(404)
    cfg = {k: t[k] for k in ("id", "name", "accept", "multi", "min", "opts", "frm")}
    related = [x for x in MAIN_TOOLS if x["id"] != t["id"]][:6]
    ctx = "https://schema.org"
    ld = [
        {"@context": ctx, "@type": "WebApplication", "name": t["name"], "url": abs_url("/" + slug),
         "applicationCategory": "UtilitiesApplication", "operatingSystem": "Any",
         "description": t["desc"], "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"}},
        {"@context": ctx, "@type": "FAQPage",
         "mainEntity": [{"@type": "Question", "name": f["q"],
                         "acceptedAnswer": {"@type": "Answer", "text": f["a"]}} for f in t["faq"]]},
        {"@context": ctx, "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": abs_url("/")},
            {"@type": "ListItem", "position": 2, "name": t["name"], "item": abs_url("/" + slug)}]},
    ]
    return render_template("tool.html", t=t, cfg=cfg, related=related, ld=ld)


PAGES = {
    "about": ("About us", """
<p>[[site]] is a free set of online tools for working with PDF files and images. You can turn images into PDFs, PDFs into images, merge and split PDFs, compress photos and convert between image formats.</p>
<p>We built [[site]] because these small tasks come up all the time, and most tools ask you to sign up, add watermarks or install software. Here you open the page, add your file and download the result.</p>
<h2>How we treat your files</h2>
<p>Files are processed in memory and are not stored. Once your conversion is finished the data is discarded.</p>
<h2>Contact</h2>
<p>Questions or suggestions? Write to <a href="mailto:[[email]]">[[email]]</a>.</p>"""),
    "privacy-policy": ("Privacy Policy", """
<p>Last updated: [[date]]</p>
<p>This policy explains what information [[site]] ("we", "our") collects and how it is used when you visit this website.</p>
<h2>Files you upload</h2>
<p>Files you upload for conversion are processed in server memory and are not saved to disk or shared with anyone. They are discarded when the conversion finishes.</p>
<h2>Information we collect</h2>
<p>Like most websites, our servers may log technical information such as IP address, browser type, pages visited and time of visit. We use this to keep the site secure, fix problems and understand how the site is used.</p>
<h2>Cookies and advertising</h2>
<p>We use Google AdSense to show ads. Google and its partners use cookies, including advertising cookies, to show ads based on your visits to this and other websites. You can opt out of personalised advertising by visiting <a href="https://www.google.com/settings/ads" rel="nofollow noopener">Google Ads Settings</a>. You can learn how Google uses data from sites that use its services at <a href="https://policies.google.com/technologies/partner-sites" rel="nofollow noopener">policies.google.com/technologies/partner-sites</a>.</p>
<p>We may also use Google Analytics to understand traffic. It uses cookies to collect anonymous usage information.</p>
<h2>Your choices</h2>
<p>You can block or delete cookies in your browser settings. Some parts of the site, including ads, may behave differently if you do.</p>
<h2>Children</h2>
<p>This site is not directed to children under 13 and we do not knowingly collect their personal information.</p>
<h2>Changes</h2>
<p>We may update this policy from time to time. The date above shows the latest version.</p>
<h2>Contact</h2>
<p>For privacy questions write to <a href="mailto:[[email]]">[[email]]</a>.</p>"""),
    "terms": ("Terms of Use", """
<p>Last updated: [[date]]</p>
<p>By using [[site]] you agree to these terms.</p>
<h2>Use of the service</h2>
<p>The tools are provided free of charge for personal and commercial use. You must only upload files that you have the right to use. Do not use the service for anything illegal or to harm others or our systems.</p>
<h2>No warranty</h2>
<p>The service is provided "as is" without any warranty. We try to make conversions accurate, but results can differ from the original, so please check important files before using them.</p>
<h2>Limitation of liability</h2>
<p>To the extent allowed by law, we are not liable for any loss or damage arising from use of the service.</p>
<h2>Changes</h2>
<p>We may change the service or these terms at any time.</p>
<h2>Contact</h2>
<p><a href="mailto:[[email]]">[[email]]</a></p>"""),
    "contact": ("Contact us", """
<p>We would love to hear from you. For questions, bug reports or ideas for new tools, email us at <a href="mailto:[[email]]">[[email]]</a>.</p>
<p>We usually reply within a few days.</p>"""),
}


def legal(slug):
    title, body = PAGES[slug]
    body = (body.replace("[[site]]", SITE_NAME).replace("[[email]]", CONTACT_EMAIL)
            .replace("[[date]]", datetime.date.today().strftime("%B %d, %Y")))
    return render_template("legal.html", title=title, body=Markup(body), slug=slug)


for _slug in PAGES:
    app.add_url_rule(f"/{_slug}", endpoint=f"legal_{_slug}", view_func=legal, defaults={"slug": _slug})


@app.get("/sitemap.xml")
def sitemap():
    today = datetime.date.today().isoformat()
    paths = ["/"] + [f"/{t['slug']}" for t in TOOLS] + [f"/{s}" for s in PAGES]
    rows = "".join(
        f"<url><loc>{abs_url(p)}</loc><lastmod>{today}</lastmod>"
        f"<priority>{'1.0' if p == '/' else '0.8' if p.strip('/') in TOOLS_BY_SLUG else '0.3'}</priority></url>"
        for p in paths
    )
    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{rows}</urlset>'
    return Response(xml, mimetype="application/xml")


@app.get("/robots.txt")
def robots():
    return Response(f"User-agent: *\nAllow: /\nDisallow: /api/\n\nSitemap: {abs_url('/sitemap.xml')}\n", mimetype="text/plain")


@app.get("/ads.txt")
def ads_txt():
    if not ADSENSE_CLIENT:
        abort(404)
    pub = ADSENSE_CLIENT.replace("ca-", "")
    return Response(f"google.com, {pub}, DIRECT, f08c47fec0942fa0\n", mimetype="text/plain")


@app.after_request
def headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return resp


@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(413)
@app.errorhandler(500)
def err(e):
    code = getattr(e, "code", 500)
    msg = getattr(e, "description", str(e))
    if code == 413:
        msg = "File is too large. The limit is 50 MB."
    if request.path.startswith("/api/"):
        return {"error": msg}, code
    if code == 404:
        return render_template("404.html"), 404
    return msg, code


if __name__ == "__main__":
    app.run(debug=True)
