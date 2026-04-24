"""
PDF to Structured Format Converter
Converts PDFs to Markdown and JSON formats for easy agent consumption
Uses PyPDF2 for lightweight PDF processing (Docling as optional enhancement)
"""

import json
import logging
from pathlib import Path
from typing import Optional, Dict
import requests
import tempfile
from PyPDF2 import PdfReader

from .reliefweb_config import API_TIMEOUT_LONG, RELIEFWEB_APPNAME, RELIEFWEB_REPORTS_API, _ssl_verify

logger = logging.getLogger(__name__)

# Try to import Docling, but make it optional
try:
    from docling.document_converter import DocumentConverter
    from docling_core.types.doc import ConversionStatus
    DOCLING_AVAILABLE = True
except ImportError:
    DOCLING_AVAILABLE = False
    logger.info("Docling not available, using PyPDF2 for PDF processing")

class PDFConverter:
    """Convert PDFs to structured formats (Markdown, JSON)"""
    
    def __init__(self):
        """Initialize document converter"""
        self.docling_available = DOCLING_AVAILABLE
        if DOCLING_AVAILABLE:
            try:
                self.converter = DocumentConverter()
                logger.info("Docling DocumentConverter initialized")
            except Exception as e:
                logger.warning(f"Could not initialize Docling: {str(e)}")
                self.converter = None
                self.docling_available = False
        else:
            self.converter = None
    
    def _extract_text_pypdf2(self, pdf_path: str) -> str:
        """Extract text using PyPDF2 (fast, lightweight)"""
        try:
            reader = PdfReader(pdf_path)
            text_blocks = []
            
            for page_num, page in enumerate(reader.pages, 1):
                text_blocks.append(f"\n--- PAGE {page_num} ---\n")
                page_text = page.extract_text()
                if page_text:
                    text_blocks.append(page_text)
            
            return "".join(text_blocks)
        except Exception as e:
            logger.error(f"Error extracting text with PyPDF2: {str(e)}")
            return ""
    
    def convert_pdf_to_markdown(self, pdf_path: str) -> Optional[str]:
        """
        Convert PDF to Markdown format
        
        Uses Docling if available, falls back to PyPDF2
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Markdown content or None if conversion fails
        """
        pdf_path_obj = Path(pdf_path)
        if not pdf_path_obj.exists():
            logger.error(f"PDF file not found: {pdf_path}")
            return None
        
        logger.info(f"Converting PDF to Markdown: {pdf_path}")
        
        # Try Docling first if available
        if self.docling_available and self.converter:
            try:
                result = self.converter.convert(str(pdf_path_obj))
                from docling_core.types.doc import ConversionStatus as ConvStatus
                
                if result.status == ConvStatus.SUCCESS:
                    markdown_content = result.document.export_to_markdown()
                    logger.info(f"PDF converted to Markdown with Docling ({len(markdown_content)} chars)")
                    return markdown_content
            except Exception as e:
                logger.warning(f"Docling conversion failed, falling back to PyPDF2: {str(e)}")
        
        # Fallback to PyPDF2
        text = self._extract_text_pypdf2(str(pdf_path_obj))
        if text:
            # Format as markdown
            markdown = f"# PDF Report\n\n{text}\n"
            logger.info(f"PDF converted to Markdown with PyPDF2 ({len(markdown)} chars)")
            return markdown
        
        return None
    
    def convert_pdf_to_json(self, pdf_path: str) -> Optional[Dict]:
        """
        Convert PDF to JSON structured format
        
        Extracts text and metadata, structures as JSON
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Dictionary with structured content or None
        """
        pdf_path_obj = Path(pdf_path)
        if not pdf_path_obj.exists():
            logger.error(f"PDF file not found: {pdf_path}")
            return None
        
        logger.info(f"Converting PDF to JSON: {pdf_path}")
        
        try:
            reader = PdfReader(str(pdf_path_obj))
            
            pages_content = []
            full_text = ""
            
            for page_num, page in enumerate(reader.pages, 1):
                page_text = page.extract_text()
                if page_text:
                    pages_content.append({
                        "page": page_num,
                        "content": page_text
                    })
                    full_text += f"\n--- PAGE {page_num} ---\n{page_text}"
            
            structured = {
                "document_type": "pdf_converted",
                "total_pages": len(reader.pages),
                "conversion_method": "docling" if self.docling_available else "pypdf2",
                "pages": pages_content,
                "full_text": full_text.strip()
            }
            
            logger.info(f"PDF converted to JSON ({len(reader.pages)} pages)")
            return structured
        
        except Exception as e:
            logger.error(f"Error converting PDF to JSON: {str(e)}")
            return None
    
    def save_markdown(self, markdown_content: str, output_path: str) -> bool:
        """Save markdown content to file"""
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(markdown_content)
            logger.info(f"Saved Markdown: {output_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save markdown: {str(e)}")
            return False
    
    def save_json(self, json_content: Dict, output_path: str) -> bool:
        """Save JSON content to file"""
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(json_content, f, indent=2, ensure_ascii=False)
            logger.info(f"Saved JSON: {output_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save JSON: {str(e)}")
            return False


class ReportFormatConverter:
    """High-level converter for ReliefWeb reports"""
    
    def __init__(self):
        self.pdf_converter = PDFConverter()
    
    def download_and_convert_report(
        self,
        report_id: int,
        output_dir: str = "reliefweb_downloads",
        formats: list = None
    ) -> Dict:
        """
        Download a report and convert its PDF to structured formats
        
        Args:
            report_id: ReliefWeb report ID
            output_dir: Directory to save converted files
            formats: List of formats to save ['markdown', 'json', 'both']
        
        Returns:
            Dictionary with conversion results
        """
        if formats is None:
            formats = ['markdown', 'json']
        
        result = {
            "report_id": report_id,
            "success": False,
            "files": {}
        }
        
        try:
            # Get report metadata
            url = f"{RELIEFWEB_REPORTS_API}/{report_id}?appname={RELIEFWEB_APPNAME}"
            response = requests.get(url, timeout=30, verify=_ssl_verify())
            response.raise_for_status()
            data = response.json()
            
            if not data.get("data"):
                return result
            
            fields = data["data"][0].get("fields", {})
            title = fields.get("title", f"report_{report_id}")
            
            # Safe directory name
            safe_title = "".join(c for c in title if c.isalnum() or c in " -_")[:50]
            report_dir = Path(output_dir) / f"{report_id}_{safe_title.strip()}"
            report_dir.mkdir(parents=True, exist_ok=True)
            
            # Find and download PDF
            files = fields.get("file", [])
            pdf_file = None
            for file_item in files:
                if file_item.get("mime_type", "").lower() == "application/pdf":
                    pdf_file = file_item
                    break
            
            if not pdf_file:
                result["error"] = "No PDF found in report"
                return result
            
            pdf_url = pdf_file.get("url", "")
            pdf_filename = pdf_file.get("filename", f"report_{report_id}.pdf")
            
            # Download PDF to temporary location
            pdf_response = requests.get(pdf_url, timeout=API_TIMEOUT_LONG, verify=_ssl_verify())
            pdf_response.raise_for_status()
            
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
                tmp.write(pdf_response.content)
                tmp_pdf_path = tmp.name
            
            try:
                # Convert to requested formats
                if 'markdown' in formats or 'both' in formats:
                    markdown = self.pdf_converter.convert_pdf_to_markdown(tmp_pdf_path)
                    if markdown:
                        md_path = report_dir / f"report_{report_id}.md"
                        if self.pdf_converter.save_markdown(markdown, str(md_path)):
                            result["files"]["markdown"] = str(md_path)
                            logger.info(f"Markdown saved for report {report_id}")
                
                if 'json' in formats or 'both' in formats:
                    json_content = self.pdf_converter.convert_pdf_to_json(tmp_pdf_path)
                    if json_content:
                        json_path = report_dir / f"report_{report_id}_structured.json"
                        if self.pdf_converter.save_json(json_content, str(json_path)):
                            result["files"]["json"] = str(json_path)
                            logger.info(f"JSON saved for report {report_id}")
                
                result["success"] = len(result["files"]) > 0
                result["title"] = title
                result["directory"] = str(report_dir)
            
            finally:
                # Cleanup temp file
                Path(tmp_pdf_path).unlink(missing_ok=True)
        
        except Exception as e:
            result["error"] = str(e)
            logger.error(f"Error converting report {report_id}: {str(e)}")
        
        return result
    
    def batch_convert_reports(
        self,
        report_ids: list,
        output_dir: str = "reliefweb_downloads",
        formats: list = None
    ) -> Dict:
        """
        Convert multiple reports in batch
        
        Args:
            report_ids: List of report IDs
            output_dir: Directory for outputs
            formats: Formats to convert to
        
        Returns:
            Summary of batch conversion
        """
        results = []
        for idx, report_id in enumerate(report_ids, 1):
            logger.info(f"Converting report {idx}/{len(report_ids)}: {report_id}")
            result = self.download_and_convert_report(report_id, output_dir, formats)
            results.append(result)
        
        summary = {
            "total": len(report_ids),
            "successful": sum(1 for r in results if r.get("success")),
            "failed": sum(1 for r in results if not r.get("success")),
            "base_directory": output_dir,
            "results": results
        }
        
        return summary
