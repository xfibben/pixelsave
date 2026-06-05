import mimetypes
import re
import subprocess
from base64 import b64decode
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urljoin, urlparse
from urllib.request import ProxyHandler, Request, build_opener
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models import DownloadJob
from app.storage import ensure_bucket, upload_file

MEDIA_URL_PATTERN = re.compile(r"https://[^\"'\\s]+?\.(?:mp4|m4v|mov|webm|m3u8|mpd)(?:\?[^\"'\\s]*)?", re.IGNORECASE)
STREAM_EXTENSIONS = (".m3u8", ".mpd")
DIRECT_EXTENSIONS = (".mp4", ".m4v", ".mov", ".webm")
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)


def detect_platform(url: str) -> str:
    hostname = (urlparse(url).hostname or "").lower()
    if "instagram.com" in hostname:
        return "instagram"
    if "facebook.com" in hostname or "fb.watch" in hostname:
        return "facebook"
    if "x.com" in hostname or "twitter.com" in hostname:
        return "x"
    if "tiktok.com" in hostname:
        return "tiktok"
    if "youtube.com" in hostname or "youtu.be" in hostname:
        return "youtube"
    return "generic"


def _guess_content_type(file_path: Path) -> str:
    content_type, _ = mimetypes.guess_type(file_path.name)
    return content_type or "application/octet-stream"


def _parse_netscape_cookies(cookies_file: str | None) -> list[dict[str, str | float | bool]]:
    if not cookies_file:
        return []

    cookies: list[dict[str, str | float | bool]] = []
    for line in Path(cookies_file).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split("\t")
        if len(parts) != 7:
            continue

        domain, _, path, secure, expires, name, value = parts
        cookie: dict[str, str | float | bool] = {
            "name": name,
            "value": value,
            "domain": domain,
            "path": path or "/",
            "secure": secure.upper() == "TRUE",
        }
        if expires.isdigit() and expires != "0":
            cookie["expires"] = float(expires)
        cookies.append(cookie)
    return cookies


def _build_cookie_header(target_url: str, cookies_file: str | None) -> str | None:
    if not cookies_file:
        return None

    hostname = urlparse(target_url).hostname or ""
    values: list[str] = []
    for cookie in _parse_netscape_cookies(cookies_file):
        domain = str(cookie["domain"]).lstrip(".")
        if hostname == domain or hostname.endswith(f".{domain}"):
            values.append(f"{cookie['name']}={cookie['value']}")
    return "; ".join(values) if values else None


def _resolve_cookies_file(settings, temp_path: Path) -> str | None:
    if settings.yt_dlp_cookies_file:
        return settings.yt_dlp_cookies_file
    if settings.yt_dlp_cookies_text:
        cookies_path = temp_path / "cookies.txt"
        cookies_path.write_text(settings.yt_dlp_cookies_text, encoding="utf-8")
        return str(cookies_path)
    if settings.yt_dlp_cookies_base64:
        cookies_path = temp_path / "cookies.txt"
        decoded = b64decode(settings.yt_dlp_cookies_base64).decode("utf-8")
        cookies_path.write_text(decoded, encoding="utf-8")
        return str(cookies_path)
    return None


def _candidate_page_urls(source_url: str, platform: str) -> list[str]:
    urls = [source_url]
    parsed = urlparse(source_url)
    normalized_path = parsed.path.rstrip("/")
    if not normalized_path:
        return urls

    if platform == "instagram" and "/embed" not in normalized_path:
        if any(token in normalized_path for token in ("/reel/", "/p/", "/tv/")):
            urls.append(urljoin(source_url, f"{normalized_path}/embed/captioned/"))
            urls.append(urljoin(source_url, f"{normalized_path}/embed/"))
    return list(dict.fromkeys(urls))


def _extract_dom_media_candidates(page) -> list[str]:
    candidates: list[str] = page.evaluate(
        """() => {
          const urls = new Set();
          const add = (value) => {
            if (typeof value === "string" && value.startsWith("http")) {
              urls.add(value);
            }
          };

          [
            'meta[property="og:video"]',
            'meta[property="og:video:secure_url"]',
            'meta[name="twitter:player:stream"]',
            'meta[property="og:audio"]',
            'meta[property="og:audio:secure_url"]'
          ].forEach((selector) => {
            const node = document.querySelector(selector);
            if (node?.content) add(node.content);
          });

          document.querySelectorAll("video, audio").forEach((media) => {
            add(media.currentSrc);
            add(media.src);
            media.querySelectorAll("source").forEach((source) => add(source.src));
          });

          document.querySelectorAll("[data-video-url], [data-src]").forEach((node) => {
            add(node.getAttribute("data-video-url"));
            add(node.getAttribute("data-src"));
          });

          for (const script of document.scripts) {
            const text = script.textContent || "";
            const matches = text.match(/https?:\\\\/\\\\/[^"'\\\\\\s]+?\\.(?:mp4|m4v|mov|webm|m3u8|mpd)(?:\\?[^"'\\\\\\s]*)?/gi) || [];
            matches.forEach((match) => add(match.replace(/\\\\u0026/g, "&").replace(/\\\\\\//g, "/")));
          }

          return Array.from(urls);
        }"""
    )
    return [candidate for candidate in candidates if isinstance(candidate, str)]


def _normalize_media_url(candidate: str) -> str:
    return candidate.replace("\\u0026", "&").replace("\\/", "/")


def _is_stream_url(media_url: str) -> bool:
    path = urlparse(media_url).path.lower()
    return path.endswith(STREAM_EXTENSIONS)


def _build_download_headers(page_url: str, media_url: str, cookies_file: str | None) -> dict[str, str]:
    headers = {
        "User-Agent": BROWSER_USER_AGENT,
        "Referer": page_url,
        "Accept": "*/*",
    }
    page_origin = urlparse(page_url)
    if page_origin.scheme and page_origin.netloc:
        headers["Origin"] = f"{page_origin.scheme}://{page_origin.netloc}"
    cookie_header = _build_cookie_header(media_url, cookies_file) or _build_cookie_header(page_url, cookies_file)
    if cookie_header:
        headers["Cookie"] = cookie_header
    return headers


def _build_opener(proxy_url: str | None):
    handlers = []
    if proxy_url:
        handlers.append(ProxyHandler({"http": proxy_url, "https": proxy_url}))
    return build_opener(*handlers)


def _download_direct_media(
    media_url: str,
    page_url: str,
    output_template: Path,
    settings,
    cookies_file: str | None,
) -> Path:
    headers = _build_download_headers(page_url, media_url, cookies_file)
    opener = _build_opener(settings.yt_dlp_proxy)
    request = Request(media_url, headers=headers)

    with opener.open(request, timeout=settings.browser_timeout_seconds) as response:
        content_type = response.headers.get("Content-Type", "application/octet-stream").split(";")[0].strip()
        extension = mimetypes.guess_extension(content_type) or Path(urlparse(media_url).path).suffix or ".mp4"
        file_path = output_template.parent / f"browser-download-{uuid4().hex}{extension}"
        with file_path.open("wb") as file_handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                file_handle.write(chunk)
    return file_path


def _download_stream_media(
    media_url: str,
    page_url: str,
    output_template: Path,
    settings,
    cookies_file: str | None,
) -> Path:
    file_path = output_template.parent / f"browser-stream-{uuid4().hex}.mp4"
    headers = _build_download_headers(page_url, media_url, cookies_file)
    header_blob = "".join(f"{key}: {value}\r\n" for key, value in headers.items())
    command = [
        "ffmpeg",
        "-y",
        "-headers",
        header_blob,
        "-i",
        media_url,
        "-c",
        "copy",
        str(file_path),
    ]
    if settings.yt_dlp_proxy:
        command[1:1] = ["-http_proxy", settings.yt_dlp_proxy]

    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=settings.browser_timeout_seconds,
    )
    if result.returncode != 0 or not file_path.exists():
        details = "\n".join(part for part in [result.stdout, result.stderr] if part).strip()
        raise RuntimeError(details or "ffmpeg no pudo descargar el stream detectado por navegador")
    return file_path


def _download_resolved_media(
    media_url: str,
    page_url: str,
    output_template: Path,
    settings,
    cookies_file: str | None,
) -> Path:
    if _is_stream_url(media_url):
        return _download_stream_media(media_url, page_url, output_template, settings, cookies_file)
    return _download_direct_media(media_url, page_url, output_template, settings, cookies_file)


def _resolve_browser_media(
    source_url: str,
    output_template: Path,
    settings,
    cookies_file: str | None,
) -> Path:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    platform = detect_platform(source_url)
    network_candidates: list[str] = []
    page_errors: list[str] = []
    browser_proxy = {"server": settings.yt_dlp_proxy} if settings.yt_dlp_proxy else None
    cookies = _parse_netscape_cookies(cookies_file)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, proxy=browser_proxy)
        context = browser.new_context(
            user_agent=BROWSER_USER_AGENT,
            viewport={"width": 1440, "height": 1024},
            locale="en-US",
        )
        if cookies:
            context.add_cookies(cookies)
        context.set_extra_http_headers(
            {
                "Accept-Language": "en-US,en;q=0.9",
                "Upgrade-Insecure-Requests": "1",
            }
        )
        page = context.new_page()

        def capture_response(response) -> None:
            try:
                url = response.url
                content_type = response.headers.get("content-type", "").lower()
                if any(ext in url.lower() for ext in DIRECT_EXTENSIONS + STREAM_EXTENSIONS):
                    network_candidates.append(url)
                    return
                if content_type.startswith(("video/", "audio/")) or "mpegurl" in content_type or "dash+xml" in content_type:
                    network_candidates.append(url)
                    return
                if "json" in content_type or "javascript" in content_type:
                    body = response.text()
                    network_candidates.extend(MEDIA_URL_PATTERN.findall(body))
            except Exception:
                return

        page.on("response", capture_response)

        try:
            for candidate_url in _candidate_page_urls(source_url, platform):
                try:
                    page.goto(candidate_url, wait_until="domcontentloaded", timeout=settings.browser_timeout_seconds * 1000)
                    page.wait_for_timeout(settings.browser_wait_after_load_ms)
                except PlaywrightTimeoutError:
                    page_errors.append(f"timeout cargando {candidate_url}")
                    continue
                except Exception as exc:
                    page_errors.append(f"error cargando {candidate_url}: {exc}")
                    continue

                candidates = _extract_dom_media_candidates(page)
                candidates.extend(network_candidates)
                for media_url in dict.fromkeys(_normalize_media_url(item) for item in candidates):
                    if not media_url.startswith("http"):
                        continue
                    try:
                        return _download_resolved_media(media_url, candidate_url, output_template, settings, cookies_file)
                    except Exception as exc:
                        page_errors.append(f"fallo descargando {media_url}: {exc}")
                        continue
        finally:
            context.close()
            browser.close()

    details = "\n".join(page_errors).strip()
    if not details:
        details = "No se detecto ningun media URL util en el navegador"
    raise RuntimeError(details)


def _set_job_status(db: Session, job: DownloadJob, status: str, error_message: str | None = None) -> None:
    job.status = status
    job.error_message = error_message
    if status == "processing" and job.started_at is None:
        job.started_at = datetime.now(UTC)
    if status in {"completed", "failed"}:
        job.completed_at = datetime.now(UTC)
    db.add(job)
    db.commit()
    db.refresh(job)


def process_job(job_id: str) -> None:
    settings = get_settings()
    ensure_bucket()

    db = SessionLocal()
    job_uuid = UUID(job_id)
    try:
        job = db.get(DownloadJob, job_uuid)
        if job is None:
            raise RuntimeError(f"Job {job_id} no existe")

        _set_job_status(db, job, "processing")

        with TemporaryDirectory(prefix=f"pixelsave-{job_id}-") as temp_dir:
            temp_path = Path(temp_dir)
            cookies_file = _resolve_cookies_file(settings, temp_path)
            output_template = temp_path / "%(title).120B-%(id)s.%(ext)s"
            downloaded_file = _resolve_browser_media(job.source_url, output_template, settings, cookies_file)

            if not downloaded_file.exists():
                raise RuntimeError("El archivo descargado no existe despues del extractor de navegador")

            object_key = f"{job.id}/{downloaded_file.name}"
            content_type = _guess_content_type(downloaded_file)
            file_size = upload_file(str(downloaded_file), object_key, content_type=content_type)

            job.title = downloaded_file.stem
            job.filename = downloaded_file.name
            job.content_type = content_type
            job.file_size_bytes = file_size
            job.storage_bucket = settings.storage_bucket
            job.storage_object_key = object_key
            _set_job_status(db, job, "completed")
    except Exception as exc:
        db.rollback()
        job = db.get(DownloadJob, job_uuid)
        if job is not None:
            _set_job_status(db, job, "failed", str(exc))
        raise
    finally:
        db.close()
