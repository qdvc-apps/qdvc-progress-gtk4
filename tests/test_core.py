"""Tests of the pure core (no display needed): ``python3 -m unittest``.

The first classes port the macOS edition's ``CoreTests.swift`` one for one;
the session tests cover what the Mac app's ``AppModel`` did.
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from qdvc import csvio, files  # noqa: E402
from qdvc.clipboard import CellClip  # noqa: E402
from qdvc.dates import DayRange, MonthKey, add_months, iso_week, monday, parse_iso  # noqa: E402
from qdvc.labels import Cell, CellLabel, PasteMode  # noqa: E402
from qdvc.log import LogEntry, ProgressLog  # noqa: E402
from qdvc.models import InactivePeriod, Programme, Project, ProjectList  # noqa: E402
from qdvc.naming import slug  # noqa: E402
from qdvc.query import ProjectQuery, SortKey, StatusFilter, layout_rows, LayoutRow  # noqa: E402
from qdvc.session import CellRef, GridSelection, Session  # noqa: E402
from qdvc.settings import FIBONACCI, WorkloadSettings  # noqa: E402
from qdvc.week_labels import (DateOrder, WeekLabels, import_labels, parse_flexible_date,  # noqa: E402
                              parse_import)
from qdvc.workspace import Workspace, looks_like_workspace  # noqa: E402


def d(s):
    return parse_iso(s)


P = LayoutRow.programme_row
R = LayoutRow.project_row


class DateTests(unittest.TestCase):
    def test_weekdays_and_mondays(self):
        self.assertEqual(d("2026-10-05").isoweekday(), 1)
        self.assertEqual(d("2026-10-11").isoweekday(), 7)
        self.assertEqual(monday(d("2026-10-10")), d("2026-10-05"))
        self.assertEqual(monday(d("2026-10-05")), d("2026-10-05"))

    def test_iso_week(self):
        self.assertEqual(iso_week(d("2026-10-09")), 41)
        self.assertEqual(iso_week(d("2021-01-03")), 53)
        self.assertEqual(iso_week(d("2026-01-01")), 1)

    def test_months(self):
        self.assertEqual(add_months(d("2026-01-31"), 1), d("2026-02-28"))
        self.assertEqual(MonthKey.parse("2026-10").last_day, d("2026-10-31"))
        self.assertEqual(files.log_relative_path(MonthKey(2026, 3)), "log/2026/2026-03.csv")
        self.assertIsNone(parse_iso("2026-02-30"))
        self.assertEqual(parse_iso(" 2026-1-5 "), d("2026-01-05"))


class LabelTests(unittest.TestCase):
    def test_lenient_labels(self):
        self.assertEqual(CellLabel.lenient(" xs "), CellLabel.XS)
        self.assertEqual(CellLabel.lenient("MTG"), CellLabel.MEETING)
        self.assertEqual(CellLabel.lenient("!"), CellLabel.DUE)
        self.assertEqual(CellLabel.lenient("(p)"), CellLabel.PLANNED)
        self.assertIsNone(CellLabel.lenient("XXL"))
        self.assertEqual(CellLabel.lenient("(OK)"), CellLabel.TICK)
        self.assertEqual(CellLabel.lenient("\u2713"), CellLabel.TICK)
        self.assertEqual(CellLabel.lenient("x"), CellLabel.CROSS)
        self.assertEqual(CellLabel.lenient("(i)"), CellLabel.INFO)
        self.assertTrue(CellLabel.DUE.is_emblem)
        self.assertFalse(CellLabel.MEETING.is_emblem)

    def test_workload_values(self):
        s = WorkloadSettings()
        self.assertEqual(s.value(CellLabel.XL), 5)
        self.assertEqual(s.value(CellLabel.MEETING), 3)
        for label in (CellLabel.DUE, CellLabel.TICK, CellLabel.CROSS, CellLabel.INFO):
            self.assertEqual(s.value(label), 0)
        s.size_values = list(FIBONACCI.values)
        s.meeting_size = CellLabel.L
        self.assertEqual(s.value(CellLabel.MEETING), 5)
        self.assertEqual(s.matching_preset, FIBONACCI)

    def test_paste_modes(self):
        source, target = Cell(CellLabel.L, "new"), Cell(CellLabel.S, "old")
        self.assertEqual(PasteMode.BOTH.apply(source, target), source)
        self.assertEqual(PasteMode.LABEL.apply(source, target), Cell(CellLabel.L, "old"))
        self.assertEqual(PasteMode.NOTE.apply(source, target), Cell(CellLabel.S, "new"))


class CSVTests(unittest.TestCase):
    def test_round_trip_with_quotes_and_newlines(self):
        rows = [["a", "b,c", 'say "hi"', "two\nlines"], ["", " padded", "x", ""]]
        self.assertEqual(csvio.parse(csvio.render(rows)), rows)

    def test_crlf_and_bom(self):
        self.assertEqual(csvio.parse("\ufeffa,b\r\nc,d\r\n"), [["a", "b"], ["c", "d"]])


class LogTests(unittest.TestCase):
    def test_log_file_round_trip(self):
        entries = [
            LogEntry(d("2026-10-06"), "beta", Cell(CellLabel.MEETING)),
            LogEntry(d("2026-10-05"), "alpha", Cell(CellLabel.M, "Drafted, revised\nand sent")),
            LogEntry(d("2026-10-05"), "beta", Cell(note="Only a note")),
        ]
        text = files.render_log(entries)
        self.assertTrue(text.startswith(
            'date,project,label,note\n2026-10-05,alpha,M,"Drafted, revised\nand sent"\n'))
        parsed, problems = files.parse_log(text, MonthKey(2026, 10))
        self.assertEqual(problems, [])
        self.assertEqual(len(parsed), 3)
        self.assertEqual(files.render_log(parsed), text)

    def test_log_file_problems(self):
        parsed, problems = files.parse_log(
            "date,project,label,note\n2026-11-01,a,M,\n2026-10-02,a,XXL,\n", MonthKey(2026, 10))
        self.assertEqual(parsed, [])
        self.assertEqual(len(problems), 2)

    def test_totals(self):
        log = ProgressLog()
        log.set("a", d("2026-10-05"), Cell(CellLabel.XL))
        log.set("b", d("2026-10-05"), Cell(CellLabel.MEETING))
        log.set("c", d("2026-10-05"), Cell(CellLabel.DUE))
        log.set("a", d("2026-10-06"), Cell(CellLabel.S))
        s = WorkloadSettings()
        self.assertEqual(log.total(d("2026-10-05"), s), 8)
        self.assertEqual(log.total(d("2026-10-05"), s, lambda k: k == "a"), 5)
        self.assertEqual(log.total_over(DayRange(d("2026-10-05"), d("2026-10-09")), s), 10)
        self.assertEqual(log.last_worked()["a"], d("2026-10-06"))
        self.assertNotIn("c", log.last_worked())
        log.set("a", d("2026-10-06"), Cell())
        self.assertEqual(log.entry_count, 3)


class ProjectTests(unittest.TestCase):
    def test_inactive_days_merge_and_split(self):
        p = Project("p", "P")
        p.set_inactive(True, [d("2026-10-05"), d("2026-10-06")])
        p.inactive_periods[0].label = "On hold"
        p.set_inactive(True, [d("2026-10-07"), d("2026-10-09")])
        self.assertEqual(len(p.inactive_periods), 2)
        self.assertEqual(p.inactive_periods[0].range, DayRange(d("2026-10-05"), d("2026-10-07")))
        self.assertEqual(p.inactive_periods[0].label, "On hold")
        p.set_inactive(True, [d("2026-10-08")])
        self.assertEqual(len(p.inactive_periods), 1)
        p.set_inactive(False, [d("2026-10-07")])
        self.assertEqual([x.range for x in p.inactive_periods], [
            DayRange(d("2026-10-05"), d("2026-10-06")), DayRange(d("2026-10-08"), d("2026-10-09"))])
        self.assertEqual([x.label for x in p.inactive_periods], ["On hold", "On hold"])

    def test_slugs_and_keys(self):
        self.assertEqual(slug("Café Réview: Phase 2!"), "cafe-review-phase-2")
        self.assertEqual(slug("???"), "project")
        self.assertEqual(ProjectList(projects=[Project("grant", "Grant")]).new_key("Grant"),
                         "grant-2")
        self.assertTrue(Project.is_conventional_code("26XY"))
        self.assertFalse(Project.is_conventional_code("2XYZ"))
        coded = ProjectList(projects=[Project("a", "A", code="26XY")])
        self.assertEqual(coded.project_with_code(" 26xy ").key, "a")
        self.assertIsNone(coded.project_with_code("26XY", excluding="a"))
        self.assertIsNone(coded.project_with_code(""))

    def test_projects_file_round_trip(self):
        plist = ProjectList([Programme("Research"), Programme("Teaching")], [
            Project("grant", "Grant renewal", "26GR", "Research", "ARC DP27", "A. Smith, B. Jones",
                    inactive_periods=[InactivePeriod(DayRange(d("2026-11-02"), d("2026-11-20")),
                                                     "Waiting: ethics")]),
            Project("stats", "STATS 101", programme="Teaching", is_active=False),
            Project("misc", "Yes"),
        ])
        text = files.render_projects(plist)
        self.assertIn("id: '26GR'", text)
        self.assertIn("title: 'Yes'", text)
        self.assertIn("active: false", text)
        parsed, problems = files.parse_projects(text)
        self.assertEqual(problems, [])
        self.assertEqual(len(parsed.projects), 3)
        self.assertEqual(parsed.projects[0].code, "26GR")
        self.assertEqual(parsed.projects[0].inactive_periods[0].label, "Waiting: ethics")
        self.assertFalse(parsed.projects[1].is_active)
        self.assertEqual(files.render_projects(parsed), text)

    def test_projects_file_repairs_and_unknown_keys(self):
        text = ("projects:\n- title: No key here\n  colour: teal\n- key: a\n  title: First\n"
                "  programme: New Programme\n- key: a\n  title: Second\n")
        parsed, problems = files.parse_projects(text)
        self.assertEqual([p.key for p in parsed.projects], ["no-key-here", "a", "a-2"])
        self.assertEqual(parsed.programme_names, ["New Programme"])
        self.assertEqual(len(problems), 2)
        self.assertIn("colour: teal", files.render_projects(parsed))

    def test_numeric_ids_stay_strings(self):
        parsed, _ = files.parse_projects("projects:\n- key: a\n  title: A\n  id: 2612\n")
        self.assertEqual(parsed.projects[0].code, "2612")

    def test_settings_round_trip(self):
        s = WorkloadSettings([1, 2, 3, 5, 8], CellLabel.S, 1, 0, 20)
        self.assertEqual(files.parse_settings(files.render_settings(s)), s)


class QueryTests(unittest.TestCase):
    @property
    def plist(self):
        return ProjectList([Programme("Research"), Programme("Teaching")], [
            Project("b", "Beta", code="26BB", programme="Teaching"),
            Project("a", "Alpha", programme="Research", collaborators="Smith"),
            Project("c", "Gamma", programme="Research", is_active=False),
            Project("d", "Delta"),
        ])

    def test_grouped_rows(self):
        rows, included = layout_rows(self.plist, ProjectQuery(), set(), {})
        self.assertEqual(rows, [P("Research", 1, False), R("a"), P("Teaching", 1, False), R("b"),
                                P("", 1, False), R("d")])
        self.assertEqual(included, ["a", "b", "d"])

    def test_inactive_today_last(self):
        plist = self.plist
        plist.projects[1].inactive_periods = [InactivePeriod(DayRange(d("2026-10-05"),
                                                                      d("2026-10-16")))]
        q = ProjectQuery(status=StatusFilter.ALL, sort=SortKey.TITLE, inactive_today_last=True)
        self.assertEqual(layout_rows(plist, q, set(), {}, d("2026-10-10"))[1], ["c", "a", "b", "d"])
        self.assertEqual(layout_rows(plist, q, set(), {}, d("2026-10-20"))[1], ["a", "c", "b", "d"])
        q = q.but(grouped=False)
        self.assertEqual(layout_rows(plist, q, set(), {}, d("2026-10-10"))[1], ["b", "d", "c", "a"])

    def test_collapsed_filtered_and_sorted(self):
        q = ProjectQuery(status=StatusFilter.ALL, sort=SortKey.TITLE)
        rows, included = layout_rows(self.plist, q, {"Research"}, {})
        self.assertEqual(rows[0], P("Research", 2, True))
        self.assertEqual(included, ["a", "c", "b", "d"])
        q = q.but(grouped=False, search="smith")
        self.assertEqual(layout_rows(self.plist, q, set(), {})[0], [R("a")])
        q = q.but(search="", programme="Research", sort=SortKey.LAST_WORKED, ascending=False)
        lw = {"c": d("2026-10-01"), "a": d("2026-09-01")}
        self.assertEqual(layout_rows(self.plist, q, set(), lw)[1], ["c", "a"])

    def test_natural_sort(self):
        plist = ProjectList(projects=[Project("x", "Paper 10"), Project("y", "paper 9"),
                                      Project("z", "")])
        q = ProjectQuery(sort=SortKey.TITLE, grouped=False)
        self.assertEqual(layout_rows(plist, q, set(), {})[1], ["y", "x", "z"])
        self.assertEqual(layout_rows(plist, q.but(ascending=False), set(), {})[1], ["x", "y", "z"])


class WeekLabelTests(unittest.TestCase):
    def test_flexible_dates(self):
        def p(s, o=DateOrder.DAY_MONTH):
            r = parse_flexible_date(s, o, 2026)
            return r[0] if r else None
        self.assertEqual(p("2026-10-05"), d("2026-10-05"))
        self.assertEqual(p("2026-10-05 00:00:00"), d("2026-10-05"))
        self.assertEqual(p("5/10/2026"), d("2026-10-05"))
        self.assertEqual(p("10/5/26", DateOrder.MONTH_DAY), d("2026-10-05"))
        self.assertEqual(p("5/10"), d("2026-10-05"))
        self.assertEqual(p("Monday, 5th October 2026"), d("2026-10-05"))
        self.assertEqual(p("Oct 5, 2026"), d("2026-10-05"))
        self.assertEqual(p("w/c 5 Oct"), d("2026-10-05"))
        self.assertEqual(p("46300"), d("2026-10-05"))
        self.assertIsNone(p("Week 5"))
        self.assertIsNone(p("Teaching week 3"))
        self.assertIsNone(p("W41"))

    def test_import_from_spreadsheet_rows(self):
        pasted = ("Week of\tLabel\n5/10/2026\tTeaching wk 9\n\n12/10/2026\tMid-sem break\n"
                  "14/10/2026\tMid-sem break\nNotes\tx\n")
        rows = parse_import(pasted, DateOrder.DAY_MONTH, 2026)
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0].skipped, "No date (a heading row?)")
        self.assertEqual((rows[1].week, rows[1].label), (d("2026-10-05"), "Teaching wk 9"))
        self.assertEqual(rows[3].skipped, "Same week as line 4")
        self.assertEqual(import_labels(rows), {d("2026-10-05"): "Teaching wk 9",
                                               d("2026-10-12"): "Mid-sem break"})

    def test_year_rolls_over_without_years(self):
        rows = parse_import("21/12\tA\n4/1\tB", DateOrder.DAY_MONTH, 2026)
        self.assertEqual(rows[1].week, d("2027-01-04"))

    def test_file_round_trip_and_display(self):
        w = WeekLabels()
        w.set(d("2026-10-07"), "Sprint 4")
        self.assertEqual(w.get(d("2026-10-11")), "Sprint 4")
        self.assertEqual(w.render_file(), "week,label\n2026-10-05,Sprint 4\n")
        self.assertEqual(WeekLabels.parse_file(w.render_file())[0], w)
        self.assertEqual(w.display(d("2026-10-12"), True)[0], "W42")


class ClipboardTests(unittest.TestCase):
    def test_text_to_clip(self):
        clip = CellClip.from_text("M\tXS\n\tmtg\n")
        self.assertEqual(clip.rows, [[Cell(CellLabel.M), Cell(CellLabel.XS)],
                                     [Cell(), Cell(CellLabel.MEETING)]])
        note = CellClip.from_text("Wrote the intro.\nSent it to Sam.")
        self.assertEqual(note.rows, [[Cell(note="Wrote the intro.\nSent it to Sam.")]])

    def test_json_round_trip(self):
        clip = CellClip([[Cell(CellLabel.DUE, "Report"), Cell()]])
        self.assertEqual(CellClip.from_json(clip.to_json()), clip)
        self.assertEqual(clip.tsv, "(!)\t")


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="progress-")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_save_load_and_protection(self):
        ws = Workspace(self.root)
        ws.ensure_layout()
        self.assertTrue(looks_like_workspace(self.root))
        oct_ = MonthKey(2026, 10)
        ws.save_month(oct_, [LogEntry(d("2026-10-05"), "a", Cell(CellLabel.L))])
        c = ws.load()
        self.assertEqual(c.issues, [])
        self.assertEqual(c.log.get("a", d("2026-10-05")).label, CellLabel.L)
        self.assertFalse(ws.has_external_changes())
        with open(os.path.join(self.root, "log/2026/2026-11.csv"), "w") as f:
            f.write("date,project,label,note\nnot-a-date,a,M,\n")
        self.assertTrue(ws.has_external_changes())
        c = ws.load()
        self.assertEqual([i.relative_path for i in c.issues], ["log/2026/2026-11.csv"])
        with self.assertRaises(Exception):
            ws.save_month(MonthKey(2026, 11), [])
        ws.save_month(oct_, [])
        self.assertFalse(os.path.exists(os.path.join(self.root, "log/2026/2026-10.csv")))

    def test_file_mode_is_not_private(self):
        ws = Workspace(self.root)
        ws.ensure_layout()
        mode = os.stat(os.path.join(self.root, "projects.yml")).st_mode & 0o777
        self.assertNotEqual(mode, 0o600)


SAMPLE = os.path.join(os.path.dirname(__file__), "..", "sample-workspace")


class ParityTests(unittest.TestCase):
    """The macOS edition wrote sample-workspace/; rewriting it must not
    change a byte, so both editions can share a workspace."""

    def test_sample_files_rewrite_identically(self):
        with open(os.path.join(SAMPLE, "projects.yml"), encoding="utf-8") as f:
            text = f.read()
        self.assertEqual(files.render_projects(files.parse_projects(text)[0]), text)
        with open(os.path.join(SAMPLE, "progress.yml"), encoding="utf-8") as f:
            text = f.read()
        self.assertEqual(files.render_settings(files.parse_settings(text)), text)
        ws = Workspace(SAMPLE)
        for month, path in ws.log_files():
            with open(ws.path(path), encoding="utf-8") as f:
                text = f.read()
            entries, problems = files.parse_log(text, month)
            self.assertEqual(problems, [])
            self.assertEqual(files.render_log(entries), text, path)
        with open(os.path.join(SAMPLE, "week-labels.csv"), encoding="utf-8") as f:
            text = f.read()
        self.assertEqual(WeekLabels.parse_file(text)[0].render_file(), text)


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="progress-")
        shutil.copytree(SAMPLE, self.root, dirs_exist_ok=True)
        self.s = Session(clock=lambda: d("2026-10-07"))
        self.s.open_workspace(self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def reload(self):
        return Workspace(self.root).load()

    def test_open_selects_today(self):
        s = self.s
        self.assertEqual(s.focus_ref, CellRef("arc-discovery-grant", d("2026-10-07")))
        self.assertEqual(s.range_start.isoweekday(), 1)
        self.assertLessEqual(s.range_start, d("2026-08-31"))
        self.assertEqual(s.rows[0], P("Research", 3, False))

    def test_set_label_saves_and_undoes(self):
        s = self.s
        ref = CellRef("phd-supervision", d("2026-10-20"))
        s.select(ref)
        s.set_label(CellLabel.XL)
        self.assertEqual(self.reload().log.get(ref.project, ref.date).label, CellLabel.XL)
        self.assertEqual(s.undo(), "Set Extra Large")
        self.assertTrue(self.reload().log.get(ref.project, ref.date).is_empty)
        s.redo()
        self.assertEqual(s.cell(ref).label, CellLabel.XL)

    def test_note_typing_is_one_undo_step_and_debounced(self):
        s = self.s
        ref = CellRef("phd-supervision", d("2026-10-20"))
        s.select(ref)
        for text in ("H", "He", "Hello"):
            s.set_note(text, ref)
        self.assertTrue(s.has_pending_saves)
        self.assertTrue(self.reload().log.get(ref.project, ref.date).is_empty)
        s.flush_saves()
        self.assertEqual(self.reload().log.get(ref.project, ref.date).note, "Hello")
        s.undo()
        self.assertEqual(s.cell(ref).note, "")

    def test_block_paste_and_single_fill(self):
        s = self.s
        a = d("2026-10-12")
        s.selection = GridSelection(CellRef("arc-discovery-grant", a),
                                    CellRef("arc-discovery-grant", a))
        s.paste(CellClip.from_text("M\tL\nS\tXS"))
        self.assertEqual(s.cell(CellRef("arc-discovery-grant", d("2026-10-13"))).label, CellLabel.L)
        self.assertEqual(s.cell(CellRef("soil-carbon-paper", a)).label, CellLabel.S)
        self.assertEqual(s.selection.focus, CellRef("soil-carbon-paper", d("2026-10-13")))
        s.selection = GridSelection(CellRef("phd-supervision", a),
                                    CellRef("phd-supervision", d("2026-10-14")))
        s.paste(CellClip([[Cell(CellLabel.MEETING, "x")]]), PasteMode.LABEL)
        self.assertEqual(s.cell(CellRef("phd-supervision", d("2026-10-14"))),
                         Cell(CellLabel.MEETING))

    def test_inactive_days_from_selection(self):
        s = self.s
        s.selection = GridSelection(CellRef("journal-reviews", d("2026-10-19")),
                                    CellRef("journal-reviews", d("2026-10-21")))
        s.toggle_selection_inactive()
        self.assertTrue(s.selection_is_inactive)
        p = self.reload().projects.project("journal-reviews")
        self.assertEqual(p.inactive_periods[0].range, DayRange(d("2026-10-19"), d("2026-10-21")))

    def test_add_move_and_delete_project(self):
        s = self.s
        key = s.add_project("New grant", "26NG", "Research")
        self.assertEqual(key, "new-grant")
        names = [p.key for p in s.project_list.projects]
        self.assertEqual(names.index("new-grant"), names.index("phd-supervision") + 1)
        self.assertIsNone(s.add_project("Other", "26ng"))
        self.assertFalse(s.can_move_project("new-grant", 1))
        s.move_project("new-grant", -1)
        names = [p.key for p in s.project_list.projects]
        self.assertEqual(names.index("new-grant") + 1, names.index("phd-supervision"))
        s.select(CellRef("new-grant", d("2026-10-07")))
        s.set_label(CellLabel.M)
        s.delete_project("new-grant")
        self.assertIsNone(self.reload().projects.project("new-grant"))
        self.assertEqual(self.reload().log.get("new-grant", d("2026-10-07")), Cell())
        s.undo()
        self.assertIsNotNone(self.reload().projects.project("new-grant"))
        self.assertEqual(self.reload().log.get("new-grant", d("2026-10-07")).label, CellLabel.M)

    def test_programmes(self):
        s = self.s
        self.assertIsNotNone(s.programme_name_problem("Teaching"))
        self.assertIsNotNone(s.programme_name_problem("No Programme"))
        s.rename_programme("Teaching", "Education")
        self.assertEqual(s.project("envs-201-lectures").programme, "Education")
        s.delete_programme("Service")
        self.assertEqual(s.project("ethics-committee").programme, "")
        self.assertNotIn("Service", self.reload().projects.programme_names)
        s.undo()
        self.assertIn("Service", s.project_list.programme_names)

    def test_totals_follow_filter(self):
        s = self.s
        day = d("2026-10-06")
        everything = s.day_total(day)
        s.query = s.query.but(programme="Teaching")
        self.assertLess(s.day_total(day), everything)
        self.assertEqual(s.footer_programmes, ["Teaching"])

    def test_week_labels_and_settings(self):
        s = self.s
        s.set_week_label("Sprint 1", d("2026-11-25"))
        self.assertEqual(self.reload().week_labels.get(d("2026-11-23")), "Sprint 1")
        s.update_settings(lambda st: setattr(st, "day_peak", 20))
        self.assertEqual(self.reload().settings.day_peak, 20)

    def test_external_change_is_noticed(self):
        s = self.s
        with open(os.path.join(self.root, "week-labels.csv"), "w") as f:
            f.write("week,label\n2026-10-05,Changed elsewhere\n")
        s.window_became_active()
        self.assertEqual(s.week_labels.get(d("2026-10-07")), "Changed elsewhere")


if __name__ == "__main__":
    unittest.main()
