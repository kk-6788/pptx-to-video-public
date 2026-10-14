import importlib
import tkinter as tk
import unittest
from unittest.mock import patch
from tests import test_narration_project as project_fixtures


class EditorTests(unittest.TestCase):
    setUp = project_fixtures.ProjectTests.setUp
    project = project_fixtures.ProjectTests.project
    def editor(self):
        module = importlib.import_module('narration_editor')
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        project, plans = self.project()
        editor = module.NarrationEditor(root, project)
        editor.withdraw()
        return editor, project

    def test_navigation_saves_and_undo_restores(self):
        editor, project = self.editor()
        editor.text.delete('1.0', 'end')
        editor.text.insert('1.0', 'Edited by user')
        editor.show_page(3)
        self.assertEqual(project.segments[1].text, 'Edited by user')
        editor.show_page(1)
        editor.undo()
        self.assertEqual(project.segments[1].text, 'First')
        self.assertTrue(editor.autosave_path.is_file())
        self.assertNotEqual(editor.autosave_path.parent, self.source.parent)

    def test_stale_rewrite_and_lock_are_rejected(self):
        editor, project = self.editor()
        revision = project.segments[1].revision
        project.update_segment(1, text='newer')
        with self.assertRaises(ValueError): editor.apply_rewrite(1, revision, {'text':'old response'})
        project.update_segment(1, locked=True)
        with self.assertRaises(ValueError): editor.apply_rewrite(1, project.segments[1].revision, {'text':'overwrite'})

    def test_rewrite_preserves_initial_and_records_selections(self):
        editor, project = self.editor()
        editor.apply_rewrite(1, 0, {'text':'Improved', 'warnings':['review'], 'status':'basic'})
        self.assertEqual(project.segments[1].initial_text, 'First')
        self.assertEqual(project.segments[1].text, 'Improved')
        self.assertEqual(project.segments[1].warnings, ['review'])

    def test_locked_identical_rewrite_cannot_change_metadata(self):
        editor, project = self.editor()
        project.update_segment(1, locked=True)
        with self.assertRaises(ValueError):
            editor.apply_rewrite(1, project.segments[1].revision, {'text':'First', 'status':'changed'})

    def test_selection_uses_engine_decision_and_rebuild_instruction(self):
        editor, project = self.editor()
        project.segments[1].units = [{'id':'a','text':'Source 1','decision':'skip'}]
        editor._render_page()
        editor.units.selection_set('0')
        editor.decision.set('讲述')
        editor.change_decision()
        self.assertEqual(project.segments[1].units[0]['decision'], 'read')
        calls=[]
        editor.rewrite = lambda *args: calls.append(args) or {'text':'rebuilt'}
        with patch.object(editor, '_background', side_effect=lambda work, callback: work()):
            editor.request_rewrite('按内容选择重建')
        self.assertEqual(calls[0][1], '按内容选择重建')
        self.assertEqual(calls[0][2][0]['decision'], 'read')
