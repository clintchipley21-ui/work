#!/usr/bin/env python3
"""Conservative P6 XER update. Standard library only; Python 3.10 or newer."""
from __future__ import annotations

import argparse
import base64
import copy
import csv
import hashlib
import json
import sys
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path


# P6 Start/Finish are composite fields. Planned dates, late dates, constraints,
# calendars and float on EXISTING activities are deliberately not overwritten.
UPDATE_FIELDS = (
    'early_start_date', 'early_end_date', 'restart_date', 'reend_date',
    'act_start_date', 'act_end_date', 'remain_drtn_hr_cnt',
    'target_work_qty', 'act_work_qty', 'phys_complete_pct',
    'status_code', 'complete_pct_type', 'target_drtn_hr_cnt', 'remain_work_qty',
)
PERCENT_SUPPORT = {'complete_pct_type', 'target_drtn_hr_cnt', 'remain_work_qty'}
REQUIRED_TASK_FIELDS = {'task_id', 'proj_id', 'task_code', 'task_name', 'wbs_id',
                        'clndr_id', *UPDATE_FIELDS}


class UpdateError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise UpdateError(message)


def new_guid():
    return base64.b64encode(uuid.uuid4().bytes_le).decode('ascii').rstrip('=')


def number(value):
    try:
        result = Decimal(value or '0')
        require(result.is_finite(), f'Invalid non-finite number: {value!r}')
        return result
    except InvalidOperation as exc:
        raise UpdateError(f'Invalid numeric value: {value!r}') from exc


@dataclass
class Table:
    name: str
    fields: list[str]
    rows: list[dict[str, str]] = field(default_factory=list)
    raw_header: str = ''
    raw_rows: list[tuple[tuple[str, ...], str]] = field(default_factory=list)

    def unique(self, key):
        result = {}
        for row in self.rows:
            value = row.get(key, '')
            require(value, f'{self.name}: blank {key}')
            require(value not in result, f'{self.name}: duplicate {key} {value!r}')
            result[value] = row
        return result


class Xer:
    """Preserve original header, table order, encoding and unchanged row text."""
    def __init__(self, path, encoding=None):
        self.path = Path(path)
        self.data = self.path.read_bytes()
        if encoding:
            self.encoding = encoding
        elif self.data.startswith(b'\xef\xbb\xbf'):
            self.encoding = 'utf-8-sig'
        else:
            try:
                self.data.decode('utf-8')
                self.encoding = 'utf-8'
            except UnicodeDecodeError:
                self.encoding = 'cp1252'
        try:
            text = self.data.decode(self.encoding)
        except UnicodeDecodeError as exc:
            raise UpdateError(f'{self.path.name}: cannot decode; use --encoding') from exc
        self.newline = '\r\n' if '\r\n' in text else '\n'
        self.parts = []
        self.tables = {}
        table = None
        saw_end = False
        for line_no, raw in enumerate(text.splitlines(keepends=True), 1):
            cells = raw.rstrip('\r\n').split('\t')
            tag = cells[0]
            if line_no == 1:
                require(tag == 'ERMHDR', f'{self.path.name}: not a P6 XER')
            if tag == '%T':
                require(not saw_end and len(cells) == 2, f'Invalid %T at line {line_no}')
                require(cells[1] not in self.tables, f'Duplicate table {cells[1]}')
                table = Table(cells[1], [])
                self.tables[table.name] = table
                self.parts.append(table)
                table.raw_header = raw
            elif tag == '%F':
                require(table is not None and not table.fields,
                        f'Unexpected %F at line {line_no}')
                table.fields = cells[1:]
                require(len(set(table.fields)) == len(table.fields),
                        f'Duplicate columns in {table.name}')
                table.raw_header += raw
            elif tag == '%R':
                require(table is not None and table.fields, f'Unexpected %R at {line_no}')
                require(len(cells) - 1 == len(table.fields),
                        f'{self.path.name}:{line_no}: row width differs from schema')
                table.rows.append(dict(zip(table.fields, cells[1:])))
                table.raw_rows.append((tuple(cells[1:]), raw))
            else:
                if tag == '%E':
                    require(not saw_end, 'Duplicate %E')
                    saw_end = True
                    table = None
                elif tag.startswith('%'):
                    raise UpdateError(f'Unsupported XER marker {tag!r} at {line_no}')
                self.parts.append(raw)
        require(saw_end, f'{self.path.name}: missing %E terminator')
        require('PROJECT' in self.tables and 'TASK' in self.tables,
                f'{self.path.name}: missing PROJECT or TASK')

    def table(self, name):
        require(name in self.tables, f'{self.path.name}: missing {name} table')
        return self.tables[name]

    def rows(self, name):
        return self.tables[name].rows if name in self.tables else []

    def ensure_table(self, name, source):
        if name not in self.tables:
            require(name in source.tables, f'Source is missing required {name}')
            t = Table(name, list(source.table(name).fields))
            self.tables[name] = t
            # Insert in source dependency order, before the first common successor.
            source_names = list(source.tables)
            successors = set(source_names[source_names.index(name) + 1:])
            position = next((i for i, p in enumerate(self.parts)
                             if isinstance(p, Table) and p.name in successors),
                            next(i for i, p in enumerate(self.parts)
                                 if isinstance(p, str) and p.startswith('%E')))
            self.parts.insert(position, t)
        return self.tables[name]

    def encoded(self):
        chunks = []
        for part in self.parts:
            if isinstance(part, str):
                chunks.append(part)
                continue
            chunks.append(part.raw_header or (
                '%T\t' + part.name + self.newline +
                '%F\t' + '\t'.join(part.fields) + self.newline))
            for i, row in enumerate(part.rows):
                values = tuple(row.get(f, '') for f in part.fields)
                if i < len(part.raw_rows) and values == part.raw_rows[i][0]:
                    chunks.append(part.raw_rows[i][1])
                else:
                    require(all('\t' not in v and '\n' not in v and '\r' not in v
                                for v in values), f'{part.name}: invalid tab/newline in value')
                    chunks.append('%R\t' + '\t'.join(values) + self.newline)
        try:
            return ''.join(chunks).encode(self.encoding)
        except UnicodeEncodeError as exc:
            raise UpdateError('Source text cannot be represented in LNTP encoding. '
                              'Use --encoding utf-8 only if both input files are UTF-8.') from exc


def one_project(xer):
    projects = xer.table('PROJECT').unique('proj_id')
    require(len(projects) == 1,
            f'{xer.path.name}: export exactly one project (found {len(projects)})')
    project = next(iter(projects.values()))
    require(REQUIRED_TASK_FIELDS <= set(xer.table('TASK').fields),
            f'{xer.path.name}: missing required TASK columns')
    tasks = xer.table('TASK').unique('task_id')
    xer.table('TASK').unique('task_code')
    require(all(t['proj_id'] == project['proj_id'] for t in tasks.values()),
            'TASK rows outside the selected project')
    return project


def wbs_paths(xer, proj_id):
    rows = xer.table('PROJWBS').unique('wbs_id')
    roots = [r for r in rows.values() if r['proj_id'] == proj_id
             and r['proj_node_flag'] == 'Y']
    require(len(roots) == 1, 'Expected one project WBS root')
    root = roots[0]
    paths, active = {}, set()

    def visit(wid):
        if wid in paths:
            return paths[wid]
        require(wid in rows, f'Missing WBS parent {wid}')
        require(wid not in active, 'Cycle in WBS hierarchy')
        active.add(wid)
        row = rows[wid]
        require(row['proj_id'] == proj_id, 'WBS belongs to another project')
        result = () if wid == root['wbs_id'] else (
            visit(row['parent_wbs_id']) + (row['wbs_short_name'],))
        active.remove(wid)
        paths[wid] = result
        return result

    for wid in rows:
        visit(wid)
    require(len(set(paths.values())) == len(paths), 'Ambiguous duplicate WBS code paths')
    return rows, paths, root


class Dependencies:
    """Add only definitions needed by NEW activities; never modify existing ones."""
    KEYS = {'CALENDAR': 'clndr_id', 'RSRC': 'rsrc_id', 'CURRTYPE': 'curr_id',
            'OBS': 'obs_id', 'LOCATION': 'location_id', 'ACTVTYPE': 'actv_code_type_id',
            'ACTVCODE': 'actv_code_id', 'UDFTYPE': 'udf_type_id'}

    def __init__(self, target, source, target_project, source_project):
        self.target, self.source = target, source
        self.tp, self.sp = target_project, source_project
        self.cache = {}
        self.active = set()
        self.added = Counter()
        self.sw, self.spaths, self.sroot = wbs_paths(source, self.sp)
        self.tw, self.tpaths, self.troot = wbs_paths(target, self.tp)
        self.wmap = {wid: next((t for t, p in self.tpaths.items() if p == path), None)
                     for wid, path in self.spaths.items()}

    def allocate(self, name, key):
        # Include source IDs to avoid accidental collisions with external references.
        ids = [r.get(key, '') for x in (self.target, self.source) for r in x.rows(name)]
        require(all(not v or v.isdecimal() for v in ids), f'Non-numeric {name}.{key}')
        return str(max([int(v) for v in ids if v] + [0]) + 1)

    def append(self, name, row):
        t = self.target.ensure_table(name, self.source)
        lost = [k for k, v in row.items() if v and k not in t.fields]
        require(not lost, f'Cannot represent new {name} columns: {lost}')
        t.rows.append({f: row.get(f, '') for f in t.fields})
        self.added[name] += 1

    def wbs(self, wid):
        require(wid in self.sw, f'Missing source WBS {wid}')
        if self.wmap[wid]:
            return self.wmap[wid]
        s = dict(self.sw[wid])
        require(not s.get('phase_id'), 'New WBS uses unsupported PHASE reference')
        parent = self.wbs(s['parent_wbs_id'])
        parent_row = next(r for r in self.target.rows('PROJWBS') if r['wbs_id'] == parent)
        s.update(wbs_id=self.allocate('PROJWBS', 'wbs_id'), proj_id=self.tp,
                 parent_wbs_id=parent, obs_id=parent_row.get('obs_id', ''),
                 guid=new_guid(), tmpl_guid='')
        self.append('PROJWBS', s)
        self.wmap[wid] = s['wbs_id']
        return s['wbs_id']

    def definition(self, name, sid):
        if not sid:
            return ''
        key = self.KEYS[name]
        cache_key = (name, sid)
        if cache_key in self.cache:
            return self.cache[cache_key]
        require(cache_key not in self.active, f'Cycle in {name} definitions')
        self.active.add(cache_key)
        sr = self.source.table(name).unique(key)
        require(sid in sr, f'Missing source {name}.{key}={sid}')
        s = dict(sr[sid])
        mapped = dict(s)
        if name == 'CALENDAR':
            require(not s.get('proj_id') or s['proj_id'] == self.sp,
                    'Calendar belongs to another source project')
            mapped['proj_id'] = self.tp if s.get('proj_id') else ''
            mapped['base_clndr_id'] = self.definition(name, s.get('base_clndr_id', ''))
            semantic = ['clndr_name', 'clndr_type', 'proj_id', 'base_clndr_id',
                        'day_hr_cnt', 'week_hr_cnt', 'month_hr_cnt', 'year_hr_cnt',
                        'rsrc_private', 'clndr_data']
        elif name == 'CURRTYPE':
            semantic = [f for f in self.source.table(name).fields if f != key]
        elif name == 'LOCATION':
            semantic = [f for f in self.source.table(name).fields if f != key]
        elif name == 'OBS':
            mapped['parent_obs_id'] = self.definition(name, s.get('parent_obs_id', ''))
            semantic = ['obs_name', 'parent_obs_id']
        elif name == 'RSRC':
            for unsupported in ['role_id', 'shift_id', 'user_id', 'unit_id']:
                require(not s.get(unsupported), f'New resource uses unsupported {unsupported}')
            mapped['parent_rsrc_id'] = self.definition(name, s.get('parent_rsrc_id', ''))
            mapped['clndr_id'] = self.definition('CALENDAR', s.get('clndr_id', ''))
            mapped['curr_id'] = self.definition('CURRTYPE', s.get('curr_id', ''))
            mapped['pobs_id'] = self.definition('OBS', s.get('pobs_id', ''))
            mapped['location_id'] = self.definition('LOCATION', s.get('location_id', ''))
            semantic = ['rsrc_short_name', 'parent_rsrc_id', 'rsrc_type']
        elif name == 'ACTVTYPE':
            require(not s.get('proj_id') or s['proj_id'] == self.sp,
                    'Activity code type belongs to another project')
            mapped['proj_id'] = self.tp if s.get('proj_id') else ''
            # Project-scoped types are identified by project/name, not a stale
            # root WBS reference present in some versions of the XER exporter.
            mapped['wbs_id'] = (self.wbs(s['wbs_id']) if s.get('wbs_id')
                                and s.get('actv_code_type_scope') == 'AS_EPS' else '')
            semantic = ['actv_code_type', 'actv_code_type_scope', 'proj_id']
            if s.get('actv_code_type_scope') == 'AS_EPS':
                semantic.append('wbs_id')
        elif name == 'ACTVCODE':
            mapped['actv_code_type_id'] = self.definition('ACTVTYPE', s['actv_code_type_id'])
            mapped['parent_actv_code_id'] = self.definition(name, s.get('parent_actv_code_id', ''))
            semantic = ['actv_code_type_id', 'short_name', 'parent_actv_code_id']
        else:  # UDFTYPE
            semantic = ['table_name', 'udf_type_name', 'udf_type_label', 'logical_data_type']
        matches = [r for r in self.target.rows(name)
                   if all(r.get(f, '') == mapped.get(f, '') for f in semantic)]
        require(len(matches) <= 1, f'Ambiguous destination {name} definition for {sid}')
        if matches:
            tid = matches[0][key]
        else:
            # Resource short names and code/UDF names identify shared P6 dictionaries.
            # Refuse incompatible reuse rather than silently modifying global definitions.
            collision_fields = {'RSRC': ['rsrc_short_name'], 'CURRTYPE': ['curr_short_name'],
                                'ACTVTYPE': ['actv_code_type', 'actv_code_type_scope', 'proj_id'],
                                'ACTVCODE': ['actv_code_type_id', 'short_name'],
                                'UDFTYPE': ['table_name', 'udf_type_name']}.get(name)
            if collision_fields:
                require(not any(all(r.get(f, '') == mapped.get(f, '') for f in collision_fields)
                                for r in self.target.rows(name)),
                        f'Incompatible existing {name} definition for source ID {sid}')
            tid = self.allocate(name, key)
            mapped[key] = tid
            if 'guid' in mapped:
                mapped['guid'] = new_guid()
            self.append(name, mapped)
        self.cache[cache_key] = tid
        self.active.remove(cache_key)
        return tid


def load_mapping(path):
    if not path:
        return {}
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        require({'engineering_activity_id', 'lntp_activity_id'} <= set(reader.fieldnames or []),
                'Mapping CSV needs engineering_activity_id,lntp_activity_id columns')
        result = {}
        for row in reader:
            s, t = row['engineering_activity_id'], row['lntp_activity_id']
            require(s and t and s not in result, 'Blank or duplicate mapping CSV activity ID')
            result[s] = t
        require(len(set(result.values())) == len(result), 'Mapping is not one-to-one')
        return result


def calculated_percent(task):
    original = number(task.get('target_drtn_hr_cnt', ''))
    remaining = number(task.get('remain_drtn_hr_cnt', ''))
    actual_units = number(task.get('act_work_qty', '')) + number(task.get('act_equip_qty', ''))
    remaining_units = number(task.get('remain_work_qty', '')) + number(task.get('remain_equip_qty', ''))
    # Milestone/zero denominator display can depend on status in P6.
    duration = (original - remaining) / original * 100 if original else (
        Decimal(100) if task.get('status_code') == 'TK_Complete' else Decimal(0))
    units = actual_units / (actual_units + remaining_units) * 100 if actual_units + remaining_units else (
        Decimal(100) if task.get('status_code') == 'TK_Complete' else Decimal(0))
    return {'physical': str(number(task.get('phys_complete_pct', ''))),
            'duration': str(duration), 'units': str(units)}


def update(target, source, mapping=None, add_new=True, percent_mode='source'):
    tp, sp = one_project(target), one_project(source)
    require(percent_mode in {'source', 'preserve'}, 'Invalid percentage mode')
    before = copy.deepcopy(target)
    target = copy.deepcopy(target)
    # Never change inputs or the project identity/settings/data date.
    dep = Dependencies(target, source, tp['proj_id'], sp['proj_id'])
    lt = target.table('TASK').unique('task_code')
    st = source.table('TASK').unique('task_code')
    mapping = mapping or {}
    require(all(s in st and t in lt for s, t in mapping.items()),
            'Mapping references an activity not present in the inputs')
    destinations = {s: mapping.get(s, s) for s in st}
    require(len(set(destinations.values())) == len(destinations),
            'Multiple engineering activities map to the same LNTP Activity ID')
    managed_source_ids = {r['task_id'] for c, r in st.items()
                          if destinations[c] in lt or add_new}
    managed_target_ids = {lt[destinations[c]]['task_id'] for c in st if destinations[c] in lt}
    for xer, managed in [(source, managed_source_ids), (target, managed_target_ids)]:
        require(not any(r.get('task_id') in managed for r in xer.rows('TASKRSRC')),
                'Managed activities have TASKRSRC resource assignments. This version updates '
                'activity-level labor totals only; assignment-level merging is required for '
                'this export. No output was written.')
    for c, row in st.items():
        if row['task_id'] not in managed_source_ids:
            continue
        # Units % Complete also uses nonlabor units; do not silently copy equipment.
        require(all(number(row.get(f, '')) == 0 for f in ['act_equip_qty', 'remain_equip_qty']),
                f'{c}: nonlabor units affect Units % Complete; unsupported in labor-only update')
        if destinations[c] in lt:
            require(all(number(lt[destinations[c]].get(f, '')) == 0
                        for f in ['act_equip_qty', 'remain_equip_qty']),
                    f'{c}: LNTP nonlabor units affect Units % Complete')

    changes, activities, warnings, taskmap, new_ids = [], [], [], {}, set()
    changed = matched = 0
    if tp.get('last_recalc_date') != sp.get('last_recalc_date'):
        warnings.append({'type': 'data_date_difference', 'activity_id': '',
                         'message': f"LNTP data date {tp.get('last_recalc_date')} retained; "
                                    f"engineering data date {sp.get('last_recalc_date')}"})
    for code, s in st.items():
        dest_code = destinations[code]
        if dest_code in lt:
            matched += 1
            t = lt[dest_code]
            old = dict(t)
            fields = [f for f in UPDATE_FIELDS
                      if percent_mode == 'source' or f not in PERCENT_SUPPORT]
            for f in fields:
                if t[f] != s[f]:
                    changes.append({'activity_id': dest_code, 'engineering_activity_id': code,
                                    'field': f, 'before': t[f], 'after': s[f]})
                    t[f] = s[f]
            if t != old:
                changed += 1
            action = 'UPDATED' if t != old else 'UNCHANGED'
            for f in ['act_start_date', 'act_end_date']:
                if old[f] and not s[f]:
                    warnings.append({'type': 'actual_date_cleared', 'activity_id': dest_code,
                                     'message': f'{f}: {old[f]} -> blank in engineering'})
                elif old[f] and s[f] and old[f] != s[f]:
                    warnings.append({'type': 'actual_date_changed', 'activity_id': dest_code,
                                     'message': f'{f}: {old[f]} -> {s[f]}'})
            if old['status_code'] == 'TK_Complete' and s['status_code'] != 'TK_Complete':
                warnings.append({'type': 'completed_activity_reopened', 'activity_id': dest_code,
                                 'message': 'Engineering changed completed activity to ' + s['status_code']})
            if old['task_name'] != s['task_name']:
                warnings.append({'type': 'name_difference', 'activity_id': dest_code,
                                 'message': 'LNTP name retained; engineering name: ' + s['task_name']})
            if percent_mode == 'preserve' and calculated_percent(t) != calculated_percent(s):
                warnings.append({'type': 'percent_mismatch', 'activity_id': dest_code,
                                 'message': 'Preserved LNTP percentage basis; calculated percentages differ'})
            if t.get('clndr_id'):
                sc = source.table('CALENDAR').unique('clndr_id').get(s['clndr_id'])
                tc = target.table('CALENDAR').unique('clndr_id').get(t['clndr_id'])
                require(sc is not None and tc is not None, f'{code}: missing calendar')
                if any(sc.get(f) != tc.get(f) for f in ['clndr_data', 'day_hr_cnt']):
                    warnings.append({'type': 'calendar_difference', 'activity_id': dest_code,
                                     'message': 'LNTP calendar retained; dates may differ after F9'})
        elif add_new:
            t = {f: s.get(f, '') for f in target.table('TASK').fields}
            unsupported = [f for f in ['cbs_id'] if s.get(f)]
            require(not unsupported, f'{code}: unsupported new activity references {unsupported}')
            for optional in ['rsrc_id', 'location_id']:
                require(optional in t or not s.get(optional),
                        f'{code}: destination TASK schema lacks required {optional}')
            t.update(task_id=dep.allocate('TASK', 'task_id'), proj_id=tp['proj_id'],
                     wbs_id=dep.wbs(s['wbs_id']),
                     clndr_id=dep.definition('CALENDAR', s['clndr_id']),
                     rsrc_id=dep.definition('RSRC', s.get('rsrc_id', '')),
                     location_id=dep.definition('LOCATION', s.get('location_id', '')),
                     guid=new_guid(), tmpl_guid='')
            t = {f: t[f] for f in target.table('TASK').fields}
            target.table('TASK').rows.append(t)
            new_ids.add(s['task_id'])
            action = 'ADDED'
        else:
            activities.append({'action': 'NOT_ADDED', 'activity_id': code,
                               'engineering_activity_id': code, 'name': s['task_name'],
                               'wbs_path': '.'.join(dep.spaths[s['wbs_id']])})
            continue
        taskmap[s['task_id']] = t['task_id']
        activities.append({'action': action, 'activity_id': t['task_code'],
                           'engineering_activity_id': code, 'name': t['task_name'],
                           'wbs_path': '.'.join(dep.spaths[s['wbs_id']])})

    managed_codes = {destinations[c] for c in st if destinations[c] in lt}
    for code, row in lt.items():
        if code not in managed_codes:
            activities.append({'action': 'PRESERVED_LNTP_ONLY', 'activity_id': code,
                               'engineering_activity_id': '', 'name': row['task_name'],
                               'wbs_path': '.'.join(dep.tpaths[row['wbs_id']])})

    # Carry activity codes and activity UDFs only for new activities.
    for row in source.rows('TASKACTV'):
        if row['task_id'] not in new_ids:
            continue
        n = dict(row)
        n.update(task_id=taskmap[row['task_id']], proj_id=tp['proj_id'],
                 actv_code_type_id=dep.definition('ACTVTYPE', row['actv_code_type_id']),
                 actv_code_id=dep.definition('ACTVCODE', row['actv_code_id']))
        dep.append('TASKACTV', n)
    udf_types = {r['udf_type_id']: r for r in source.rows('UDFTYPE')}
    for row in source.rows('UDFVALUE'):
        if udf_types.get(row['udf_type_id'], {}).get('table_name') != 'TASK' or row['fk_id'] not in new_ids:
            continue
        require(not row.get('udf_code_id'), 'New activity has unsupported coded UDF')
        n = dict(row)
        n.update(fk_id=taskmap[row['fk_id']], proj_id=tp['proj_id'],
                 udf_type_id=dep.definition('UDFTYPE', row['udf_type_id']))
        dep.append('UDFVALUE', n)

    # Existing logic is immutable. Import only links touching an added activity.
    logic = []
    source_ids = source.table('TASK').unique('task_id')
    for r in source.rows('TASKPRED'):
        if r['task_id'] not in new_ids and r['pred_task_id'] not in new_ids:
            continue
        require(r['proj_id'] == sp['proj_id'] and r['pred_proj_id'] == sp['proj_id'],
                'New activity has external-project logic; export its dependencies or resolve it manually')
        require(r['task_id'] in taskmap and r['pred_task_id'] in taskmap,
                'New activity has a relationship to an unavailable endpoint')
        n = dict(r)
        n.update(task_pred_id=dep.allocate('TASKPRED', 'task_pred_id'),
                 task_id=taskmap[r['task_id']], pred_task_id=taskmap[r['pred_task_id']],
                 proj_id=tp['proj_id'], pred_proj_id=tp['proj_id'])
        signature = lambda x: (x['task_id'], x['pred_task_id'], x['pred_type'], number(x['lag_hr_cnt']))
        if any(signature(x) == signature(n) for x in target.rows('TASKPRED')):
            continue
        dep.append('TASKPRED', n)
        logic.append({'predecessor': source_ids[r['pred_task_id']]['task_code'],
                      'successor': source_ids[r['task_id']]['task_code'],
                      'type': r['pred_type'], 'lag_hours': r['lag_hr_cnt']})

    # Detect probable renamed activities, but never match by name automatically.
    old_only = [r for c, r in lt.items() if c not in managed_codes]
    by_name = defaultdict(list)
    for row in old_only:
        by_name[row['task_name'].strip().casefold()].append(row['task_code'])
    for code, s in st.items():
        if s['task_id'] in new_ids:
            for old_code in by_name[s['task_name'].strip().casefold()]:
                warnings.append({'type': 'possible_activity_id_change', 'activity_id': code,
                                 'message': 'Same name as preserved LNTP activity ' + old_code +
                                            '; review mapping CSV to avoid a duplicate'})

    validate_preservation(before, target, source, taskmap, percent_mode)
    summary = {
        'lntp_input': str(before.path), 'engineering_input': str(source.path),
        'input_sha256': {'lntp': hashlib.sha256(before.data).hexdigest(),
                         'engineering': hashlib.sha256(source.data).hexdigest()},
        'matching_activities': matched, 'updated_activities': changed,
        'unchanged_matching_activities': matched - changed,
        'preserved_lntp_only_activities': len(old_only), 'added_activities': len(new_ids),
        'total_output_activities': len(target.rows('TASK')),
        'added_relationships': len(logic),
        'preserved_relationships': len(before.rows('TASKPRED')),
        'changed_fields': dict(Counter(r['field'] for r in changes)),
        'added_definitions': dict(dep.added), 'percent_mode': percent_mode,
        'warning_counts': dict(Counter(r['type'] for r in warnings)),
        'lntp_data_date_retained': tp.get('last_recalc_date'),
        'engineering_data_date': sp.get('last_recalc_date'),
        'planned_dates_preserved_on_existing_activities': True,
        'existing_logic_preserved': True,
        'p6_import_validated': False,
    }
    return target, summary, changes, activities, logic, warnings


def validate_preservation(before, after, source, taskmap, percent_mode):
    original = before.table('TASK').unique('task_id')
    result = after.table('TASK').unique('task_id')
    after.table('TASK').unique('task_code')
    managed = set(taskmap.values())
    allowed = set(UPDATE_FIELDS) if percent_mode == 'source' else set(UPDATE_FIELDS) - PERCENT_SUPPORT
    for tid, old in original.items():
        require(tid in result, f'Existing activity {tid} was removed')
        changes = {f for f in old if old[f] != result[tid][f]}
        require(changes <= (allowed if tid in managed else set()),
                f'Protected LNTP fields changed on {old["task_code"]}: {changes - allowed}')
    for name, table in before.tables.items():
        if name == 'TASK':
            continue
        require(after.rows(name)[:len(table.rows)] == table.rows,
                f'Existing {name} rows changed or removed')
    # Check all local references; leave original external relationships intact.
    pid = one_project(after)['proj_id']
    wbs_ids = after.table('PROJWBS').unique('wbs_id')
    cal_ids = after.table('CALENDAR').unique('clndr_id')
    resource_ids = {r['rsrc_id'] for r in after.rows('RSRC')}
    for row in result.values():
        require(row['wbs_id'] in wbs_ids and row['clndr_id'] in cal_ids,
                f'Unresolved WBS/calendar on {row["task_code"]}')
        if row['task_id'] not in original:
            require(not row.get('rsrc_id') or row['rsrc_id'] in resource_ids,
                    'Unresolved new primary resource')
    if 'TASKPRED' in after.tables:
        after.table('TASKPRED').unique('task_pred_id')
    for r in after.rows('TASKPRED'):
        require(r['proj_id'] != pid or r['task_id'] in result, 'Unresolved local successor')
        require(r['pred_proj_id'] != pid or r['pred_task_id'] in result, 'Unresolved local predecessor')
    if percent_mode == 'source':
        for s in source.rows('TASK'):
            if s['task_id'] in taskmap:
                require(calculated_percent(s) == calculated_percent(result[taskmap[s['task_id']]]),
                        f'Calculated percentage mismatch on {s["task_code"]}')


def write_csv(path, columns, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def percentage_comparison(before, source, after, mapping):
    old = before.table('TASK').unique('task_code')
    result = after.table('TASK').unique('task_code')
    rows = []
    for s in source.rows('TASK'):
        code = mapping.get(s['task_code'], s['task_code'])
        if code not in result:
            continue
        row = {'activity_id': code, 'engineering_activity_id': s['task_code'],
               'name': result[code]['task_name']}
        for label, task in [('lntp_before', old.get(code)), ('engineering', s),
                            ('lntp_after', result[code])]:
            row[label + '_percent_type'] = task['complete_pct_type'] if task else ''
            values = calculated_percent(task) if task else {}
            for key in ['physical', 'duration', 'units']:
                row[label + '_' + key + '_percent'] = values.get(key, '')
        rows.append(row)
    return rows


def export_update(lntp, engineering, output, report_dir=None, mapping_path=None,
                  add_new=True, percent_mode='source', encoding=None, dry_run=False):
    """Generate an XER/report set for CLI or desktop callers; raise on failure."""
    lntp, engineering, output = Path(lntp), Path(engineering), Path(output)
    require(output.resolve() not in {lntp.resolve(), engineering.resolve()},
            'Output must differ from both input paths')
    require(not output.exists(), 'Output already exists; choose a new filename')
    report = Path(report_dir) if report_dir else output.with_suffix('.reports')
    require(not report.exists(), 'Report directory already exists; choose a new directory')
    target, source = Xer(lntp, encoding), Xer(engineering, encoding)
    mapping = load_mapping(mapping_path)
    out, summary, changes, activities, logic, warnings = update(
        target, source, mapping, add_new, percent_mode)
    data = out.encoded()
    report.mkdir(parents=True)
    summary['dry_run'] = dry_run
    summary['output_sha256'] = hashlib.sha256(data).hexdigest() if not dry_run else None
    if not dry_run:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('xb') as f:
            f.write(data)
        parsed = Xer(output, out.encoding)
        require({n: t.rows for n, t in parsed.tables.items()} ==
                {n: t.rows for n, t in out.tables.items()}, 'Output round-trip validation failed')
    write_csv(report / 'field_changes.csv',
              ['activity_id', 'engineering_activity_id', 'field', 'before', 'after'], changes)
    write_csv(report / 'activities.csv',
              ['action', 'activity_id', 'engineering_activity_id', 'name', 'wbs_path'], activities)
    write_csv(report / 'added_logic.csv', ['predecessor', 'successor', 'type', 'lag_hours'], logic)
    write_csv(report / 'warnings.csv', ['type', 'activity_id', 'message'], warnings)
    percent_columns = ['activity_id', 'engineering_activity_id', 'name'] + [
        label + '_' + key for label in ['lntp_before', 'engineering', 'lntp_after']
        for key in ['percent_type', 'physical_percent', 'duration_percent', 'units_percent']]
    write_csv(report / 'percent_comparison.csv', percent_columns,
              percentage_comparison(target, source, out, mapping))
    (report / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lntp', required=True, type=Path)
    parser.add_argument('--engineering', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path,
                        help='New XER path; never replaces an input')
    parser.add_argument('--report-dir', type=Path, help='New, empty report directory')
    parser.add_argument('--mapping', type=Path, help='Explicit Activity ID mapping CSV')
    parser.add_argument('--no-add-new', action='store_true')
    parser.add_argument('--percent-mode', choices=['source', 'preserve'], default='source')
    parser.add_argument('--encoding', help='Optional explicit input/output encoding')
    parser.add_argument('--dry-run', action='store_true', help='Reports only; do not write XER')
    args = parser.parse_args(argv)
    try:
        report = args.report_dir or args.output.with_suffix('.reports')
        summary = export_update(args.lntp, args.engineering, args.output, report,
                                args.mapping, not args.no_add_new, args.percent_mode,
                                args.encoding, args.dry_run)
        print(json.dumps(summary, indent=2))
        print('Reports:', report)
        print('XER:', 'not written (dry run)' if args.dry_run else args.output)
        return 0
    except (UpdateError, OSError, UnicodeError) as exc:
        print('ERROR:', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
