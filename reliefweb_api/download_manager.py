"""
ReliefWeb Report Download Manager
Downloads and stores reports (PDF, HTML, text) to local filesystem
"""

import os
import requests
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict
import logging

from .reliefweb_config import (
    API_TIMEOUT_LONG,
    RELIEFWEB_REPORTS_API,
    RELIEFWEB_APPNAME,
    PDF_SIZE_LIMIT,
    PDF_SIZE_LIMIT_MB,
)
from .reliefweb_utils import clean_html_body, format_error, format_response

logger = logging.getLogger(__name__)

class DownloadManager:
    """Manages downloading and storing ReliefWeb reports"""
    
    def __init__(self, base_download_dir: str = "reliefweb_downloads"):
        """
        Initialize download manager
        
        Args:
            base_download_dir: Root directory for downloads
        """
        self.base_dir = Path(base_download_dir)
        self.base_dir.mkdir(exist_ok=True)
        self.download_log = []
    
    def _create_report_dir(self, report_id: int, report_title: str = "") -> Path:
        """Create a unique directory for each report"""
        # Sanitize title for filename
        safe_title = "".join(c for c in report_title if c.isalnum() or c in " -_")[:50]
        if safe_title:
            dir_name = f"{report_id}_{safe_title.strip()}"
        else:
            dir_name = str(report_id)
        
        report_dir = self.base_dir / dir_name
        report_dir.mkdir(exist_ok=True)
        return report_dir
    
    def get_report_metadata(self, report_id: int) -> Optional[Dict]:
        """Fetch report metadata from API"""
        try:
            url = f"{RELIEFWEB_REPORTS_API}/{report_id}?appname={RELIEFWEB_APPNAME}&fields[include][]=file&fields[include][]=body-html&fields[include][]=body&fields[include][]=title&fields[include][]=date&fields[include][]=source&fields[include][]=country&fields[include][]=disaster&fields[include][]=theme&fields[include][]=url&fields[include][]=format&fields[include][]=language"
            response = requests.get(url, timeout=API_TIMEOUT_LONG, verify=False)
            response.raise_for_status()
            data = response.json()
            
            if data.get("data") and len(data["data"]) > 0:
                return data["data"][0]
            return None
        except Exception as e:
            logger.error(f"Failed to get report metadata: {str(e)}")
            return None
    
    def download_pdf(self, report_id: int, output_dir: Path) -> Optional[str]:
        """
        Download PDF from report if available
        
        Args:
            report_id: Report ID
            output_dir: Directory to save PDF
            
        Returns:
            Path to downloaded PDF file or None
        """
        try:
            # Get report data
            report_data = self.get_report_metadata(report_id)
            if not report_data:
                logger.warning(f"Could not fetch report {report_id}")
                return None
            
            fields = report_data.get("fields", {})
            files = fields.get("file", [])
            
            # Find PDF — API returns "mimetype" (no underscore)
            pdf_file = None
            for file_item in files:
                mt = file_item.get("mimetype") or file_item.get("mime_type", "")
                if mt.lower() == "application/pdf":
                    pdf_file = file_item
                    break
            
            if not pdf_file:
                logger.info(f"No PDF found in report {report_id}")
                return None
            
            # Check size
            pdf_url = pdf_file.get("url", "")
            pdf_size = int(pdf_file.get("filesize", 0))
            pdf_filename = pdf_file.get("filename", f"report_{report_id}.pdf")
            
            if pdf_size > PDF_SIZE_LIMIT:
                logger.warning(f"PDF too large: {pdf_size / 1_000_000:.2f}MB (max {PDF_SIZE_LIMIT_MB}MB)")
                return None
            
            # Download
            pdf_response = requests.get(pdf_url, timeout=API_TIMEOUT_LONG, verify=False)
            pdf_response.raise_for_status()
            
            pdf_path = output_dir / pdf_filename
            with open(pdf_path, "wb") as f:
                f.write(pdf_response.content)
            
            logger.info(f"Downloaded PDF: {pdf_path}")
            return str(pdf_path)
        
        except Exception as e:
            logger.error(f"Failed to download PDF: {str(e)}")
            return None
    
    def download_html_content(self, report_id: int, output_dir: Path) -> Optional[str]:
        """
        Download HTML body content as text file
        
        Args:
            report_id: Report ID
            output_dir: Directory to save file
            
        Returns:
            Path to saved file or None
        """
        try:
            report_data = self.get_report_metadata(report_id)
            if not report_data:
                return None
            
            fields = report_data.get("fields", {})
            # Try multiple field names for body content
            body_html = (
                fields.get("body-html") or 
                fields.get("body") or 
                fields.get("full_content") or 
                ""
            )
            
            if not body_html:
                logger.warning(f"No HTML content in report {report_id}")
                return None
            
            # Clean HTML
            clean_content = clean_html_body(body_html)
            
            # Save
            content_path = output_dir / f"report_{report_id}_content.txt"
            with open(content_path, "w", encoding="utf-8") as f:
                f.write(clean_content)
            
            logger.info(f"Saved content: {content_path}")
            return str(content_path)
        
        except Exception as e:
            logger.error(f"Failed to download content: {str(e)}")
            return None
    
    def download_metadata(self, report_id: int, output_dir: Path) -> Optional[str]:
        """
        Save report metadata as JSON
        
        Args:
            report_id: Report ID
            output_dir: Directory to save file
            
        Returns:
            Path to saved metadata file or None
        """
        try:
            report_data = self.get_report_metadata(report_id)
            if not report_data:
                return None
            
            fields = report_data.get("fields", {})
            
            # Extract key metadata
            metadata = {
                "id": report_id,
                "title": fields.get("title", ""),
                "date": fields.get("date", {}),
                "source": fields.get("source", []),
                "countries": fields.get("country", []),
                "disasters": fields.get("disaster", []),
                "themes": fields.get("theme", []),
                "url": fields.get("url", ""),
                "language": fields.get("language", ""),
                "format": fields.get("format", ""),
            }
            
            # Save
            metadata_path = output_dir / f"report_{report_id}_metadata.json"
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Saved metadata: {metadata_path}")
            return str(metadata_path)
        
        except Exception as e:
            logger.error(f"Failed to save metadata: {str(e)}")
            return None
    
    def download_report(
        self,
        report_id: int,
        include_pdf: bool = True,
        include_content: bool = True,
        include_metadata: bool = True
    ) -> Dict:
        """
        Download all content for a single report
        
        Args:
            report_id: Report ID
            include_pdf: Download PDF if available
            include_content: Download HTML content as text
            include_metadata: Download metadata as JSON
            
        Returns:
            Dictionary with download results
        """
        # Get metadata first
        report_data = self.get_report_metadata(report_id)
        if not report_data:
            return {
                "success": False,
                "report_id": report_id,
                "error": "Could not fetch report metadata"
            }
        
        fields = report_data.get("fields", {})
        title = fields.get("title", "")
        
        # Create report directory
        report_dir = self._create_report_dir(report_id, title)
        
        result = {
            "success": True,
            "report_id": report_id,
            "title": title,
            "directory": str(report_dir),
            "files": {}
        }
        
        # Download files
        if include_pdf:
            pdf_path = self.download_pdf(report_id, report_dir)
            if pdf_path:
                result["files"]["pdf"] = pdf_path
        
        if include_content:
            content_path = self.download_html_content(report_id, report_dir)
            if content_path:
                result["files"]["content"] = content_path
        
        if include_metadata:
            metadata_path = self.download_metadata(report_id, report_dir)
            if metadata_path:
                result["files"]["metadata"] = metadata_path
        
        self.download_log.append(result)
        return result
    
    def download_reports_batch(
        self,
        report_ids: List[int],
        include_pdf: bool = True,
        include_content: bool = True,
        include_metadata: bool = True
    ) -> Dict:
        """
        Download multiple reports
        
        Args:
            report_ids: List of report IDs
            include_pdf: Download PDFs
            include_content: Download content
            include_metadata: Download metadata
            
        Returns:
            Summary of batch download
        """
        results = []
        start_time = datetime.now()
        
        for idx, report_id in enumerate(report_ids, 1):
            logger.info(f"Downloading report {idx}/{len(report_ids)}: {report_id}")
            
            result = self.download_report(
                report_id,
                include_pdf=include_pdf,
                include_content=include_content,
                include_metadata=include_metadata
            )
            results.append(result)
        
        elapsed = (datetime.now() - start_time).total_seconds()
        
        summary = {
            "total": len(report_ids),
            "successful": sum(1 for r in results if r.get("success")),
            "failed": sum(1 for r in results if not r.get("success")),
            "elapsed_seconds": elapsed,
            "base_directory": str(self.base_dir),
            "results": results
        }
        
        return summary
    
    def get_download_summary(self) -> str:
        """Get summary of all downloads as JSON string"""
        return json.dumps({
            "base_directory": str(self.base_dir),
            "total_downloads": len(self.download_log),
            "downloads": self.download_log
        }, indent=2, ensure_ascii=False)


# Global download manager instance
_manager = None

def get_download_manager(base_dir: str = "reliefweb_downloads") -> DownloadManager:
    """Get or create global download manager"""
    global _manager
    if _manager is None:
        _manager = DownloadManager(base_dir)
    return _manager

