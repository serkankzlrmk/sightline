# NovaSphere — Kod Haritası

> Son güncelleme: 28 Mayıs 2026
> Bu belge projenin geldiği noktayı kaydeder. Her dosyanın ne yaptığını, veri akışını, API route'larını ve mimari kararları açıklar. Gelecek geliştirme oturumlarında hızlıca bağlam kurmak için kullanılır.

---

## İçindekiler

1. [Proje Özeti](#1-proje-özeti)
2. [Dizin Yapısı](#2-dizin-yapısı)
3. [Dosya Referansı](#3-dosya-referansı)
4. [Veri Akışı](#4-veri-akışı)
5. [API Route Tablosu](#5-api-route-tablosu)
6. [Konfigürasyon Referansı](#6-konfigürasyon-referansı)
7. [Frontend Mimarisi](#7-frontend-mimarisi)
8. [Deployment Mimarisi](#8-deployment-mimarisi)
9. [Bilinen Sorunlar ve Teknik Borç](#9-bilinen-sorunlar-ve-teknik-borç)
10. [Geliştirme Rehberi](#10-geliştirme-rehberi)

---

## 1. Proje Özeti

**NovaSphere**, insani yardım verilerini analiz eden bir web platformudur. 3 ana özellik sunar:

| Tab | İşlev | Kullanıcı |
|-----|-------|-----------|
| **Database** | ReliefWeb raporlarını tarayıcı, filtrele, detay görüntüle | Herkes |
| **NovaSphere** | AI destekli sohbet asistanı (ChromaDB + ReliefWeb API) | Herkes |
| **SITREP** | Otomatik durum raporu üretim hattı (9.5 aşama) | Admin |

**Teknoloji Stack:**
- **Backend:** Flask + Gunicorn (Python 3.12+)
- **Veritabanı:** SQLite (yapılandırılmış veri) + ChromaDB (vektör arama)
- **LLM:** OpenRouter API (google/gemini-2.5-flash varsayılan)
- **Auth:** Firebase Admin SDK (Google Sign-In)
- **Frontend:** Vanilla JS + CSS (tek sayfa uygulama)
- **Deployment:** Hetzner ARM64 + Nginx + Systemd + Auto-deploy cron

**Mimari Şema:**
```
Kullanıcı → Nginx (HTTPS) → Gunicorn (127.0.0.1:5001) → Flask (server.py)
                                                              │
                                              ┌───────────────┼───────────────┐
                                              │               │               │
                                         SQLite + ChromaDB  LangGraph Agent  SITREP Pipeline
                                              │               │               │
                                         ReliefWeb API ←──────┘       OpenRouter LLM
```

---

## 2. Dizin Yapısı

```
NovaSphere/
├── server.py              # Birleşik Flask sunucusu (tüm API route'ları)
├── auth.py                # Kimlik doğrulama (Firebase + API key + dev mode)
├── config.py              # Tüm konfigürasyon (.env'den override)
├── requirements.txt       # Python bağımlılıkları
├── .env.example           # Çevre değişkenleri şablonu
├── .gitignore             # Git hariç tutma kuralları
├── pyproject.toml         # Proje metadata + ruff lint config
│
├── agent/                 # LangGraph AI Agent
│   ├── model.py           # LLM model başlatma (OpenRouter/Ollama)
│   ├── relief_agent.py    # Agent graph + system prompt + CLI
│   └── setup.py           # Bağımlılık/dizin doğrulama
│
├── reliefweb_api/         # ReliefWeb API entegrasyonu
│   ├── reliefweb.py       # 13+ LangChain @tool fonksiyonu
│   ├── db_manager.py      # SQLite CRUD + chunking
│   ├── vector_store.py    # ChromaDB vektör arama
│   ├── ingest_pipeline.py # API'den → SQLite + ChromaDB ingest
│   ├── download_manager.py# Dosya indirme (legacy, artık kullanılmıyor)
│   ├── pdf_converter.py   # PDF → Markdown/JSON dönüşüm
│   ├── reliefweb_config.py# API URL'leri, ülke haritası, zaman aşımları
│   └── reliefweb_utils.py # HTTP yardımcıları, HTML temizleme, doğrulama
│
├── sitrep/                # SITREP durum raporu hattı
│   ├── pipeline.py        # 9.5 aşama orkestrasyon + checkpoint
│   ├── chroma_adapter.py  # ChromaDB veri çekme + semantik arama
│   ├── llm_client.py      # LLM istemcisi (raw requests)
│   ├── clustering.py      # UMAP + HDBSCAN kümeleme
│   ├── question_generation.py  # Küme bazlı soru üretimi
│   ├── question_filtering.py  # 4 kriterli soru filtreleme
│   ├── rag_answers.py     # RAG Fusion cevap üretimi
│   ├── citation_postprocess.py # Atıf doğrulama + yeniden sıralama
│   ├── cluster_summary.py # Küme özetleri
│   ├── executive_summary.py# Yönetici özeti
│   ├── narrative_report.py# HTML anlatı raporu
│   └── report_assembly.py # Son rapor birleştirme (LLM yok)
│
├── database/              # CLI yardımcı scriptleri
│   ├── ingest.py          # Toplu ingest + ChromaDB senkronizasyon
│   └── db_query.py        # DB sorgu aracı (Türkçe UI)
│
├── scripts/               # Otomasyon scriptleri
│   ├── daily_ingest.py    # Günlük otomatik ingest + purge
│   └── backfill_ingest.py # 1 seferlik geçmiş veri çekme
│
├── deploy/                # Üretim deployment
│   ├── deploy.sh          # Güvenli deploy (otomatik rollback)
│   ├── rollback.sh        # Manuel rollback
│   ├── setup.sh           # VM kurulum scripti
│   ├── auto-deploy.sh    # Cron tabanlı otomatik deploy
│   ├── backup.sh          # Günlük DB yedekleme
│   ├── update.sh          # deploy.sh wrapper
│   ├── gunicorn.conf.py   # Gunicorn konfigürasyonu
│   ├── nginx.conf         # Nginx reverse proxy
│   ├── novasphere.service# Systemd unit dosyası
│   ├── logrotate.conf     # Log rotasyonu
│   ├── daily-ingest.cron  # Günlük ingest cron girdisi
│   └── cloud-init.yaml    # Oracle Cloud VM otomatik kurulum
│
├── templates/
│   └── index.html         # Tek sayfa HTML (3 tab + auth overlay + modal)
│
├── static/
│   ├── app.js             # Ana frontend JS (tüm tab mantığı)
│   ├── auth.js            # Firebase auth + dev mode bypass
│   ├── style.css          # Tam CSS tasarım sistemi
│   └── logo.png           # Marka logosu
│
├── tests/                 # Temel testler
│   ├── test_health.py     # Health endpoint testi
│   ├── test_config.py     # Konfigürasyon testi
│   └── test_imports.py    # Modül import testi
│
└── .github/workflows/     # CI/CD (şu an devre dışı)
    ├── ci.yml             # Ruff lint + pytest
    ├── deploy.yml         # GitHub Actions deploy
    └── rollback.yml       # GitHub Actions rollback
```

---

## 3. Dosya Referansı

### 3.1 Kök Düzey Dosyalar

#### `server.py` (~1450 satır)
Birleşik Flask sunucusu. Tüm API route'ları, chat kalıcılığı, SITREP iş çalıştırıcı, DB yardımcıları ve güvenlik başlıkları burada.

| Fonksiyon | İşlev |
|-----------|-------|
| `_ssl_verify()` | `SSL_VERIFY` env var'ına göre requests verify parametresi |
| `add_security_headers()` | CSP, COOP, COEP, CORP, X-Frame-Options başlıkları |
| `_check_api_rate_limit()` | IP bazlı günlük rate limiter (100/gün) — **NOT: hiçbir route'a uygulanmadı** |
| `_chats_db()` | chats.db SQLite bağlantısı (WAL modu) |
| `_check_rate_limit(uid)` | Kullanıcı bazlı günlük mesaj sayısı kontrolü |
| `_increment_rate_limit(uid)` | Atomik günlük sayı artırma |
| `_init_chats_db()` | chats, chat_messages, rate_limits tabloları + uid migrasyonu |
| `_ensure_active_chat(uid)` | Kullanıcı için aktif sohbet döndür/oluştur |
| `_load_langchain_messages(chat_id)` | DB mesajlarını LangChain nesnelerine yükle |
| `_get_agent()` | LangGraph agent lazy singleton |
| `_generate_chat_title()` | Arka plan thread'de LLM başlık üretimi |
| `_db_conn()` | reliefweb.db SQLite bağlantısı |
| `_run_job()` | SITREP pipeline subprocess çalıştırıcı (ANSI temizleme) |

**Önemli notlar:**
- ONNX/TensorRT env var'ları dosyanın en üstünde ayarlanır
- `_user_active_chat` dict ile kullanıcı bazlı sohbet izolasyonu
- `_user_agent_busy` dict ile 10 dakika otomatik kilit açma timeout'u
- `_check_api_rate_limit` tanımlı ama hiçbir route'a bağlanmadı (teknik borç)

---

#### `auth.py` (~260 satır)
Kimlik doğrulama tek kaynağı. Firebase Admin SDK token doğrulama, eski API key modu, dev mode bypass.

| Fonksiyon | İşlev |
|-----------|-------|
| `_firebase_app()` | Firebase Admin SDK lazy-init (3 yolda SA dosyası arar) |
| `_admins()` | ADMIN_UIDS env var'ından admin UID seti döndür |
| `_api_key()` | SERVER_API_KEY döndür |
| `_dev_mode()` | `DEV_AUTH_BYPASS=true` VEYA (SERVER_DEBUG=true + Firebase SA yok + API key yok) |
| `verify_firebase_token(token)` | Firebase ID token doğrulama (`check_revoked=False`, clock skew retry) |
| `current_uid()` | `g.current_user.uid` döndür |
| `require_auth(f)` | Firebase Bearer token VEYA API key VEYA dev mode bypass |
| `require_admin(f)` | require_auth + UID ADMIN_UIDS içinde olmalı |

**Önemli notlar:**
- Dev mode mock kullanıcı: `{uid: "dev-local", email: "dev@localhost", admin: True}`
- Clock skew retry: 2 saniye bekle, tekrar dene
- SA dosyası 3 konumda aranır: proje kökü, data/, current/

---

#### `config.py` (~200 satır)
Tüm konfigürasyon. Her değer `.env` ile override edilebilir.

| Kategori | Anahtar Değerler |
|----------|-----------------|
| **Yollar** | `PROJECT_ROOT`, `DOWNLOADS_DIR`, `DB_PATH`, `CHATS_DB_PATH`, `CHROMA_DIR` |
| **LLM** | `LLM_PROVIDER` (openrouter/ollama), `OPENROUTER_BASE_URL/KEY`, `OLLAMA_BASE_URL/KEY` |
| **Model** | `ACTIVE_MODEL`, `LLM_MODEL` (varsayılan: `google/gemini-2.5-flash`) |
| **Parametreler** | `MODEL_TEMPERATURE=0.3`, `MODEL_MAX_TOKENS=2048` |
| **SITREP LLM** | `LLM_MODEL_QUESTIONS/FILTER/ANSWERS`, ayrı sıcaklık ayarları |
| **Retrieval** | `RETRIEVAL_TOP_K=10`, `RETRIEVAL_TOP_K_SUMMARY=20`, `RRF_K=60` |
| **Kümeleme** | `UMAP_N_COMPONENTS=10`, `HDBSCAN` parametreleri, `HP_SEARCH_ITERATIONS=30` |
| **Soru Üretim** | `QUESTION_RUNS_PER_CLUSTER=3`, `MAX_QUESTIONS_PER_CLUSTER=6` |
| **Sunucu** | `SERVER_HOST=0.0.0.0`, `SERVER_PORT=5001`, `DAILY_MESSAGE_LIMIT=10` |

**Önemli notlar:**
- Modül yüklemesinde ONNX/TensorRT gürültü bastırma
- `_Config` sınıfı geriye uyumluluk için (`from config import config`)
- Output dizinleri otomatik oluşturulur

---

### 3.2 `agent/` Dizini

#### `agent/model.py` (~200 satır)
LLM model başlatma ve yönetim. OpenRouter ve Ollama sağlayıcıları destekler.

| Fonksiyon | İşlev |
|-----------|-------|
| `ModelInitializationError` | Özel hata sınıfı |
| `check_llm_connectivity(max_retries=3)` | OpenRouter `/models` veya Ollama `/api/tags` kontrol |
| `check_model_available(model_name)` | OpenRouter her zaman True; Ollama yerel model listesini kontrol |
| `initialize_model(skip_checks=False)` | `ChatOpenAI` örneği oluşturur |
| `get_model(skip_checks=False)` | Singleton wrapper, başarısızlıkta None döner |

**Not:** OpenRouter modelleri isteğe bağlı sunulur (kullanılabilirlik kontrolü gerekmez).

---

#### `agent/relief_agent.py` (~400 satır)
LangGraph tabanlı ajan sistemi. Agent graph (llm_call → tool_node döngüsü), ~250 satırlık system prompt ve CLI arayüzü.

| Fonksiyon | İşlev |
|-----------|-------|
| `_build_system_prompt()` | Tarih, kimlik, güvenlik kuralları, araç açıklamaları, atıf formatı |
| `llm_call(state)` | LLM düğümü: araç çağrısı veya yanıt üretir |
| `tool_node(state)` | Araç çağrılarını yürütür (bozuk isim kurtarma ile) |
| `should_continue(state)` | Koşullu kenar: tool_node veya END |
| `relief_agent` | Derlenmiş LangGraph `StateGraph` |
| `run_conversational_agent()` | Çok turlu CLI arayüzü |

**Notlar:**
- LLM akış artifact'larından kaynaklanan araç ismi bozulması düzeltmesi var
- `recursion_limit=25`
- `sys.path.insert` ile agent/ ve kök dizin eklenir (CLI için)

---

#### `agent/setup.py` (~100 satır)
Sistem kurulum doğrulama yardımcıları.

| Fonksiyon | İşlev |
|-----------|-------|
| `verify_dependencies()` | Gerekli Python paketlerini kontrol |
| `verify_directories()` | DOWNLOADS_DIR ve CHROMA_DIR yazılabilirlik kontrol |
| `verify_ollama()` | Ollama çalışıyor + model mevcut mu |
| `run_setup()` | Tüm kontrolleri çalıştır |

**⚠️ Sorun:** `check_ollama_connectivity` referansı `model.py`'de `check_llm_connectivity` olarak yeniden adlandırıldı — import hatası olabilir.

---

### 3.3 `reliefweb_api/` Dizini

#### `reliefweb_api/reliefweb.py` (~900 satır)
13+ LangChain `@tool` fonksiyonu. Agent'ın ReliefWeb API ile etkileşimi buradan.

| Araç | İşlev |
|------|-------|
| `search_sitreps()` | Gelişmiş filtrelerle rapor arama (ülke, tema, kaynak, tarih, format, dil, afet, org tipi) |
| `get_sitrep_summary(report_id)` | Kısa özet (~700 karakter), yerel DB önce, sonra API |
| `get_report_full_content(report_id)` | Tam içerik, yerel DB önce, sonra API |
| `search_disasters(country, status)` | Afet arama |
| `search_disasters_by_date(start, end)` | Tarih aralığı afet arama |
| `get_latest_headlines(limit)` | Son küresel başlıklar |
| `download_and_read_full_pdf(report_id)` | PDF içeriğini bellekte indir |
| `ingest_report_from_api(report_id)` | Tek rapor fetch + ingest (bellekte) |
| `ingest_reports_batch(report_ids)` | Toplu ingest (akıllı dedup) |
| `convert_report_to_markdown/json(report_id)` | Format dönüşüm |
| `parse_reliefweb_url(url)` | ReliefWeb URL'sini parse et |
| `search_sources(query, country)` | Organizasyon arama |
| `search_knowledge_base(query, n_results)` | **ChromaDB semantik arama** (agent'ın birincil bilgi kaynağı) |
| `mcp_langchain_tools` | Tüm araçların listesi (agent binding için) |

**Not:** `search_knowledge_base` agent'ın ilk başvuru kaynağıdır. Bulamazsa `search_sitreps` ile API'ye düşer.

---

#### `reliefweb_api/db_manager.py` (~350 satır)
SQLite destekli ReliefWeb rapor deposu. Deduplication ve chunking.

| Fonksiyon/Sınıf | İşlev |
|-----------------|-------|
| `DatabaseManager` | CRUD sınıfı: `report_exists()`, `insert_report()`, `get_stats()`, `purge_old_reports()`, `get_old_report_ids()` |
| `chunk_text(text, chunk_size=800, overlap=150)` | Cümle sınırı duyarlı parçalama |
| `build_chunk_with_header(raw_chunk, metadata, source_type)` | Metadata başlığı ekler |
| `extract_pdf_text(pdf_path)` | PyPDF2 metin çıkarma |
| `get_db(db_path)` | Fabrika fonksiyonu |

**Not:** Her işlemde yeni bağlantı (WAL modu). `CHUNK_SIZE=800`, `CHUNK_OVERLAP=150`.

---

#### `reliefweb_api/vector_store.py` (~250 satır)
ChromaDB destekli semantik arama.

| Fonksiyon/Sınıf | İşlev |
|-----------------|-------|
| `VectorStore` | `report_exists()`, `add_report()`, `search(query, n_results, country, source)`, `delete_report()`, `purge_by_report_ids()` |

**Not:** `get_or_create_collection` kullanır (koleksiyon yoksa çökmez). Kosinüs mesafesi. Chunk ID formatı: `{report_id}_{chunk_index}`.

---

#### `reliefweb_api/ingest_pipeline.py` (~250 satır)
İndirilen raporları SQLite + ChromaDB'ye eklemek için paylaşılan mantık.

| Fonksiyon | İşlev |
|-----------|-------|
| `is_ingested(report_id, db_path)` | SQLite'da var mı |
| `is_ingested_with_pdf(report_id, db_path)` | PDF içeriği var mı |
| `auto_ingest(report_id, downloads_root, db_path, chroma_dir)` | Disk klasöründen → ingest (legacy) |
| `ingest_from_api(report_id, db_path, chroma_dir)` | **API'den bellekte → ingest (modern yol, disk yazımı yok)** |

**Not:** `ingest_from_api` güncel yoldur. `auto_ingest` eski disk tabanlı yoldur.

---

#### `reliefweb_api/download_manager.py` (~250 satır)
ReliefWeb raporlarını dosya sistemine indirir.

| Fonksiyon/Sınıf | İşlev |
|-----------------|-------|
| `DownloadManager` | `get_report_metadata()`, `download_pdf()`, `download_html_content()`, `download_metadata()`, `download_report()`, `download_reports_batch()` |

**⚠️ Legacy:** Artık `server.py` veya `daily_ingest.py` tarafından kullanılmıyor. `ingest_from_api` doğrudan API'den bellekte çalışıyor. Gelecek temizlikte kaldırılabilir.

---

#### `reliefweb_api/pdf_converter.py` (~200 satır)
PDF → Markdown/JSON dönüşümü. Docling varsa kullanır, yoksa PyPDF2'ye düşer.

| Sınıf | İşlev |
|-------|-------|
| `PDFConverter` | `convert_pdf_to_markdown()`, `convert_pdf_to_json()`, `save_markdown()`, `save_json()` |
| `ReportFormatConverter` | `download_and_convert_report()`, `convert_reports_batch()` |

---

#### `reliefweb_api/reliefweb_config.py` (~200 satır)
ReliefWeb API konfigürasyon sabitleri, ülke isim haritası, afet tipleri.

| Değer | Açıklama |
|-------|----------|
| `RELIEFWEB_REPORTS_API` | `https://api.reliefweb.int/v2/reports` |
| `RELIEFWEB_DISASTERS_API` | `https://api.reliefweb.int/v2/disasters` |
| `RELIEFWEB_SOURCES_API` | `https://api.reliefweb.int/v2/sources` |
| `API_TIMEOUT_SHORT/LONG` | 30s / 120s |
| `PDF_SIZE_LIMIT` | 50MB |
| `COUNTRY_NAME_MAP` | 40+ ülke isim normalizasyonu (ör: "syria" → "Syrian Arab Republic") |
| `_ssl_verify()` | `SSL_VERIFY` env var'ına göre verify parametresi |

---

#### `reliefweb_api/reliefweb_utils.py` (~200 satır)
Paylaşılan yardımcı fonksiyonlar.

| Fonksiyon | İşlev |
|-----------|-------|
| `normalize_country_name(country)` | ReliefWeb isimlendirmesine map |
| `clean_html_body(body_html)` | Tag temizleme, entity çözme, boşluk normalizasyonu |
| `truncate_text(text, max_length, suffix)` | Suffix ile kısaltma |
| `validate_country/date/limit()` | Girdi doğrulama |
| `retry_request(method, url, max_retries)` | 429/5xx/network hatalarında retry |

#### `reliefweb_api/hdx_client.py` (~900 satır)
HDX HAPI API doğrudan HTTP istemcisi (MCP server bağımlılığı yok).

| Sınıf/Fonksiyon | İşlev |
|-----------------|-------|
| `HDXClient` | Ana istemci sınıfı, async + sync metodlar |
| `HDXResult` | API yanıt sarmalayıcı (data, success, error) |
| `SimpleCache` | 24h TTL bellek içi önbellek |
| `get_country_overview_sync(cc)` | 9 endpoint paralel fetch |
| `get_sitrep_context_sync(cc)` | SITREP-ready format (summary + data_sources) |
| `get_refugees/idps/funding/conflict_sync()` | Tekil veri endpoint'leri |

#### `reliefweb_api/hdx_tools.py` (~200 satır)
LangChain @tool tanımları (6 HDX aracı).

| Tool | İşlev |
|------|-------|
| `hdx_get_country_overview` | Kapsamlı ülke insani veri özeti |
| `hdx_get_data_availability` | Veri bulunabilirliği kontrolü |
| `hdx_get_refugees` | UNHCR mülteci verileri |
| `hdx_get_idps` | IDP verileri |
| `hdx_get_funding` | Finansman verileri |
| `hdx_get_conflict_events` | ACLED çatışma olayları |

#### `reliefweb_api/country_codes.py` (~200 satır)
Ülke adı → ISO 3166-1 alpha-3 kod eşlemesi (128 ülke).

| Fonksiyon | İşlev |
|-----------|-------|
| `get_iso_code(country_name)` | Ülke adı → ISO kod (fuzzy match dahil) |
| `get_country_name(iso_code)` | ISO kod → ülke adı |
| `COUNTRY_TO_ISO` | 128 ülke eşleme dict |

---

### 3.4 `sitrep/` Dizini

#### `sitrep/pipeline.py` (~250 satır)
10.5 aşamalı SITREP pipeline orkestrasyonu. Checkpoint/resume desteği. HDX enrichment Stage 1.5.

| Fonksiyon | İşlev |
|-----------|-------|
| `_safe_name(country, event)` | Güvenli dosya adı |
| `_filter_hash(themes, date_from, date_to)` | MD5 hash (checkpoint farklılaştırma) |
| `_checkpoint_path/load/save()` | Checkpoint JSON oku/yaz |
| `run_pipeline(country, event, themes, ...)` | Tam pipeline çalıştırıcı (HDX enrichment dahil) |

**Not:** `MIN_CHUNKS_FOR_CLUSTERING=20` (altında tek küme). `sys.path.insert` subprocess için. Stage 1.5 HDX enrichment optional — fallback ile çalışır.

#### `sitrep/hdx_enrichment.py` (~250 satır)
HDX veri formatlama fonksiyonları (SITREP, bulletin, RAG, narrative için).

| Fonksiyon | İşlev |
|-----------|-------|
| `fetch_hdx_context(country)` | Ülke adı → HDX context dict (ISO kod dönüşümü dahil) |
| `format_hdx_summary_for_prompt(ctx)` | LLM prompt için özet format |
| `format_hdx_for_rag_context(ctx)` | RAG source format (numbered) |
| `format_hdx_for_bulletin(ctx)` | Bulletin key_figures + context_text |
| `format_hdx_for_narrative(ctx)` | Narrative report için yapılandırılmış veri |

---

#### `sitrep/chroma_adapter.py` (~200 satır)
ChromaDB veri çekme + semantik arama (SITREP pipeline için).

| Fonksiyon/Sınıf | İşlev |
|-----------------|-------|
| `ChromaAdapter` | `count()`, `list_countries()`, `list_themes()`, `get_date_range()`, `get_chunks_by_country()`, `get_chunks_by_country_and_themes()`, `retrieve()`, `retrieve_bulk()` |

**Not:** Chroma `$contains` operatörü yok → tema/tarih filtreleme Python tarafında. Pool-based retrieval numpy kosinüs benzerliği kullanır.

---

#### `sitrep/llm_client.py` (~200 satır)
LLM istemcisi. Raw `requests` çağrıları (LangChain kullanmaz).

| Fonksiyon | İşlev |
|-----------|-------|
| `_get_base_url_and_headers()` | Sağlayıcıya göre URL + auth başlıkları |
| `chat(messages, model, temperature, max_tokens)` | Ana LLM çağrısı (retry ile) |
| `chat_simple(user_prompt, system_prompt)` | Tek kullanıcı mesajı kısayolu |

**Not:** `