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

### Kısıtlamalar:
- **Neon/Mor Gradyan Yasağı**: Klasik "AI Mor/Mavi" parlamaları ve gradyanları arayüzde kullanılamaz.
- **Saf Siyah Yasağı**: Yazı rengi olarak asla `#000000` kullanmayın. Her zaman `--text` veya `--navy` (`#1D1D1F`) kullanın.

---

## 2. Tipografi Standartları

- **Font Ailesi**: Arayüz genelinde yalnızca `Geist` (sans-serif) ve kod/veri/sayısal alanlarda `Geist Mono` kullanılır.
- **Yasaklı Fontlar**: `Inter` ve tarayıcının varsayılan serif font stacks (`Times New Roman`, `Georgia` vb.) premium alanlarda kesinlikle yasaktır.
- **Hiyerarşi**: Başlıklar sıkıştırılmış harf aralığına (`tracking-tighter` / `-0.025em`) ve sıkıştırılmış satır yüksekliğine (`leading-none` veya `leading-[1.1]`) sahip olmalıdır.

---

## 3. İkon ve Karakter Kuralları (Kesin Yasaklar)

Arayüzde **Unicode sembollerin veya emojilerin kullanımı kesinlikle yasaktır**.

- ❌ **Yasaklı**: `⬆ Upload`, `↻ Refresh`, `Date ↓`, `▶ Run`, `✕`, `×`, `⚠ Warning` vb.
-  **Doğru**: Temiz, tek renk, çizgi tarzında (stroke-based) **inline SVG** kullanımı.
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
- **Butonlar ve Inputlar**: `--radius-sm` (8px) veya `--radius` (12px)
- **Kartlar ve Büyük Modaller**: `--radius-lg` (16px) or `--radius-xl` (20px)

---

## 6. Fonksiyonel Güvenlik (Backend Entegrasyonu)

- Arayüzü güzelleştirirken veya HTML/CSS güncellerken JavaScript (`static/app.js`) ve Flask server (`server.py`) tarafından dinlenen **`id` veya `data-*` niteliklerini kesinlikle değiştirmeyin**.
- CSS sınıflarını güncellerken event dinleyicilerin tetiklendiği sınıfları (örneğin `.sidebar-tab`, `.mobile-tab`, `[data-action="..."]`) korumaya özen gösterin.
