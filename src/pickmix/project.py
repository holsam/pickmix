'''
pickmix: project creation from RELION runs
'''

# Import external dependencies
from collections.abc import Sequence
from pathlib import Path

# Import internal pickmix objects
from pickmix.config import Config, save_config
from pickmix.utils.star import MergeResult, merge_tomograms

# create_project: merge the runs into project_dir and write its config.toml; refuses to overwrite either
def create_project(
    project_dir: Path, runs: Sequence[tuple[str, Path]], tomo_job: str, raw_dir: Path,
    *, denoised_dir: Path | None = None, denoised_suffix: str = '',
) -> tuple[Path, MergeResult]:
    config_path = project_dir / 'config.toml'
    for path in (config_path, project_dir / 'tomograms.star'):
        if path.exists():
            raise FileExistsError(f'{str(path)!r} already exists')
    result = merge_tomograms(runs, tomo_job, project_dir)
    config = Config(
        raw_dir=raw_dir.resolve(),
        denoised_dir=denoised_dir.resolve() if denoised_dir else None,
        denoised_suffix=denoised_suffix,
        tomograms_star=result.star,
    )
    save_config(config, config_path)
    return config_path, result
