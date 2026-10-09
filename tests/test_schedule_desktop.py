import os
import queue
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_update_lntp import task, write_xer
from schedule_desktop import Job, bundled_mapping, completion_text, run_job, validate_job
from update_lntp import UpdateError


class DesktopJobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.lntp = self.root / 'LNTP with spaces.xer'
        self.engineering = self.root / 'Engineering update.xer'
        write_xer(self.lntp, '1', [task('100', '1', 'ENG1'), task('101', '1', 'SITE1')])
        write_xer(self.engineering, '9', [task('500', '9', 'ENG1', phys_complete_pct='50'),
                                         task('501', '9', 'ENG2')])
        self.job = Job(self.lntp, self.engineering, self.root)

    def test_generates_xer_and_all_reports_without_touching_inputs(self):
        originals = [p.read_bytes() for p in [self.lntp, self.engineering]]
        result = run_job(self.job)
        self.assertTrue(result.xer.is_file())
        self.assertEqual(result.xer.name, 'LNTP with spaces_UPDATED.xer')
        for name in ['summary.json', 'field_changes.csv', 'activities.csv', 'added_logic.csv',
                     'warnings.csv', 'percent_comparison.csv']:
            self.assertTrue((result.reports / name).is_file(), name)
        self.assertEqual(result.summary['added_activities'], 1)
        self.assertEqual(result.summary['preserved_lntp_only_activities'], 1)
        self.assertEqual(originals, [p.read_bytes() for p in [self.lntp, self.engineering]])
        self.assertFalse(list(self.root.glob('.lntp-working-*')))

    def test_each_run_has_unique_folder(self):
        first = run_job(self.job)
        original = first.xer.read_bytes()
        second = run_job(self.job)
        self.assertNotEqual(first.folder, second.folder)
        self.assertEqual(first.xer.read_bytes(), original)

    def test_same_file_is_rejected(self):
        with self.assertRaisesRegex(UpdateError, 'two different files'):
            validate_job(Job(self.lntp, self.lntp, self.root))

    def test_hardlinked_same_file_is_rejected(self):
        link = self.root / 'same file.xer'
        os.link(self.lntp, link)
        with self.assertRaisesRegex(UpdateError, 'same file'):
            validate_job(Job(self.lntp, link, self.root))

    def test_non_xer_file_is_rejected(self):
        other = self.root / 'schedule.txt'
        other.write_text('not an XER')
        with self.assertRaisesRegex(UpdateError, '.xer extension'):
            validate_job(Job(other, self.engineering, self.root))

    def test_missing_output_folder_is_rejected(self):
        with self.assertRaisesRegex(UpdateError, 'output folder'):
            validate_job(Job(self.lntp, self.engineering, self.root / 'missing'))

    def test_partial_failed_run_is_cleaned_and_existing_results_preserved(self):
        existing = self.root / 'existing results.txt'
        existing.write_text('keep my work')

        def fail_after_writing(lntp, engineering, xer, reports, *args):
            xer.write_text('partial output')
            reports.mkdir()
            (reports / 'partial.csv').write_text('partial')
            raise UpdateError('simulated export failure')

        with patch('schedule_desktop.export_update', side_effect=fail_after_writing):
            with self.assertRaisesRegex(UpdateError, 'simulated export failure'):
                run_job(self.job)
        self.assertEqual(existing.read_text(), 'keep my work')
        self.assertFalse(list(self.root.glob('.lntp-working-*')))
        self.assertFalse(list(self.root.glob('LNTP_Update_*')))

    def test_mapping_is_applied(self):
        write_xer(self.engineering, '9', [task('500', '9', 'RENAMED', phys_complete_pct='50')])
        mapping = self.root / 'mapping.csv'
        mapping.write_text('engineering_activity_id,lntp_activity_id\nRENAMED,ENG1\n')
        result = run_job(Job(self.lntp, self.engineering, self.root, mapping))
        self.assertEqual(result.summary['added_activities'], 0)
        self.assertEqual(result.summary['matching_activities'], 1)

    def test_add_new_checkbox_respected(self):
        result = run_job(Job(self.lntp, self.engineering, self.root, add_new=False))
        self.assertEqual(result.summary['added_activities'], 0)

    def test_completion_includes_counts_paths_and_review_notes(self):
        result = run_job(self.job)
        result.summary['warning_counts'] = {'completed_activity_reopened': 22,
                                            'actual_date_cleared': 22}
        text = completion_text(result)
        self.assertIn('22 completed activities', text)
        self.assertIn('22 actual-date fields', text)
        self.assertIn(str(result.xer), text)
        self.assertIn('P6 test copy', text)

    def test_packaged_mapping_found(self):
        self.assertEqual(bundled_mapping().name, 'activity_id_mapping.csv')

    def test_gui_worker_communicates_errors_without_tk_calls(self):
        from schedule_gui import ScheduleApp
        app = ScheduleApp.__new__(ScheduleApp)
        app.events = queue.Queue()
        with patch('schedule_gui.run_job', side_effect=UpdateError('bad input')):
            app.worker(self.job)
        self.assertEqual(app.events.get_nowait(), ('error', 'bad input'))


if __name__ == '__main__':
    unittest.main()
