"""Download a pinned, unmodified subset of the authors' differentiable HBV."""
import hashlib
import json
import shutil
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REVISION = 'b163a3c0125c5188f730f379643437d83b4e5d35'
FILES = [
    'LICENSE', 'README.md', 'src/hydrodl2/models/hbv/hbv.py',
    'src/hydrodl2/models/base.py', 'src/hydrodl2/core/calc/__init__.py',
    'src/hydrodl2/core/calc/fdj.py', 'src/hydrodl2/core/calc/uh_routing.py',
    'src/hydrodl2/core/calc/utils.py',
]


def main():
    records = []
    for name in FILES:
        url = f'https://raw.githubusercontent.com/mhpi/hydrodl2/{REVISION}/{name}'
        target = ROOT / 'source_reference' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(urllib.request.urlopen(url, timeout=60).read())
        records.append({'path': name, 'url': url,
                        'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
        if name.startswith('src/'):
            destination = ROOT / '_vendor' / name.removeprefix('src/')
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, destination)
    for name in ('hydrodl2', 'hydrodl2/core', 'hydrodl2/models', 'hydrodl2/models/hbv'):
        path = ROOT / '_vendor' / name / '__init__.py'
        if not path.exists():
            path.write_text('', encoding='utf-8')
    (ROOT / 'source_reference/provenance.json').write_text(json.dumps({
        'repository': 'https://github.com/mhpi/hydrodl2', 'revision': REVISION,
        'model': 'HBV 1.0, Feng et al. (2022), authors implementation',
        'license': 'PSU non-commercial software license; see LICENSE',
        'files': records,
    }, indent=2) + '\n', encoding='utf-8')
    print('Pinned HBV sources downloaded; original source bytes retained.')


if __name__ == '__main__':
    main()
