# AGENT_NOTES.md — NovaSphere Production Handoff Notes

> Created: 24 Nisan 2026
> Branch: feature/ui-redesign
> Status: Production hardening tamamlandı, Oracle Cloud VM'de deploy edilecek

---

## Bu Branche Yapılan Tüm Değişiklikler

### 1. Security Hardening (Security Audit Tamamlandı)
- `@require_auth` eklendi: Tüm `/api/db/*`, `/api/ingest/search` route'lara
- `@require_admin` eklendi: `/api/agent/chat/unlock`
- Input validation: SITREP run (country:100, event:200, themes:10×80, dates:regex), Upload (MIME type PDF, MAX_CONTENT_LENGTH=50MB)
- XSS sanitization: `sanitizeHtml()` fonksiyonu (script/iframe/on* temizle), narrative_html artık textContent ile parse ediliyor
- CORS: `CORS_ORIGINS` env var'dan okunuyor, default `*` (dev modu)
- CSP header: `unsafe-inline` + `unsafe-eval` ekli (inline onclick handler'lar ve marked.js için)
- COOP/COEP/CORP header'ları: Firebase popup compat için
- Clock-skew tolerance: `check_revoked=False`, 2s retry mekanizması ("Token used too early" fix)
- SSL verification: `verify=False` → merkezi `_ssl_verify()` fonksiyonu, `SSL_VERIFY` env var ile kontrol
- Error sanitization: 500 hataları generic mesaj, detail server-side log
- Secret management: `SECRET_KEY` env var, `.env.example` oluşturuldu

### 2. Auth Race Condition Fix
- `auth.js`: `signInWithRedirect` fallback eklendi, auth dedup mekanizması
- `app.js`: `auth-ready` event bekleme + 3s fallback timeout
- Server-side: `_admins()` merkezi fonksiyon, `os.getenv` inline kullanımı kaldırıldı
- Debug logging: `require_auth`/`require_admin` token verify failure'ları logluyor

### 3. Deploy Configs
- `deploy/setup.sh` — VM otomatik kurulum
- `deploy/update.sh` — Git pull + pip install + restart
- `deploy/backup.sh` — SQLite + ChromaDB günlük yedekleme
- `deploy/gunicorn.conf.py` — 1 worker, 4 threads, 120s timeout
- `deploy/novasphere.service` — systemd unit
- `deploy/nginx.conf` — reverse proxy (SSE support)
- `deploy/logrotate.conf` — log rotation

### 4. Gunicorn + Requirements
- `requirements.txt`'e `gunicorn>=21.2.0` eklendi
- `.env.example` oluşturuldu (tüm değişkenler placeholder ile)
- `.gitignore` düzeltildi: `.env.*` yerine sadece `.env.local` ve `.env.production` ignore ediliyor

---

## Hâlâ Çözülmemiş / Dikkat Edilmesi Gereken Sorunlar

1. **ONNX/TensorRT log noise** — `config.py`'de suppress ediliyor ama her embedding call'dan önce yapılmıyor, bazen gürültü olabilir
2. **Firebase token clock skew** — 2s retry eklendi ama %100 çalıştığı garanti değil, saat sync önemli
3. **CSP `unsafe-inline`** — 28 inline onclick handler var, production'da kaldırılması lazım
4. **Rate limiting** — Per-IP limiter eklendi ama aktif değil (fonksiyon var, route'lara eklenmemiş)
5. **SSL verify** — `verify=False` kalmadı ama `reliefweb.py`'de hâlâ `urllib3.disable_warnings()` var

---

## Bir Sonraki Agent'ın Yapması Gerekenler (Deploy için)

### Adım 1: Oracle Cloud VM Oluşturma (Kullanıcı Tarafından)
- https://cloud.oracle.com → Sign Up (kart gerekiyor, always free, para çekilmez)
- Region: **Frankfurt** (veya London)
- Compute → Instances → Create Instance
- Name: `novasphere`, Image: Ubuntu 24.04, Shape: Ampere A1 (4 OCPU, 24GB RAM)
- SSH Key oluştur, Boot volume: 50GB
- Public IP adresini not al
- Security List ingress rules: Port 22, 80, 443 (source: 0.0.0.0/0)

### Adım 2: SSH ile VM'ye bağlanıp Komutları Çalıştırma
```bash
ssh -i /path/to/key ubuntu@YOUR_PUBLIC_IP

sudo apt update && sudo apt install -y git
git clone -b feature/ui-redesign https://github.com/serkankzlrmk/RedAgent.git /opt/novasphere
sudo bash /opt/novasphere/deploy/setup.sh
```

### Adım 3: Manuel Ayarlar
#### 3a. .env Düzenleme
```bash
sudo nano /opt/novasphere/.env
```
**Zorunlu değişiklikler:**
- `OLLAMA_API_KEY=` → Gerçek Ollama Cloud API key
- `ADMIN_UIDS=` → Firebase UID (virgülle ayrı liste, örn: `uid1,uid2`)
- `CORS_ORIGINS=http://YOUR_PUBLIC_IP` (ileride domain alınırsa değiştir)
- `SERVER_DEBUG=false`
- `SECRET_KEY=` → `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` çalıştırıp kopyala

#### 3b. firebase-service-account.json Kopyalama
```bash
scp -i /path/to/key firebase-service-account.json ubuntu@YOUR_PUBLIC_IP:/opt/novasphere/
```

#### 3c. nginx.conf Public IP Güncelleme
```bash
sudo nano /etc/nginx/sites-available/novasphere
# YOUR_SERVER_IP yerine VM'in public IP adresini yaz
sudo nginx -t && sudo systemctl reload nginx
```

### Adım 4: Servisi Başlatma
```bash
sudo systemctl start novasphere
sudo systemctl status novasphere
curl http://localhost:5000/api/health  # 200 döndürmeli
```

### Adım 5: Firebase Console Ayarları
- https://console.firebase.google.com → Authentication → Settings → Authorized domains
- `YOUR_PUBLIC_IP` (örn: `192.168.xxx.xxx`) ekle
- `localhost` ve `127.0.0.1` kalabilir (dev için)

### Adım 6: HTTPS Sertifikası (İsteğe Bağlı — Domain ile)
Eğer domain alınırsa:
```bash
sudo certbot --nginx -d yourdomain.com
# nginx.conf'te server_name güncelle
```

### Adım 7: Yedekleme Kurulumu
```bash
echo "0 3 * * * /opt/novasphere/deploy/backup.sh" | sudo crontab -
sudo cp /opt/novasphere/deploy/logrotate.conf /etc/logrotate.d/novasphere
```

### Adım 8: Önemli Komutlar
```bash
# Logları izle
sudo journalctl -u novasphere -f

# Hızlı güncelleme
sudo bash /opt/novasphere/deploy/update.sh

# Servisi yeniden başlat
sudo systemctl restart novasphere

# Nginx yeniden yükle
sudo systemctl reload nginx
```

---

## Branch Stratejisi

Deploy sonrası:
1. `feature/ui-redesign` → `main` merge (PR ile)
2. `main` dalına `v1.0.0` tag'i at
3. İlerideki v1.1, v1.2... için yeni feature branch'ler aç

---

## Mevcut Sorunlar (Devam Eden)

- **Clock skew**: Server saati ile Firebase arasında fark varsa token verify hala sıkıntı verebilir. Server'da NTP sync yapılmalı: `sudo apt install ntp`
- **CSP**: Production modunda (`SERVER_DEBUG=false`) CSP aktif ve inline handler'lar için `unsafe-inline` gerekiyor. İleride tüm onclick'leri JS event listener'a çevir ve bu kuralı kaldır
- **Rate limiting**: `_check_api_rate_limit()` fonksiyonu var ama henüz hiçbir route'a eklenmemiş. İhtiyaç varsa eklenmeli
- **Admin UIDs**: `ADMIN_UIDS` env var'da yönetiliyor. İleride Firebase Custom Claims'a taşımalı

---

## Önemli Dosyalar

- `/opt/novasphere/.env` — production ayarlar
- `/opt/novasphere/.env.example` — referans template
- `/opt/novasphere/firebase-service-account.json` — Firebase Admin SDK
- `/var/log/novasphere/` — uygulama logları
- `/etc/nginx/sites-available/novasphere` — nginx config
- `/etc/systemd/system/novasphere.service` — systemd config
- `/opt/novasphere/deploy/` — tüm deploy script'leri

---

## İletişim / Yardım

Herhangi bir problemde:
1. `sudo systemctl status novasphere` ile servis durumunu kontrol et
2. `sudo journalctl -u novasphere --no-pager -n 50` ile son logları gör
3. `tail -f /var/log/novasphere/error.log` ile canlı log izle
4. Health check: `curl http://localhost:5000/api/health`