# Human Calibration — LLM Judge'ı insanla hizalama

> Amaç: LLM judge'ın 1–5 skorlarının **senin/uzmanın** verdiği skorlarla ne kadar
> uyuştuğunu ölçmek. Judge tek başına "doğru" değildir; kalibre edilmeden karar
> mekanizması olarak kullanılmamalı.
>
> Araç: [`scripts/calibrate_judge.py`](scripts/calibrate_judge.py) ·
> Metrikler: QWK (birincil), Spearman, Pearson, MAE, exact/within-1.
> Tarih: 2026-11-10 · Durum: local, canlıya alınmadı.

---

## 0. Hızlı yol: Admin panelinden (CSV'siz)

`/app → Admin → Observability → Human Calibration`:

1. **Load next unlabeled turns** → judge'lanmış, senin puanlamadığın 10 tur gelir.
2. Kartta soru + cevap + kanıt; judge skoru **gizli** (kör).
3. 1–5 seç, istersen not yaz → **Submit rating**.
4. Submit sonrası judge skoru ve farkı gösterilir; otomatik sonraki karta geçer.
5. **Compute QWK** → QWK/Spearman/MAE + verdict; panelde kalıcı satır güncellenir.

Bu yol günlük/iteratif kullanım içindir. Aşağıdaki CSV akışı toplu ve offline
çalışma (ör. başka bir uzmana gönderme) içindir; ikisi aynı `human_labels`
tablosunu kullanır.

---

## 1. Süreç özeti (5 adım)

```
1) Judge'ı çalıştır (30 tur)         → eval_scores dolar
2) Kör CSV export et                → soru + cevap + kanıt; judge skoru YOK
3) Sen 1–5 puanla (human_score)     → Excel/Sheets
4) Score et                         → QWK + Spearman + MAE + uyuşmazlıklar
5) QWK düşükse rubric'i revize et   → aynı örneklerle tekrar judge → tekrar ölç
```

**Senin rolün:** 3. adımdaki insan puanlayıcı. Evet, geri bildirimi sen veriyorsun —
ama uygulama içi 👍/👎 değil, **kör CSV puanlaması** (bu, judge kalibrasyonu için
gereken doğru yöntem). Uygulama içi thumbs up/down ayrı bir "kullanıcı memnuniyeti"
sinyalidir ve şu an yok.

---

## 2. Adım adım komutlar

### 2.1 Önce judge skorları üret (yalnızca judge'lanmış turlar export edilir)

```bash
cd /Users/serkankizilirmak/Documents/reliefweb/RedAgent
.venv/bin/python scripts/eval_agent.py --days 3650 --sample 30 --samples 3 \
  --judge-model openai/gpt-5.1 --apply
```

- 30 tur × 3 sample = 90 judge çağrısı (maliyet ~$0.5–1; istersen `--sample 15`).
- `--days 3650` tarihsel backfill turlarını da kapsar (local veri Nisan–Ağustos).
- Ucuz deneme: `--samples 1 --judge-model deepseek/deepseek-chat --sample 10`.

### 2.2 Kör puanlama sayfasını export et

```bash
.venv/bin/python scripts/calibrate_judge.py --export 30 --out data/calibration/round1.csv
```

Çıktı:
- `data/calibration/round1.csv` → Excel/Sheets ile aç.
- `data/calibration/round1.meta.json` → hangi ayarlarla üretildiği (judge modeli vs.).
- CSV kolonları:

| Kolon | Ne yapmalısın |
|---|---|
| `turn_id` | Dokunma (eşleştirme anahtarı) |
| `question` | Kullanıcının sorusu |
| `answer` | Değerlendirilecek cevap |
| `evidence` | Judge'ın gördüğü tool kanıtı (varsa) |
| `human_score` | **1–5 arası tam sayı yaz** (boş bırakılan satır atlanır) |
| `notes` | Kısa not (opsiyonel; ör. "kanıt yok", "atıf yanlış") |

> **Körlük kuralı:** Judge skorları CSV'de yoktur, `meta.json`'da da yoktur.
> Puanlamadan önce DB'den judge skoruna bakma; yoksa kalibrasyon anlamsızlaşır.

### 2.3 Rubrik (puanlarken kullan)

| Skor | Anlam |
|---|---|
| **5** | Kanıta tamamen dayalı, soruya tam cevap, eksiksiz, net; atıflar tutarlı |
| **4** | Doğru/ilgili; küçük boşluk veya ifade sorunu |
| **3** | Kısmen faydalı: ilgili ama yüzeysel/dağınık/eksik |
| **2** | Çoğunlukla yanlış, yanıltıcı veya kaçamak |
| **1** | Uydurma, tehlikeli veya tamamen konu dışı |

Kurallar:
- **Uzunluk kalite değildir** — uzun cevaba bonus, kısa cevaba ceza yok.
- **"Yeterli kanıt bulamadım"** doğru sonuçtur; ceza verme (eğer gerekçeli ise).
- `evidence` boşsa: yalnızca iç tutarlılık/ilgililik değerlendir; "kanıt yok" notu düş.
- Her cevabı **bağımsız** puanla; diğer cevaplarla kıyaslayarak sıralama yapma.

Excel ipuçları: filtre uygulama, `human_score` hücresine veri doğrulama (1–5 tamsayı)
koy; boş satır bırakabilirsin (atlanır). 20–30 satır hedefle; 50 idealdir.

### 2.4 Skorla ve raporu al

```bash
.venv/bin/python scripts/calibrate_judge.py --score data/calibration/round1.csv
```

Bu komut:
1. insan puanlarını `obs.db.human_labels`'a yazar (upsert; tekrar çalıştırılabilir),
2. judge skorlarıyla eşleştirir,
3. `calibration_runs` tablosuna bir kayıt atar,
4. şu raporu basar:

```json
{
  "matched_pairs": 30,
  "metrics": {
    "n": 30,
    "qwk": 0.67,
    "spearman": 0.71,
    "pearson": 0.73,
    "mae": 0.53,
    "exact_rate": 0.6,
    "within1_rate": 0.93,
    "human_mean": 3.4,
    "judge_mean": 3.9,
    "interpretation": {
      "verdict": "good",
      "bias": 0.5,
      "advice": ["Judge insana göre +0.50 puan cömert; ..."]
    }
  },
  "confusion": {"rows": "human 1-5", "cols": "judge 1-5", "matrix": [[...]]},
  "top_disagreements": [...]
}
```

### 2.5 Yorumlama ve aksiyon

| QWK | Yorum | Ne yapmalı |
|---|---|---|
| **≥ 0.8** | Excellent | Judge güvenilir; üretim metriklerinde kullan |
| **0.6–0.8** | Good | Kabul edilebilir; küçük rubric iyileştirmeleri |
| **0.4–0.6** | Moderate | Rubric çapalarını netleştir, örnek ekle, tekrar ölç |
| **< 0.4** | Poor | Judge'ı karar mekanizması olarak kullanma; rubric/prompt/model değiştir |

Ek göstergeler:
- **`within1_rate` düşükse** → komşu puanlar (3 vs 4) karışıyor; 3/4 çapalarını somutlaştır.
- **`bias` > +0.25** → judge cömert; "kanıt yoksa en fazla 3" gibi sertlik ekle.
- **`bias` < -0.25** → judge katı; "eksik ama doğru" cevaplar için 4 çapasını gevşet.
- `top_disagreements` listesi: en büyük farkların turn_id'leri; tek tek cevaplara bakıp
  rubric'in nerede kaydığını teşhis et.

Kalibrasyon döngüsü:
```
rubric güncelle → eval_agent'ı AYNI ayarlarla tekrar çalıştır (--apply)
→ calibrate_judge --score AYNI CSV (insan puanları değişmez)
→ QWK'yi karşılaştır
```
Böylece "rubric değişikliği işe yaradı mı" ölçülür.

---

## 3. Panelde görünüm

`/app → Admin → Observability → Chat Quality Evaluation` altında:

```
Judge-human calibration: QWK 0.670 · Spearman 0.710 · MAE 0.53 · n=30 · judge openai/gpt-5.1
```

Kalibrasyon yoksa: "not run yet (N human-labeled turns)". API:
`GET /api/admin/obs/calibration`.

---

## 4. Sık sorulanlar

**"Kaç örnek yeterli?"** 20–30 başlangıç; 50 daha stabil QWK. Araştırma 50'yi
istatistiksel minimum, 100–200'ü 1 puanlık farkları ayırmak için öneriyor.

**"Aynı CSV'yi iki kez puanlayabilir miyim?"** Evet; `human_labels` upsert eder,
`calibration_runs` yeni bir kayıt ekler (trend görürsün).

**"İki kişi puanlarsa?"** `--rater ali` / `--rater ayse` ile ayrı ayrı skorla;
şu an ara-puanlayıcı (inter-rater) metriği yok, ayrı ayrı QWK raporlanır.
İleride Cohen kappa ile iki insan arası uyum eklenebilir.

**"Bu uygulama içi geri bildirim mi?"** Hayır. Uygulama içi 👍/👎 ayrı bir özellik
(henüz yok). Buradaki geri bildirim, judge'ı kalibre etmek için **uzman puanlaması**.

**"Judge skorunu görmeden puanlamak zor"** — doğru, ama körlük şart. İstersen
`notes` alanına gerekçeni yaz; skorla karşılaştırınca rubric'in nerede kaydığını
daha iyi görürsün.

**"Maliyet?"** Judge tarafı: 30 tur × 3 sample ≈ 90 çağrı. İnsan tarafı: 30 cevap
okuma/puanlama ≈ 30–45 dk.

---

## 5. Tek komut özeti

```bash
# 1) judge
.venv/bin/python scripts/eval_agent.py --days 3650 --sample 30 --apply

# 2) kör export
.venv/bin/python scripts/calibrate_judge.py --export 30 --out data/calibration/round1.csv

# 3) CSV'yi doldur (human_score 1-5)

# 4) skorla
.venv/bin/python scripts/calibrate_judge.py --score data/calibration/round1.csv

# 5) sonucu panelde/CLI'da gör
.venv/bin/python scripts/calibrate_judge.py --latest
```
