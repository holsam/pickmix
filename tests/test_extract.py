'''
pickmix: tests for box extraction
'''

# Import external dependencies
import mrcfile, numpy as np, pytest
from collections.abc import Callable
from pathlib import Path

# Import internal pickmix objects
from pickmix.config import Kind
from pickmix.estimate.registry import Fit
from pickmix.extract import crop_box, extract_kind
from pickmix.model import Pick
from pickmix.project import open_project

# TestExtract: cropping and writing boxes
class TestExtract:
    # test_crop_pads_with_mean: a crop leaving the volume is padded with the crop's own mean
    def test_crop_pads_with_mean(self) -> None:
        vol = np.arange(4 * 6 * 8, dtype=np.float32).reshape(4, 6, 8)
        box = crop_box(vol, (0, 0, 0), 4)
        assert box.shape == (4, 4, 4)
        assert np.array_equal(box[2:, 2:, 2:], vol[:2, :2, :2])
        assert box[0, 0, 0] == pytest.approx(vol[:2, :2, :2].mean())

    # test_extract_kind: one even box per particle at the reconstruction pixel size
    def test_extract_kind(self, make_config: Callable[..., Path]) -> None:
        project = open_project(make_config())
        kind = Kind(marker_a=20, box_a=21.44)
        fit = Fit(x=4, y=3, z=2, radius_a=10, box_a=21.44, snr=0, z_lo=2, z_hi=2)
        s = extract_kind('yellow', kind, [(Pick(1, 'Position_1_2', 'yellow', 4, 3, 2), fit)], project.tomos, project.config)
        assert s.written == 1 and s.box_px == 4
        path = project.config.out_dir / 'particles' / 'yellow' / 'Position_1_2' / 'Position_1_2_000.mrc'
        with mrcfile.open(path) as mrc:
            expected = np.arange(4 * 6 * 8, dtype=np.float32).reshape(4, 6, 8)[0:4, 1:5, 2:6]
            assert np.array_equal(mrc.data, expected)
            assert float(mrc.voxel_size.x) == pytest.approx(5.36, rel=1e-4)

    # test_nothing: no particles is an error
    def test_nothing(self, make_config: Callable[..., Path]) -> None:
        project = open_project(make_config())
        with pytest.raises(ValueError, match='nothing to extract'):
            extract_kind('yellow', Kind(marker_a=20, box_a=20), [], project.tomos, project.config)
