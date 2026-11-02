'''
pickmix: project creation from RELION runs
'''

# Import external dependencies
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

# Import internal pickmix objects
from pickmix.config import Config, load_config, save_config
from pickmix.utils.io import Tomogram, TomogramError, find_tomograms
from pickmix.utils.star import MergeResult, merge_tomograms, read_star_loop

# Project: an open config.toml
@dataclass
class Project:
    path: Path
    config: Config
    names: list[str]
    tomos: dict[str, Tomogram]
    issues: dict[str, TomogramError]

    # update: swap config fields, validated, and write config.toml
    def update(self, **changes: object) -> None:
        config = self.config.replace(**changes)
        save_config(config, self.path)
        self.config = config

# open_project: load a config.toml and discover its tomograms
def open_project(path: Path) -> Project:
    config = load_config(path)
    issues: dict[str, TomogramError] = {}
    tomos = find_tomograms(config, issues=issues)
    names = [row['rlnTomoName'] for row in read_star_loop(config.tomograms_star)]
    return Project(path.resolve(), config, names, tomos, issues)

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
