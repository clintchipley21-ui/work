"""Independent checks for a generated XER against a pair of uploaded inputs."""
import csv
import json
import sys
from decimal import Decimal
from pathlib import Path


def read_tables(path):
    # Independent parser to avoid validating writer output with its own parser only.
    data = Path(path).read_bytes()
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = data.decode('cp1252')
    tables, name, fields = {}, None, []
    for line in text.splitlines():
        cells = line.split('\t')
        if cells[0] == '%T':
            name = cells[1]
            tables[name] = []
        elif cells[0] == '%F':
            fields = cells[1:]
        elif cells[0] == '%R':
            assert len(cells) - 1 == len(fields), 'Malformed row width'
            tables[name].append(dict(zip(fields, cells[1:])))
    return tables


def check(lntp_path, engineering_path, output_path, mapping_path=None):
    l, e, o = map(read_tables, [lntp_path, engineering_path, output_path])
    mapping = {}
    if mapping_path:
        with open(mapping_path, encoding='utf-8-sig', newline='') as f:
            mapping = {r['engineering_activity_id']: r['lntp_activity_id'] for r in csv.DictReader(f)}
    lt, et, ot = [{r['task_code']: r for r in tables['TASK']} for tables in [l, e, o]]
    allowed = {'early_start_date', 'early_end_date', 'restart_date', 'reend_date',
               'act_start_date', 'act_end_date', 'remain_drtn_hr_cnt', 'target_work_qty',
               'act_work_qty', 'phys_complete_pct', 'status_code', 'complete_pct_type',
               'target_drtn_hr_cnt', 'remain_work_qty'}
    managed = {mapping.get(c, c) for c in et}
    preserved = updated = 0
    for code, row in lt.items():
        assert code in ot, 'Existing activity removed'
        if code not in managed:
            assert row == ot[code], 'LNTP-only activity changed'
            preserved += 1
        else:
            assert all(v == ot[code][f] for f, v in row.items() if f not in allowed), \
                'Non-approved existing activity fields changed'
            updated += row != ot[code]
    for code, row in et.items():
        dest = mapping.get(code, code)
        assert dest in ot, 'Engineering activity absent from result'
        assert all(ot[dest][f] == row[f] for f in allowed), 'Requested field mismatch'
        # Independently compare all three percentage inputs and numerical values.
        for fields in [('phys_complete_pct',), ('target_drtn_hr_cnt', 'remain_drtn_hr_cnt'),
                       ('act_work_qty', 'remain_work_qty')]:
            assert all(Decimal(ot[dest][f] or 0) == Decimal(row[f] or 0) for f in fields)
    for name, rows in l.items():
        if name != 'TASK':
            assert o[name][:len(rows)] == rows, 'Existing non-TASK records changed: ' + name
    assert len(ot) == len(lt) + len(managed - lt.keys())
    task_ids = {r['task_id'] for r in o['TASK']}
    assert len(task_ids) == len(ot), 'Duplicate internal task IDs'
    wbs_ids = {r['wbs_id'] for r in o['PROJWBS']}
    calendars = {r['clndr_id'] for r in o['CALENDAR']}
    project_id = o['PROJECT'][0]['proj_id']
    for r in o['TASK']:
        assert r['proj_id'] == project_id and r['wbs_id'] in wbs_ids and r['clndr_id'] in calendars
    for r in o['TASKPRED']:
        assert r['task_id'] in task_ids and r['pred_task_id'] in task_ids
        assert r['proj_id'] == r['pred_proj_id'] == project_id
    type_ids = {r['actv_code_type_id'] for r in o['ACTVTYPE']}
    code_ids = {r['actv_code_id'] for r in o['ACTVCODE']}
    for r in o['TASKACTV']:
        assert r['task_id'] in task_ids and r['actv_code_type_id'] in type_ids and r['actv_code_id'] in code_ids
    source_ids = {r['task_id']: mapping.get(r['task_code'], r['task_code']) for r in e['TASK']}
    output_ids = {r['task_id']: r['task_code'] for r in o['TASK']}
    new = managed - lt.keys()
    expected_logic = {(source_ids[r['pred_task_id']], source_ids[r['task_id']],
                       r['pred_type'], Decimal(r['lag_hr_cnt'] or '0')) for r in e['TASKPRED']
                      if source_ids[r['task_id']] in new or source_ids[r['pred_task_id']] in new}
    added_logic = {(output_ids[r['pred_task_id']], output_ids[r['task_id']],
                    r['pred_type'], Decimal(r['lag_hr_cnt'] or '0'))
                   for r in o['TASKPRED'][len(l['TASKPRED']):]}
    assert expected_logic == added_logic, 'New-activity logic mismatch'
    result = dict(matched=len(managed & lt.keys()), updated=updated,
                  preserved_lntp_only=preserved, added_activities=len(new),
                  total_activities=len(ot), preserved_relationships=len(l['TASKPRED']),
                  added_relationships=len(added_logic), all_checks_passed=True)
    print(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    check(*sys.argv[1:])
