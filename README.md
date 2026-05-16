# PixelSave

MVP dockerizado para gestionar descargas de medios publicos mediante jobs en segundo plano.

## Stack

- `web`: Next.js 15.5.2 + React 19.1.1
- `api`: FastAPI 0.136.1
- `worker`: RQ 2.8.0 + `yt-dlp` 2026.3.17 + `ffmpeg`
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
- Se puede configurar un `cookies.txt` opcional via `YT_DLP_COOKIES_FILE` para casos donde una plataforma degrade el acceso anonimo.
- No hay autenticacion ni rate limiting todavia.
- La separacion por "usuario" es por navegador/dispositivo mediante un identificador local persistente.
- Los jobs y archivos expiran a las 24 horas.

## Notas para Instagram

- El worker ahora usa `yt-dlp` con `impersonation`, reintentos y headers web especificos de Instagram para mejorar la descarga anonima de reels y posts publicos.
- Si Instagram responde con `login required`, `rate-limit reached` o `unable to extract video url`, lo siguiente a revisar es:
  - actualizar la imagen para tomar una version mas reciente de `yt-dlp`
  - verificar que `curl-cffi` este instalado dentro del contenedor
  - montar un `cookies.txt` opcional en `YT_DLP_COOKIES_FILE` para los casos que Meta no entregue bien el media URL de forma anonima

## Nota de cumplimiento

Meta y X imponen restricciones al acceso automatizado y a la redistribucion de contenido. Antes de publicar esto, revisa terminos, permisos y uso legitimo por plataforma.
