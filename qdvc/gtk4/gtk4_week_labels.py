"""Week Labels (Ctrl+L): set the header's week labels by pasting two columns
from a spreadsheet — a date in the week, and the label — with a live preview
of how each row is read; and review or remove the current labels."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk  # noqa: E402

from ..session import Session  # noqa: E402
from ..ui_prefs import long_day, plural, short_day  # noqa: E402
from ..week_labels import DateOrder, WeekLabels, import_labels, parse_import  # noqa: E402


def locale_date_order() -> DateOrder:
    """Day/month or month/day, from the order of the locale's dates."""
    import time
    s = time.strftime("%x", (2026, 11, 22, 0, 0, 0, 0, 326, 0))
    try:
        return DateOrder.MONTH_DAY if s.index("11") < s.index("22") else DateOrder.DAY_MONTH
    except ValueError:
        return DateOrder.DAY_MONTH


class WeekLabelsDialog(Adw.Dialog):
    def __init__(self, session: Session):
        super().__init__(title="Week Labels", content_width=860, content_height=640)
        self.s = session
        stored = session.config.get("date_order")
        self.order = DateOrder(stored) if stored in [o.value for o in DateOrder] \
            else locale_date_order()
        self._labels = {}

        self.stack = Adw.ViewStack()
        self.stack.add_titled_with_icon(self._paste_page(), "paste", "Paste from Spreadsheet",
                                        "edit-paste-symbolic")
        self.current_page = self.stack.add_titled_with_icon(
            self._current_page(), "current", "Current Labels", "view-list-symbolic")
        self.apply = Gtk.Button(label="Apply")
        self.apply.add_css_class("suggested-action")
        self.apply.connect("clicked", self._on_apply)
        header = Adw.HeaderBar(title_widget=Adw.ViewSwitcher(
            stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE))
        header.pack_end(self.apply)
        self.stack.connect("notify::visible-child-name",
                           lambda *_: self.apply.set_visible(
                               self.stack.get_visible_child_name() == "paste"))
        self.toasts = Adw.ToastOverlay(child=self.stack)
        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(self.toasts)
        self.set_child(view)
        self._update_preview()
        self._refresh_current()
        self._listener = lambda e, _p: self._refresh_current() if e == "changed" else None
        session.connect(self._listener)

    # --- paste ------------------------------------------------------------

    def _paste_page(self):
        intro = Gtk.Label(wrap=True, xalign=0, label=(
            "Each week can carry a label in the grid\u2019s header, such as a teaching week, a "
            "sprint or a holiday. Copy two columns from a spreadsheet \u2014 a date in the week "
            "(any day) and its label \u2014 and paste them below. Weeks without a label show "
            "their week number."))
        intro.add_css_class("dim-label")

        self.text = Gtk.TextView(monospace=True, top_margin=8, bottom_margin=8, left_margin=8,
                                 right_margin=8)
        self.text.get_buffer().connect("changed", lambda *_: self._update_preview())
        text_sw = Gtk.ScrolledWindow(vexpand=True, hexpand=True, child=self.text)
        text_sw.add_css_class("card")
        paste = Gtk.Button(label="Paste from Clipboard")
        paste.connect("clicked", self._on_paste_clipboard)
        orders = Gtk.DropDown.new_from_strings([o.title for o in DateOrder])
        orders.set_selected(list(DateOrder).index(self.order))
        orders.set_tooltip_text("How dates such as 5/10 are read")
        orders.connect("notify::selected", self._on_order)
        tools = Gtk.Box(spacing=6)
        tools.append(paste)
        spacer = Gtk.Box(hexpand=True)
        tools.append(spacer)
        tools.append(orders)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True)
        heading = Gtk.Label(label="Rows from a Spreadsheet", xalign=0)
        heading.add_css_class("heading")
        left.append(heading)
        left.append(text_sw)
        left.append(tools)

        self.preview = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.preview.add_css_class("boxed-list")
        self.preview.set_placeholder(self._placeholder("Nothing pasted yet"))
        prev_sw = Gtk.ScrolledWindow(vexpand=True, hexpand=True, child=self.preview,
                                     hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.summary = Gtk.Label(xalign=0)
        self.summary.add_css_class("caption")
        self.summary.add_css_class("dim-label")
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True)
        heading = Gtk.Label(label="Preview", xalign=0)
        heading.add_css_class("heading")
        right.append(heading)
        right.append(prev_sw)
        right.append(self.summary)

        panes = Gtk.Box(spacing=18, homogeneous=True, vexpand=True)
        panes.append(left)
        panes.append(right)

        self.add_mode = Gtk.CheckButton(label="Add to the current labels (replacing those of "
                                              "the same weeks)", active=True)
        self.replace_mode = Gtk.CheckButton(label="Replace all current labels",
                                            group=self.add_mode)
        modes = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        modes.append(self.add_mode)
        modes.append(self.replace_mode)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for m in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{m}")(18)
        box.append(intro)
        box.append(panes)
        box.append(modes)
        return box

    @staticmethod
    def _placeholder(text):
        label = Gtk.Label(label=text, margin_top=18, margin_bottom=18)
        label.add_css_class("dim-label")
        return label

    def _on_paste_clipboard(self, *_):
        clip = Gdk.Display.get_default().get_clipboard()

        def done(c, res):
            try:
                text = c.read_text_finish(res)
            except Exception:  # noqa: BLE001 - nothing usable on the clipboard
                text = None
            if text:
                self.text.get_buffer().set_text(text)
        clip.read_text_async(None, done)

    def _on_order(self, dd, _pspec):
        self.order = list(DateOrder)[dd.get_selected()]
        self.s.config.set("date_order", self.order.value)
        self._update_preview()

    def _update_preview(self):
        buf = self.text.get_buffer()
        pasted = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        rows = parse_import(pasted, self.order, self.s.today.year)
        self._labels = import_labels(rows)
        self.preview.remove_all()
        for r in rows:
            row = Adw.ActionRow()
            icon = Gtk.Image(icon_name="emblem-ok-symbolic" if r.is_label
                             else "action-unavailable-symbolic")
            icon.add_css_class("success" if r.is_label else "dim-label")
            row.add_prefix(icon)
            if r.is_label:
                row.set_title(GLib_escape(r.label))
                row.set_subtitle(f"Line {r.line} \u00b7 week of {short_day(r.week)} {r.week.year}")
            else:
                row.set_title(GLib_escape(r.skipped))
                row.set_subtitle(GLib_escape(f"Line {r.line} \u00b7 "
                                             + r.source.replace("\t", "  \u21e5  ")))
                row.add_css_class("dim-label")
            self.preview.append(row)
        skipped = len(rows) - len(self._labels)
        self.summary.set_text("" if not rows else
                              f"{plural(len(self._labels), 'week')} to label"
                              + (f", {plural(skipped, 'row')} skipped" if skipped else "") + ".")
        self.apply.set_sensitive(bool(self._labels))

    def _on_apply(self, *_):
        if not self._labels:
            return
        n = len(self._labels)
        self.s.import_week_labels(self._labels, self.replace_mode.get_active())
        self.text.get_buffer().set_text("")
        self.toasts.add_toast(Adw.Toast(title=f"Labelled {plural(n, 'week')}", timeout=3))

    # --- current ----------------------------------------------------------

    def _current_page(self):
        self.current = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.current.add_css_class("boxed-list")
        self.current.set_placeholder(self._placeholder("No week labels yet"))
        copy = Gtk.Button(label="Copy for Spreadsheet",
                          tooltip_text="Copy the labels as two tab-separated columns, to edit "
                                       "in a spreadsheet and paste back")
        copy.connect("clicked", self._on_copy)
        self.remove_all = Gtk.Button(label="Remove All")
        self.remove_all.add_css_class("destructive-action")
        self.remove_all.connect("clicked", lambda *_: self.s.replace_week_labels(
            WeekLabels(), "Remove Week Labels"))
        tools = Gtk.Box(spacing=6, halign=Gtk.Align.END)
        tools.append(copy)
        tools.append(self.remove_all)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.append(tools)
        box.append(self.current)
        clamp = Adw.Clamp(maximum_size=640, child=box)
        for m in ("top", "bottom", "start", "end"):
            getattr(clamp, f"set_margin_{m}")(18)
        return Gtk.ScrolledWindow(child=clamp, vexpand=True,
                                  hscrollbar_policy=Gtk.PolicyType.NEVER)

    def _refresh_current(self):
        self.current.remove_all()
        items = self.s.week_labels.sorted()
        for week, label in items:
            row = Adw.ActionRow(title=GLib_escape(label), subtitle=f"Week of {long_day(week)}")
            remove = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                                tooltip_text="Remove This Label")
            remove.add_css_class("flat")
            remove.connect("clicked", lambda _b, w=week: self.s.set_week_label("", w))
            row.add_suffix(remove)
            self.current.append(row)
        self.remove_all.set_sensitive(bool(items))
        self.current_page.set_badge_number(len(items))

    def _on_copy(self, *_):
        text = "\n".join(f"{w.isoformat()}\t{label}" for w, label in self.s.week_labels.sorted())
        Gdk.Display.get_default().get_clipboard().set(text)
        self.toasts.add_toast(Adw.Toast(title="Copied", timeout=2))

    def do_closed(self):
        self.s.disconnect(self._listener)


def GLib_escape(text: str) -> str:
    """Row titles are Pango markup; show the text as typed."""
    from gi.repository import GLib
    return GLib.markup_escape_text(text)
