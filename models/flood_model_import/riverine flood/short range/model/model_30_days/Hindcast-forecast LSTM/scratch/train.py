"""Fit one 30-day LSTM, evaluate it, then stop for user feedback."""
import argparse
import json
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

from data import load_config, public_config, resolve
from _training import run_training
from evaluate import evaluate, save_json, sha256

ROOT = Path(__file__).resolve().parent


class Tee:
    def __init__(self, stream, file):
        self.stream, self.file = stream, file

    def write(self, text):
        self.stream.write(text)
        self.file.write(text)
        self.file.flush()
        return len(text)

    def flush(self):
        self.stream.flush()
        self.file.flush()


def main(config_path):
    cfg = load_config(config_path)
    options = cfg['training']
    if options['ensemble_size'] != 1 or options['seeds'] != [42]:
        raise ValueError('This frozen first experiment uses one seed, 42; use a separate variant for other runs')
    seed = options['seeds'][0]
    output = resolve(cfg, options['output_dir'])
    if (output / f'seed_{seed}/best.pt').exists():
        raise FileExistsError('Existing checkpoint: choose a new output directory to preserve it')
    source = resolve(cfg, cfg['data']['daily_file'])
    before = sha256(source)
    save_json(ROOT / 'protocol.json', {
        'config_sha256': sha256(Path(config_path)), 'configuration_frozen_before_training': True,
        'source_sha256': before, 'forecast_horizon': cfg['data']['forecast_horizon'],
        'training_year_range': cfg['splits']['train'], 'validation_year_range': cfg['splits']['validation'],
        'test_year_range': cfg['splits']['test'], 'checkpoint_selection': 'validation masked pinball only',
        'training_mode': 'scratch', 'no_hpo_search': True, 'one_real_model_only': True,
        'next_model_requires_user_feedback': True, 'discharge_filling': False,
        'forecast_mode': cfg['data']['forecast_mode'], 'archived_weather_forecasts': 'not available',
    })
    with (ROOT / 'training.log').open('x', encoding='utf-8') as log, redirect_stdout(Tee(sys.stdout, log)):
        checkpoint = run_training(cfg, seed)
        save_json(output / 'ensemble.json', {'checkpoints': [str(checkpoint)], 'seeds': [seed]})
        result = evaluate(cfg)
        if sha256(source) != before:
            raise RuntimeError('Source table changed during the experiment')
        (ROOT / 'requirements-lock.txt').write_text(subprocess.check_output([sys.executable, '-m', 'pip', 'freeze'], text=True), encoding='utf-8')
        queue_path = ROOT.parents[1] / 'training_queue.json'
        queue = json.loads(queue_path.read_text(encoding='utf-8'))
        queue[0]['status'] = 'trained and evaluated; awaiting user feedback'
        queue[0]['completed_variant'] = 'scratch'
        queue[0]['selected_epoch'] = result['selected_epoch']
        save_json(queue_path, queue)
        index = ROOT.parents[1] / 'README.md'
        index.write_text(index.read_text(encoding='utf-8').replace('first experiment prepared', queue[0]['status']), encoding='utf-8')
        print('First model complete. No other 30-day model was trained. Awaiting user feedback.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=str(ROOT / 'config.yaml'))
    main(parser.parse_args().config)
