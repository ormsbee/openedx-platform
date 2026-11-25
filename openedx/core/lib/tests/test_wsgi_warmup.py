"""
Tests for wsgi_warmup.py
"""
import gc
from unittest.mock import call, patch

from django.test import SimpleTestCase
from django.test.utils import override_settings

from openedx.core.lib.wsgi_warmup import GC_THRESHOLDS, warm_up_and_freeze_gc

MODULESTORE = {
    "default": {
        "ENGINE": "xmodule.modulestore.mixed.MixedModuleStore",
        "OPTIONS": {
            "stores": [
                {"NAME": "split", "ENGINE": "xmodule.modulestore.split_mongo.split_draft.DraftVersioningModuleStore"},
            ],
        },
    },
}
CONTENTSTORE = {"ENGINE": "xmodule.contentstore.mongo.MongoContentStore"}


@override_settings(MODULESTORE=MODULESTORE, CONTENTSTORE=CONTENTSTORE)
@patch("openedx.core.lib.wsgi_warmup.import_module")
@patch("django.urls.reverse")
class TestWarmUpAndFreezeGC(SimpleTestCase):
    """
    Test warm_up_and_freeze_gc().
    """

    def setUp(self):
        super().setUp()
        self.original_thresholds = gc.get_threshold()
        self.was_enabled = gc.isenabled()
        gc.disable()  # as the WSGI modules do before they import anything

    def tearDown(self):
        gc.unfreeze()
        gc.set_threshold(*self.original_thresholds)
        if self.was_enabled:
            gc.enable()
        else:
            gc.disable()
        super().tearDown()

    def assert_gc_frozen_and_enabled(self, thresholds=GC_THRESHOLDS):
        assert gc.isenabled()
        assert gc.get_threshold() == thresholds
        assert gc.get_freeze_count() > 0

    def test_warms_up_then_freezes(self, mock_reverse, mock_import_module):
        warm_up_and_freeze_gc()

        mock_reverse.assert_called_once_with("heartbeat")
        assert mock_import_module.call_args_list == [
            call("xmodule.modulestore.mixed"),
            call("xmodule.contentstore.mongo"),
            call("xmodule.modulestore.split_mongo.split_draft"),
        ]
        self.assert_gc_frozen_and_enabled()

    def test_custom_thresholds(self, mock_reverse, mock_import_module):  # pylint: disable=unused-argument
        warm_up_and_freeze_gc(thresholds=(5000, 10, 10))

        self.assert_gc_frozen_and_enabled(thresholds=(5000, 10, 10))

    def test_failed_step_does_not_stop_the_others(self, mock_reverse, mock_import_module):
        mock_reverse.side_effect = RuntimeError("no URLconf")

        with self.assertLogs("openedx.core.lib.wsgi_warmup", level="ERROR") as logs:
            warm_up_and_freeze_gc()

        assert "_load_urls failed" in logs.output[0]
        assert mock_import_module.call_count == 3
        self.assert_gc_frozen_and_enabled()

    def test_failure_still_enables_gc(self, mock_reverse, mock_import_module):  # pylint: disable=unused-argument
        mock_import_module.side_effect = ImportError("no such store")

        with self.assertLogs("openedx.core.lib.wsgi_warmup", level="ERROR") as logs:
            warm_up_and_freeze_gc()

        assert "_import_stores failed" in logs.output[0]
        self.assert_gc_frozen_and_enabled()
