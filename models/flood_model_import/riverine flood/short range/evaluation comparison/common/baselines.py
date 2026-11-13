"""Shared baseline CLI; implementations/artifacts live in named model folders."""
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
import json
import pickle
from pathlib import Path
import yaml

from data import DataStore, fit_statistics, load_config, public_config, resolve, years
from gradient_boosting.model import GradientBoosting
from persistence.model import Persistence
from climatology.model import Climatology


class Baselines:
    def fit(self, store, stats):
        self.cfg, self.stats = store.cfg, stats
        self.training_years = years(self.cfg['splits']['train'])
        self.components = {'persistence': Persistence(), 'climatology': Climatology().fit(store),
                           'gradient_boosting': GradientBoosting().fit(store, stats)}
        for name, component in self.components.items():
            output = resolve(self.cfg, self.cfg['baselines']['output_dirs'][name])
            output.mkdir(parents=True, exist_ok=True)
            (output / 'model.pkl').write_bytes(pickle.dumps(component))
            (output / 'config.yaml').write_text(yaml.safe_dump(public_config(self.cfg), sort_keys=False))
            (output / 'normalization.json').write_text(json.dumps(stats, indent=2) + '\n')
            (output / 'years.json').write_text(json.dumps({'training_years': self.training_years}, indent=2) + '\n')
        return self

    def predict(self, dataset):
        return {name: component.predict(dataset) for name, component in self.components.items()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=str(Path(__file__).with_name('config.yaml')))
    args = parser.parse_args()
    cfg = load_config(args.config)
    store = DataStore(cfg)
    Baselines().fit(store, fit_statistics(store))
    print('Saved each baseline under its named model folder.')
