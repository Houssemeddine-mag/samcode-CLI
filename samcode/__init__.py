import sys
import subprocess
import warnings
from rich.console import Console

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*urllib3.*")
warnings.filterwarnings("ignore", message=".*NumPy.*")

console = Console()

LIBS_TO_INSTALL = {
    'pdfplumber': 'pdfplumber', 'docx': 'python-docx', 'openpyxl': 'openpyxl',
    'pptx': 'python-pptx', 'PIL': 'Pillow', 'bs4': 'beautifulsoup4',
    'chromadb': 'chromadb', 'sentence_transformers': 'sentence-transformers',
    'ruff': 'ruff', 'pandas': 'pandas', 'matplotlib': 'matplotlib', 'seaborn': 'seaborn', 
    'nbformat': 'nbformat', 'sqlalchemy': 'sqlalchemy', 'pyarrow': 'pyarrow', 
    'psycopg2': 'psycopg2-binary', 'pymysql': 'pymysql', 'nbconvert': 'nbconvert',
    'pytesseract': 'pytesseract', 'tabulate': 'tabulate', 'rich': 'rich', 'questionary': 'questionary', 
    'prompt_toolkit': 'prompt_toolkit', 'requests': 'requests', 'textual': 'textual'
}


def lazy_import(module_name: str, package_name: str = None):
    """Import a module lazily, auto-installing if missing."""
    try:
        return __import__(module_name)
    except ImportError:
        pkg = package_name or LIBS_TO_INSTALL.get(module_name, module_name)
        console.print(f"[cyan]Installing {pkg}...[/cyan]")
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", pkg], capture_output=True)
        return __import__(module_name)
