#!/usr/bin/env python3
"""LNTP Schedule Updater desktop interface. Python 3.10+, standard library only."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from schedule_desktop import Job, bundled_mapping, completion_text, run_job, validate_job
from update_lntp import UpdateError


def open_path(path):
    if sys.platform == 'win32':
        os.startfile(str(path))
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', str(path)])
    else:
        subprocess.Popen(['xdg-open', str(path)])


class ScheduleApp:
    def __init__(self, root):
        self.root = root
        root.title('LNTP Schedule Updater')
        root.geometry('920x730')
        root.minsize(780, 670)
        self.events = queue.Queue()
        self.busy = False
        self.result = None
        self.controls = []
        self.lntp = tk.StringVar()
        self.engineering = tk.StringVar()
        self.output = tk.StringVar(value=str(Path.home()))
        mapping = bundled_mapping()
        self.mapping = tk.StringVar(value=str(mapping) if mapping else '')
        self.add_new = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value='Select your two schedules to get started.')

        style = ttk.Style(root)
        if 'clam' in style.theme_names():
            style.theme_use('clam')
        style.configure('TFrame', background='#f4f6f8')
        style.configure('TLabel', background='#f4f6f8', font=('Segoe UI', 10))
        style.configure('Title.TLabel', font=('Segoe UI', 22, 'bold'), foreground='#143550')
        style.configure('Heading.TLabel', font=('Segoe UI', 11, 'bold'))
        style.configure('TButton', font=('Segoe UI', 10), padding=(12, 7))
        style.configure('Primary.TButton', font=('Segoe UI', 11, 'bold'))
        style.configure('TCheckbutton', background='#f4f6f8', font=('Segoe UI', 10))

        body = ttk.Frame(root, padding=24)
        body.pack(fill='both', expand=True)
        body.columnconfigure(0, weight=1)
        ttk.Label(body, text='LNTP Schedule Updater', style='Title.TLabel').grid(
            row=0, column=0, sticky='w')
        ttk.Label(body, text='Select two P6 XER files. Get an updated LNTP XER and review reports.').grid(
            row=1, column=0, sticky='w', pady=(4, 18))
        self.file_row(body, 2, '1. Current LNTP schedule', self.lntp,
                      lambda: self.choose_file(self.lntp, 'Select the current LNTP schedule'))
        self.file_row(body, 3, '2. Engineering weekly update', self.engineering,
                      lambda: self.choose_file(self.engineering, 'Select the engineering update'))
        self.file_row(body, 4, '3. Save results in', self.output, self.choose_output)

        options = ttk.Frame(body)
        options.grid(row=5, column=0, sticky='ew', pady=(4, 8))
        checkbox = ttk.Checkbutton(options, text='Add new engineering activities and their logic',
                                   variable=self.add_new)
        checkbox.pack(anchor='w')
        self.controls.append(checkbox)
        self.file_row(body, 6, 'Activity ID corrections CSV (optional)', self.mapping,
                      self.choose_mapping, clear=True)
        ttk.Label(body, text='The included CSV keeps your confirmed LNTP Activity ID correction.',
                  foreground='#586473').grid(row=7, column=0, sticky='w', pady=(0, 10))

        action = ttk.Frame(body)
        action.grid(row=8, column=0, sticky='ew', pady=(0, 12))
        self.run_button = ttk.Button(action, text='Update Schedule', style='Primary.TButton',
                                     command=self.start)
        self.run_button.pack(side='left')
        self.controls.append(self.run_button)
        self.progress = ttk.Progressbar(action, mode='indeterminate', length=180)
        self.progress.pack(side='left', padx=18)
        ttk.Label(body, textvariable=self.status, wraplength=830).grid(
            row=9, column=0, sticky='w', pady=(0, 8))

        results_frame = ttk.Frame(body)
        results_frame.grid(row=10, column=0, sticky='nsew')
        body.rowconfigure(10, weight=1)
        self.results = tk.Text(results_frame, height=10, wrap='word', state='disabled',
                               font=('Segoe UI', 10), background='white', relief='flat',
                               padx=12, pady=10)
        scrollbar = ttk.Scrollbar(results_frame, command=self.results.yview)
        self.results.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.results.pack(side='left', fill='both', expand=True)
        self.show_text('Original files stay unchanged. Each run creates a new results folder.\n\n'
                       'The updater preserves LNTP-only work and existing relationships. '
                       'It copies engineering progress and the inputs for Physical, Duration '
                       'and Units % Complete.\n\nReview the reports before importing into P6.')
        buttons = ttk.Frame(body)
        buttons.grid(row=11, column=0, sticky='ew', pady=(12, 0))
        self.folder_button = ttk.Button(buttons, text='Open Results Folder', state='disabled',
                                        command=lambda: self.open_result('folder'))
        self.folder_button.pack(side='left')
        self.changes_button = ttk.Button(buttons, text='Open Change Report', state='disabled',
                                         command=lambda: self.open_result('changes'))
        self.changes_button.pack(side='left', padx=8)
        self.warnings_button = ttk.Button(buttons, text='Open Warnings', state='disabled',
                                          command=lambda: self.open_result('warnings'))
        self.warnings_button.pack(side='left')
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(100, self.poll)

    def file_row(self, parent, row, title, variable, command, clear=False):
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=0, sticky='ew', pady=(0, 10))
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text=title, style='Heading.TLabel').grid(row=0, column=0, sticky='w')
        entry = ttk.Entry(frame, textvariable=variable, font=('Segoe UI', 10))
        entry.grid(row=1, column=0, sticky='ew', pady=(4, 0))
        browse = ttk.Button(frame, text='Browse…', command=command)
        browse.grid(row=1, column=1, padx=(8, 0), pady=(4, 0))
        self.controls.extend([entry, browse])
        if clear:
            button = ttk.Button(frame, text='Clear', command=lambda: variable.set(''))
            button.grid(row=1, column=2, padx=(8, 0), pady=(4, 0))
            self.controls.append(button)

    def choose_file(self, variable, title):
        selected = filedialog.askopenfilename(parent=self.root, title=title,
                                              filetypes=[('P6 XER schedules', '*.xer'),
                                                         ('All files', '*.*')])
        if selected:
            variable.set(selected)

    def choose_output(self):
        selected = filedialog.askdirectory(parent=self.root, title='Choose where to save results',
                                           mustexist=True)
        if selected:
            self.output.set(selected)

    def choose_mapping(self):
        selected = filedialog.askopenfilename(parent=self.root, title='Select Activity ID corrections',
                                              filetypes=[('CSV files', '*.csv')])
        if selected:
            self.mapping.set(selected)

    def show_text(self, text):
        self.results.configure(state='normal')
        self.results.delete('1.0', 'end')
        self.results.insert('1.0', text)
        self.results.configure(state='disabled')

    def start(self):
        if self.busy:
            return
        try:
            if not self.lntp.get().strip() or not self.engineering.get().strip():
                raise UpdateError('Select both the LNTP schedule and the engineering update.')
            if not self.output.get().strip():
                raise UpdateError('Select an output folder.')
            job = Job(Path(self.lntp.get().strip()), Path(self.engineering.get().strip()),
                      Path(self.output.get().strip()),
                      Path(self.mapping.get().strip()) if self.mapping.get().strip() else None,
                      self.add_new.get())
            validate_job(job)
        except (UpdateError, OSError) as exc:
            messagebox.showerror('Check your selections', str(exc), parent=self.root)
            return
        self.busy = True
        self.result = None
        for control in self.controls:
            control.configure(state='disabled')
        for button in [self.folder_button, self.changes_button, self.warnings_button]:
            button.configure(state='disabled')
        self.status.set('Updating schedule… Keep this window open until the update finishes.')
        self.show_text('Reading your schedules, matching activities, and generating the XER and reports…')
        self.progress.start(12)
        threading.Thread(target=self.worker, args=(job,), daemon=True).start()

    def worker(self, job):
        # Tk widgets are accessed only by the main thread through the event queue.
        try:
            self.events.put(('done', run_job(job)))
        except (UpdateError, OSError, UnicodeError) as exc:
            self.events.put(('error', str(exc)))
        except Exception as exc:
            self.events.put(('error', f'Unexpected error ({type(exc).__name__}): {exc}'))

    def poll(self):
        try:
            event, payload = self.events.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            self.progress.stop()
            for control in self.controls:
                control.configure(state='normal')
            if event == 'done':
                self.result = payload
                self.status.set('Complete — your updated XER and reports are ready.')
                self.show_text(completion_text(payload))
                for button in [self.folder_button, self.changes_button, self.warnings_button]:
                    button.configure(state='normal')
            else:
                self.status.set('Update stopped. Your original files have not been changed.')
                self.show_text('No completed result was saved.\n\n' + payload)
                messagebox.showerror('Schedule update stopped', payload, parent=self.root)
        self.root.after(100, self.poll)

    def open_result(self, kind):
        if self.result is None:
            return
        paths = {'folder': self.result.folder,
                 'changes': self.result.reports / 'field_changes.csv',
                 'warnings': self.result.reports / 'warnings.csv'}
        try:
            open_path(paths[kind])
        except OSError as exc:
            messagebox.showerror('Could not open the result',
                                 f'{exc}\n\nOpen this path manually:\n{paths[kind]}', parent=self.root)

    def close(self):
        if self.busy:
            messagebox.showinfo('Update in progress',
                                'Wait for the update to finish before closing this window.', parent=self.root)
            return
        self.root.destroy()


def main():
    root = tk.Tk()
    ScheduleApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
