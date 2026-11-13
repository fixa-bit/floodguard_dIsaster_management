"""Copy the existing observed table verbatim and bundle its sample loader."""
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SHORT_RANGE = ROOT.parents[2]


def main():
    source = SHORT_RANGE / 'evaluation comparison/common/data/marala_daily.csv'
    output = ROOT / 'data/marala_daily.csv'
    output.parent.mkdir(parents=True, exist_ok=True)
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    if output.exists() and digest(output) != digest(source):
        raise ValueError('Existing model table differs from source; use a separate run')
    if not output.exists():
        shutil.copy2(source, output)
    original_loader = SHORT_RANGE / 'evaluation comparison/common/data.py'
    reference = ROOT / 'source_reference/project_core_data.py'
    reference.parent.mkdir(parents=True, exist_ok=True)
    if not reference.exists():
        shutil.copy2(original_loader, reference)
    # Remove only the workspace path bootstrap so this model is self contained.
    text = reference.read_text(encoding='utf-8-sig')
    local = ROOT / '_core_data.py'
    if not local.exists():
        local.write_text('"""Bundled original daily sample loader; see source_reference."""\n' + text[text.index('import argparse'):], encoding='utf-8')
    (ROOT / 'data/preparation_report.json').write_text(json.dumps({
        'source': str(source), 'source_sha256': digest(source),
        'copy_sha256': digest(output), 'byte_identical': True,
        'no_discharge_filling': True, 'original_loader_sha256': digest(reference),
        'bundled_loader_sha256': digest(local),
        'loader_change': 'Removed workspace sys.path bootstrap only',
    }, indent=2) + '\n', encoding='utf-8')
    print('Copied source data without altering any values or NaNs.')


if __name__ == '__main__':
    main()
