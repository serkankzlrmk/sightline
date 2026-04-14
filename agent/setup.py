"""
Setup and initialization utilities for ReliefWeb Agent.
"""

import logging
import sys
from pathlib import Path

# Ensure agent/ and project root are on sys.path
_AGENT_DIR = str(Path(__file__).parent.resolve())
_ROOT_DIR  = str(Path(__file__).parent.parent.resolve())
for _p in (_AGENT_DIR, _ROOT_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from config import config
from model import check_ollama_connectivity, check_model_available

logger = logging.getLogger(__name__)


def verify_dependencies():
    """Verify all required Python dependencies are installed."""
    required_packages = [
        'flask',
        'langchain',
        'langchain-core',
        'langchain-openai',
        'langgraph',
        'requests',
        'python-dotenv',
    ]
    
    missing = []
    for package in required_packages:
        try:
            __import__(package.replace('-', '_'))
        except ImportError:
            missing.append(package)
    
    if missing:
        logger.error(f"Missing required packages: {', '.join(missing)}")
        logger.info(
            f"Install with: pip install {' '.join(missing)}"
        )
        return False
    
    logger.info("✓ All required packages are installed")
    return True


def verify_directories():
    """Verify that required directories exist and are writable."""
    directories = [
        config.DOWNLOADS_DIR,
        config.CHROMA_DIR,
    ]
    
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
        
        # Test write permission
        test_file = directory / ".write_test"
        try:
            test_file.write_text("test")
            test_file.unlink()
            logger.info(f"✓ Directory writable: {directory}")
        except Exception as e:
            logger.error(f"✗ Cannot write to {directory}: {e}")
            return False
    
    return True


def verify_ollama():
    """Verify Ollama is running and model is available."""
    if not check_ollama_connectivity():
        logger.error("✗ Ollama is not running")
        logger.info("Start Ollama with: ollama serve")
        return False
    
    logger.info("✓ Ollama is running")
    
    if not check_model_available(config.OLLAMA_MODEL):
        logger.warning(f"✗ Model {config.OLLAMA_MODEL} is not available")
        logger.info(f"Pull it with: ollama pull {config.OLLAMA_MODEL}")
        return False
    
    logger.info(f"✓ Model {config.OLLAMA_MODEL} is available")
    return True


def run_setup():
    """Run full system setup verification."""
    logger.info("="*60)
    logger.info("ReliefWeb Agent - System Setup Verification")
    logger.info("="*60)
    
    checks = [
        ("Dependencies", verify_dependencies),
        ("Directories", verify_directories),
        ("Ollama", verify_ollama),
    ]
    
    results = {}
    for name, check_fn in checks:
        logger.info(f"\n[{name}]")
        try:
            results[name] = check_fn()
        except Exception as e:
            logger.error(f"Error during {name} check: {e}")
            results[name] = False
    
    logger.info("\n" + "="*60)
    logger.info("SETUP SUMMARY")
    logger.info("="*60)
    
    for name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        logger.info(f"{name}: {status}")
    
    all_passed = all(results.values())
    
    if all_passed:
        logger.info("\n✓ System is ready to use!")
        return True
    else:
        logger.error("\n✗ System setup incomplete. Please fix the issues above.")
        return False


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s: %(message)s'
    )
    
    success = run_setup()
    sys.exit(0 if success else 1)
