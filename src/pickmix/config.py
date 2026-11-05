'''
pickmix: project configuration schema, kinds table and TOML load/save
'''

# Import external dependencies
import re, tomllib, tomli_w
from pathlib import Path
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Literal

# HOTKEYS: number of hotkeys, keys 1 to 9
HOTKEYS: int = 9

# Kind: one class of particle; title and description feed the kind dialog
class Kind(BaseModel):
    # displayed marker diameter, Angstrom
    marker_a: float = Field(gt=0, title='Marker diameter (Å)', description='Diameter of the marker drawn on a pick.')
    # extraction box edge, Angstrom; 0 takes the box from the estimator
    box_a: float = Field(default=0.0, ge=0, title='Box edge (Å)', description='Extraction box edge. 0 takes the box from the estimator.')
    # name in the estimator registry
    estimator: str = Field(default='none', title='Estimator', description='Estimator that fits each pick of this kind.')
    # any Qt colour name or #rrggbb
    colour: str = Field(default='blue', title='Colour', description='Marker colour: a name or hex code (#rrggbb).')
    # kind whose nearest estimate supplies membrane-normal geometry
    parent: str | None = Field(default=None, title='Parent', description='Kind whose nearest estimate supplies membrane-normal geometry.')
    # how far a pick may sit from the parent's surface and still count as on it
    parent_tolerance_a: float = Field(default=100.0, gt=0, title='Parent tolerance (Å)', description='How far a pick may sit from the parent surface and still count as on it.')
    # written as rlnAngleTiltPrior when set
    tilt_prior_deg: float | None = Field(default=None, title='Tilt prior (°)', description='Written as rlnAngleTiltPrior when set, and left out otherwise.')
    # pixel size of the RELION extraction in Angstrom per pixel
    extract_angpix: float = Field(default=10.68, gt=0, title='Extract pixel size (Å/px)', description='Pixel size of the RELION extraction in Å per pixel.')

# RingParams: settings of the ring estimator, all lengths in Angstrom; title and description feed the settings form
class RingParams(BaseModel):
    # cage radius sweep and ring width
    radius_range_a: tuple[float, float] = Field(default=(150.0, 500.0), title='Radius range (Å)', description='Smallest and largest cage radius tried.')
    radius_step_a: float = Field(default=25.0, title='Radius step (Å)', description='Spacing of the radii tried across the range.')
    ring_sigma_a: float = Field(default=30.0, title='Ring width σ (Å)', description='Width of the dark ring template.')
    # background flattening and light smoothing of each projection
    highpass_sigma_a: float = Field(default=500.0, title='High-pass σ (Å)', description='Gaussian width removed from each projection to flatten the background.')
    smooth_sigma_a: float = Field(default=8.0, title='Smoothing σ (Å)', description='Light Gaussian smoothing of each projection.')
    # ring half-width and the background annulus as multiples of the ring radius
    ring_halfwidth_a: float = Field(default=40.0, title='Ring half-width (Å)', description='Half-width of the ring used to score its contrast.')
    bg_range: tuple[float, float] = Field(default=(1.3, 1.8), title='Background annulus (× radius)', description='Inner and outer edge of the background annulus, as multiples of the ring radius.')
    # z slab grown up to walk_max_half_a, stopping after walk_patience steps without a better SNR
    walk_max_half_a: float = Field(default=400.0, title='Max slab half-thickness (Å)', description='The z slab grows up to this half-thickness.')
    walk_patience: int = Field(default=3, title='Walk patience (steps)', description='Growth stops after this many steps without a better SNR.')
    # how far the centre may move from the pick in xy, and the slab centre in z
    locate_range_a: float = Field(default=200.0, title='Locate range (Å)', description='How far the ring centre may move from the pick in xy.')
    z_shift_a: float = Field(default=100.0, title='Z shift (Å)', description='How far the slab centre may move from the pick in z.')
    # box edge as a multiple of the ring diameter when the kind takes its box from the estimator
    box_margin: float = Field(default=1.25, title='Box margin (× diameter)', description='Box edge as a multiple of the ring diameter, for kinds that take their box from the estimator.')

# _default_kinds: the single cage kind used when a config has no kinds table
def _default_kinds() -> dict[str, Kind]:
    return {'cage': Kind(marker_a=600.0, estimator='ring')}

# Config: validated project settings
class Config(BaseModel):
    # project name (shown on Project tab and in window title, None falls back to directory name)
    name: str | None = None
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
    # most memory the slice cache may hold; scrolling is smooth where a whole tomogram fits
    cache_mb: int = Field(default=2048, ge=64, title='Slice cache (MB)', description='Most memory the viewer may use to keep slices of tomograms ready for scrolling.')
    ring: RingParams = Field(default_factory=RingParams)
    kinds: dict[str, Kind] = Field(default_factory=_default_kinds)
    # kind chosen by each of the keys 1 to 9, '' for an unused key
    hotkeys: list[str] = Field(default_factory=list)

    # replace: validated copy with some fields swapped
    def replace(self, **changes: object) -> 'Config':
        if 'kinds' in changes and 'hotkeys' not in changes:
            changes = {**changes, 'hotkeys': []}
        return Config.model_validate({**self.model_dump(), **changes})

    # _blank_name: a blank name is no name
    @field_validator('name')
    @classmethod
    def _blank_name(cls, name: str | None) -> str | None:
        return (name or '').strip() or None

    # _names: kind names become folder names, so keep them plain
    @field_validator('kinds')
    @classmethod
    def _names(cls, kinds: dict[str, Kind]) -> dict[str, Kind]:
        for name in kinds:
            if not re.fullmatch(r'[A-Za-z0-9_]+', name):
                raise ValueError(f'kind name {name!r} may only use letters, digits and underscores')
        return kinds

    # _fill_hotkeys: fill the default, pad to nine slots, and check each names a known kind and is used once
    @model_validator(mode='after')
    def _fill_hotkeys(self) -> 'Config':
        keys = self.hotkeys or [*self.kinds][:HOTKEYS]
        if len(keys) > HOTKEYS:
            raise ValueError(f'at most {HOTKEYS} hotkeys, got {len(keys)}')
        used = [k for k in keys if k]
        for name in used:
            if name not in self.kinds:
                raise ValueError(f'hotkey names unknown kind {name!r}')
        if len(set(used)) != len(used):
            raise ValueError('a kind may only be on one hotkey')
        self.hotkeys = [*keys, *[''] * (HOTKEYS - len(keys))]
        return self

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
