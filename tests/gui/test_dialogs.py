'''
pickmix: tests for gui dialogs
'''

# Import external dependencies
import pytest
from pathlib import Path
from PySide6.QtWidgets import QFormLayout, QLabel
from pytestqt.qtbot import QtBot

# Import internal pickmix objects
from pickmix.config import Kind
from pickmix.gui.dialogs.kind_dialog import DELETED, KindDialog
from pickmix.gui.dialogs.new_project_dialog import NewProjectDialog

# _ok: a check that accepts anything
def _ok(_name: str, _kind: Kind) -> str | None:
    return None

# TestKindDialog: kind dialog
class TestKindDialog:
    # test_values_round_trip: showing a kind and reading it back gives the same kind, including parent and tilt prior
    def test_values_round_trip(self, qtbot: QtBot) -> None:
        kind = Kind(marker_a=40, box_a=200, estimator='ring', colour='#00ff00', parent='cage', parent_tolerance_a=80, tilt_prior_deg=0, extract_angpix=7.5)
        dialog = KindDialog(None, 'green', kind, ['cage'], _ok)
        qtbot.addWidget(dialog)
        assert dialog.values() == ('green', kind)

    # test_defaults_when_adding: a new kind starts as an editable passthrough with no tilt prior
    def test_defaults_when_adding(self, qtbot: QtBot) -> None:
        dialog = KindDialog(None, None, None, [], _ok)
        qtbot.addWidget(dialog)
        assert not dialog.name_edit.isReadOnly() and dialog.delete_button.isHidden()
        dialog.name_edit.setText('yellow')
        assert dialog.values() == ('yellow', Kind(marker_a=100, box_a=100))

    # test_delete_only_when_editing: an existing kind can be deleted, a new one cannot
    def test_delete_only_when_editing(self, qtbot: QtBot) -> None:
        dialog = KindDialog(None, 'cage', Kind(marker_a=600), [], _ok)
        qtbot.addWidget(dialog)
        assert not dialog.delete_button.isHidden()
        dialog.delete_button.click()
        assert dialog.result() == DELETED

    # test_rename: an existing kind's name can be changed, but not to another kind's
    def test_rename(self, qtbot: QtBot) -> None:
        dialog = KindDialog(None, 'cage', Kind(marker_a=600), ['green'], _ok)
        qtbot.addWidget(dialog)
        assert not dialog.name_edit.isReadOnly()
        dialog.name_edit.setText('green')
        dialog.accept()
        assert 'already exists' in dialog.error.text() and dialog.result() == 0
        dialog.name_edit.setText('cage2')
        dialog.accept()
        assert dialog.result() == 1 and dialog.values()[0] == 'cage2'

    # test_labels_have_help: every row is titled from the Kind field with a tooltip
    def test_labels_have_help(self, qtbot: QtBot) -> None:
        dialog = KindDialog(None, None, None, [], _ok)
        qtbot.addWidget(dialog)
        assert dialog.labels['marker_a'].text() == 'Marker diameter (Å)' and dialog.labels['extract_angpix'].text() == 'Extract pixel size (Å/px)'
        assert set(dialog.labels) == {'name', *Kind.model_fields}
        assert all(label.toolTip() for label in dialog.labels.values())

    # test_bad_entries_keep_dialog_open: a bad name, colour or check result is shown and nothing is accepted
    def test_bad_entries_keep_dialog_open(self, qtbot: QtBot) -> None:
        dialog = KindDialog(None, None, None, [], lambda n, k: 'taken' if n == 'cage' else None)
        qtbot.addWidget(dialog)
        dialog.name_edit.setText('bad name')
        dialog.accept()
        assert 'letters' in dialog.error.text() and dialog.result() == 0
        dialog.name_edit.setText('cage')
        dialog.colour_edit.setText('notacolour')
        dialog.accept()
        assert 'not a colour' in dialog.error.text()
        dialog.colour_edit.setText('red')
        dialog.accept()
        assert dialog.error.text() == 'taken' and dialog.result() == 0
        dialog.name_edit.setText('yellow')
        dialog.accept()
        assert dialog.result() == 1

    # test_unregistered_estimator_kept: an estimator the registry does not know survives editing
    def test_unregistered_estimator_kept(self, qtbot: QtBot) -> None:
        dialog = KindDialog(None, 'cage', Kind(marker_a=600, estimator='future_fit'), [], _ok)
        qtbot.addWidget(dialog)
        assert dialog.values()[1].estimator == 'future_fit'

    # test_tilt_prior_optional: the tilt prior is only written when its box is ticked
    def test_tilt_prior_optional(self, qtbot: QtBot) -> None:
        dialog = KindDialog(None, 'cage', Kind(marker_a=600), [], _ok)
        qtbot.addWidget(dialog)
        assert not dialog.tilt_spin.isEnabled() and dialog.values()[1].tilt_prior_deg is None
        dialog.tilt_box.setChecked(True)
        dialog.tilt_spin.setValue(-15)
        assert dialog.values()[1].tilt_prior_deg == -15

    # test_new_name_must_be_free: adding a kind cannot reuse a name, so it never overwrites one
    def test_new_name_must_be_free(self, qtbot: QtBot) -> None:
        dialog = KindDialog(None, None, None, ['cage'], _ok)
        qtbot.addWidget(dialog)
        dialog.name_edit.setText('cage')
        dialog.accept()
        assert 'already exists' in dialog.error.text() and dialog.result() == 0

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
        assert values['name'] is None

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

    # test_name: a typed name is passed on, the placeholder follows the directory
    def test_name(self, qtbot: QtBot) -> None:
        dlg = NewProjectDialog()
        qtbot.addWidget(dlg)
        dlg.add_run('r1', '/data/p1')
        dlg.project_dir.edit.setText('/work/cages')
        dlg.raw_dir.edit.setText('/raw')
        assert dlg.name.placeholderText() == 'cages' and dlg.values()['name'] is None
        dlg.name.setText('  Cage run  ')
        assert dlg.values()['name'] == 'Cage run'

    # test_tooltips: every field has a label that explains itself
    def test_tooltips(self, qtbot: QtBot) -> None:
        dlg = NewProjectDialog()
        qtbot.addWidget(dlg)
        form = dlg.findChild(QFormLayout)
        for row in range(form.rowCount()):
            assert form.itemAt(row, QFormLayout.ItemRole.LabelRole).widget().findChildren(QLabel)[1].toolTip()
        assert dlg.runs.toolTip()
