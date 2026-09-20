import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtGui import QContextMenuEvent
from PyQt5.QtWidgets import QApplication


def _load_metadata_panel():
    path = Path(__file__).parents[1] / 'views' / 'panels' / 'roi_metadata.py'
    spec = importlib.util.spec_from_file_location('roi_metadata_under_test', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


roi_metadata = _load_metadata_panel()


class SetMetadataForAllTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel = roi_metadata.ROIMetadataPanel()
        self.changes = []
        self.panel.metadata_changed.connect(
            lambda index, metadata: self.changes.append((index, metadata))
        )

    def tearDown(self):
        self.panel.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def set_metadata(self, records, instrument='ZCAM'):
        self.panel.set_rois(
            [{'left_rect': (0, 0, 2, 2), 'metadata': record} for record in records],
            [(255, 0, 0)] * len(records),
            [f'roi {index}' for index in range(len(records))],
            instrument=instrument,
        )

    def select_set_for_all(self, key, source=0, cancel=False):
        editor = self.panel._cards[source]._editors[key]
        self.select_context_action(editor, 'set for all', cancel)

    def select_context_action(self, widget, label, cancel=False):
        def choose_action(menu, _position):
            self.assertEqual([action.text() for action in menu.actions()], [label])
            return None if cancel else menu.actions()[0]

        event = QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(1, 1))
        with patch.object(roi_metadata.QMenu, 'exec_', choose_action):
            QApplication.sendEvent(widget, event)

    def test_zcam_json_edits_control_options_labels_and_dependent_fields(self):
        schema_path = Path(__file__).parents[1] / 'resources' / 'zcam_roi_metadata.json'
        schema = json.loads(schema_path.read_text(encoding='utf-8'))
        fields = {field['key']: field for field in schema['fields']}
        fields['FORMATION']['options'].append('New formation')
        fields['MEMBER']['options']['New formation'] = ['New member']
        schema['fields'].append({
            'key': 'CUSTOM', 'label': 'Custom field', 'options': ['sample'],
            'hints': {'sample': 'Sample label'},
            'visible_when': {'FEATURE': ['rock']},
        })
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'zcam_roi_metadata.json'
            path.write_text(json.dumps(schema), encoding='utf-8')
            with patch.object(roi_metadata, '_resource_path', return_value=str(path)):
                edited_fields = roi_metadata._load_metadata_fields(roi_metadata._ZCAM_SCHEMA_FILE)

        with patch.dict(roi_metadata._INSTRUMENT_METADATA_FIELDS, {'ZCAM': edited_fields}):
            self.set_metadata([{
                'FEATURE': 'rock', 'FORMATION': 'New formation',
                'MEMBER': 'New member', 'CUSTOM': 'sample',
            }])

        card = self.panel._cards[0]
        self.assertEqual(card._editors['FORMATION'].currentData(), 'New formation')
        self.assertEqual(card._editors['MEMBER'].currentData(), 'New member')
        self.assertEqual(card._rows['CUSTOM']._label.text(), 'Custom field')
        self.assertEqual(card._editors['CUSTOM'].currentText(), 'Sample label')
        card.set_field_value('FEATURE', 'soil')
        self.assertTrue(card._rows['CUSTOM'].isHidden())
        self.assertNotIn('CUSTOM', card._metadata)

    def test_group_menu_copies_parents_and_children_preserving_descriptions(self):
        source = {'FEATURE': 'rock', 'FEATURE_SUBTYPE': 'abraded surface',
                  'FORMATION': 'Maaz', 'MEMBER': 'Chal', 'DISTANCE': 'nearfield'}
        self.set_metadata([
            {**source, 'DESCRIPTION': 'source description'},
            {'FEATURE': 'soil', 'GRAIN_SIZE': 'mixed', 'DESCRIPTION': 'keep me'},
            {'FEATURE': 'rock', 'FORMATION': 'Seitah', 'MEMBER': 'Issole', 'FLOAT': 'float'},
        ])

        self.select_context_action(self.panel._cards[0]._title, 'set for all')

        self.assertEqual(self.changes, [
            (1, {**source, 'DESCRIPTION': 'keep me'}), (2, source),
        ])
        for card in self.panel._cards:
            self.assertEqual(card._editors['MEMBER'].currentData(), 'Chal')
            self.assertEqual(card._editors['FEATURE'].currentData(), 'rock')
            self.assertEqual(card._editors['FLOAT'].currentData(), '')
            self.assertTrue(card._rows['GRAIN_SIZE'].isHidden())

    def test_group_menu_copies_blank_states_and_clears_dependent_values(self):
        self.set_metadata([
            {},
            {'FEATURE': 'rock', 'FORMATION': 'Maaz', 'MEMBER': 'Chal',
             'DISTANCE': 'farfield', 'DESCRIPTION': 'keep me'},
        ])

        self.select_context_action(self.panel._cards[0], 'set for all')

        self.assertEqual(self.changes, [(1, {'DESCRIPTION': 'keep me'})])
        target = self.panel._cards[1]
        self.assertTrue(target._rows['MEMBER'].isHidden())
        self.assertEqual(target._editors['FEATURE'].currentData(), '')
        self.assertEqual(target._editors['DISTANCE'].currentData(), '')

    def test_group_menu_cancel_preserves_all_states(self):
        records = [{'FEATURE': 'rock'}, {'FEATURE': 'soil', 'DISTANCE': 'farfield'}]
        self.set_metadata(records)

        self.select_context_action(self.panel._cards[0], 'set for all', cancel=True)

        self.assertEqual(self.changes, [])
        self.assertEqual([card._metadata for card in self.panel._cards], records)

    def test_pancam_group_menu_copies_entire_dropdown_state_from_any_group(self):
        source = {'FEATURE': 'rock', 'FEATURE_SUBTYPE': 'vein', 'TEXTURE': 'massive'}
        self.set_metadata([
            {'FEATURE': 'soil', 'FEATURE_SUBTYPE': 'undisturbed soil', 'DISTANCE': 'farfield'},
            source,
        ], instrument='PCAM')

        self.select_context_action(self.panel._cards[1]._title, 'set for all')

        self.assertEqual(self.changes, [(0, source)])
        target = self.panel._cards[0]
        self.assertEqual(target._editors['FEATURE_SUBTYPE'].currentData(), 'vein')
        self.assertEqual(target._editors['TEXTURE'].currentData(), 'massive')
        self.assertEqual(target._editors['DISTANCE'].currentData(), '')

    def test_context_action_copies_selected_field_and_preserves_other_metadata(self):
        self.set_metadata([
            {'DISTANCE': 'nearfield', 'FEATURE': 'rock'},
            {'DISTANCE': 'farfield', 'FEATURE': 'soil', 'DESCRIPTION': 'keep me'},
            {},
        ])
        source = self.panel._cards[0]._editors['DISTANCE']
        self.assertEqual(source.contextMenuPolicy(), Qt.CustomContextMenu)
        self.assertEqual(source.currentText(), 'nearfield (< 10 m)')

        self.select_set_for_all('DISTANCE')

        self.assertEqual(self.changes, [
            (1, {'DISTANCE': 'nearfield', 'FEATURE': 'soil', 'DESCRIPTION': 'keep me'}),
            (2, {'DISTANCE': 'nearfield'}),
        ])
        for card in self.panel._cards:
            self.assertEqual(card._editors['DISTANCE'].currentData(), 'nearfield')

    def test_cancel_does_not_change_any_roi(self):
        self.set_metadata([{'DISTANCE': 'nearfield'}, {'DISTANCE': 'farfield'}])

        self.select_set_for_all('DISTANCE', cancel=True)

        self.assertEqual(self.changes, [])
        self.assertEqual(self.panel._cards[1]._metadata['DISTANCE'], 'farfield')

    def test_blank_selection_clears_only_that_field(self):
        self.set_metadata([{}, {'DISTANCE': 'farfield', 'DESCRIPTION': 'keep me'}])

        self.select_set_for_all('DISTANCE')

        self.assertEqual(self.changes, [(1, {'DESCRIPTION': 'keep me'})])
        self.assertEqual(self.panel._cards[1]._editors['DISTANCE'].currentData(), '')

    def test_dependent_field_skips_incompatible_parents(self):
        source = {'FEATURE': 'rock', 'FORMATION': 'Maaz', 'MEMBER': 'Chal'}
        compatible = {'FEATURE': 'rock', 'FORMATION': 'Maaz', 'MEMBER': 'Artuby'}
        incompatible = {'FEATURE': 'rock', 'FORMATION': 'Seitah', 'MEMBER': 'Issole'}
        hidden = {'FEATURE': 'soil'}
        self.set_metadata([source, compatible, incompatible, hidden])

        self.select_set_for_all('MEMBER')

        self.assertEqual(self.changes, [(1, source)])
        self.assertEqual(self.panel._cards[2]._metadata, incompatible)
        self.assertEqual(self.panel._cards[3]._metadata, hidden)

    def test_changing_parent_uses_normal_dependent_field_cleanup(self):
        self.set_metadata([
            {'FEATURE': 'soil'},
            {'FEATURE': 'rock', 'FORMATION': 'Maaz', 'MEMBER': 'Chal',
             'FLOAT': 'float', 'FEATURE_SUBTYPE': 'abraded surface', 'DISTANCE': 'farfield'},
        ])

        self.select_set_for_all('FEATURE')

        self.assertEqual(self.changes, [(1, {'FEATURE': 'soil', 'DISTANCE': 'farfield'})])
        target = self.panel._cards[1]
        self.assertTrue(target._rows['FORMATION'].isHidden())
        self.assertEqual(target._editors['FEATURE_SUBTYPE'].currentData(), '')

    def test_pancam_subtype_uses_its_schema_and_skips_incompatible_rois(self):
        source = {'FEATURE': 'rock', 'FEATURE_SUBTYPE': 'vein'}
        incompatible = {'FEATURE': 'soil', 'FEATURE_SUBTYPE': 'undisturbed soil'}
        self.set_metadata([
            {'FEATURE': 'rock', 'FEATURE_SUBTYPE': 'meteorite'},
            source, incompatible,
        ], instrument='PCAM')

        self.select_set_for_all('FEATURE_SUBTYPE', source=1)

        self.assertEqual(self.changes, [(0, source)])
        self.assertEqual(self.panel._cards[2]._metadata, incompatible)


if __name__ == '__main__':
    unittest.main()
