"""Download the actual author's final checkpoint and exact global scalers."""
# Model workspace import path.
import sys as _layout_sys
from pathlib import Path as _LayoutPath
for _layout_parent in _LayoutPath(__file__).resolve().parents:
    if (_layout_parent / 'evaluation comparison' / 'common').is_dir():
        _layout_sys.path.insert(0, str(_layout_parent / 'model' / 'model_15 days'))
        _layout_sys.path.insert(0, str(_layout_parent / 'model' / 'model_10 days'))
        _layout_sys.path.insert(0, str(_layout_parent / 'evaluation comparison' / 'common'))
        break

import hashlib
import json
from pathlib import Path

import requests
import yaml


REVISION = '43f1ab45d2c3678e728b552919b898824e5f1069'


def main():
    root = Path(__file__).resolve().parent
    output = root / 'pretrained/caravan_base'
    receipt = {'repository': 'EmilRyd/caravan_model', 'revision': REVISION, 'files': []}
    for name in ['config.yml', 'train_data/train_data_scaler.yml', 'model_epoch040.pt']:
        url = f'https://huggingface.co/EmilRyd/caravan_model/resolve/{REVISION}/caravan_base/{name}'
        response = requests.get(url, timeout=120); response.raise_for_status()
        path = output / name; path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != response.content:
            raise ValueError('Existing pretrained source differs; use a new source directory')
        if not path.exists():
            path.write_bytes(response.content)
        receipt['files'].append({'name': name, 'url': url, 'sha256': hashlib.sha256(response.content).hexdigest(), 'bytes': len(response.content)})
    (output.parent / 'download_receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    cfg = yaml.safe_load((output / 'config.yml').read_text())
    (output / 'config.json').write_text(json.dumps(cfg, indent=2) + '\n')
    print('Downloaded genuine global Caravan weights and global scalers:', output, flush=True)


if __name__ == '__main__':
    main()
