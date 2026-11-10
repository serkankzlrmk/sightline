# Chat Evaluation & Retrieval Evaluation — Sightline

> Bu doküman, chat tarafındaki **LLM/RAG evaluation sürecinin** nasıl çalıştığını,
> hangi komutların kullanıldığını ve sonuçların nerede görüldüğünü anlatır.
> Araştırma temeli: `docs/research/notebooklm_rag_eval.md` (NotebookLM, 115 kaynak).
> Tarih: 2026-11-10 · Durum: **local/CI, canlıya alınmadı**.

---

## 1. Amaç

Chat cevaplarının "iyi" olup olmadığını ölçmek; bunu tek seferlik bir his değil,
**tekrarlanabilir bir süreç** haline getirmek:

```
gerçek chat turları → obs.db telemetri → örnekleme → G-Eval judge → skorlar
      ↑                                                        │
geçmiş chat'ler (backfill)                            admin paneli + düşük skor kuyruğu
```

İki ayrı ölçüm var:
1. **Chat cevap kalitesi** (LLM-as-judge, G-Eval) — bu dokümanın ana konusu.
2. **Retrieval kalitesi** (golden set üzerinde Recall@K / nDCG@10 / MRR) — SITREP
   ve ileride chat RAG'i için.

---

## 2. Veri kaynakları

| Kaynak | İçerik | Nerede |
|---|---|---|
| `turns` | Her chat turu: model, token, maliyet, latency, citation/no-answer sinyalleri | `obs.db` |
| `tool_calls` | Tool adı, grup, MCP server, süre, hata, `result_preview` (ilk 1.2 KB) | `obs.db` |
| `chat_messages` | Gerçek soru/cevap metni | `chats.db` |
| `eval_scores` | Judge skoru + gerekçe/issue'lar (turn başına tek kayıt, upsert) | `obs.db` |
| `eval_retrieval` | Golden-set retrieval run özeti + detay | `obs.db` |

**Önemli:** `tool_calls.result_preview` yalnızca yeni turlarda dolar. Backfill edilen
eski turlarda kanıt yoktur; judge bunu açıkça "no evidence stored" olarak görür ve
groundedness iddia etmez.

---

## 3. Chat evaluation süreci (adım adım)

### 3.1 Geçmiş veriyi hazırla (bir kez / periyodik)

```bash
# önce dry-run: kaç tur bulunduğunu gösterir
python scripts/backfill_turns.py --days 90

# obs.db'ye yaz (idempotent: backfill-<message_id> ile upsert)
python scripts/backfill_turns.py --days 90 --apply
```

Sınırlar: token/maliyet/tool kanıtı eski kayıtlarda yoktur; `meta.backfilled=true`
ile işaretlenir.

### 3.2 Değerlendirme çalıştır

```bash
# dry-run (varsayılan): skorları gösterir, obs.db'ye YAZMAZ
python scripts/eval_agent.py --days 30 --sample 10

# kalıcı yaz (admin panelinde görünür)
python scripts/eval_agent.py --days 30 --sample 10 --apply

# ucuz/hızlı judge (cross-family korunur)
python scripts/eval_agent.py --sample 5 --samples 1 --judge-model deepseek/deepseek-chat
```

Varsayılanlar:
- **Judge:** `openai/gpt-5.1` (cevaplar Gemini olduğu için **cross-family**; self-preference azaltır).
- **Örneklem:** 3 judge çağrısı / cevap, skorların ortalaması (1–5 sıkışmasını azaltır).
- **Kanıt:** tool preview'ları judge'a gönderilir; yoksa "internal consistency only".
- **Güvenlik:** dry-run varsayılan; `--sample` en fazla 50 (CLI) / 25 (admin).

### 3.3 Rubrik (G-Eval)

`scripts/eval_agent.py` içindeki `_RUBRIC`:
- 1–5 çapa metinleri (5 = tam grounded/on-point; 1 = fabricated/dangerous).
- Groundedness, relevance, completeness, citation disiplini, dürüst abstention.
- **Uzunluk kalite değildir**; "kanıt bulamadım" doğru cevaptır.
- Çıktı: `{"reasoning": ..., "score": 1-5, "issues": [...]}`.

### 3.4 Admin panelinden tetikleme

- `/app` → **Admin → Observability → Chat Quality Evaluation**.
- "Run evaluation (10 turns)" butonu: `POST /api/admin/obs/eval/run`
  (arka plan thread, 10 tur × 3 sample, `apply=true`).
- "dry run" işaretliyse skorlar yazılmaz.
- Durum: `GET /api/admin/obs/eval/run/status/<job_id>`; UI 3 sn'de bir poll eder.
- Aynı anda tek eval job'ı (409 ile engellenir).

### 3.6 Uygulama içi 👍/👎 ve admin kalibrasyon UI

- **Kullanıcı memnuniyeti:** her assistant cevabının altında 👍/👎. `POST /api/agent/feedback`
  (`turn_id`, `rating` ±1); `obs.db.feedback` tablosunda `(turn_id, uid)` tekildir, oy
  değiştirilebilir. Mesaj geçmişi `feedback` alanıyla döner, UI seçili oyu gösterir.
- **Admin insan kalibrasyonu (CSV'siz):** Admin → Observability → **Human Calibration**.
  Queue yalnızca judge'lanmış ama bu admin tarafından puanlanmamış turları getirir;
  **judge skoru gizlidir**. 1–5 seç + not → submit; submit yanıtı judge skorunu ve
  farkı gösterir. "Compute QWK" ile QWK/Spearman/MAE hesaplanıp `calibration_runs`'a yazılır.
  CSV export (`--export`) toplu/offline çalışma için korunur.

### 3.7 Sonuçları oku

Admin panelinde:
- **Avg judge score**, scored turns, low-score (<3) sayısı/oranı.
- Son skorlar tablosu: judge modeli, skor, issue'lar, turn id.
- `GET /api/admin/obs/eval?days=30&low=1` ile düşük skor kuyruğu.
- Turn drill-down: `GET /api/admin/obs/turn/<turn_id>` (tool trace + preview).

---

## 4. Retrieval evaluation (golden set)

Chat RAG'in retrieval tarafı ve SITREP için:

```bash
# 1) adayları çıkar (insan etiketler)
python scripts/eval_retrieval.py --curate "cholera and health needs in Sudan" --country Sudan --k 5

# 2) golden set JSON'u doldur (relevant = insanın onayladığı report id'leri)
#    scripts/golden_set.template.json formatı: query + country + relevant[]

# 3) çalıştır (iki aşamalı)
python scripts/eval_retrieval.py --gold data/golden_set.json --k 10 --stage1-k 50

# 4) obs.db'ye kaydet (admin panelinde görünür)
python scripts/eval_retrieval.py --gold data/golden_set.json --apply
```

**Kritik düzeltme:** `retrieve()`'e üretimdeki gibi `candidate_pool` geçilir
(`get_chunks_by_country`). Pool olmadan ChromaDB backend'i ARM64 segfault koruması
nedeniyle **boş liste** döndürür; eski kod bu yüzden her sorguda 0 veriyordu.

İki aşama:
- **Stage 1 (Recall@stage1_k, default 50):** aday havuzunun tavanı.
- **Stage 2 (nDCG@10, MRR@10, Recall@10):** generator'ın gerçekten gördüğü sıralama.

Golden set kuralları (NotebookLM araştırması):
- 50 sorgu minimum, 100–200 ideal; sorgu tipleri katmanlı.
- Relevance kademeli (0–3) olmalı; insan etiketi şart.
- Yüzeyel lexical örtüşmeyi önlemek için etiketlerken sorguyu değil kanıtı değerlendir.
- %20 cevaplanamaz sorgu hedefi (şu an format yalnız `relevant` dolu entry kabul ediyor;
  abstention metriği gelecek sürümde).

---

## 5. Metrik tanımları

| Metrik | Nasıl hesaplanır | Nerede |
|---|---|---|
| Judge score | 3 örnek ortalaması (1–5) | `eval_scores.score` |
| Low-score rate | skor < 3 / toplam skor | `eval_summary.low_rate` |
| Citation rate | citation>0 olan ok turn / ok turn | `summary.citation_rate` |
| No-answer rate | `no_answer=1` / ok turn | `summary.no_answer_rate` |
| Tool error rate | hata tool çağrısı / tüm çağrılar | `tool_stats.error_rate` |
| p50/p95 latency | `turns.latency_ms` | `summary` / `timeseries` |
| 👍/👎 positive rate | up / (up+down) | `feedback_summary` / `/eval` |
| Recall@K | ilgili raporların top-K'da oranı | `eval_retrieval` |
| nDCG@10 | sıralama kalitesi | `eval_retrieval` |
| MRR | ilk ilgili raporun sırası | `eval_retrieval` |

---

## 6. Maliyet ve güvenlik

- Chat eval maliyeti judge modeline bağlıdır: 10 tur × 3 sample ≈ 30 çağrı.
  Panel varsayılanı 10 tur; CLI `--sample` ile sınırlanır.
- Judge çağrıları OpenRouter üzerinden gider; `OPENROUTER_API_KEY` yoksa eval
  çalışmaz (açık hata).
- Eval skorları **yalnızca obs.db**'ye yazılır; `reliefweb.db`/`chats.db` şemasına
  dokunulmaz, production'a otomatik bir şey gönderilmez.
- Backfill idempotenttir; tekrar çalıştırmak kayıt çoğaltmaz.
- `eval_scores` unique: `(turn_id, judge_model, judge)`; tekrar `--apply` eski skoru
  günceller.
- Retention: `prune()` eski `turns`, `tool_calls`, `feedback`, `eval_scores`,
  `eval_retrieval` satırlarını siler (`OBS_RETENTION_DAYS`, default 90).

---

## 7. Bilinen sınırlar / sonraki adımlar

1. **Backfill turlarında kanıt yok** → groundedness judge'ı sınırlı; yeni turlarda
   tool preview'ları sayesinde gerçek kanıt kontrolü var.
2. **Judge-human kalibrasyon aracı var, insan etiketi bekliyor**: `scripts/calibrate_judge.py`
   kör CSV export + QWK/Spearman/MAE ölçer; 20–30 etiketle başla (`docs/CALIBRATION.md`).
3. **Faithfulness/claim-level metrik yok**: şimdilik judge rubric + citation proxy.
4. **Golden set insan etiketi bekliyor**; %20 cevaplanamaz sorgu için abstention
   metriği eklenmeli.
5. **Reranker / hybrid / parent-child** retrieval iyileştirmeleri henüz kodda yok;
   NotebookLM öncelik sırası ve 2 vCPU kısıtı `docs/research/notebooklm_rag_eval.md`
   içinde.
6. **TTFT / faz-bazlı latency** henüz `turns` tablosunda yok (sonraki observability
   dilimi).

---

## 8. Komut özeti

```bash
.venv/bin/python scripts/backfill_turns.py --days 90 --apply
.venv/bin/python scripts/eval_agent.py --sample 10            # dry run
.venv/bin/python scripts/eval_agent.py --sample 10 --apply    # persist
.venv/bin/python scripts/eval_retrieval.py --curate "..." --country Sudan
.venv/bin/python scripts/eval_retrieval.py --gold data/golden_set.json --apply

# testler
.venv/bin/python -m pytest tests/test_eval_agent.py tests/test_eval_retrieval.py \
  tests/test_observability.py tests/test_backfill_turns.py -q
```
