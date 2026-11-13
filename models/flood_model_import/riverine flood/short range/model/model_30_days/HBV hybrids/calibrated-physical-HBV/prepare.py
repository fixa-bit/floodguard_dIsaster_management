"""Copy the source daily table byte-for-byte; preserve all observed values and NaNs."""
import hashlib
import json
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    config = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))
    source = (ROOT / config['source_daily_file']).resolve()
    destination = (ROOT / config['daily_file']).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and digest(destination) != digest(source):
        raise ValueError('Existing model data differs from source; refusing to overwrite it')
    if not destination.exists():
        shutil.copy2(source, destination)
    receipt = {
        'source': str(source), 'source_sha256': digest(source),
        'copy_sha256': digest(destination), 'byte_identical': digest(source) == digest(destination),
        'discharge_filled_or_modified': False,
    }
    (destination.parent / 'preparation_report.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
