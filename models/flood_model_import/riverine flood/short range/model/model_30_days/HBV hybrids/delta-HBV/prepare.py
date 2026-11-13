"""Copy the observed-only daily table without changing values or missing targets."""
import hashlib
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parents[3] / 'evaluation comparison' / 'common' / 'data' / 'marala_daily.csv'
DESTINATION = ROOT / 'data' / 'marala_daily.csv'


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    if DESTINATION.exists() and sha256(DESTINATION) != sha256(SOURCE):
        raise ValueError('Existing daily table differs from the observed source; refusing to overwrite it')
    if not DESTINATION.exists():
        shutil.copy2(SOURCE, DESTINATION)
    if sha256(DESTINATION) != sha256(SOURCE):
        raise RuntimeError('Copied table does not match source bytes')
    report = {
        'source': str(SOURCE), 'source_sha256': sha256(SOURCE),
        'copy_sha256': sha256(DESTINATION), 'byte_identical': True,
        'discharge_interpolated_or_filled': False,
    }
    (ROOT / 'data' / 'preparation_report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
