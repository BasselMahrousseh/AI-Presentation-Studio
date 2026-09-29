"""Load one local Studio environment, never a fallback after a parent profile."""
import os
import re
from pathlib import Path

from dotenv import dotenv_values


def load_studio_environment():
    selected = os.environ.get('STUDIO_ENV_FILE')
    if selected == '':
        return
    if selected is None:
        if os.environ.get('ENVIRONMENT', 'development').lower() != 'development':
            return
        source = Path(__file__).resolve().parents[1] / '.env'
        if not source.is_file():
            return
    else:
        source = Path(selected).resolve()
    seen = set()
    for number, line in enumerate(source.read_text(encoding='utf-8-sig').splitlines(), 1):
        match = re.match(r'\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=', line)
        if match:
            if match[1] in seen:
                raise ValueError(f'Duplicate configuration key {match[1]} at {source.name}:{number}')
            seen.add(match[1])
    for key, value in dotenv_values(source, interpolate=False).items():
        if value is not None:
            os.environ.setdefault(key, value)
