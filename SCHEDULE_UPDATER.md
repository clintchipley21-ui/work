# Weekly engineering update into the LNTP schedule

This tool reads **your current LNTP XER** and **the new engineering XER**, then writes a separate updated LNTP XER. It does not connect to or change your live P6 database. Both input files are left untouched. Python 3.10 or newer is required; there are no packages to install.

## Run it

Save `update_lntp.py`, `activity_id_mapping.csv` and your two XERs in one folder. Open a terminal in that folder and run this command (one line):

```sh
python update_lntp.py --lntp "FERMI-64 10-9-26.xer" --engineering "Fermi America Power Plant Project - Engineering & Procurement Schedule - Update 10-05-2026.xer" --output "FERMI-64_LNTP_UPDATED.xer" --mapping "activity_id_mapping.csv"
```

On Windows, `py -3` can replace `python` if needed. For each subsequent week, use a fresh export of your current LNTP schedule, the engineers' latest export, and a new output filename. This preserves changes made to your LNTP work between updates. Keep the mapping argument so the confirmed Activity ID correction continues to apply.

The output XER and its `.reports` folder must not already exist. This prevents accidentally overwriting an earlier result. To review changes without generating an XER, add `--dry-run`; reports will still be created. Add `--no-add-new` if you want to update matches without bringing in new activities. Neither option deletes LNTP work.

## How matching works

Activities match by **exact Activity ID** (`task_code`), not the database's internal `task_id`, the activity name, or position. The internal IDs differ between these two files. Duplicated Activity IDs, multiple projects in one file, and ambiguous mappings stop the update rather than guessing.

The included mapping contains the correction you confirmed:

| Engineering Activity ID | LNTP Activity ID retained |
| --- | --- |
| EE.50.560.035.IFR | EE.50.560.035I.FR |

Add additional confirmed renames to that CSV using the same two columns. Matching by name is deliberately avoided. A name match with a different ID is reported as a possible rename, but otherwise added as a new activity. Mapped activities retain their LNTP ID, internal ID, name, WBS, and identity GUID. If a mapping refers to an activity missing from either input, the tool stops: remove or revise the obsolete mapping before running again.

## What changes on existing matching activities

| Requested information | P6 XER fields copied from engineering |
| --- | --- |
| Current Start / Finish and remaining dates | `early_start_date`, `early_end_date`, `restart_date`, `reend_date` |
| Actual Start / Finish | `act_start_date`, `act_end_date` |
| Remaining Duration | `remain_drtn_hr_cnt` |
| Budgeted Labor Units | `target_work_qty` |
| Actual Labor Units | `act_work_qty` |
| Physical % Complete | `phys_complete_pct` |
| % complete method | `complete_pct_type` |
| Duration % Complete supporting value | `target_drtn_hr_cnt` (Original/Planned Duration) |
| Units % Complete supporting value | `remain_work_qty` (Remaining Labor Units) |
| Activity status, consistent with actual dates | `status_code` |

You authorized the supporting fields because percentages would not match reliably if the LNTP method, original duration, remaining labor or status stayed different. Values are copied in the XER's native **hours/units**; there is no days-to-hours conversion. Blank actual dates in engineering clear matching LNTP actual dates, rather than leaving stale actuals. Clears, changed actuals and reopened completed activities are flagged in `warnings.csv`.

For an activity with a nonzero original duration, Duration % is `(Original Duration - Remaining Duration) / Original Duration × 100`. Labor-only Units % is `Actual Labor / (Actual Labor + Remaining Labor) × 100`; it is not Actual Labor divided by Budgeted Labor. Physical % is copied directly. `percent_comparison.csv` compares all three numerical values before and after the update. The report uses status as a fallback for zero-denominator activities; verify P6's display for milestones and summaries after import.

P6's displayed Start and Finish are composite values. Actual dates take precedence on started/completed work; remaining/early dates drive unstarted and unfinished work. **Planned Start and Planned Finish** (`target_start_date`, `target_end_date`) on existing activities are preserved. Late dates, float, Expected Finish, constraints, activity names, calendars, types, WBS, equipment units, activity codes, UDFs, other labor fields, project settings and the LNTP data date are also preserved. Float and late dates can be stale until P6 schedules the updated project.

Performance % Complete, Schedule % Complete and WBS earned-value percentages depend on P6 baselines, earned-value settings and rollups. They are **not** activity Physical/Duration/Units percentages and this tool does not synchronize them. Summary/WBS/LOE displayed values may be recalculated by P6.

`--percent-mode preserve` is an alternative that retains the LNTP % method, original duration and remaining labor. It still updates the requested progress fields and status, but may produce different percentages. Differences are flagged; use the default `source` mode for the behavior you requested.

## New activities and relationships

All engineering activities absent from LNTP are added unless `--no-add-new` is supplied. Their attributes are copied into the LNTP project with new internal IDs and GUIDs. Their WBS is matched by its hierarchical WBS **code path**, excluding the project root. Missing WBS branches are created under the existing root and inherit the destination parent's OBS. Existing WBS nodes are untouched.

Required calendars and primary-resource definitions are reused or added with remapped IDs. Only new activities receive their engineering activity codes and activity UDF values. Existing activities' primary resources, codes and UDFs remain untouched. Resource rates, costs, financial-period history, notebooks, steps, baselines and other supplemental records are not synchronized.

Every source relationship with **at least one newly added activity** is brought over, including links between new activities and matching existing activities. Relationship types and lags are retained. All original LNTP relationships are preserved exactly. Relationships entirely between existing activities are not added, removed, or updated—even when the engineering logic differs. This avoids overwriting your LNTP logic, but means this is not a full engineering logic synchronization. A later weekly update will not revise logic on activities already added in a prior week.

This version supports the activity-level labor totals in your uploaded exports, which contain no `TASKRSRC` assignment rows. If future exports contain resource assignments on activities being managed, the tool stops because P6 can recalculate activity totals from those assignments. An assignment-aware extension is needed for that case. Nonzero actual/remaining equipment units also stop the update, since they affect Units % Complete and are outside your requested labor-only scope. Unsupported required references and external-project links on new activities stop the update instead of creating an incomplete XER.

## Review and import

The `.reports` folder contains Excel-readable UTF-8 CSVs:

- `activities.csv`: updated, unchanged, added and preserved LNTP-only activities.
- `field_changes.csv`: every changed field, with old and new values.
- `percent_comparison.csv`: LNTP before, engineering, and LNTP after for the three % complete types.
- `added_logic.csv`: added predecessors/successors, relationship type and lag in hours.
- `warnings.csv`: actual-date changes/clears, reopened activities, name differences, potential renames and data-date/calendar differences.
- `summary.json`: counts, changed-field totals, file hashes and validation status.

These CSVs are **review reports**, not P6 Excel import templates. Import the generated **XER** to bring in activities and relationships together.

First import the output into a disposable test project/copy using P6's import wizard. Both supplied exports have project short name `FERMI-64`; check the target project and import action carefully. Ensure import settings do not delete activities or relationships absent from the input, and that the selected options import the actuals and labor units you intend. Review the import log, then check representative updated activities, the mapped Activity ID, new activities, new relationships and the preserved LNTP-only work.

The script validates XER structure, field preservation, reference mapping and percentage inputs, but it **does not run P6** and cannot certify your P6 import settings or recalculated results. Schedule a test copy with F9 and review dates and rollups. F9 calculates the combined LNTP network using your retained calendars, constraints, logic and data date; forecasts can differ from the engineers' standalone schedule after recalculation. Avoid automatic actual/unit recalculation settings that would override the copied values without checking the result.

For these inputs, the LNTP data date stored in `PROJECT.last_recalc_date` is **September 13, 2026**, while engineering's is **October 5, 2026**. The October 9 LNTP filename/export date is not its data date. This tool retains the LNTP data date because changing it affects your other work. Choose the appropriate reporting data date in P6 as a separate scheduling decision.

The engineering update reopens **22 completed activities** and clears **22 actual-date fields** in the LNTP. Those changes come from engineering; review `warnings.csv` before importing into the live project.

## Validation

Run the included regression tests:

```sh
python -m unittest discover -s tests -v
```

Run an independent file-level audit after creating a result:

```sh
python tests/check_uploaded_schedules.py "FERMI-64 10-9-26.xer" "Fermi America Power Plant Project - Engineering & Procurement Schedule - Update 10-05-2026.xer" "FERMI-64_LNTP_UPDATED.xer" "activity_id_mapping.csv"
```

Running the updater again using its output as LNTP and the same engineering input should add nothing and change nothing. The implementation checks that every pre-existing activity remains, every LNTP-only activity is unchanged, only the documented fields change on matches, and existing records in all other tables remain unchanged.
