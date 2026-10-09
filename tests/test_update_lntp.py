import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from update_lntp import Xer, UpdateError, UPDATE_FIELDS, update, main


TASK_FIELDS = ['task_id', 'proj_id', 'task_code', 'task_name', 'wbs_id', 'clndr_id',
               'rsrc_id', 'guid', 'tmpl_guid', 'task_type', 'duration_type',
               'target_start_date', 'target_end_date', 'cstr_type', 'cstr_date',
               'act_equip_qty', 'remain_equip_qty', *UPDATE_FIELDS]


def task(tid, pid, code, name=None, **overrides):
    r = {f: '' for f in TASK_FIELDS}
    r.update(task_id=tid, proj_id=pid, task_code=code, task_name=name or code,
             wbs_id=pid + '1', clndr_id=pid + '2', guid='keep-' + tid,
             task_type='TT_Task', duration_type='DT_FixedDrtn', status_code='TK_NotStart',
             complete_pct_type='CP_Units', phys_complete_pct='0', target_drtn_hr_cnt='80',
             remain_drtn_hr_cnt='80', act_work_qty='0', remain_work_qty='80', target_work_qty='80',
             act_equip_qty='0', remain_equip_qty='0', target_start_date='2026-01-01 08:00',
             target_end_date='2026-01-10 17:00', cstr_type='CS_MSOA',
             cstr_date='2026-01-01 08:00')
    r.update(overrides)
    return r


def write_xer(path, pid, tasks, logic=(), extra=()):
    tables = [
        ('PROJECT', ['proj_id', 'proj_short_name', 'last_recalc_date'],
         [{'proj_id': pid, 'proj_short_name': 'EXAMPLE', 'last_recalc_date': '2026-01-01 08:00'}]),
        ('CALENDAR', ['clndr_id', 'clndr_name', 'proj_id', 'base_clndr_id', 'clndr_type',
                      'clndr_data', 'day_hr_cnt'],
         [{'clndr_id': pid + '2', 'clndr_name': '5x8', 'proj_id': pid,
           'base_clndr_id': '', 'clndr_type': 'CA_Project', 'clndr_data': 'verified-calendar',
           'day_hr_cnt': '8'}]),
        ('PROJWBS', ['wbs_id', 'proj_id', 'parent_wbs_id', 'proj_node_flag',
                     'wbs_short_name', 'wbs_name', 'obs_id', 'guid', 'tmpl_guid', 'phase_id'],
         [{'wbs_id': pid + '1', 'proj_id': pid, 'parent_wbs_id': 'external-eps',
           'proj_node_flag': 'Y', 'wbs_short_name': 'EXAMPLE', 'wbs_name': 'Example',
           'obs_id': '', 'guid': 'root-' + pid, 'tmpl_guid': '', 'phase_id': ''}]),
        ('TASK', TASK_FIELDS, tasks),
        ('TASKPRED', ['task_pred_id', 'task_id', 'pred_task_id', 'proj_id',
                      'pred_proj_id', 'pred_type', 'lag_hr_cnt', 'comments'], list(logic)),
        *extra,
    ]
    lines = ['ERMHDR\t24.12\t2026-01-01\tProject']
    for name, fields, rows in tables:
        lines.extend(['%T\t' + name, '%F\t' + '\t'.join(fields)])
        for r in rows:
            lines.append('%R\t' + '\t'.join(r.get(f, '') for f in fields))
    lines.append('%E')
    path.write_bytes(('\r\n'.join(lines) + '\r\n').encode('cp1252'))
    return Xer(path)


def relationship(rid, pid, pred, succ, kind='PR_FS', lag='0'):
    return dict(task_pred_id=rid, proj_id=pid, pred_proj_id=pid, pred_task_id=pred,
                task_id=succ, pred_type=kind, lag_hr_cnt=lag, comments='preserve comment')


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.lpath, self.epath = self.root / 'l.xer', self.root / 'e.xer'
        self.old = task('100', '1', 'ENG1', name='LNTP retained name')
        self.other = task('101', '1', 'SITE1')
        self.engineer = task('500', '9', 'ENG1', name='Engineering name',
                             complete_pct_type='CP_Phys', phys_complete_pct='55',
                             status_code='TK_Active', act_start_date='2026-01-03 08:00',
                             target_drtn_hr_cnt='160', remain_drtn_hr_cnt='40',
                             act_work_qty='60', remain_work_qty='40', target_work_qty='120',
                             early_start_date='2026-01-03 08:00',
                             early_end_date='2026-01-12 17:00',
                             restart_date='2026-01-06 08:00', reend_date='2026-01-12 17:00',
                             target_start_date='2026-01-03 08:00')

    def inputs(self, new=True):
        l = write_xer(self.lpath, '1', [self.old, self.other],
                      [relationship('1000', '1', '100', '101')],
                      [('CUSTOM', ['key', 'value'], [{'key': 'x', 'value': 'retain é'}])])
        tasks = [self.engineer] + ([task('501', '9', 'ENG2')] if new else [])
        e = write_xer(self.epath, '9', tasks,
                      [relationship('2000', '9', '500', '501', 'PR_SS', '16')] if new else [])
        return l, e

    def test_allowed_fields_only_and_other_work_untouched(self):
        l, e = self.inputs()
        result, summary, *_ = update(l, e)
        rows = result.table('TASK').unique('task_code')
        self.assertEqual(rows['SITE1'], self.other)
        changed = {f for f in self.old if self.old[f] != rows['ENG1'][f]}
        self.assertLessEqual(changed, set(UPDATE_FIELDS))
        self.assertEqual(rows['ENG1']['task_name'], self.old['task_name'])
        self.assertEqual(rows['ENG1']['guid'], self.old['guid'])
        self.assertEqual(rows['ENG1']['target_start_date'], self.old['target_start_date'])
        self.assertEqual(rows['ENG1']['cstr_type'], self.old['cstr_type'])
        self.assertEqual(result.rows('CUSTOM'), l.rows('CUSTOM'))
        self.assertEqual(summary['preserved_lntp_only_activities'], 1)
        self.assertEqual(l.table('TASK').unique('task_code')['ENG1'], self.old)

    def test_all_three_percentages_have_source_values(self):
        l, e = self.inputs(False)
        result, *_ = update(l, e)
        t = result.rows('TASK')[0]
        self.assertEqual(t['complete_pct_type'], 'CP_Phys')
        self.assertEqual(float(t['phys_complete_pct']), 55)
        self.assertEqual((1 - float(t['remain_drtn_hr_cnt']) / float(t['target_drtn_hr_cnt'])) * 100, 75)
        self.assertEqual(float(t['act_work_qty']) /
                         (float(t['act_work_qty']) + float(t['remain_work_qty'])) * 100, 60)

    def test_new_activity_and_remapped_logic_without_deleting_existing(self):
        l, e = self.inputs()
        result, summary, *_ = update(l, e)
        tasks = result.table('TASK').unique('task_code')
        self.assertNotEqual(tasks['ENG2']['task_id'], '501')
        self.assertEqual(tasks['ENG2']['proj_id'], '1')
        self.assertEqual(tasks['ENG2']['wbs_id'], '11')
        self.assertEqual(tasks['ENG2']['clndr_id'], '12')
        self.assertEqual(result.rows('TASKPRED')[0], l.rows('TASKPRED')[0])
        edge = result.rows('TASKPRED')[1]
        self.assertEqual(edge['task_id'], tasks['ENG2']['task_id'])
        self.assertEqual(edge['pred_task_id'], '100')
        self.assertEqual(edge['lag_hr_cnt'], '16')
        self.assertEqual(edge['pred_type'], 'PR_SS')
        self.assertEqual(summary['added_relationships'], 1)

    def test_repeat_update_is_byte_identical(self):
        l, e = self.inputs()
        first, *_ = update(l, e)
        second, summary, *_ = update(first, e)
        self.assertEqual(first.encoded(), second.encoded())
        self.assertEqual(summary['added_activities'], 0)
        self.assertEqual(summary['updated_activities'], 0)
        self.assertEqual(summary['added_relationships'], 0)

    def test_existing_engineering_logic_is_not_replaced(self):
        l, e = self.inputs(False)
        # Changed engineering link between matching activities must be ignored.
        e.rows('TASK').append(task('501', '9', 'SITE1'))
        e.rows('TASKPRED').append(relationship('2000', '9', '501', '500', 'PR_FF', '32'))
        result, *_ = update(l, e)
        self.assertEqual(result.rows('TASKPRED'), l.rows('TASKPRED'))

    def test_duplicate_activity_code_fails(self):
        l, e = self.inputs()
        e.rows('TASK')[1]['task_code'] = 'ENG1'
        with self.assertRaisesRegex(UpdateError, 'duplicate task_code'):
            update(l, e)

    def test_explicit_mapping_preserves_lntp_id(self):
        l, e = self.inputs(False)
        e.rows('TASK')[0]['task_code'] = 'RENAMED'
        result, summary, *_ = update(l, e, {'RENAMED': 'ENG1'})
        self.assertEqual(summary['added_activities'], 0)
        self.assertEqual(result.rows('TASK')[0]['task_code'], 'ENG1')
        self.assertEqual(result.rows('TASK')[0]['task_id'], '100')

    def test_ambiguous_mapping_fails(self):
        l, e = self.inputs()
        with self.assertRaisesRegex(UpdateError, 'Multiple engineering'):
            update(l, e, {'ENG2': 'ENG1'})

    def test_resource_loaded_input_fails_without_corrupting_totals(self):
        l, e = self.inputs()
        from update_lntp import Table
        e.tables['TASKRSRC'] = Table('TASKRSRC', ['task_id'], [{'task_id': '500'}])
        with self.assertRaisesRegex(UpdateError, 'TASKRSRC'):
            update(l, e)

    def test_external_new_logic_fails(self):
        l, e = self.inputs()
        e.rows('TASKPRED')[0]['pred_proj_id'] = '77'
        with self.assertRaisesRegex(UpdateError, 'external-project logic'):
            update(l, e)

    def test_actual_clear_is_reported(self):
        l, e = self.inputs(False)
        l.rows('TASK')[0].update(status_code='TK_Complete', act_end_date='2026-01-05 17:00')
        result, summary, *_, warnings = update(l, e)
        self.assertEqual(result.rows('TASK')[0]['act_end_date'], '')
        self.assertEqual(summary['warning_counts']['actual_date_cleared'], 1)
        self.assertEqual(summary['warning_counts']['completed_activity_reopened'], 1)

    def test_round_trip_preserves_bytes_and_encoding(self):
        l, _ = self.inputs()
        self.assertEqual(l.encoded(), self.lpath.read_bytes())

    def test_bad_row_width_fails(self):
        self.lpath.write_text('ERMHDR\t24\n%T\tTASK\n%F\ta\tb\n%R\tx\n%E\n')
        with self.assertRaisesRegex(UpdateError, 'row width'):
            Xer(self.lpath)

    def test_multiple_projects_fails(self):
        l, e = self.inputs()
        e.rows('PROJECT').append({'proj_id': '77'})
        with self.assertRaisesRegex(UpdateError, 'exactly one project'):
            update(l, e)

    def test_no_add_new_preserves_count_and_existing_links(self):
        l, e = self.inputs()
        result, summary, *_ = update(l, e, add_new=False)
        self.assertEqual(len(result.rows('TASK')), 2)
        self.assertEqual(summary['added_activities'], 0)
        self.assertEqual(result.rows('TASKPRED'), l.rows('TASKPRED'))

    def test_cli_dry_run_reports_without_xer(self):
        self.inputs()
        output = self.root / 'updated.xer'
        self.assertEqual(main(['--lntp', str(self.lpath), '--engineering', str(self.epath),
                               '--output', str(output), '--dry-run']), 0)
        self.assertFalse(output.exists())
        self.assertTrue(output.with_suffix('.reports').joinpath('summary.json').exists())

    def test_cli_never_overwrites_inputs(self):
        self.inputs()
        previous = self.lpath.read_bytes()
        self.assertEqual(main(['--lntp', str(self.lpath), '--engineering', str(self.epath),
                               '--output', str(self.lpath)]), 1)
        self.assertEqual(self.lpath.read_bytes(), previous)


if __name__ == '__main__':
    unittest.main()
