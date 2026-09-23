"""Tasks tab: the paid-task website catalog and the Search tasks browser hand-off."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication

from jautomatic.models import DEFAULT_TASK_PLATFORM_NAMES, AppSettings, Profile
from jautomatic.services.task_platforms import task_platform, task_platform_names, task_search_terms
from jautomatic.ui.tasks_tab import TasksTab
from tests.support import WorkspaceTestCase


class TaskPlatformCatalogTests(TestCase):
    def test_catalog_matches_the_settings_default(self):
        self.assertEqual(task_platform_names(), list(DEFAULT_TASK_PLATFORM_NAMES))
        self.assertEqual(len(set(task_platform_names())), len(task_platform_names()))

    def test_every_platform_opens_an_https_site_with_a_hint(self):
        for name in task_platform_names():
            platform = task_platform(name)
            url = platform.search_url('data entry')
            self.assertTrue(url.startswith('https://'), f'{name}: {url}')
            self.assertTrue(platform.label.strip())
            self.assertTrue(platform.hint.strip())
            self.assertTrue(platform.homepage.startswith('https://'))

    def test_query_words_reach_sites_that_support_search(self):
        self.assertIn('q=data+entry', task_platform('upwork').search_url('data entry'))
        self.assertIn('s=web+research', task_platform('oneforma').search_url('web research'))

    def test_clickworker_routes_to_matching_category_pages(self):
        self.assertIn('categorization', task_platform('clickworker').search_url('categorisation'))
        self.assertIn('web-research', task_platform('clickworker').search_url('data entry'))
        self.assertIn('workplace.clickworker.com', task_platform('clickworker').search_url('testing'))

    def test_search_terms_fall_back_to_the_selected_type(self):
        self.assertEqual(task_search_terms('  Data   entry '), 'Data entry')
        self.assertEqual(task_search_terms('', 'Testing'), 'testing')
        self.assertEqual(task_search_terms('', 'All types'), 'micro tasks')

    def test_settings_default_enables_every_website(self):
        self.assertEqual(AppSettings().task_platforms_enabled, list(DEFAULT_TASK_PLATFORM_NAMES))
        self.assertEqual(AppSettings.from_dict({}).task_platforms_enabled, list(DEFAULT_TASK_PLATFORM_NAMES))
        custom = AppSettings.from_dict({'task_platforms_enabled': ['upwork', 'clickworker']})
        self.assertEqual(custom.task_platforms_enabled, ['upwork', 'clickworker'])
        self.assertEqual(AppSettings.from_dict({'task_platforms_enabled': []}).task_platforms_enabled, [])


class TasksTabSearchTests(WorkspaceTestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_tab(self):
        ctx = SimpleNamespace(workspace=self.workspace, settings=AppSettings(), profile=Profile(),
                              save_settings=self.workspace.save_settings, notify=Mock())
        tab = TasksTab(ctx)
        self.addCleanup(tab.close)
        return tab, ctx

    def test_search_button_opens_the_checked_websites(self):
        tab, ctx = self.make_tab()
        self.assertEqual(sorted(tab.platform_boxes), sorted(DEFAULT_TASK_PLATFORM_NAMES))
        for box in tab.platform_boxes.values():
            box.setChecked(False)
        tab.platform_boxes['clickworker'].setChecked(True)
        tab.platform_boxes['upwork'].setChecked(True)
        tab.query.setText('data entry')
        ctx.notify.reset_mock()
        with patch('jautomatic.ui.theme.open_in_browser', side_effect=lambda url: True) as opened:
            tab.search_websites()
        urls = [call.args[0] for call in opened.call_args_list]
        self.assertEqual(len(urls), 2)
        self.assertTrue(any('upwork.com' in url and 'q=data+entry' in url for url in urls), urls)
        self.assertTrue(any('clickworker.com' in url for url in urls), urls)
        message = ctx.notify.call_args.args[0]
        self.assertIn('2', message)
        self.assertIn('data entry', message)

    def test_search_without_a_website_asks_for_one(self):
        tab, ctx = self.make_tab()
        for box in tab.platform_boxes.values():
            box.setChecked(False)
        ctx.notify.reset_mock()
        with patch('jautomatic.ui.theme.open_in_browser') as opened:
            tab.search_websites()
        opened.assert_not_called()
        self.assertIn('Tick at least one', ctx.notify.call_args.args[0])

    def test_website_selection_persists_and_survives_reload(self):
        tab, _ctx = self.make_tab()
        for box in tab.platform_boxes.values():
            box.setChecked(True)
        tab.platform_boxes['mturk'].setChecked(False)
        reloaded = self.workspace.load_settings()
        self.assertNotIn('mturk', reloaded.task_platforms_enabled)
        self.assertIn('clickworker', reloaded.task_platforms_enabled)
        self.assertEqual(len(reloaded.task_platforms_enabled), len(DEFAULT_TASK_PLATFORM_NAMES) - 1)

    def test_profile_suggestions_render_as_website_links(self):
        tab, ctx = self.make_tab()
        self.assertIn('Profile suggestions', tab.recommendations.toPlainText())
        self.assertIn('add your experience', tab.recommendations.toPlainText())
        ctx.profile.skills.append('data entry and records management')
        tab.refresh()
        html = tab.recommendations.toHtml()
        self.assertIn('clickworker.com', html)
        self.assertIn('href=', html)
