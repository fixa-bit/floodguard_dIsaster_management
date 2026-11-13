"""Continue an existing 30-day checkpoint using config-defined fine-tuning."""
import argparse
from pathlib import Path
from data import load_config
from _training import load_checkpoint, run_training


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=str(Path(__file__).with_name('config.yaml')))
    parser.add_argument('--checkpoint', required=True)
    args = parser.parse_args()
    cfg = load_config(args.config)
    original = load_checkpoint(args.checkpoint)
    if original['config']['data']['forecast_horizon'] != cfg['data']['forecast_horizon']:
        raise ValueError('Horizon transfer requires explicit lead-embedding adaptation; this CLI continues a 30-day model only')
    target = Path(cfg['_root']) / cfg['finetuning']['output_dir'] / f"seed_{cfg['training']['seeds'][0]}" / 'best.pt'
    if target.exists():
        raise FileExistsError('Choose a new fine-tuning output directory')
    print(run_training(cfg, cfg['training']['seeds'][0], initial_checkpoint=args.checkpoint))
