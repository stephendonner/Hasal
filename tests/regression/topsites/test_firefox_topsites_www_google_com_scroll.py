
from lib.perfBaseTest import PerfBaseTest


class TestSikuli(PerfBaseTest):

    def setUp(self):
        super(TestSikuli, self).setUp()

    def test_firefox_topsites_www_google_com_scroll(self):
        self.round_status = self.sikuli.run_test(self.env.test_name, self.env.output_name, test_target="https://www.google.com/#q=barack+obama", script_dp=self.env.test_script_py_dp)
