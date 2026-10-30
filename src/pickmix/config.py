'''
pickmix: project configuration schema, kinds table and TOML load/save
'''

# Import external dependencies
import re, tomllib, tomli_w
from pathlib import Path
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Literal

# Kind: one class of particle
class Kind(BaseModel):
    # displayed marker diameter, Angstrom
    marker_a: float = Field(gt=0)
    # extraction box edge, Angstrom; 0 takes the box from the estimator
    box_a: float = Field(default=0.0, ge=0)
    # name in the estimator registry
    estimator: str = 'none'
    # any Qt colour name or #rrggbb
    colour: str = 'yellow'
    # kind whose nearest estimate supplies membrane-normal geometry
    parent: str | None = None
    # how far a pick may sit from the parent's surface and still count as on it
    parent_tolerance_a: float = Field(default=100.0, gt=0)
    # written as rlnAngleTiltPrior when set
    tilt_prior_deg: float | None = None
    # pixel size of the RELION extraction in Angstrom per pixel
    extract_angpix: float = Field(default=10.68, gt=0)

# RingParams: settings of the ring estimator, all lengths in Angstrom
class RingParams(BaseModel):
    # cage radius sweep and ring width
    radius_range_a: tuple[float, float] = (150.0, 500.0)
    radius_step_a: float = 25.0
    ring_sigma_a: float = 30.0
    # background flattening and light smoothing of each projection
    highpass_sigma_a: float = 500.0
    smooth_sigma_a: float = 8.0
    # ring half-width and the background annulus as multiples of the ring radius
    ring_halfwidth_a: float = 40.0
    bg_range: tuple[float, float] = (1.3, 1.8)
    # z slab grown up to walk_max_half_a, stopping after walk_patience steps without a better SNR
    walk_max_half_a: float = 400.0
    walk_patience: int = 3
    # how far the centre may move from the pick in xy, and the slab centre in z
    locate_range_a: float = 200.0
    z_shift_a: float = 100.0
    # box edge as a multiple of the ring diameter when the kind takes its box from the estimator
    box_margin: float = 1.25

# _default_kinds: the single cage kind used when a config has no kinds table
def _default_kinds() -> dict[str, Kind]:
    return {'cage': Kind(marker_a=600.0, estimator='ring')}

# Config: validated project settings
class Config(BaseModel):
    # tomogram locations; denoised_dir None means raw only
    raw_dir: Path
    denoised_dir: Path | None = None
    # stripped from denoised stems so they pair with raw stems
    denoised_suffix: str = ''
    # RELION tomograms star: authoritative for names, unbinned pixel size, binning and tomogram size
    tomograms_star: Path
    # every pickmix output lands here
    out_dir: Path = Path('out')
    # volume read for display, estimation and extraction; falls back to raw when a tomogram has no denoised pair
    source: Literal['raw', 'denoised'] = 'denoised'
    ring: RingParams = Field(default_factory=RingParams)
    # table order sets the 1 to 9 hotkeys
    kinds: dict[str, Kind] = Field(default_factory=_default_kinds)

    # replace: validated copy with some fields swapped
    def replace(self, **changes: object) -> 'Config':
        return Config.model_validate({**self.model_dump(), **changes})

    # _names: kind names become folder names, so keep them plain
    @field_validator('kinds')
    @classmethod
    def _names(cls, kinds: dict[str, Kind]) -> dict[str, Kind]:
        if not kinds:
            raise ValueError('at least one kind is needed')
        for name in kinds:
            if not re.fullmatch(r'[A-Za-z0-9_]+', name):
                raise ValueError(f'kind name {name!r} may only use letters, digits and underscores')
        return kinds

    # _relations: parents must exist and form no cycle, and a passthrough kind needs a box
    @model_validator(mode='after')
    def _relations(self) -> 'Config':
        for name, kind in self.kinds.items():
            if kind.estimator == 'none' and kind.box_a == 0:
                raise ValueError(f'kind {name!r}: estimator "none" needs box_a above 0')
            seen, parent = {name}, kind.parent
            while parent is not None:
                if parent not in self.kinds:
                    raise ValueError(f'kind {name!r}: unknown parent {parent!r}')
                if parent in seen:
                    raise ValueError(f'kind {name!r}: parent chain loops through {parent!r}')
                seen.add(parent)
                parent = self.kinds[parent].parent
        return self

# load_config: read a TOML file into a Config instance, resolving relative paths
def load_config(path: Path) -> Config:
    with open(path, 'rb') as handle:
        config = Config(**tomllib.load(handle))
    base = path.resolve().parent
    fixed = {
        field: base / value
        for field in ('raw_dir', 'denoised_dir', 'tomograms_star', 'out_dir')
        if (value := getattr(config, field)) is not None and not value.is_absolute()
    }
    return config.model_copy(update=fixed)

# save_config: write a Config instance as TOML (leaving None fields empty)
def save_config(config: Config, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'wb') as handle:
        tomli_w.dump(config.model_dump(mode='json', exclude_none=True), handle)
