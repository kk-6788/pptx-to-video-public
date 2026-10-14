import importlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source.pptx'
        self.source.write_bytes(b'original ppt')

    def project(self):
        module = importlib.import_module('narration_project')
        slides = [NS(index=i, title=f'Page {i}', text_content=f'Source {i}', notes='', content_units=[]) for i in (1, 3)]
        plans = [NS(slide_index=1, slide_indices=[1, 3], narration_by_slide={1:'First',3:'Third'})]
        return module.NarrationProject.from_plans(self.source, slides, plans, {'voice':'test','api_key':'SECRET','nested':{'token':'SECRET','length':'short'}}), plans

    def test_persistence_final_text_and_mute(self):
        project, plans = self.project()
        project.update_segment(1, text='This is edited')
        project.update_segment(3, muted=True)
        output = self.root / 'project.json'
        project.save(output)
        self.assertNotIn('SECRET', output.read_text(encoding='utf-8'))
        reopened = type(project).load(output)
        reopened.validate_source(self.source)
        reopened.apply_to_plans(plans)
        self.assertEqual(plans[0].narration_by_slide, {1:'This is edited',3:''})
        self.assertEqual(plans[0].narration_text, plans[0].subtitle_text)
        self.assertEqual(plans[0].narration_muted_by_slide, {1:False,3:True})
        self.assertEqual(reopened.segments[3].text, 'Third')
        exported = self.root / 'script.md'
        reopened.export_script(exported)
        self.assertIn('This is edited', exported.read_text(encoding='utf-8'))
        self.assertNotIn('Third', exported.read_text(encoding='utf-8'))

    def test_source_change_and_missing_page_rejected(self):
        project, plans = self.project()
        self.source.write_bytes(b'changed')
        with self.assertRaises(ValueError): project.validate_source(self.source)
        with self.assertRaises(ValueError): project.apply_to_plans([NS(slide_index=2, slide_indices=[2])])

    def test_lock_revision_restore_and_explicit_empty(self):
        project, plans = self.project()
        project.update_segment(1, text='')
        self.assertEqual(project.segments[1].revision, 1)
        project.apply_to_plans(plans)
        self.assertEqual(plans[0].narration_by_slide[1], '')
        with self.assertRaises(ValueError): project.update_segment(1, text='late', expected_revision=0)
        project.restore_initial(1)
        self.assertEqual(project.segments[1].text, 'First')
        project.update_segment(1, locked=True)
        with self.assertRaises(ValueError): project.update_segment(1, text='overwrite')

    def test_unknown_schema_rejected(self):
        project, _ = self.project()
        output = self.root / 'project.json'
        project.save(output)
        data=json.loads(output.read_text())
        data['schema_version']=999
        output.write_text(json.dumps(data))
        with self.assertRaises(ValueError): type(project).load(output)

    def test_visual_plans_preserve_grouping_and_prompts(self):
        module = importlib.import_module('narration_project')
        slides = [NS(index=i, title='title', text_content='source', notes='') for i in (1, 3)]
        plan = NS(slide_index=1, slide_indices=[1, 3], image_prompt='original prompt',
                  video_prompt='motion', narration_by_slide={1:'First',3:'Third'}, visual_mode='creative')
        project = module.NarrationProject.from_plans(self.source, slides, [plan])
        output = self.root / 'visual.json'
        project.save(output)
        reopened = module.NarrationProject.load(output)
        reopened.update_segment(3, text='Edited third')
        rebuilt = reopened.build_plans(slides)
        self.assertEqual(len(rebuilt), 1)
        self.assertEqual(rebuilt[0].slide_indices, [1,3])
        self.assertEqual(rebuilt[0].image_prompt, 'original prompt')
        self.assertEqual(rebuilt[0].narration_by_slide[3], 'Edited third')
