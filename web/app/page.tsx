"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import en from "../messages/en.json";
import es from "../messages/es.json";
import pt from "../messages/pt.json";

type Job = {
  id: string;
  source_url: string;
  platform: string;
  status: string;
  error_message: string | null;
  title: string | null;
  filename: string | null;
  content_type: string | null;
  file_size_bytes: number | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
  download_url: string | null;
};

const translations = { es, en, pt };
const supportedLocales = ["es", "en", "pt"] as const;
const statusFilters = ["all", "queued", "processing", "completed", "failed"] as const;
type Locale = (typeof supportedLocales)[number];
type StatusFilter = (typeof statusFilters)[number];
type Translation = (typeof translations)[Locale];

function getApiBaseUrl(): string {
  if (typeof window === "undefined") {
    return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://api:8000";
  }
  const envValue = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (envValue) {
    return envValue;
  }
  return `${window.location.protocol}//${window.location.hostname}:8000`;
}

function getClientId(): string {
  const storageKey = "pixelsave-client-id";
  const existingId = window.localStorage.getItem(storageKey);
  if (existingId) {
    return existingId;
  }
  const newId = window.crypto.randomUUID();
  window.localStorage.setItem(storageKey, newId);
  return newId;
}

function detectLocale(): Locale {
  const savedLocale = window.localStorage.getItem("pixelsave-locale");
  if (savedLocale && supportedLocales.includes(savedLocale as Locale)) {
    return savedLocale as Locale;
  }
  for (const language of navigator.languages) {
    const base = language.toLowerCase().split("-")[0] as Locale;
    if (supportedLocales.includes(base)) {
      return base;
    }
  }
  return "es";
}

function setStoredLocale(locale: Locale) {
  window.localStorage.setItem("pixelsave-locale", locale);
}

function formatFileSize(bytes: number | null, locale: Locale): string {
  if (!bytes) {
    return "-";
  }
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${new Intl.NumberFormat(locale, {
    maximumFractionDigits: value >= 10 || unitIndex === 0 ? 0 : 1
  }).format(value)} ${units[unitIndex]}`;
}

function formatDate(dateValue: string, locale: Locale): string {
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(new Date(dateValue));
}

function getStatusTone(status: string): string {
  switch (status) {
    case "completed":
      return "is-success";
    case "failed":
      return "is-danger";
    case "processing":
      return "is-warning";
    default:
      return "is-neutral";
  }
}

export default function HomePage() {
  const apiBaseUrl = useMemo(() => getApiBaseUrl(), []);
  const clientId = useMemo(() => (typeof window === "undefined" ? "" : getClientId()), []);
  const [locale, setLocale] = useState<Locale>("es");
  const [url, setUrl] = useState("");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<StatusFilter>("all");

  const t: Translation = translations[locale];

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const detectedLocale = detectLocale();
    setLocale(detectedLocale);
    document.documentElement.lang = detectedLocale;
  }, []);

  async function loadJobs(activeLocale: Locale) {
    if (!clientId) {
      throw new Error(translations[activeLocale].errors.missingClientId);
    }
    const response = await fetch(`${apiBaseUrl}/api/v1/jobs`, {
      cache: "no-store",
      headers: {
        "X-Client-Id": clientId
      }
    });
    if (!response.ok) {
      throw new Error(translations[activeLocale].errors.loadJobs);
    }
    const payload = await response.json();
    setJobs(payload.items);
  }

  useEffect(() => {
    loadJobs(locale).catch((loadError: Error) => setError(loadError.message));
    const timer = window.setInterval(() => {
      loadJobs(locale).catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [apiBaseUrl, clientId, locale]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);

    try {
      const response = await fetch(`${apiBaseUrl}/api/v1/jobs`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Client-Id": clientId
        },
        body: JSON.stringify({ url })
      });

      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? t.errors.createJob);
      }

      setUrl("");
      await loadJobs(locale);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : t.errors.unexpected);
    } finally {
      setSubmitting(false);
    }
  }

  function handleLocaleChange(nextLocale: Locale) {
    setLocale(nextLocale);
    setStoredLocale(nextLocale);
    document.documentElement.lang = nextLocale;
  }

  const filteredJobs = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return jobs.filter((job) => {
      const matchesFilter = filter === "all" ? true : job.status === filter;
      const haystack = [job.source_url, job.filename ?? "", job.title ?? "", job.platform].join(" ").toLowerCase();
      const matchesQuery = normalizedQuery ? haystack.includes(normalizedQuery) : true;
      return matchesFilter && matchesQuery;
    });
  }, [filter, jobs, query]);

  return (
    <main className="page-shell">
      <header className="topbar">
        <div className="brand-cluster">
          <div className="brand-mark">PS</div>
          <div>
            <p className="eyebrow">{t.tagline}</p>
            <h1 className="app-title">{t.appName}</h1>
          </div>
        </div>
        <div className="language-switcher" aria-label={t.language.label}>
          {supportedLocales.map((option) => (
            <button
              key={option}
              type="button"
              className={`locale-button${locale === option ? " active" : ""}`}
              onClick={() => handleLocaleChange(option)}
            >
              {t.language[option]}
            </button>
          ))}
        </div>
      </header>

      <section className="hero-card">
        <p className="hero-title">{t.heroTitle}</p>
        <p className="hero-description">{t.heroDescription}</p>

        <form className="hero-form" onSubmit={handleSubmit}>
          <input
            className="hero-input"
            type="url"
            placeholder={t.composer.placeholder}
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            required
          />
          <button className="primary-button hero-button" type="submit" disabled={submitting}>
            {submitting ? t.composer.submitBusy : t.composer.submitIdle}
          </button>
        </form>

        <p className="hero-helper">{t.composer.description}</p>
        <div className="helper-list">
          {t.composer.helperItems.map((item) => (
            <span className="helper-pill" key={item}>
              {item}
            </span>
          ))}
        </div>

        {error ? <p className="error-banner">{error}</p> : null}
      </section>

      <section className="history-section">
        <div className="history-header">
          <div>
            <h2>{t.history.title}</h2>
            <p>{t.history.description}</p>
          </div>
        </div>

        <div className="history-toolbar">
          <input
            className="search-input"
            type="search"
            placeholder={t.history.searchPlaceholder}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <div className="filter-group">
            {statusFilters.map((status) => (
              <button
                key={status}
                type="button"
                className={`filter-chip${filter === status ? " active" : ""}`}
                onClick={() => setFilter(status)}
              >
                {t.history.filters[status]}
              </button>
            ))}
          </div>
        </div>

        <div className="jobs-list">
          {filteredJobs.length === 0 ? <p className="empty-state">{t.history.empty}</p> : null}
          {filteredJobs.map((job) => {
            const downloadHref = job.download_url
              ? `${apiBaseUrl}${job.download_url}?client_id=${encodeURIComponent(clientId)}`
              : null;

            return (
              <article className="job-card" key={job.id}>
                <div className="job-topline">
                  <div className="platform-chip">{job.platform}</div>
                  <div className={`status-chip ${getStatusTone(job.status)}`}>
                    {t.statusLabels[job.status as keyof typeof t.statusLabels] ?? job.status}
                  </div>
                </div>

                <div className="job-title">{job.filename ?? job.title ?? job.source_url}</div>

                <dl className="job-metadata">
                  <div>
                    <dt>{t.history.source}</dt>
                    <dd>{job.source_url}</dd>
                  </div>
                  <div>
                    <dt>{t.history.size}</dt>
                    <dd>{formatFileSize(job.file_size_bytes, locale)}</dd>
                  </div>
                  <div>
                    <dt>{t.history.created}</dt>
                    <dd>{formatDate(job.created_at, locale)}</dd>
                  </div>
                  <div>
                    <dt>{t.history.status}</dt>
                    <dd>{t.statusLabels[job.status as keyof typeof t.statusLabels] ?? job.status}</dd>
                  </div>
                </dl>

                {job.error_message ? <p className="job-error">{job.error_message}</p> : null}
                {downloadHref ? (
                  <a className="download-link" href={downloadHref}>
                    {t.history.download}
                  </a>
                ) : null}
              </article>
            );
          })}
        </div>
      </section>
    </main>
  );
}
