import json
import os
import sqlite3
import sys
from pathlib import Path

# Ensure project root is on sys.path (for reliefweb_api, config, etc.)
_ROOT = str(Path(__file__).parent.parent.resolve())
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

os.environ["ORT_LOGGING_LEVEL"] = "3"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

# Use config for DB path (respects .env overrides)
from config import DB_PATH as _DEFAULT_DB_PATH

DB_PATH = str(_DEFAULT_DB_PATH)


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def list_reports():
    conn = get_conn()
    rows = conn.execute(
        "SELECT report_id, title, date, countries, source, has_pdf, has_content FROM reports ORDER BY date DESC"
    ).fetchall()
    conn.close()
    if not rows:
        print("Veritabaninda rapor yok.")
        return
    print(f"\n{'ID':<12} {'Tarih':<12} {'Ulke':<20} {'Kaynak':<30} {'PDF':>4} {'Metin':>6}  Baslik")
    print("-" * 110)
    for r in rows:
        pdf = "VAR" if r["has_pdf"] else "-"
        txt = "VAR" if r["has_content"] else "-"
        try:
            countries_list = json.loads(r["countries"] or "[]")
            country = (countries_list[0] if countries_list else "")[:18]
        except Exception:
            country = (r["countries"] or "")[:18]
        source = (r["source"] or "")[:28]
        title = (r["title"] or "")[:60]
        print(f"{r['report_id']:<12} {r['date'] or '':<12} {country:<20} {source:<30} {pdf:>4} {txt:>6}  {title}")
    print(f"\nToplam: {len(rows)} rapor")


def show_report(report_id, show_chunks=False, export=False):
    conn = get_conn()
    row = conn.execute("SELECT * FROM reports WHERE report_id=?", (report_id,)).fetchone()
    if not row:
        print(f"Rapor bulunamadi: {report_id}")
        conn.close()
        return

    try:
        countries_list = json.loads(row["countries"] or "[]")
        country_str = ", ".join(countries_list)
    except Exception:
        country_str = row["countries"] or ""

    print(f"\n=== RAPOR: {row['report_id']} ===")
    print(f"Baslik   : {row['title']}")
    print(f"Tarih    : {row['date']}")
    print(f"Ulke     : {country_str}")
    print(f"Kaynak   : {row['source']}")
    print(f"Temalar  : {row['themes']}")
    print(f"URL      : {row['url']}")
    print(f"Format   : {row['format_type']}")
    print(f"Dil      : {row['language']}")
    print(f"PDF      : {'Mevcut' if row['has_pdf'] else 'Yok'}  ({row['pdf_pages']} sayfa)")
    print(f"Icerik   : {'Mevcut' if row['has_content'] else 'Yok'}  ({row['total_chunks']} chunk)")
    print(f"Eklendi  : {row['ingested_at']}")

    if show_chunks:
        chunks = conn.execute(
            "SELECT chunk_index, source_type, content FROM chunks WHERE report_id=? ORDER BY chunk_index",
            (report_id,)
        ).fetchall()
        print(f"\n--- {len(chunks)} Chunk ---")
        for c in chunks:
            print(f"\n[Chunk {c['chunk_index']} / {c['source_type']}]\n{c['content'][:400]}")

    if export:
        chunks = conn.execute(
            "SELECT chunk_index, source_type, content FROM chunks WHERE report_id=? ORDER BY chunk_index",
            (report_id,)
        ).fetchall()
        out = {
            "report_id": row["report_id"],
            "title": row["title"],
            "date": row["date"],
            "countries": country_str,
            "source": row["source"],
            "themes": row["themes"],
            "url": row["url"],
            "format_type": row["format_type"],
            "language": row["language"],
            "has_pdf": bool(row["has_pdf"]),
            "has_content": bool(row["has_content"]),
            "pdf_pages": row["pdf_pages"],
            "total_chunks": row["total_chunks"],
            "ingested_at": row["ingested_at"],
            "chunks": [{"index": c["chunk_index"], "source": c["source_type"], "text": c["content"]} for c in chunks],
        }
        fname = f"export_{report_id}.json"
        with open(fname, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"\nDisa aktarildi: {fname}")

    conn.close()


def search_text(keyword):
    conn = get_conn()
    rows = conn.execute(
        "SELECT r.report_id, r.title, r.date, r.countries FROM reports r "
        "WHERE r.title LIKE ? "
        "OR EXISTS (SELECT 1 FROM chunks c WHERE c.report_id=r.report_id AND c.content LIKE ?) "
        "ORDER BY r.date DESC",
        (f"%{keyword}%", f"%{keyword}%")
    ).fetchall()
    conn.close()
    if not rows:
        print(f"'{keyword}' icin sonuc bulunamadi.")
        return
    print(f"\n'{keyword}' aramasinda {len(rows)} rapor bulundu:\n")
    for r in rows:
        try:
            countries_list = json.loads(r["countries"] or "[]")
            country = (countries_list[0] if countries_list else "")[:20]
        except Exception:
            country = (r["countries"] or "")[:20]
        print(f"  {r['report_id']}  {r['date'] or '':<12}  {country:<20}  {r['title']}")


def vector_search(query, top_k=5):
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "reliefweb_api"))
        from vector_store import get_vector_store
        vs = get_vector_store()
        results = vs.search(query, n_results=top_k)
        if not results:
            print("ChromaDB sorgusunda sonuc yok.")
            return
        print(f"\nVektor arama: '{query}'\n")
        for i, r in enumerate(results, 1):
            print(f"[{i}] Benzerlik: {r['similarity']:.3f}  |  {r['report_id']}  {r['date'] or ''}  {r['title']}")
            print(f"     {r['chunk_preview'][:200]}\n")
    except Exception as e:
        print(f"ChromaDB hatasi: {e}")


def show_stats():
    conn = get_conn()
    report_count = conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
    chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    rows = conn.execute("SELECT countries FROM reports").fetchall()
    conn.close()

    country_counts = {}
    for r in rows:
        try:
            clist = json.loads(r["countries"] or "[]")
            for c in clist:
                country_counts[c] = country_counts.get(c, 0) + 1
        except Exception:
            pass

    print("\n=== Veritabani Istatistikleri ===")
    print(f"Toplam rapor : {report_count}")
    print(f"Toplam chunk : {chunk_count}")
    if country_counts:
        print("\nUlkeye gore:")
        for c, cnt in sorted(country_counts.items(), key=lambda x: -x[1]):
            print(f"  {c:<30} {cnt} rapor")


def print_help():
    print("""
Kullanim:
  python db_query.py                          -> Tum raporlari listele
  python db_query.py --stats                  -> Istatistikleri goster
  python db_query.py <REPORT_ID>              -> Rapor detaylarini goster
  python db_query.py <REPORT_ID> --chunks     -> Chunklari da goster
  python db_query.py <REPORT_ID> --export     -> JSON dosyasina aktar
  python db_query.py --search <kelime>        -> Baslik/icerik metin arama
  python db_query.py --vector "<sorgu>"       -> ChromaDB vektor arama
  python db_query.py --help                   -> Bu yardim mesaji
""")


if __name__ == "__main__":
    args = sys.argv[1:]

    if not args:
        list_reports()
    elif "--help" in args or "-h" in args:
        print_help()
    elif "--stats" in args:
        show_stats()
    elif "--search" in args:
        idx = args.index("--search")
        keyword = args[idx + 1] if idx + 1 < len(args) else ""
        if not keyword:
            print("Kullanim: python db_query.py --search <kelime>")
        else:
            search_text(keyword)
    elif "--vector" in args:
        idx = args.index("--vector")
        query = args[idx + 1] if idx + 1 < len(args) else ""
        if not query:
            print("Kullanim: python db_query.py --vector \"sorgu metni\"")
        else:
            vector_search(query)
    else:
        report_id = args[0]
        show_chunks = "--chunks" in args
        export = "--export" in args
        show_report(report_id, show_chunks=show_chunks, export=export)
