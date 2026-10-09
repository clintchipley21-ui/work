"""Desktop job runner, independent of Tk so it can be tested without a display."""
from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from update_lntp import UpdateError, export_update, require


@dataclass(frozen=True)
class Job:
    lntp: Path
    engineering: Path
    output_folder: Path
    mapping: Path | None = None
    add_new: bool = True


@dataclass(frozen=True)
class Result:
    folder: Path
    xer: Path
    reports: Path
    summary: dict


def bundled_mapping():
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    candidate = base / 'activity_id_mapping.csv'
    return candidate if candidate.is_file() else None


def validate_job(job):
    for label, path in [('LNTP', job.lntp), ('Engineering', job.engineering)]:
        require(path.is_file(), f'Select an existing {label} XER file.')
        require(path.suffix.lower() == '.xer', f'The {label} file must have an .xer extension.')
    require(job.lntp.resolve() != job.engineering.resolve(),
            'Select two different files: the current LNTP and the engineering update.')
    require(not os.path.samefile(job.lntp, job.engineering),
            'The LNTP and engineering selections refer to the same file.')
    require(job.output_folder.is_dir(), 'Select an existing output folder.')
    if job.mapping is not None:
        require(job.mapping.is_file(), 'The Activity ID corrections CSV was not found.')


def run_job(job):
    validate_job(job)
    # A failed run removes only its own temporary files. Publish the result folder
    # after the engine has generated and checked the XER and every report.
    with tempfile.TemporaryDirectory(prefix='.lntp-working-', dir=job.output_folder) as tmp:
        staging = Path(tmp)
        xer = staging / (job.lntp.stem + '_UPDATED.xer')
        reports = staging / 'Reports'
        summary = export_update(job.lntp, job.engineering, xer, reports,
                                job.mapping, job.add_new)
        stamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        suffix = staging.name.removeprefix('.lntp-working-')
        final = job.output_folder / f'LNTP_Update_{stamp}_{suffix}'
        require(not final.exists(), 'Result folder already exists; try the update again.')
        staging.rename(final)
    return Result(final, final / xer.name, final / 'Reports', summary)


def completion_text(result):
    s = result.summary
    counts = s['warning_counts']
    lines = [
        'Update complete. Your original files have not been changed.', '',
        f"Updated activities: {s['updated_activities']:,}",
        f"Added activities: {s['added_activities']:,}",
        f"Preserved LNTP-only activities: {s['preserved_lntp_only_activities']:,}",
        f"Added relationships: {s['added_relationships']:,}",
        f"Preserved existing relationships: {s['preserved_relationships']:,}",
        '', 'Physical, Duration and Units % Complete inputs copied from engineering.',
        'Existing LNTP logic and planned dates preserved.',
    ]
    if counts.get('completed_activity_reopened'):
        lines.append(f"Review: engineering reopens {counts['completed_activity_reopened']} completed activities.")
    if counts.get('actual_date_cleared'):
        lines.append(f"Review: engineering clears {counts['actual_date_cleared']} actual-date fields.")
    if counts.get('possible_activity_id_change'):
        lines.append('Review: possible Activity ID changes were found in warnings.csv.')
    if counts.get('data_date_difference'):
        lines.append('The LNTP data date was retained; it differs from engineering.')
    lines.extend(['', 'Review the reports and import the XER into a P6 test copy first.',
                  'P6 import/recalculation has not been validated by this program.',
                  '', f'XER: {result.xer}', f'Reports: {result.reports}'])
    return '\n'.join(lines)
