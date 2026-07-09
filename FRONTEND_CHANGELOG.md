# Frontend Değişiklik Dokümantasyonu
> Bu oturumda yapılan tüm frontend değişiklikleri — backend bağlantıları için referans.

---

## 1. Hamburger Menü — Sidebar Düzeltmesi

**Dosya:** `templates/index.html`, `static/style.css`

**Ne değişti:**
- Hamburger (3 çizgi) butonu her sayfada (home/db/agent/sitrep) doğru pozisyona getirildi
- Ana ekrana tıklanınca sidebar otomatik kapanıyor (`click-outside` dinleyicisi eklendi)

**Backend bağlantısı:** Yok — tamamen UI.

---

## 2. Sağ Üst: Ülke Arama + İkon Güzelleştirme

**Dosya:** `templates/index.html`, `static/style.css`

**Ne değişti:**
- Sağ üstteki ülke arama inputu ve ikonlar yeniden stilize edildi (glassmorphism badge)
- `.source-badge-glass` sınıfı ile tüm veri kaynaklarına görsel badge eklendi

**Veri kaynağı badge'leri (şu an statik, backend'den dinamik hale getirilebilir):**

| Badge | Kaynak | Canlı mı? |
|---|---|---|
| ReliefWeb | ReliefWeb API | ✅ Aktif |
| HDX | HDX API | ✅ Aktif |
| GDACS | GDACS Alerts | ✅ Aktif |
| World Bank | World Bank API | ✅ Aktif |
| News | NewsAPI.org | ✅ Aktif |
| Weather | Open-Meteo | ✅ Aktif |
| Brave MCP | Brave Search MCP | ✅ Bağlı |
| ArXiv MCP | ArXiv MCP | ✅ Bağlı |
| Thinking MCP | Sequential Thinking MCP | ✅ Bağlı |

> **Backend TODO:** Badge durumlarını `/api/health` endpoint'inden dinamik çekip yeşil/sarı/kırmızı gösterilebilir.

---

## 3. Proje Geneli Tipografi

**Dosya:** `templates/index.html` (font import), `static/style.css`

**Ne değişti:**
- Geist fontundan **Outfit** + **JetBrains Mono** 'ya geçildi
- Outfit: genel metin, başlıklar, butonlar
- JetBrains Mono: log satırları, sayılar, tablolar, badge'ler

**Backend bağlantısı:** Yok.

---

## 4. Harita Zoom Kontrolü

**Dosya:** `static/app.js`

**Ne değişti:**
- `zoomControl: false` → `zoomControl: true`
- `minZoom: 1`, `maxZoom: 10`, `doubleClickZoom: true` aktif edildi
- Zoom butonları `top: 60px; left: 16px` konumuna taşındı (hamburger altına)
- Glassmorphism stil eklendi (`static/style.css`)

**Backend bağlantısı:** Yok — Leaflet map zaten frontend'de initialize ediliyor.

---

## 5. Haftalık Brief Başlığı

**Dosya:** `templates/index.html`

**Ne değişti:**
- "Weekly Intelligence Brief" → "Weekly **Brief**" olarak güncellendi
- Başlık iki renge ayrıldı: siyah + `#E8364E` (kırmızı vurgu)

**Backend bağlantısı:**
- `GET /api/public/bulletins` → `#dash-weekly-text` içeriğini doldurur (zaten app.js'de mevcut)
- `GET /api/public/bulletin/<filename>` → "Read Full Bulletin" butonu

---

## 6. Platform Walkthrough — Dikey Özellik Kartları

**Dosyalar:** `templates/index.html`, `static/style.css`, `static/app.js`

### HTML Yapısı

```html
<div id="wt-promo-block">         <!-- Giriş sonrası collapse olan wrapper -->
  <div id="wt-section">           <!-- 4 özellik kartı -->

    <!-- Her kart: .wt-feature-row .wt-row-even/.wt-row-odd -->
    <div class="wt-feature-row wt-row-even">
      <div class="wt-feature-text">
        <div class="wt-feature-badge">01</div>
        <h3 class="wt-feature-title">...</h3>
        <p class="wt-feature-desc">...</p>
        <ul class="wt-feature-bullets">...</ul>
      </div>
      <div class="wt-feature-media">
        <div class="wt-video-wrap">
          <video class="wt-video" src="/static/videos/dashboard.mp4"
                 autoplay loop muted playsinline></video>
          <div class="wt-video-placeholder">...</div>  <!-- Video yoksa fallback -->
        </div>
      </div>
    </div>

    <!-- 02 agent, 03 sitrep, 04 bulletin kartları da aynı yapıda -->

    <!-- Login CTA (giriş yapılmamışsa görünür) -->
    <div id="walkthrough-cta-auth" class="wt-cta-card">
      <button id="auth-google-btn-bottom">Continue with Google</button>
    </div>

    <!-- Logged-in CTA (giriş yapılınca görünür) -->
    <div id="walkthrough-cta-explore" class="wt-cta-card" style="display:none">
      <button data-action="go-chat">Open AI Agent Chat →</button>
    </div>

  </div>
</div>
```

### Video Dosyaları

Video yokken otomatik placeholder gösterilir. Eklemek için:

```
static/videos/
  dashboard.mp4   → Ana ekran/harita tanıtımı
  agent.mp4       → AI Chat agent tanıtımı
  sitrep.mp4      → SITREP generator tanıtımı
  bulletin.mp4    → Haftalık bulletin tanıtımı
```

Dosyaları ekledikten sonra: `docker compose up -d --build`

### Scroll Animasyon

`app.js` sonunda — her `.wt-feature-row` görüntüye girince `.wt-visible` class'ı ekleniyor:
- `opacity: 0 → 1`
- `translateY(40px) → translateY(0)`
- Threshold: %15 görünürlük

---

## 7. Login / Auth Akışı Değişiklikleri

**Dosya:** `static/auth.js`

### Yeni elementler bağlandı

```javascript
// _initFirebase() içine eklendi:
const btnBottom = document.getElementById("auth-google-btn-bottom");
if (btnBottom) btnBottom.addEventListener("click", doSignIn);
```

### updateVisibility() güncellemeleri

```javascript
const promoBlock = document.getElementById("wt-promo-block");
const isAuthed   = !!getIdToken();

// Login sonrası tüm tanıtım bölümü smooth collapse:
if (isAuthed) {
  promoBlock.style.maxHeight     = "0px";
  promoBlock.style.opacity       = "0";
  promoBlock.style.pointerEvents = "none";
  promoBlock.style.marginTop     = "0";
} else {
  promoBlock.style.maxHeight     = "9999px";
  promoBlock.style.opacity       = "1";
  promoBlock.style.pointerEvents = "auto";
}
```

### Auth Durumuna Göre Görünüm

| Durum | Walkthrough Bölümü | CTA Kartı |
|---|---|---|
| Anonim | ✅ Görünür | "Continue with Google" |
| Giriş yapıldı | ❌ Smooth collapse (kaybolur) | — |
| Giriş sonrası scroll | Sadece harita + Weekly Brief | "Open AI Agent Chat →" |

---

## 8. Backend Entegrasyonu için TODO

### Öncelik 1 — Mevcut çalışan bağlantılar (kontrol et)

- [ ] `GET /api/public/bulletins` → `#dash-weekly-text` doldurulması
- [ ] `GET /api/country/summaries` → Haritadaki ülke kartları  
- [ ] `GET /api/public/stats` → Hero stats (raporlar / ülkeler / chunks)

### Öncelik 2 — Badge durumlarını dinamikleştir

```
GET /api/health
Response: { mcp_arxiv: true, mcp_brave: true, mcp_sequential: true, ... }
```

Bu response ile `.animate-pulse-glow` badge'lerini yeşil/sarı/kırmızı yapabilirsin.

Örnek badge ID'leri (şu an statik HTML):
- `#badge-reliefweb`, `#badge-hdx`, `#badge-gdacs`, `#badge-worldbank`
- `#badge-news`, `#badge-weather`, `#badge-brave`, `#badge-arxiv`, `#badge-thinking`

### Öncelik 3 — Video içerikleri (manual)

```bash
# Ekran kaydı al, sonra:
cp dashboard_recording.mp4 static/videos/dashboard.mp4
cp agent_recording.mp4     static/videos/agent.mp4
cp sitrep_recording.mp4    static/videos/sitrep.mp4
cp bulletin_recording.mp4  static/videos/bulletin.mp4
docker compose up -d --build
```

---

## Değiştirilen Dosyalar Özeti

| Dosya | Değişiklik |
|---|---|
| `templates/index.html` | Walkthrough section, CTA kartları, promo wrapper, tüm badge'ler |
| `static/style.css` | `.wt-feature-row`, `.wt-video-wrap`, `.wt-cta-card`, zoom kontrol stilleri, badge stilleri |
| `static/app.js` | Zoom enable, eski slider kodu silindi, IntersectionObserver, video error fallback |
| `static/auth.js` | `auth-google-btn-bottom` binding, `updateVisibility` promo block collapse |
| `static/videos/` | Klasör oluşturuldu (boş — video eklenecek) |

---

## 9. Design System Düzeltmeleri (Taste Review Sonrası)

**Dosyalar:** `static/style.css`, `static/app.js`, `DESIGN_DIRECTIVES.md`

### CSS Variable Eksiklikleri Giderildi
- `:root`'a eklendi: `--radius-md: 10px`, `--hover-bg`, `--hover-bg-strong`, `--primary-rgb`, `--green-rgb`, `--red-rgb`, `--amber-rgb`, `--blue-rgb`, `--color-panel-dark`, `--color-bg-dark`, `--color-brand-accent`, `--radius-3xl: 28px`, `--dark-surface`, `--dark-surface-2`

### Shape Consistency (border-radius → CSS variables)
- Tüm hardcoded `border-radius` değerleri CSS variable ölçeğine çekildi: `10px → var(--radius-md)`, `14px → var(--radius)`, `18px → var(--radius-lg)`, `20px → var(--radius-xl)`, `28px → var(--radius-3xl)`
- `.auth-logo` radius: `14px → var(--radius)`
- `.wt-cta-card` radius: `28px → var(--radius-3xl)`
- `.wt-cta-btn` radius: `14px → var(--radius)`
- `.wt-cta-icon` radius: `18px → var(--radius-lg)`
- `.wt-video-wrap` radius: `20px → var(--radius-xl)`
- `.dash-weekly-text` radius: `20px → var(--radius-xl)`

### Hardcoded Renkler → CSS Variables
- Walkthrough bölümü: `#111827 → var(--navy)`, `#6B7280 → var(--text-secondary)`, `#374151 → var(--text)`, `#10B981 → var(--green)`, `#E8364E → var(--primary)`, rgba tint'ler → `rgba(var(--primary-rgb), ...)`
- Crisis severity: `#ef4444 → var(--red)`, `#f59e0b → var(--amber)`, `#22c55e → var(--green)`
- CTA kart: gradient renkler → `var(--dark-surface)`, `var(--dark-surface-2)`
- `.search-input-glass:focus` rgba primary tint → `rgba(var(--primary-rgb), ...)`
- `.wt-cta-btn` renkler → `var(--text-inverse)`, `var(--navy)`

### Duplicate CSS Temizlendi
- `.bulletin-gen-btn` çift tanım kaldırıldı (sadece solid blue versiyon kaldı)

### Video Fallback Düzeltildi
- JS: Video error handler artık `video.setAttribute('error', '')` set ediyor, CSS `[error]` selector'ü düzgün çalışıyor

### Severity Badge CSS Class'lara Taşındı
- `severityBadge()` JS fonksiyonu inline style yerine CSS class kullanıyor: `.severity-high`, `.severity-medium`, `.severity-low`
- Her class rgba tint ile styled

### Mobil Responsive Eklendi
- **768px breakpoint**: Proposal panel stack layout, slide-over drawer 85vw, walkthrough tek sütun, CTA padding küçültme
- **480px breakpoint**: Proposal sidebar 100% width/max 180px, editor/advisor stack, split-gutter gizli, slide-over drawer 100%

### Walkthrough Layout Varyasyonu
- 4. walkthrough satırından itibaren (`.wt-feature-row:nth-child(n+4)`) tam genişlik tek sütun düzen — zigzag tekrarı kırıldı

### DESIGN_DIRECTIVES.md Güncellendi
- Font kuralı: `Geist` → `Outfit` + `JetBrains Mono` (şirket kararı)
- RGB değerleri eklendi (alpha compositing için)
- Shape consistency lock tam radius ölçeği belgeli
- Walkthrough layout kuralları eklendi
- Mobil responsive kuralları eklendi
- Bilinen eksiklikler ve TODO'lar bölümü eklendi
