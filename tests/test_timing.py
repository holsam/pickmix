'''
pickmix: tests for timing output
'''

# Import external dependencies
import pytest

# Import internal pickmix objects
from pickmix.timing import Timer, timed

# TestTiming: timing hook
class TestTiming:
    # test_off_by_default: nothing is printed unless PICKMIX_TIMING=1
    def test_off_by_default(self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv('PICKMIX_TIMING', raising=False)
        with timed('step'):
            pass
        Timer('t').lap('a')
        assert capsys.readouterr().err == ''

    # test_on: both helpers print their label
    def test_on(self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('PICKMIX_TIMING', '1')
        with timed('load'):
            pass
        timer = Timer('switch')
        timer.lap('contrast')
        err = capsys.readouterr().err
        assert '[timing] load:' in err and '[timing] switch: contrast' in err
