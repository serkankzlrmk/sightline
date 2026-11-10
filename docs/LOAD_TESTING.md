# Load Testing — Sightline

> Amaç: yüksek trafikte nerede tıkandığımızı **ölçmek**, sonra guard/ölçekleme
> kararını veriyle vermek. Tarih: 2026-11-10 · Durum: local, canlıya alınmadı.

---

## 1. Mevcut kapasite gerçekleri

| Kısıt | Değer | Etki |
|---|---|---|
| Gunicorn worker | 1 | SQLite/Chroma tek-process kısıtı |
| Thread | 4 (`gthread`) | Aynı anda ~4 uzun istek |
| Chat SSE | 6–30 sn/istek | Her stream bir thread'i tutar |
| `max_requests` | 1000 | Worker restart; in-memory nonce/job/rate sıfırlanır |
| Caddy SSE | 300s read/write | Uzun stream'lerde timeout uyumu |
| Gunicorn timeout | 120s | SSE ile uyumsuzluk riski |
| Rate limit | 120/dk/IP; agent 30/dk; custom 100/gün/IP | Paylaşımlı IP tıkanabilir |

**Beklenti:** public SSR/API yüksek RPS'e dayanabilir (cache ile), ama **eşzamanlı
chat ~4** ile sınırlı. Bu yüzden chat için concurrency guard (503 + Retry-After)
ve kuyruk/rate-limit tasarımı gerekir.

---

## 2. Araç

`scripts/load_test.py` — async httpx, harici bağımlılık yok:

```bash
# 20 eşzamanlı, 200 istek (public endpoint'ler)
.venv/bin/python scripts/load_test.py --concurrency 20 --requests 200

# Belirli path'ler
.venv/bin/python scripts/load_test.py \
  --paths /crisis,/countries,/api/public/stats \
  --concurrency 50 --requests 500
```

Çıktı: `rps`, `p50/p95/p99`, `error_rate`, `max_ms`, hata örnekleri.

> Chat SSE yük testi gerçek LLM maliyeti yaratır. Bir sonraki adımda mock
> OpenAI-compatible sunucu (`scripts/mock_openai_server.py`) ile yapılacak;
> o zamana kadar chat için sadece düşük adetli smoke yapın.

---

## 3. Senaryolar

1. **Public okuma** (varsayılan): `/api/public/stats`, `/api/map/countries`, `/crisis`.
2. **SSR sayfalar**: `/countries`, `/sitreps`, `/bulletins`.
3. **Auth/DB**: `/api/db/stats` (token gerekir; load test script şu an public).
4. **Chat**: mock LLM; 1/4/8/16 eşzamanlı; guard davranışı.
5. **SITREP/proposal**: mock job veya tek gerçek run (dikkatli).

---

## 4. Yorumlama

- p95 hedefi: public API < 500 ms, SSR < 1 sn (cache sonrası).
- error_rate > %1 → guard/cache/DB incelemesi.
- RPS artarken p95 dikleşiyorsa: CPU, thread pool, SQLite lock veya LLM.
- 503 oranı > 0 ve Retry-After dönüyorsa concurrency guard devrede (beklenen).
- `max_requests` restart'ları test sırasında görülürse state kaybı riski.

---

## 5. Guard'lar (uygulanan)

- `CHAT_MAX_CONCURRENT` (default 8): chat SSE semaphore; doluysa 503 +
  `retry_after=10`, `code=ERR-capacity`.
- Public cache header: `/api/public/*`, `/api/map/*`, SSR yayın sayfaları 60 sn
  (`stale-while-revalidate`).
- Request/error sayaçları `errors.db.error_stats_minute`'a 30 sn'de bir toplu yazılır.
- Rate limit / admin muafiyetleri mevcut.

> Not: gunicorn 4 thread iken semaphore 8 pratikte devreye girmez; thread sayısı
> veya replika artırıldığında etkili olur. Ölçüme göre `deploy/gunicorn.conf.py`
> `threads` 8'e çıkarılabilir (bellek testi sonrası).

---

## 5.1 Ölçülen baseline (local, 2026-11-10)

Komut:

```bash
python scripts/load_test.py --concurrency 20 --requests 100 \
  --paths /api/public/stats,/api/map/countries,/crisis
```

Sonuç (local Mac, dev sunucu):

| Metrik | Değer |
|---|---|
| Toplam istek | 100 |
| Hata | 0 (%0) |
| RPS | 384.2 |
| p50 | 35.3 ms |
| p95 | 120.9 ms |
| p99 | 128.4 ms |
| max | 129.5 ms |

**Bulgu:** `/api/map/countries` cold cache'te (60 ülke taraması) dakikalarca
sürebiliyor ve gelen thread'leri tıkıyor. Düzeltme: `output/map_countries_cache.json`
disk cache'i + 30 dk TTL + stale-while-revalidate + single-flight; restart sonrası
ilk istek diskten **1.6 ms**. Cold build (cache yokken) hâlâ yavaştır; deploy
sonrası bir kez ısıtma (`curl /api/map/countries` veya cron) önerilir.

---

## 6. Sonraki adımlar (veriyle)

1. Baseline raporunu doldur (RPS/p95/hata).
2. Chat mock LLM load testi + guard 503 doğrulaması.
3. Gerekirse: gunicorn threads 8, Redis rate-limit/job, Postgres/pgvector, CDN.
4. SLO alarmları (`scripts/alert_check.py`) + uptime monitor.
