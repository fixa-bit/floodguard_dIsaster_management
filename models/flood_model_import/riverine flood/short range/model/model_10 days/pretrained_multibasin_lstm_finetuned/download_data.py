"""Download selected original CAMELS members without the entire 3.4 GB ZIP."""
# Model workspace import path.
import sys as _layout_sys
from pathlib import Path as _LayoutPath
for _layout_parent in _LayoutPath(__file__).resolve().parents:
    if (_layout_parent / 'evaluation comparison' / 'common').is_dir():
        _layout_sys.path.insert(0, str(_layout_parent / 'model' / 'model_15 days'))
        _layout_sys.path.insert(0, str(_layout_parent / 'model' / 'model_10 days'))
        _layout_sys.path.insert(0, str(_layout_parent / 'evaluation comparison' / 'common'))
        break

import argparse
import binascii
import hashlib
import json
import struct
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml


def workflow(path):
    path = Path(path).resolve()
    cfg = yaml.safe_load(path.read_text())
    cfg['_root'] = path.parent
    return cfg


def get(url, start=None, end=None):
    headers = {'Accept-Encoding': 'identity'}
    if start is not None:
        headers['Range'] = f'bytes={start}-{end}'
        url += ('&' if '?' in url else '?') + f'part={start}-{end}'
    for attempt in range(3):
        response = requests.get(url, headers=headers, timeout=90, stream=True)
        if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
            response.close()
            time.sleep(2 + attempt)
            continue
        response.raise_for_status()
        if start is not None:
            expected = f'bytes {start}-{end}/'
            if response.status_code != 206 or not response.headers.get('Content-Range', '').startswith(expected):
                response.close()
                raise RuntimeError('Server did not honor the requested byte range; full archive download refused')
        try:
            return response.content
        finally:
            response.close()


def directory(url, size):
    tail = get(url, size - 131072, size - 1)
    position = tail.rfind(b'PK\x05\x06')
    if position < 0:
        raise ValueError('ZIP directory footer missing')
    footer = struct.unpack_from('<4s4H2IH', tail, position)
    length, offset = footer[5:7]
    central = get(url, offset, offset + length - 1)
    entries, cursor = {}, 0
    while cursor < len(central):
        fields = struct.unpack_from('<4s6H3I5H2I', central, cursor)
        if fields[0] != b'PK\x01\x02':
            raise ValueError('Invalid ZIP central directory')
        name_length, extra_length, comment_length = fields[10:13]
        name = central[cursor + 46:cursor + 46 + name_length].decode('utf-8')
        entries[name] = {'method': fields[4], 'crc32': fields[7], 'compressed_size': fields[8],
                         'size': fields[9], 'offset': fields[16]}
        cursor += 46 + name_length + extra_length + comment_length
    return entries


def extract_member(url, name, info):
    start = info['offset']
    block = get(url, start, start + info['compressed_size'] + 8191)
    header = struct.unpack_from('<4s5H3I2H', block)
    if header[0] != b'PK\x03\x04':
        raise ValueError('Invalid ZIP local header')
    begin = 30 + header[9] + header[10]
    compressed = block[begin:begin + info['compressed_size']]
    data = zlib.decompress(compressed, -15) if info['method'] == 8 else compressed
    if info['method'] not in (0, 8) or len(data) != info['size'] or binascii.crc32(data) != info['crc32']:
        raise ValueError(f'ZIP member verification failed: {name}')
    return data


def download(cfg):
    options, root = cfg['sources'], cfg['_root']
    output = (root / options['raw_dir']).resolve()
    output.mkdir(parents=True, exist_ok=True)
    metadata = json.loads(get(options['record_url']))
    (output / 'record_metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    files = {item['key']: item for item in metadata['files']}
    archive = files[options['archive_name']]
    url = archive['links']['self']
    entries = directory(url, archive['size'])
    receipt = {'downloaded_at_utc': datetime.now(timezone.utc).isoformat(),
               'record_url': options['record_url'], 'doi': metadata['metadata'].get('doi'),
               'license': metadata['metadata'].get('license'), 'archive_url': url, 'files': []}
    for name in ('readme.txt', 'camels_name.txt', 'camels_clim.txt', 'camels_topo.txt'):
        target = output / name
        if not target.exists():
            target.write_bytes(get(files[name]['links']['self']))
        receipt['files'].append({'path': str(target), 'url': files[name]['links']['self'],
                                 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    for basin in options['basins']:
        for kind, suffix in [('forcing', f'{basin}_lump_{options["forcing"]}_forcing_leap.txt'),
                             ('streamflow', f'{basin}_streamflow_qc.txt')]:
            matches = [(name, info) for name, info in entries.items() if name.endswith('/' + suffix)
                       and ('/usgs_streamflow/' in name if kind == 'streamflow'
                            else f'/basin_mean_forcing/{options["forcing"]}/' in name)]
            if len(matches) != 1:
                raise ValueError(f'Expected one original member for {basin}/{kind}, found {len(matches)}')
            name, info = matches[0]
            target = output / basin / suffix
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if binascii.crc32(target.read_bytes()) != info['crc32']:
                    raise ValueError(f'Existing raw file differs from original archive: {target}')
            else:
                target.write_bytes(extract_member(url, name, info))
            receipt['files'].append({'path': str(target), 'archive_member': name,
                                     'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), **info})
            (output / 'download_receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
            print(f'{basin}: verified original {kind}, {target.stat().st_size} bytes', flush=True)
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=str(Path(__file__).with_name('config.yaml')))
    arguments = parser.parse_args()
    download(workflow(arguments.config))
