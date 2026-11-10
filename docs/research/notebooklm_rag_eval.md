# NotebookLM Research → Sightline: RAG Eval & Retrieval Optimization

> **Kaynak:** NotebookLM defteri **"Document Chunking and Semantic Retrieval Optimization"**
> (`6a35d852-3be2-4b6e-82b9-963d3cf3dc64`, 115 kaynak, 2026-11-09 oluşturuldu).
> **Yöntem:** `notebooklm` CLI 0.8.6 (geçici `/tmp` kurulumu) + Chrome cookie importu ile
> 5 hedefli soru soruldu; ham yanıtlar `docs/research/raw/q1..q5.md` ve
> `docs/research/raw/nlm_metadata.json` içinde.
> **Tarih:** 2026-11-10. Bu doküman, NotebookLM sentezi ile Sightline kod gerçeğinin
> ("mix") uygulama planıdır.

---

## TL;DR — 8 karar

1. **İki aşamalı ölçüm**: retrieval (Recall@K / MRR / nDCG) + generation (faithfulness,
   answer relevance, citation accuracy) ayrı ayrı ölçülmeli. Retrieval, tüm pipeline'ın
   tavanını belirler.
2. **İlk yatırım reranker**: top-50/100 aday → cross-encoder → top 3–5. En yüksek
   kalite/kaynak oranı; Hit@1 ve Recall@5'te +%11–18.
3. **İkinci yatırım parent-child chunking**: child 100–250 token (retrieval), parent
   500–1.500 token (LLM context). 800 karakterlik sabit chunk'ın precision/recall
   çelişkisini çözer.
4. **Hibrit retrieval**: BM25 + dense + RRF. Exact-match körlüğünü giderir; BM25 <30 ms.
   Mevcut RRF k=60 korunabilir, golden set ile 20/40/60/100 test edilmeli.
5. **Embedding değişimi en son**: MiniLM-384 zayıf ama değişim 61.5K chunk'ın yeniden
   embed edilmesi demek; önce golden set ile kazanç ölçülmeli (BGE-M3 / bge-large).
6. **Judge = G-Eval**: Auto-CoT + form-filling + olasılık-ağırlıklı skor; 1–5 çapa
   metinleri; uzunluk/pozisyon/self-preference kontrolleri; **cevaplayan modelden farklı
   aile**; insan etiketiyle kalibrasyon.
7. **Golden set disiplini**: en az 50 (ideal 100–200) sorgu, %20 cevaplanamaz, 0–3
   kademeli relevance, bootstrap güven aralığı, çeyreklik yenileme.
8. **Observability**: TTFT, faz-bazlı latency, token/cost, hata taksonomisi, retrieval
   boş-sonuç oranı, citation coverage, judge skoru; SLO eşikleri + dashboard.

---

## 1. Değerlendirme çerçevesi

RAG değerlendirmesi iki bağımsız aşamaya ayrılır (Q1):

| Aşama | Ne ölçülür | Neden |
|---|---|---|
| **Retrieval** | Adayların kapsamı ve sıralaması | Doğru kanıt aday havuzunda yoksa, sonraki hiçbir adım kurtaramaz |
| **Generation** | Cevabın kanıta dayanması, soruya uygunluğu, atıf doğruluğu | Halüsinasyonu retrieval hatasından ayırır |

**Kritik ilke:** retrieval metrikleri gerekli ama yeterli değil; generation metrikleri
tek başına retrieval hatasını gizler. İkisi birlikte raporlanmalı.

---

## 2. Metrikler (Q1)

| Metrik | Tanım | Ne zaman | Araç/benchmark |
|---|---|---|---|
| **Recall@K / Hit@K** | İlgili dokümanların top-K içinde bulunma oranı / en az birinin bulunması | First-stage retrieval (dense, BM25, RRF) | BEIR, MTEB, MIRACL |
| **MRR** | İlk ilgili dokümanın sırasının tersi (1. sıra=1.0, 2. sıra=0.5) | Factoid / tek dokümanlık sorular | Standart IR |
| **nDCG@K** | Kademeli relevance + log pozisyon cezası | Sıralama kalitesi; reranker sonrası | BEIR, nDCG@10 |
| **Faithfulness / Groundedness** | Cevaptaki iddiaların yalnızca retrieved context'ten çıkarılabilmesi | Halüsinasyon tespiti | RAGAS, claim-based |
| **Answer Relevance / Correctness** | Cevabın soruya uygunluğu / doğruluğu | Generation kalitesi | RAGAS, G-Eval |
| **Citation Accuracy** | Atıfların gerçekten destekleyici kaynağı göstermesi | Atıf disiplini | G-Eval, insan |
| **LLM-as-judge** | G-Eval (Auto-CoT + form-filling + olasılık ağırlıklı), Prometheus 2, RAGAS | Ölçekli offline kalite | G-Eval, Prometheus 2 |

**Sightline kararı:** Chat için citation accuracy + faithfulness proxy (deterministik
sinyaller + judge), SITREP için retrieval Recall@K/nDCG + citation post-process oranı.

---

## 3. Retrieval optimizasyonu — öncelik sırası (Q2)

| # | Değişiklik | Beklenen etki | Maliyet/latency | Sightline uyumu |
|---|---|---|---|---|
| **P1** | **Cross-encoder reranker**: top 50–100 → top 3–5 | Hit@1/Recall@5 +%11–18 | bge-reranker-v2-m3: ~80–140 ms/100 aday (GPU); CPU'da daha yavaş. Cohere Rerank: 200–600 ms, ~$2/1K arama | 2 vCPU/4GB tek worker'da CPU reranker riskli → önce küçük model veya Cohere API benchmark'ı |
| **P2** | **Parent-child chunking**: child 100–250 token, parent 500–1.500 token; child embed, parent'ı LLM'e ver | Faithfulness ~0.70 → ~0.84 | Ingest şema değişikliği + yeniden embed | `chunks` tablosuna `parent_id`/`parent_text`; ingest pipeline değişir. En büyük mimari iş |
| **P3** | **Hybrid BM25 + dense + RRF** | Recall@100 artışı (MSMARCO 0.66→0.80 örneği); exact-match'te %70'e kadar kazanç | BM25 <10–30 ms CPU | SQLite **FTS5** ile ek servis gerekmeden yapılabilir; mevcut RRF'e 3. kanal |
| **P4** | **RRF / sub-query tuning**: k=60, 3 alt sorgu | Küçük ama bedava kazanç | Yok | Golden set ile k∈{20,40,60,100}, alt sorgu sayısı test edilmeli |
| **P5** | **Embedding modeli**: MiniLM-384 → BGE-M3 / bge-large | Model duyarlılığı yüksek; ölçmeden geçilmemeli | 61.5K chunk yeniden embed; CPU'da saatler | En son; golden set kazancı görülmeden yapılmamalı |

**Uyarı:** 500+ adayı rerank etmek 485–2000× latency patlaması yapar; rerank derinliği
50–100'de tutulmalı.

---

## 4. LLM-as-a-judge tasarımı (Q3, Q5)

### G-Eval mekaniği
1. Task intro + kriter verilir; LLM **Auto-CoT** ile değerlendirme adımlarını üretir.
2. Form-filling: context + cevap + adımlar tek prompt'ta; çıktı form şeklinde.
3. **Olasılık-ağırlıklı skor**: 1–5 token logprob'ları üzerinden beklenen değer
   (`Σ p(s_i)·s_i`). Düz integer skorlama "3'te yığılma" (score compression) yapar.

### Bias kontrolleri
| Bias | Kontrol |
|---|---|
| **Pozisyon** | Çift yönlü değerlendirme (A,B / B,A), tutarsızlığı tie say; farklı model ailelerinden çoklu judge |
| **Uzunluk** | Uzunluk-açık rubric; "kısa cevap cezalandırılmaz"; ön-truncation |
| **Self-preference** | **Cevaplayan modelden farklı aile** (Sightline cevapları Gemini; judge GPT/Claude/DeepSeek olmalı) |
| **Skor sıkışması** | Olasılık-ağırlıklı skor veya 3 örnek ortalaması |

### Örneklem ve insan doğrulaması
- **50 sorgu**: kaba 3 puanlık nDCG farkını yakalamak için istatistiksel minimum.
- **100–200+ sorgu**: 1 puanlık farkları ayırmak için.
- **%20 cevaplanamaz** sorgu zorunlu (abstention testi).
- **Bootstrap güven aralığı** / 5-fold CV; 100 sorguda <~2 puan fark gürültü.
- Judge-human uyumu: **Cohen/Fleiss kappa**; iyi benchmark'larda κ≈0.74–0.80 hedefi.
- Judge'ı 20–30 insan etiketli örnekle kalibre et; kappa <0.6 ise rubric'i düzelt.

### Sightline mevcut durumu (kod)
- `scripts/eval_agent.py`: tek integer JSON skor, varsayılan judge **flash** (cevaplayanla
  aynı aile), Auto-CoT/logprob yok, insan kalibrasyonu yok.
- **Yapılacak:** judge modelini `gemini-3.1-pro-preview` yerine **farklı aile** (ör.
  `openai/gpt-5.1`, `anthropic/claude-sonnet-4.5`, `deepseek/deepseek-chat`) yap;
  Auto-CoT + form-filling prompt; logprob varsa olasılık-ağırlıklı, yoksa 3 örnek
  ortalaması; rubric'e humanitarian safety çapaları ekle.

---

## 5. Observability ve SLO'lar (Q4)

### Operasyonel
- **TTFT / time-to-first-chunk** (client ve server ayrı), TPOT/TBT, toplam latency.
- **Faz ayrıştırma**: gateway/kuyruk, retrieval, rerank, prefill, decode.
- **Token ve maliyet**: input/output, model bazında, istek başına.
- **Hata taksonomisi**: 429, timeout, downstream, schema validation, agent loop.
- **Agent loop sayısı**: invocation başına LLM çağrısı (runaway tespiti).

### Kalite
- First-stage Recall@K / nDCG@10, rerank sonrası metrikler.
- Faithfulness/claim verification, answer relevance, citation accuracy.
- Judge skoru (G-Eval), düşük skor kuyruğu.

### Önerilen eşikler (Q4 tablosu)
| Metrik | Eşik | Not |
|---|---|---|
| TTFT p95 | < 1.5–2.0 s | İnteraktif chat için |
| Hata oranı | > %1 (5 dk baseline) | Düşük trafikte 24 saatlik pencere daha doğru |
| Schema failure | > %5 | Model/format drift |
| Agent loop | > 10–12 çağrı/invocation | Maliyet patlaması |
| Faithfulness (24h ort.) | < 0.85 | Halüsinasyon artışı |
| Context relevancy | < 0.80 | Retrieval drift |

**Sightline kararı:** `turns` tablosuna **TTFT** ve faz süreleri eklenmeli; SLO'lar
tek-worker/2 vCPU gerçeğine göre (chat TTFT p95 < 2 s hedef, SITREP için ayrı) ayarlanmalı.

---

## 6. Golden set metodolojisi (Q5)

1. **Kademeli relevance (0–3)**, binary değil; nDCG için gerekli.
2. **Sorgu körlüğü**: passage relevance'ı değerlendirirken kullanıcı sorgusunu gizle
   (ChunkBench yaklaşımı) → yüzeysel lexical örtüşme yerine gerçek kanıt desteği.
3. **Katmanlı dağılım**: factoid, multi-hop, broad/topical, troubleshooting/comparative.
4. **%20 cevaplanamaz** sorgu.
5. **50 minimum, 100–200 ideal**; bootstrap CI.
6. **Sızıntı/contamination** kontrolü: eval sorguları üretim prompt'larında görünmemeli.
7. **Yenileme**: model/prompt/tool değişiminde; rutin olarak çeyreklik.

**Uygulama:** `scripts/eval_retrieval.py --curate` ile gerçek adayları çıkar, insan
(veya sen) yalnızca gerçekten ilgili olanları `relevant` listesine yaz; template'teki
fake ID'leri asla kullanma.

---

## 7. Sightline'a uyarlama — uygulama planı

### P0 — mevcut eval kodunun düzeltilmesi
1. **`scripts/eval_retrieval.py` pool bug'ı**: `adapter.retrieve(query=..., country=...)`
   `candidate_pool` olmadan ChromaDB'de **boş liste** döner (ARM64 guard). Üretimdeki
   gibi `get_chunks_by_country(country)` ile pool kurup `candidate_pool=pool` geçir.
   Aksi halde tüm metrikler 0 çıkar.
2. **İki aşamalı raporlama**: first-stage Recall@50/100 + rerank sonrası nDCG@10/MRR@10
   ayrı gösterilsin.
3. **`eval_scores` tekilleştirme**: `UNIQUE(turn_id, judge_model, judge)` + UPSERT;
   yeniden `--apply` skorları çoğaltmasın.
4. **ruff format**: yeni eval dosyaları CI formatına uydurulmalı.

### P1 — judge ve metrik kalitesi
5. Judge'ı G-Eval tarzına çek: Auto-CoT, form-filling, çapa metinleri, uzunluk/pozisyon
   kontrolü, **cross-family model**, 3 örneklem ortalaması; model adı `eval_scores`'ta.
6. Golden set: 50 sorgu (10 cevaplanamaz) oluştur; `--curate` + insan etiketi; graded
   relevance; bootstrap CI raporu.
7. Retrieval sonuçlarını `obs.db`'de `eval_runs`/`eval_results` (veya `eval_scores`
   genişletmesi) olarak sakla; admin `/api/admin/obs/eval` altında göster.

### P2 — observability derinleştirme
8. `turns` tablosuna `ttft_ms`, `retrieval_ms`, `tool_ms`, `judge_score` alanları;
   agent SSE döngüsünde ilk `token` event zamanını ölç.
9. Admin Observability paneline eval sekmesi: skor dağılımı, düşük skor kuyruğu,
   judge-human kappa (kalibrasyon sonrası), SLO kartları.

### P3 — retrieval iyileştirme (ürün tarafı)
10. **Reranker benchmark'ı**: 2 vCPU'da bge-reranker-base / Cohere API latency ölçümü;
    golden set kazancı doğrulanmadan prod'a alınmamalı.
11. **Hybrid BM25 (SQLite FTS5)** → RRF'e üçüncü kanal (en düşük maliyetli büyük kazanç).
12. **Parent-child chunking**: ingest şema değişikliği; en büyük iş, ayrı planlanmalı.
13. Embedding değişimi en son (61.5K chunk yeniden embed).

---

## 8. Kısıtlar / riskler

- **Donanım**: prod 2 vCPU/4GB, gunicorn 1 worker. Cross-encoder CPU'da yavaş olabilir;
  ölçmeden karar verilmemeli. Cohere API opsiyonu maliyetli ama zero-ops.
- **ChromaDB ARM64**: `collection.get/count/query` segfault riski; pool tabanlı yol
  korunmalı (not: eval düzeltmesi de bu yüzden kritik).
- **Judge maliyeti**: G-Eval Auto-CoT + 3 örnek = cevap başına birkaç kat token;
  örneklem ve bütçe sınırı konmalı (ör. günlük 50 skor).
- **NotebookLM bağlantısı**: oturum cookie'leri `/tmp`'de tutuldu ve iş sonunda silindi;
  yeniden gerekiyorsa Chrome'dan cookie importu tekrar yapılabilir. Üretim `.env`'ine
  asla NotebookLM kimlik bilgisi konmamalı.
- **MCP**: `notebooklm-mcp` 0.8.6 ile kurulabilir ama bu DSH oturumunda MCP istemcisi
  bağlı değil; CLI kullanıldı. MCP'yi Claude Code/Codex gibi istemcilerde kullanmak için
  ayrı profil kurulumu gerekir.

---

## 9. Ana kaynaklar (115 kaynaktan öne çıkanlar)

- Liu et al., **G-Eval: NLG Evaluation using GPT-4 with Better Human Alignment** (EMNLP 2023) — https://aclanthology.org/2023.emnlp-main.153/
- **A Systematic Investigation of Document Chunking Strategies and Embedding Sensitivity** — https://arxiv.org/html/2603.06976v1
- **H-RAG (SemEval-2026 Task 8): Hierarchical Parent–Child Retrieval** — https://arxiv.org/html/2605.00631v1
- **Lost in the Middle: How Language Models Use Long Contexts** — https://arxiv.org/abs/2307.03172
- **Judging the Judges: Position Bias in LLM-as-a-Judge** — https://arxiv.org/html/2406.07791v9
- **Prometheus 2: Open Source LM Specialized in Evaluating Other LMs** — https://arxiv.org/pdf/2405.01535
- **RAGAS: Automated Evaluation of Retrieval Augmented Generation** — https://huggingface.co/papers/2309.15217
- **OpenTelemetry GenAI semantic conventions** — https://opentelemetry.io/blog/2026/genai-observability/
- **Dynatrace AI Observability metrics reference** — https://docs.dynatrace.com/docs/observe/dynatrace-for-ai-observability/metrics-reference
- Reranker karşılaştırmaları: BGE-v2-m3 / Cohere Rerank 3.5 / Qwen3-Reranker — https://reranker.uk/guides/compare-rerankers
- Hybrid search + RRF: https://redis.io/blog/reciprocal-rank-fusion/
- Chunking stratejileri: https://futureagi.com/blog/advanced-chunking-techniques-for-rag/

Tam kaynak listesi: `docs/research/raw/nlm_metadata.json` (115 kayıt).
Ham Q&A: `docs/research/raw/q1.md` … `q5.md`.
