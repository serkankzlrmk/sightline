# Sightline — Design System Directives

> **Rehber Doküman**: Gelecekte bu kod tabanında değişiklik yapacak tüm geliştirici ajanlar (Antigravity, Cursor vb.) kullanıcı arayüzü eklerken veya güncellerken bu kurallara **kesinlikle uymak zorundadır**.

Arayüzümüz, **Apple esintili temiz, sıcak gri/beyaz bir açık tema** üzerine kuruludur.

---

## 1. Tasarım Dili ve Renk Paleti

Tasarımdaki tüm renkler CSS değişkenleri (`static/style.css`) üzerinden okunmalıdır:

| Değişken | Hex/RGBA Değeri | Rolü |
|---|---|---|
| `--bg` | `#F5F5F7` | Ana sayfa arka planı (sıcak gri-beyaz) |
| `--surface` | `#FFFFFF` | Kartlar, modaller ve panellerin arka planı |
| `--primary` | `#E8364E` | Sightline kırmızı marka rengi |
| `--text` | `#1D1D1F` | Birincil metin rengi (koyu antrasit - asla saf siyah değil) |
| `--text-secondary` | `#6E6E73` | İkincil metin, açıklamalar ve alt başlıklar |
| `--border` | `rgba(0, 0, 0, 0.08)` | Genel kenarlıklar ve ince çizgiler |
| `--blue` | `#007AFF` | Linkler, bilgi durumları ve odaklanma çerçeveleri |

### RGB Değerleri (Alpha Compositing İçin)

| Değişken | Değer | Kullanım |
|---|---|---|
| `--primary-rgb` | `232, 54, 78` | `rgba(var(--primary-rgb), 0.15)` gibi alpha tint'ler |
| `--green-rgb` | `48, 209, 88` | Yeşil alpha tint'ler |
| `--red-rgb` | `255, 59, 48` | Kırmızı alpha tint'ler |
| `--amber-rgb` | `255, 159, 10` | Amber alpha tint'ler |
| `--blue-rgb` | `0, 122, 255` | Mavi alpha tint'ler |

### Ek Sistem Değişkenleri

| Değişken | Değer | Rolü |
|---|---|---|
| `--hover-bg` | `rgba(0,0,0,.04)` | Hover arka plan rengi |
| `--hover-bg-strong` | `rgba(0,0,0,.08)` | Güçlü hover arka plan |
| `--color-panel-dark` | `#18181b` | Koyu panel arka plan (CTA kartları) |
| `--color-bg-dark` | `#09090b` | Koyu bölüm arka plan |
| `--color-brand-accent` | `#E8364E` | Marka vurgu rengi (= `--primary`) |
| `--dark-surface` | `#111827` | Koyu CTA kart gradient |
| `--dark-surface-2` | `#1e1b4b` | Koyu CTA kart gradient derinlik |

### Kısıtlamalar:
- **Neon/Mor Gradyan Yasağı**: Klasik "AI Mor/Mavi" parlamaları ve gradyanları arayüzde kullanılamaz.
- **Saf Siyah Yasağı**: Yazı rengi olarak asla `#000000` kullanmayın. Her zaman `--text` veya `--navy` (`#1D1D1F`) kullanın.
- **Hardcoded Hex Yasağı**: Yeni CSS kurallarında hardcoded renk değerleri (`#111827`, `#6B7280` vb.) kullanmayın. Her zaman CSS variable'larını kullanın.

---

## 2. Tipografi Standartları

- **Font Ailesi**: Arayüz genelinde `Outfit` (sans-serif) ve kod/veri/sayısal alanlarda `JetBrains Mono` kullanılır.
- **Yasaklı Fontlar**: `Inter` ve tarayıcının varsayılan serif font stacks (`Times New Roman`, `Georgia` vb.) premium alanlarda kesinlikle yasaktır.
- **Hiyerarşi**: Başlıklar sıkıştırılmış harf aralığına (`tracking-tighter` / `-0.025em`) ve sıkıştırılmış satır yüksekliğine (`leading-none` veya `leading-[1.1]`) sahip olmalıdır.

> **Not**: Orijinal design directives `Geist` fontunu belirtiyordu, ancak güncel kod tabanı `Outfit` + `JetBrains Mono` kullanmaktadır. Bu değişiklik FRONTEND_CHANGELOG.md'de belgelenmiştir.

---

## 3. İkon ve Karakter Kuralları (Kesin Yasaklar)

Arayüzde **Unicode sembollerin veya emojilerin kullanımı kesinlikle yasaktır**.

- ❌ **Yasaklı**: `⬆ Upload`, `↻ Refresh`, `Date ↓`, `▶ Run`, `✕`, `×`, `⚠ Warning` vb.
- ✅ **Doğru**: Temiz, tek renk, çizgi tarzında (stroke-based) **inline SVG** kullanımı.
- **SVG İkon Boyutları**: Standart buton ve menü içi SVG ikonlar `width="16" height="16"` veya `width="18" height="18"` olmalıdır. Stroke kalınlığı (`stroke-width`) `1.5` veya `2.0` olmalıdır.

### SVG Buton İçi Hizalama Standardı:
Buton içine SVG ikon eklerken dikey hizalamanın bozulmaması için buton elementine `.btn-with-icon` sınıfını verin ve iç yapıyı şu şekilde kurun:
```html
<button class="btn btn-primary btn-with-icon">
  <svg class="icon-svg" ...>...</svg>
  <span>Metin</span>
</button>
```

---

## 4. Etkileşimler ve Taktil Geri Bildirim (Tactile Feedback)

Kullanıcı arayüzdeki bir butona tıkladığında fiziksel bir basılma hissi almalıdır.
- Tüm butonlar (`.btn`, `button`), tablar (`.sidebar-tab`, `.mobile-tab`) ve hızlı işlem butonları (`.quick-prompt-btn`) tıklandığında basılma efekti almalıdır:
```css
.btn:active, button:active {
  transform: scale(0.97); /* Hafifçe küçülme */
}
```
- Bu etkileşimin akıcı olması için transition özellikleri `--transition-fast` (`.15s ease`) ile desteklenmelidir.

---

## 5. Şekil Tutarlılığı Kilidi (Shape Consistency Lock)

Uygulama genelinde rastgele köşe yumuşatmalar (border-radius) kullanılmamalıdır. Yalnızca CSS variables içindeki radius ölçeğine sadık kalın:

| Token | Değer | Kullanım |
|---|---|---|
| `--radius-xs` | 6px | Badge'ler, küçük etiketler |
| `--radius-sm` | 8px | Küçük butonlar, inputlar |
| `--radius-md` | 10px | Orta boy kartlar, popover'lar |
| `--radius` | 12px | Standart butonlar, kartlar |
| `--radius-lg` | 16px | Büyük kartlar, modaller |
| `--radius-xl` | 20px | Büyük paneller, arama kutuları |
| `--radius-2xl` | 24px | Hero bölümler, büyük CTA |
| `--radius-3xl` | 28px | Walkthrough CTA kartları |
| `--radius-full` | 9999px | Pill şeklindeki etiketler, avatar'lar |

**Kural**: Yeni bir `border-radius` değeri eklerken yukarıdaki ölçekten birini kullanın. Ölçekte olmayan değerler (14px, 18px, 22px vb.) yasaktır.

---

## 6. Walkthrough Layout Kuralları

Platform walkthrough bölümü (`.wt-section`) için geçerli kurallar:

- **Zigzag Limiti**: En fazla 3 satır zigzag düzeni (text-media değişmeli). 4. satırdan itibaren **tam genişlik** (tek sütun) düzen kullanılmalıdır.
- **Scroll Animasyonu**: Her `.wt-feature-row` görüntüye girince `.wt-visible` class'ı ile `opacity: 0→1`, `translateY: 40px→0` animasyonu uygulanır.
- **Video Placeholder**: Video dosyaları mevcut olmadığında `.wt-video-placeholder` fallback gösterilir. JS error handler video'yu gizler ve placeholder'ı gösterir.
- **CTA Kartları**: Login öncesi "Continue with Google", login sonrası "Open AI Agent Chat" CTA gösterilir. Auth state değişince `updateVisibility()` ile geçiş yapılır.

---

## 7. Mobil Responsive Kurallar

| Breakpoint | Hedef | Önemli Kurallar |
|---|---|---|
| `768px` | Tablet | Sidebar gizli, mobile tab bar aktif, proposal stack layout, walkthrough tek sütun |
| `480px` | Küçük mobil | Dar padding, küçük font, auth card tam genişlik, CTA padding azaltılmış |

### Proposal Panel (768px altı):
- `.proposal-page` → `flex-direction: column`
- `.proposal-sidebar` → `width: 100%; max-height: 200px`
- `.proposal-workspace` → `flex-direction: column`
- `.split-gutter` → `display: none`
- `.slide-over-drawer` → `width: 85vw`

---

## 8. Fonksiyonel Güvenlik (Backend Entegrasyonu)

- Arayüzü güzelleştirirken veya HTML/CSS güncellerken JavaScript (`static/app.js`) ve Flask server (`server.py`) tarafından dinlenen **`id` veya `data-*` niteliklerini kesinlikle değiştirmeyin**.
- CSS sınıflarını güncellerken event dinleyicilerin tetiklendiği sınıfları (örneğin `.sidebar-tab`, `.mobile-tab`, `[data-action="..."]`) korumaya özen gösterin.

---

## 9. Bilinen Eksiklikler ve TODO'lar

- [ ] Badge durumlarını `/api/health` endpoint'inden dinamik çek (şu an statik yeşil dot)
- [ ] Video dosyaları eklenmeli: `static/videos/dashboard.mp4`, `agent.mp4`, `sitrep.mp4`, `bulletin.mp4`
- [ ] `--radius-md` ve `--hover-bg` yeni eklendi — eski hardcoded referanslar temizlendi
- [ ] `.bulletin-gen-btn` çift tanım temizlendi — sadece solid blue stil kaldı