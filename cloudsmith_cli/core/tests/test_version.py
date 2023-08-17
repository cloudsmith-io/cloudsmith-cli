"""Core version utilities - Tests."""

from unittest import TestCase
from unittest.mock import ANY, patch

from .. import utils, version


class TestGetVersion(TestCase):
    def setUp(self):
        patcher = patch.object(utils, "read_file", autospec=True)
        self.addCleanup(patcher.stop)
        self.read_file_mock = patcher.start()

    def test_read_version(self):
        self.read_file_mock.return_value = "1.0.0"
        self.assertEqual("1.0.0", version.get_version())
        self.read_file_mock.assert_called_once_with(ANY, "VERSION")
