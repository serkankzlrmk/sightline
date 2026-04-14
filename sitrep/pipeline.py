"""
sitrep_pipeline/pipeline.py
Ana orkestrasyon. Her adımın çıktısını ara JSON olarak kaydeder.
Kırık noktadan devam desteği: mevcut ara çıktı varsa o adım atlanır.

Kullanım:
    python pipeline.py --country Sudan --event "Sudan conflict"

    veya Python'dan:
        from pipeline import run_pipeline
        report_path = run_pipeline("Sudan", "Sudan conflict")
"""

import sys
import json
import logging
import argparse
from pathlib import Path
from typing import Optional

# Ensure sitrep/ (for chroma_adapter, clustering, etc.) and project root
# (for config.py) are on sys.path — needed when run as a subprocess.
_SITREP_DIR = str(Path(__file__).parent.resolve())
_ROOT_DIR   = str(Path(__file__).parent.parent.resolve())
for _p in (_SITREP_DIR, _ROOT_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from config import (
    OUTPUT_CLUSTERS_DIR,
    OUTPUT_QUESTIONS_DIR,
    OUTPUT_ANSWERS_DIR,
    OUTPUT_SUMMARIES_DIR,
    OUTPUT_REPORTS_DIR,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pipeline")


# ---------------------------------------------------------------------------
# Ara dosya yönetimi
# ---------------------------------------------------------------------------

def _safe_name(country: str, event: str) -> str:
    """Dosya adı için güvenli string üretir."""
    return f"{country}_{event}".replace(" ", "_").replace("/", "-")


def _checkpoint_path(step_name: str, country: str, event: str) -> Path:
    step_dirs = {
        "clusters"     : OUTPUT_CLUSTERS_DIR,
        "questions"    : OUTPUT_QUESTIONS_DIR,
        "filtered"     : OUTPUT_QUESTIONS_DIR,
        "answers"      : OUTPUT_ANSWERS_DIR,
        "answers_post" : OUTPUT_ANSWERS_DIR,
        "summaries"    : OUTPUT_SUMMARIES_DIR,
        "exec_summary" : OUTPUT_SUMMARIES_DIR,
    }
    base = step_dirs.get(step_name, OUTPUT_REPORTS_DIR)
    return base / f"{_safe_name(country, event)}_{step_name}.json"


def _load_checkpoint(step_name: str, country: str, event: str):
    path = _checkpoint_path(step_name, country, event)
    if path.exists():
        logger.info("  [CHECKPOINT] '%s' loaded: %s", step_name, path)
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def _save_checkpoint(data, step_name: str, country: str, event: str) -> None:
    path = _checkpoint_path(step_name, country, event)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info("  [CHECKPOINT] '%s' saved: %s", step_name, path)


# ---------------------------------------------------------------------------
# Ana pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    country: str,
    event: str,
    themes: Optional[list] = None,
    skip_cache: bool = False,
) -> Path:
    """
    Verilen ülke ve olay için tam SITREP pipeline'ını çalıştırır.

    Args:
        country    : primary_country değeri (Chroma metadata filtresi)
        event      : Olay adı (prompt'larda kullanılır)
        themes     : Opsiyonel tema filtresi (["Health", "Protection"] vb.)
        skip_cache : True ise ara checkpoint'leri yoksay, tüm adımları tekrar çalıştır

    Returns:
        Kayıt edilen rapor JSON'ının yolu.
    """
    logger.info("=" * 60)
    logger.info("SITREP Pipeline starting: %s / %s", country, event)
    logger.info("=" * 60)

    # ---- Adım 0: ChromaDB bağlantısı ----
    logger.info("[0] Connecting to Chroma DB...")
    from chroma_adapter import ChromaAdapter
    db = ChromaAdapter()
    total = db.count()
    logger.info("    Koleksiyon: %d chunk", total)

    # ---- Adım 1: Chunk'ları çek ----
    logger.info("[1] Loading chunks: country='%s'", country)
    chunks = _load_checkpoint("chunks_raw", country, event) if not skip_cache else None
    if chunks is None:
        chunks = db.get_chunks_by_country_and_themes(country, themes)
        if not chunks:
            raise ValueError(
                f"No chunks found for '{country}' in Chroma DB. "
                "Check the primary_country field."
            )
        _save_checkpoint(chunks, "chunks_raw", country, event)
    logger.info("    %d chunks loaded.", len(chunks))

    # ---- Adım 2: Clustering ----
    logger.info("[2] Running clustering...")
    clusters = _load_checkpoint("clusters", country, event) if not skip_cache else None
    if clusters is None:
        from clustering import run_clustering
        clusters = run_clustering(chunks)
        _save_checkpoint(clusters, "clusters", country, event)
    logger.info("    %d clusters generated.", len(clusters))

    # ---- Adım 3: Soru üretimi ----
    logger.info("[3] Generating questions...")
    questions_raw = _load_checkpoint("questions", country, event) if not skip_cache else None
    if questions_raw is None:
        from question_generation import generate_questions
        questions_raw = generate_questions(clusters, event=event, country=country)
        _save_checkpoint(questions_raw, "questions", country, event)

    # ---- Adım 4: Soru filtreleme ----
    logger.info("[4] Filtering questions...")
    filtered_questions = _load_checkpoint("filtered", country, event) if not skip_cache else None
    if filtered_questions is None:
        from question_filtering import filter_questions
        filtered_questions = filter_questions(questions_raw)
        _save_checkpoint(filtered_questions, "filtered", country, event)

    total_q = sum(len(v["filtered_questions"]) for v in filtered_questions.values())
    logger.info("    %d questions remaining after filtering.", total_q)

    # ---- Adım 5: RAG Cevap üretimi ----
    logger.info("[5] Generating RAG answers...")
    raw_answers = _load_checkpoint("answers", country, event) if not skip_cache else None
    if raw_answers is None:
        from rag_answers import answer_questions
        raw_answers = answer_questions(
            filtered_questions=filtered_questions,
            clusters=clusters,
            chroma_adapter=db,
            country=country,
        )
        _save_checkpoint(raw_answers, "answers", country, event)
    logger.info("    %d answers generated.", len(raw_answers))

    # ---- Adım 6: Citation post-processing ----
    logger.info("[6] Citation post-processing...")
    postprocessed = _load_checkpoint("answers_post", country, event) if not skip_cache else None
    if postprocessed is None:
        from citation_postprocess import postprocess_citations
        postprocessed = postprocess_citations(raw_answers)
        _save_checkpoint(postprocessed, "answers_post", country, event)

    # ---- Adım 7: Cluster özetleri ----
    logger.info("[7] Generating cluster summaries...")
    cluster_summaries = _load_checkpoint("summaries", country, event) if not skip_cache else None
    if cluster_summaries is None:
        from cluster_summary import generate_cluster_summaries
        cluster_summaries = generate_cluster_summaries(postprocessed, clusters)
        _save_checkpoint(cluster_summaries, "summaries", country, event)

    # ---- Adım 8: Executive summary ----
    logger.info("[8] Generating executive summary...")
    exec_summary = _load_checkpoint("exec_summary", country, event) if not skip_cache else None
    if exec_summary is None:
        from executive_summary import generate_executive_summary
        exec_summary = generate_executive_summary(postprocessed, cluster_summaries=cluster_summaries)
        _save_checkpoint(exec_summary, "exec_summary", country, event)

    # ---- Adım 9: Rapor birleştirme ----
    logger.info("[9] Assembling final report...")
    from report_assembly import assemble_report, save_report, generate_markdown

    report = assemble_report(
        country=country,
        event=event,
        clusters=clusters,
        filtered_questions=filtered_questions,
        postprocessed_answers=postprocessed,
        cluster_summaries=cluster_summaries,
        exec_summary=exec_summary,
    )

    report_path = save_report(report, country, event)

    # Markdown da kaydet
    md_path = OUTPUT_REPORTS_DIR / f"{_safe_name(country, event)}_report.md"
    md_path.write_text(generate_markdown(report), encoding="utf-8")
    logger.info("Markdown report saved: %s", md_path)

    logger.info("=" * 60)
    logger.info("Pipeline completed successfully!")
    logger.info("  JSON  : %s", report_path)
    logger.info("  MD    : %s", md_path)
    logger.info("=" * 60)

    return report_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="SITREP Pipeline — Chroma + OpenRouter"
    )
    parser.add_argument(
        "--country", required=True,
        help="Ülke adı (Chroma'daki primary_country değeri ile eşleşmeli)",
    )
    parser.add_argument(
        "--event", required=False, default="",
        help="Olay/kriz adı (prompt'larda kullanılır). Boş bırakılırsa ülke adı kullanılır.",
    )
    parser.add_argument(
        "--themes", nargs="*", default=None,
        help="Opsiyonel tema filtresi (örn: --themes Health Protection)",
    )
    parser.add_argument(
        "--skip-cache", action="store_true",
        help="Checkpoint'leri yoksay, tüm adımları yeniden çalıştır",
    )

    args = parser.parse_args()
    run_pipeline(
        country=args.country,
        event=args.event or args.country,
        themes=args.themes,
        skip_cache=args.skip_cache,
    )
