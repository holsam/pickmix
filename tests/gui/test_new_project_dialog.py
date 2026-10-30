'''
pickmix: tests for the new project dialog
'''

# Import external dependencies
import pytest
from pathlib import Path
from pytestqt.qtbot import QtBot

# Import internal pickmix objects
from pickmix.gui.new_project_dialog import NewProjectDialog

# TestNewProjectDialog: project creation dialog
class TestNewProjectDialog:
    # test_values: filled fields become create_project arguments
    def test_values(self, qtbot: QtBot) -> None:
        dlg = NewProjectDialog()
        qtbot.addWidget(dlg)
        dlg.add_run('r1', '/data/p1')
        dlg.project_dir.edit.setText('/proj')
        dlg.raw_dir.edit.setText('/raw')
        values = dlg.values()
        assert values['runs'] == [('r1', Path('/data/p1'))]
        assert values['project_dir'] == Path('/proj')
        assert values['denoised_dir'] is None
        assert values['denoised_suffix'] == '.denoised'

    # test_validation: missing runs and directories give readable errors
    def test_validation(self, qtbot: QtBot) -> None:
        dlg = NewProjectDialog()
        qtbot.addWidget(dlg)
        with pytest.raises(ValueError, match='at least one run'):
            dlg.values()
        dlg.add_run('r1', '/data/p1')
        with pytest.raises(ValueError, match='project directory'):
            dlg.values()
        dlg.accept()
        assert 'project directory' in dlg.error.text()
        assert dlg.result() == 0
