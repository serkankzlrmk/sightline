# Specification: Proposal Design Pipeline (Proje Tasarım Odası)

Bu doküman, Sightline platformuna eklenecek olan otonom ve interaktif **Proje Teklifi Tasarım Hattı (Proposal Design Pipeline)** için tasarımsal ve teknik bir yol haritasıdır. Geliştirici ajanların backend API'lerini ve LLM entegrasyonlarını bu kurallara göre kurması beklenmektedir.

---

## 1. Kullanıcı Deneyimi (UX/UI Flow)

Sistem, kullanıcının ReliefWeb ve HDX verilerinden beslenerek insani yardım proje teklifleri (Logframe, ToC, tam teklif metni) tasarlamasını sağlar.

### Arayüz Düzeni (Workspace Split Layout):
* **Sol Panel (%65 genişlik)**: İnteraktif Proje Çalışma Alanı.
  * **Sekme 1: Context**: Ülke, kriz konusu, hedeflenen donör ve verilerin listelendiği alan.
  * **Sekme 2: Theory of Change (ToC)**: Projenin etki zincirinin görselleştirildiği alan (SVG düğümleri ile interaktif).
  * **Sekme 3: Logframe**: Klasik USAID/ECHO 4x4 Mantıksal Çerçeve Matrisi. Hücreler tıklanabilir ve anında düzenlenebilir.
  * **Sekme 4: Narrative**: Donör formatında üretilen tam teklif metni.
* **Sağ Panel (%35 genişlik - Frosted Glass)**: **Yapay Zekâ Proje Danışmanı (AI Advisor)**.
  * Proje tasarımını sürekli denetleyen, donör yönergelerine ve SMART kriterlerine göre eleştiren ve kullanıcıyla sohbet eden panel.
  * Önerilen iyileştirmelerin yanında bir **"Uygula" (Apply)** butonu yer alır. Tıklandığında sol taraftaki matris güncellenir.

---

## 2. API Uç Noktaları (Geliştirilecek Backend Route'ları)

Geliştirici ajanın `server.py` ve ilgili modüllere eklemesi gereken API route'ları şunlardır:

### 1. Proje Yönetimi
* **`GET /api/proposals`**: Kullanıcının geçmiş projelerini listeler.
  * *Response*: `[{ "id": "prop_01", "title": "WASH South Sudan", "country": "Sudan", "created_at": "..." }]`
* **`POST /api/proposals/new`**: Yeni bir proje teklifi taslağı oluşturur.
  * *Request*: `{ "title": "...", "country": "...", "event": "...", "themes": ["WASH"], "donor": "ECHO" }`
* **`GET /api/proposals/<id>`**: Proje detaylarını (ToC, Logframe, Narrative) döner.
* **`PUT /api/proposals/<id>`**: Proje verilerini (kullanıcının el ile yaptığı düzenlemeleri) kaydeder.
* **`DELETE /api/proposals/<id>`**: Projeyi siler.

### 2. Yapay Zekâ Üretim ve Eleştiri Uç Noktaları
* **`POST /api/proposals/<id>/generate-toc`**: Kriz verilerini okuyarak bir Theory of Change taslağı (düğümler halinde) üretir.
* **`POST /api/proposals/<id>/generate-logframe`**: ToC ve veri bağlamını kullanarak 4x4 Logframe matrisini oluşturur.
* **`POST /api/proposals/<id>/advisor/chat`**: AI Advisor ile eleştirel konuşma kanalı.
  * *Request*: `{ "message": "Göstergeyi daha gerçekçi yapabilir miyiz?" }`
  * *Response (SSE veya JSON)*: Önerilen eleştiri metni + `{ "action": "update_cell", "cell_id": "indicator_1", "new_value": "..." }` gibi yapısal komutlar.
* **`POST /api/proposals/<id>/generate-narrative`**: Logframe ve ToC tabanlı tam teklif metni üretir.

---

## 3. Front-End Entegrasyonu (Yapılan İşlemler)

Tasarım şefi olarak, projeyi bozmadan ek bir sistem katmanı olarak aşağıdaki yapıları kurdum:

1. **`index.html`** dosyasına:
   - Sidebar navigasyonuna `tab-proposal` ("Proposals") butonu ve simgesi eklendi.
   - Panel alanına `#panel-proposal` adında, split-pane yapısına sahip çalışma alanı yerleştirildi.
   - SITREP raporunun detay ekranındaki aksiyon barına **"Design Proposal"** butonu yerleştirildi. Bu buton, mevcut krizin bağlamını (ülke, tema, tarihler) doğrudan Proje Tasarım Odasına aktarır.

2. **`style.css`** dosyasına:
   - Split panel yerleşimi (`.proposal-page`, `.proposal-sidebar`, `.proposal-workspace`), ToC SVG düğümleri ve Logframe matris tabloları için Apple esintili modern CSS kuralları eklendi.

3. **`app.js`** dosyasına:
   - Panel geçiş tetikleyicileri ve SITREP'ten projeye geçiş bağlamını yakalayan JS fonksiyon yapısı eklendi.

## 4. Geliştirici Ajanlara Not (Handoff Instructions)

* JavaScript tarafında `proposalState` adında bir durum nesnesi oluşturulmuştur. Bu nesne `activeProposalId`, `currentStep` ve `projectData` bilgilerini tutar.
* `/api/proposals/...` uç noktaları geliştirilirken, donör kriterlerinin (ECHO veya USAID) sistem promptlarına doğru bir şekilde verilmesi gerekmektedir.
* ToC akış düğümlerini render ederken, dinamik SVG yolları veya basit kutu yapıları (`.toc-node`) kullanılarak kullanıcıların tıklama olayları yakalanmalıdır.
* Logframe hücresi düzenlendiğinde `change` event'i ile anında `PUT /api/proposals/<id>` API'sine kaydetme (autosave) tetiklenmelidir.
