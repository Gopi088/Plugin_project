"""Check the current Python interpreter before running parsing or evaluation."""
import importlib
import sys
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ('pdfplumber', 'pdfminer', 'pypdfium2', 'docx', 'PIL')


def main():
    print(f'Python: {sys.executable}')
    print(f'Environment: {sys.prefix}')
    failures = []
    for name in REQUIRED:
        try:
            module = importlib.import_module(name)
            print(f'OK {name}: {getattr(module, "__version__", "installed")}')
            if name == 'docx' and not hasattr(module.Document(), 'iter_inner_content'):
                failures.append('python-docx >= 1.1.0 is required for table order')
        except Exception as exc:
            failures.append(f'{name}: {type(exc).__name__}: {exc}')
    if Path(sys.prefix).resolve() != (ROOT / 'venv').resolve():
        print(f'NOTE: this is not the project environment. Use {ROOT}/venv/bin/python.')
    if failures:
        for failure in failures:
            print(f'ERROR {failure}')
        print(f'Install dependencies: {ROOT}/venv/bin/python -m pip install -r {ROOT}/requirements.txt')
        return 1
    for executable in ('tesseract', 'antiword'):
        print(f'Optional {executable}: {shutil.which(executable) or "not installed"}')
    print('All required document dependencies are available.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
