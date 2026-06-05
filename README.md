# PixelSave

MVP dockerizado para gestionar descargas de medios publicos mediante jobs en segundo plano.

## Stack

- `web`: Next.js 15.5.2 + React 19.1.1
- `api`: FastAPI 0.136.1
- `worker`: RQ 2.8.0 + Playwright Chromium + `ffmpeg`
- `redis`: cola de jobs
- `postgres`: persistencia
- `minio`: almacenamiento S3-compatible

## Arranque

1. Copia variables base:

```bash
cp .env.example .env
```

2. Levanta todo:

```bash
docker compose up --build
```

## URLs

- Web: `http://localhost:3000`
- API: `http://localhost:8000`
- MinIO Console: `http://localhost:9001`

## Endpoints principales

- `POST /api/v1/jobs`
- `GET /api/v1/jobs`
- `GET /api/v1/jobs/{job_id}`
- `GET /api/v1/jobs/{job_id}/download`

## Limitaciones del MVP

- Solo pensado para contenido publico.
- No maneja login interactivo ni cookies de navegador del host.
- Se puede configurar un `cookies.txt` opcional via `YT_DLP_COOKIES_FILE`, `YT_DLP_COOKIES_TEXT` o `YT_DLP_COOKIES_BASE64`.
- No hay autenticacion ni rate limiting todavia.
- La separacion por "usuario" es por navegador/dispositivo mediante un identificador local persistente.
- Los jobs y archivos expiran a las 24 horas.

## Resolver de Medios

- Todas las plataformas pasan por un resolver basado en Chromium headless con Playwright.
- El resolver intenta detectar URLs directas de video/audio y manifests HLS/DASH desde el DOM y desde las respuestas de red.
- Si detecta un archivo directo, lo descarga por HTTP.
- Si detecta un stream `.m3u8` o `.mpd`, lo materializa con `ffmpeg`.
- Si una plataforma exige login o limita la IP, revisa estas variables:
  - `YT_DLP_COOKIES_FILE`, `YT_DLP_COOKIES_TEXT` o `YT_DLP_COOKIES_BASE64`
  - `YT_DLP_PROXY`
  - `BROWSER_TIMEOUT_SECONDS`
  - `BROWSER_WAIT_AFTER_LOAD_MS`

## Nota de cumplimiento

Meta y X imponen restricciones al acceso automatizado y a la redistribucion de contenido. Antes de publicar esto, revisa terminos, permisos y uso legitimo por plataforma.
