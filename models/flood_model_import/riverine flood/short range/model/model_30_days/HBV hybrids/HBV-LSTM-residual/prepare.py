"""Check that bundled data and physical-base references match their sources."""
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    cfg = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))
    source = (ROOT / cfg['source_daily_file']).resolve()
    local = (ROOT / cfg['daily_file']).resolve()
    if digest(source) != digest(local):
        raise ValueError('Model daily data copy differs from the observed source')
    files = sorted((ROOT / cfg['modis_dir']).glob('[12][0-9][0-9][0-9].csv'))
    if not files:
        raise ValueError('Bundled MODIS snow input files were not found')
    result = {
        'source_daily_sha256': digest(source), 'local_daily_sha256': digest(local),
        'daily_copy_byte_identical': True, 'modis_year_files': len(files),
        'modis_sha256': {p.name: digest(p) for p in files},
        'base_calibration_sha256': digest(ROOT / cfg['base_calibration']),
        'discharge_filled_or_modified': False,
    }
    (ROOT / 'data' / 'preparation_report.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
