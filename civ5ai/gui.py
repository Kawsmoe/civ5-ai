"""Desktop GUI (PyQt6): py gui.py

The agent plays in a background thread (runner.Runner); everything it reports
arrives here through a Qt signal, so the window stays responsive.
"""
import html
import json
import sys
import threading
import urllib.request
from pathlib import Path

if __package__ in (None, ""):
    # run as a plain file (e.g. VS Code's Run button on this file): make the package importable
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "civ5ai"

from PyQt6.QtCore import QObject, QSettings, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QTextCursor
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QSplitter, QTextBrowser,
    QToolButton, QVBoxLayout, QWidget,
)

from . import lessons
from .agent import DEFAULT_MODEL, LESSONS_EVERY, MODEL_OPTIONS, OLLAMA_URL, PLAN_FILE
from .runner import Runner

OK, ERR, WARN, MODEL, MUTED = "#2e9d5b", "#d2453b", "#c08a1e", "#7a68e0", "#8a8f99"

STYLE = """
QFrame#card { border: 1px solid palette(mid); border-radius: 10px; background: palette(base); }
QLabel#cardTitle { color: palette(placeholder-text); font-size: 9pt; font-weight: 600; letter-spacing: 1px; }
QLabel#turn { font-size: 20pt; font-weight: 700; }
QLabel#statKey { color: palette(placeholder-text); font-size: 8pt; }
QLabel#statValue { font-size: 12pt; font-weight: 650; }
QLabel#status { padding: 3px 10px; border-radius: 9px; font-weight: 600; }
QPushButton#primary { font-weight: 600; padding: 5px 14px; }
QTextBrowser, QPlainTextEdit { border: 1px solid palette(mid); border-radius: 8px; }
"""
STATUS_COLORS = {"playing": OK, "connecting": MODEL, "waiting": MODEL, "reviewing": MODEL,
                 "stopping": WARN, "stopped": MUTED, "idle": MUTED}


def ollama_models():
    """Installed models: [(name, label)], marking the one loaded in GPU memory."""
    base = OLLAMA_URL.rsplit("/api/", 1)[0]
    with urllib.request.urlopen(base + "/api/tags", timeout=5) as r:
        tags = json.load(r)["models"]
    try:
        with urllib.request.urlopen(base + "/api/ps", timeout=5) as r:
            loaded = {m["name"] for m in json.load(r)["models"]}
    except OSError:
        loaded = set()
    return [(m["name"], f"{m['name']}  ({m.get('details', {}).get('parameter_size', '?')}, "
                        f"{m['size'] / 2**30:.1f} GB{', loaded' if m['name'] in loaded else ''})") for m in tags]


class Bridge(QObject):
    """Carries agent events from the worker thread to the GUI thread."""
    event = pyqtSignal(str, str, dict)


def card(title):
    """A titled panel; returns (frame, its layout)."""
    frame = QFrame(objectName="card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(12, 10, 12, 12)
    layout.setSpacing(6)
    layout.addWidget(QLabel(title.upper(), objectName="cardTitle"))
    return frame, layout


def bullet_label(empty="–"):
    label = QLabel(empty)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


def set_bullets(label, items, empty, color=None):
    if not items:
        label.setText(f"<span style='color:{MUTED}'><i>{html.escape(empty)}</i></span>")
        return
    css = (f"color:{color};" if color else "") + "margin:0 0 4px 0"
    label.setText("".join(f"<p style='{css}'>• {html.escape(str(i))}</p>" for i in items))


class LessonsDialog(QDialog):
    def __init__(self, parent, current):
        super().__init__(parent)
        self.setWindowTitle("Edit lessons")
        self.resize(560, 380)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("One lesson per line. These are shown to the model every turn."))
        self.edit = QPlainTextEdit("\n".join(current))
        layout.addWidget(self.edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def lessons(self):
        return [line.lstrip("-* ").strip() for line in self.edit.toPlainText().splitlines() if line.strip()]


class OpeningDialog(QDialog):
    """Asked on Start: the direction the model gets on its first turn."""

    def __init__(self, parent, text, model):
        super().__init__(parent)
        self.setWindowTitle("Start the game")
        self.resize(560, 300)
        layout = QVBoxLayout(self)
        intro = QLabel(f"<b>Opening message for {html.escape(model)}</b><br>"
                       f"<span style='color:{MUTED}'>What should the model aim for this game? For example: "
                       "\"You are Germany on Deity. Go for a science victory, expand to 4 cities early, and keep "
                       "the barbarians away.\" Leave it empty to let the model decide everything.</span>")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.edit = QPlainTextEdit(text)
        layout.addWidget(self.edit, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        start = buttons.addButton("Start game", QDialogButtonBox.ButtonRole.AcceptRole)
        start.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.edit.setFocus()
        self.edit.moveCursor(QTextCursor.MoveOperation.End)

    def text(self):
        return self.edit.toPlainText().strip()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Civ V Agent")
        self.resize(1440, 900)
        self.settings = QSettings("civ5ai", "gui")
        self.bridge = Bridge()
        self.bridge.event.connect(self.on_event)
        self.runner = None
        self.thread = None
        self.prompts = {}  # turn -> what the model saw
        # Qt rich text has no transparency, so pick a solid bubble colour for light or dark mode
        dark = self.palette().base().color().lightness() < 128
        self.bubble = "#2b2748" if dark else "#eeecfb"

        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(10, 8, 10, 10)
        outer.addLayout(self.build_toolbar())
        self.banner = QLabel()
        self.banner.setStyleSheet(f"color:{ERR}; padding:4px")
        self.banner.hide()
        outer.addWidget(self.banner)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.build_left())
        splitter.addWidget(self.build_feed())
        splitter.addWidget(self.build_right())
        splitter.setSizes([320, 760, 360])
        splitter.setStretchFactor(1, 1)
        outer.addWidget(splitter, 1)
        self.setCentralWidget(root)

        self.load_models()
        self.load_files()
        self.timer = QTimer(self, interval=500, timeout=self.refresh_controls)
        self.timer.start()
        self.refresh_controls()

    # --- layout ---------------------------------------------------------------------

    def build_toolbar(self):
        bar = QHBoxLayout()
        title = QLabel("Civ V Agent")
        title.setFont(QFont(title.font().family(), 13, QFont.Weight.Bold))
        bar.addWidget(title)
        self.status = QLabel("idle", objectName="status")
        bar.addWidget(self.status)
        self.set_status("idle")
        bar.addStretch(1)

        bar.addWidget(QLabel("Model"))
        self.model = QComboBox(minimumWidth=280)
        bar.addWidget(self.model)
        refresh = QToolButton(text="↻", toolTip="Reload the list of installed Ollama models")
        refresh.clicked.connect(self.load_models)
        bar.addWidget(refresh)

        def spin(label, lo, hi, step, value, tip):
            bar.addWidget(QLabel(label))
            box = QSpinBox(minimum=lo, maximum=hi, singleStep=step, value=value, toolTip=tip)
            bar.addWidget(box)
            return box

        self.ctx = spin("Context", 4096, 65536, 1024, int(self.settings.value("ctx", MODEL_OPTIONS["num_ctx"])),
                        "Model context size in tokens. Lower it if the model doesn't fit on the GPU next to the game.")
        self.turns = spin("Turns", 1, 1000, 10, int(self.settings.value("turns", 500)), "Stop after this many turns.")
        self.lessons_every = spin("Lessons every", 0, 100, 1, int(self.settings.value("lessons_every", LESSONS_EVERY)),
                                  "Turns between reviews that update lessons.md (0 = off).")

        self.start_btn = QPushButton("Start", objectName="primary")
        self.start_btn.clicked.connect(self.start)
        self.stop_turn_btn = QPushButton("Stop after turn")
        self.stop_turn_btn.clicked.connect(lambda: self.stop(now=False))
        self.stop_now_btn = QPushButton("Stop now")
        self.stop_now_btn.setStyleSheet(f"color:{ERR}")
        self.stop_now_btn.clicked.connect(lambda: self.stop(now=True))
        for b in (self.start_btn, self.stop_turn_btn, self.stop_now_btn):
            bar.addWidget(b)
        return bar

    def build_left(self):
        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 6, 0)
        col.setSpacing(10)

        frame, lay = card("Empire")
        self.turn_label = QLabel("–", objectName="turn")
        self.civ_label = QLabel("no game yet")
        self.civ_label.setStyleSheet(f"color:{MUTED}")
        row = QHBoxLayout()
        row.addWidget(self.turn_label)
        row.addWidget(self.civ_label, 1, Qt.AlignmentFlag.AlignBottom)
        lay.addLayout(row)
        grid = QGridLayout()
        grid.setSpacing(6)
        self.stat_values = {}
        for i, key in enumerate(["Gold", "Science", "Culture", "Faith", "Happiness", "Units"]):
            box = QVBoxLayout()
            box.setSpacing(0)
            box.addWidget(QLabel(key, objectName="statKey"))
            value = QLabel("–", objectName="statValue")
            box.addWidget(value)
            self.stat_values[key] = value
            grid.addLayout(box, i // 3, i % 3)
        lay.addLayout(grid)
        self.research = QLabel("")
        self.research.setWordWrap(True)
        self.research.setStyleSheet(f"color:{MUTED}")
        lay.addWidget(self.research)
        col.addWidget(frame)

        self.lists = {}
        for key, title in [("todo", "To do this turn"), ("threats", "Threats"), ("opportunities", "Opportunities"),
                           ("victory", "Victory race"), ("cities", "Cities"), ("units", "Units")]:
            frame, lay = card(title)
            label = bullet_label()
            lay.addWidget(label)
            self.lists[key] = label
            col.addWidget(frame)
        col.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(inner)
        scroll.setMinimumWidth(280)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return scroll

    def build_feed(self):
        frame, lay = card("Activity")
        self.follow = QCheckBox("Follow the newest", checked=True)
        lay.addWidget(self.follow)
        self.feed = QTextBrowser()
        self.feed.setOpenLinks(False)
        self.feed.document().setMaximumBlockCount(6000)
        self.feed.setHtml(f"<p style='color:{MUTED}'><i>Pick a model and press Start. Load a game in Civ V "
                          "first, and close FireTuner.</i></p>")
        lay.addWidget(self.feed, 1)
        return frame

    def build_right(self):
        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(6, 0, 0, 0)
        col.setSpacing(10)

        frame, lay = card("Talk to the model")
        self.msg = QPlainTextEdit(placeholderText="Direction for the model while it plays, e.g. \"Settle the river "
                                                  "to the north next.\" It is sent at the start of the next turn. "
                                                  "Ctrl+Enter sends.")
        self.msg.setFixedHeight(90)
        lay.addWidget(self.msg)
        row = QHBoxLayout()
        send = QPushButton("Send", objectName="primary")
        send.clicked.connect(self.send_message)
        row.addWidget(send)
        self.send_note = QLabel("")
        self.send_note.setStyleSheet(f"color:{MUTED}")
        self.send_note.setWordWrap(True)
        row.addWidget(self.send_note, 1)
        lay.addLayout(row)
        col.addWidget(frame)

        frame, lay = card("Plan")
        self.plan = bullet_label("none yet")
        lay.addWidget(self.plan)
        clear = QPushButton("Clear plan", toolTip="Do this when you start a new game")
        clear.clicked.connect(self.clear_plan)
        lay.addWidget(clear, 0, Qt.AlignmentFlag.AlignLeft)
        col.addWidget(frame)

        frame, lay = card("Lessons")
        self.lessons_label = bullet_label("none yet")
        lay.addWidget(self.lessons_label)
        edit = QPushButton("Edit lessons…")
        edit.clicked.connect(self.edit_lessons)
        lay.addWidget(edit, 0, Qt.AlignmentFlag.AlignLeft)
        col.addWidget(frame)

        frame, lay = card("What the model sees")
        row = QHBoxLayout()
        row.addWidget(QLabel("Turn"))
        self.prompt_turn = QComboBox()
        self.prompt_turn.currentIndexChanged.connect(self.show_prompt)
        row.addWidget(self.prompt_turn, 1)
        lay.addLayout(row)
        self.prompt_view = QPlainTextEdit(readOnly=True)
        self.prompt_view.setFont(QFont("Consolas", 9))
        self.prompt_view.setPlaceholderText("The full prompt for each turn appears here.")
        self.prompt_view.setMinimumHeight(260)
        lay.addWidget(self.prompt_view, 1)
        col.addWidget(frame, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(inner)
        scroll.setMinimumWidth(300)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return scroll

    # --- models, files, controls ------------------------------------------------------

    def load_models(self):
        keep = self.model.currentData() or self.settings.value("model", DEFAULT_MODEL)
        self.model.clear()
        try:
            models = ollama_models()
            self.banner.hide()
        except OSError as e:
            models = [(DEFAULT_MODEL, DEFAULT_MODEL)]
            self.show_banner(f"Ollama isn't reachable ({e}). Start Ollama, then press ↻.")
        for name, label in models:
            self.model.addItem(label, name)
        index = self.model.findData(keep)
        self.model.setCurrentIndex(index if index >= 0 else 0)

    def load_files(self):
        self.show_plan(PLAN_FILE.read_text(encoding="utf-8") if PLAN_FILE.exists() else "")
        self.show_lessons(lessons.load())

    def show_banner(self, text):
        self.banner.setText(text)
        self.banner.setVisible(bool(text))

    def set_status(self, status):
        color = STATUS_COLORS.get(status, MUTED)
        self.status.setText(status)
        self.status.setStyleSheet(f"color:{color}; border:1px solid {color}")

    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def refresh_controls(self):
        running = self.running
        self.start_btn.setEnabled(not running)
        self.stop_turn_btn.setEnabled(running)
        self.stop_now_btn.setEnabled(running)
        for w in (self.model, self.ctx, self.turns, self.lessons_every):
            w.setEnabled(not running)
        queued = self.runner.messages.qsize() if running else 0
        if running:
            self.send_note.setText(f"{queued} message(s) waiting for the next turn" if queued else "")

    def start(self):
        if self.running:
            return
        model = self.model.currentData() or DEFAULT_MODEL
        draft = self.msg.toPlainText().strip() or self.settings.value("opening", "")
        dialog = OpeningDialog(self, draft, model)
        if not dialog.exec():
            return  # cancelled: don't start
        opening = dialog.text()
        for key, value in [("model", model), ("ctx", self.ctx.value()), ("turns", self.turns.value()),
                           ("lessons_every", self.lessons_every.value()), ("opening", opening)]:
            self.settings.setValue(key, value)
        self.msg.clear()
        self.send_note.setText("")
        self.runner = Runner(model=model, ctx=self.ctx.value(), turns=self.turns.value(),
                             lessons_every=self.lessons_every.value(), say=opening, on_event=self.emit)
        self.thread = threading.Thread(target=self.run_agent, daemon=True)
        self.thread.start()
        self.refresh_controls()

    def run_agent(self):
        try:
            self.runner.run()
        except Exception:  # already reported as an error event by the runner
            pass

    def stop(self, now):
        if self.running:
            self.runner.request_stop(now=now)

    def emit(self, kind, text="", **data):
        """Called from the agent's thread; hands the event to the GUI thread."""
        self.bridge.event.emit(kind, text, data)

    def send_message(self):
        text = self.msg.toPlainText().strip()
        if not text:
            return
        if not self.running:
            self.send_note.setText("Not playing yet: press Start, and this text will be offered as the opening message.")
            return
        self.runner.send(text)
        self.msg.clear()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and e.modifiers() & Qt.KeyboardModifier.ControlModifier \
                and self.msg.hasFocus():
            self.send_message()
        else:
            super().keyPressEvent(e)

    def clear_plan(self):
        if QMessageBox.question(self, "Clear plan", "Clear the plan? Do this when you start a new game.") \
                != QMessageBox.StandardButton.Yes:
            return
        if PLAN_FILE.exists():
            PLAN_FILE.unlink()
        if self.running and self.runner.agent:
            self.runner.agent.plan = ""
        self.show_plan("")

    def edit_lessons(self):
        dialog = LessonsDialog(self, lessons.load())
        if dialog.exec():
            kept = lessons.save(dialog.lessons(), "edited by you")
            if self.running and self.runner.agent:
                self.runner.agent.lessons = kept
            self.show_lessons(kept)

    def show_plan(self, plan):
        set_bullets(self.plan, [plan] if plan else [], "none yet")

    def show_lessons(self, items):
        set_bullets(self.lessons_label, items, "none yet")

    def show_prompt(self):
        self.prompt_view.setPlainText(self.prompts.get(self.prompt_turn.currentData(), ""))

    # --- events from the agent ---------------------------------------------------------

    def on_event(self, kind, text, data):
        if kind == "status":
            self.set_status(data.get("status", ""))
            if not text:
                return
        if kind == "turn":
            self.show_turn(data, text)
            self.append(f"<h3 style='margin:14px 0 4px 0'>Turn {data.get('turn')}</h3>")
            return
        if kind == "lessons":
            self.show_lessons(data.get("lessons", []))
        if kind == "plan":
            self.show_plan(data.get("plan", ""))
            self.append(self.line(MODEL, "P", f"New plan: {html.escape(text)}"))
            return
        if kind == "action":
            ok = data.get("ok", False)
            head = f"<b>{html.escape(data.get('tool') or 'action')}</b>"
            args = data.get("args") or {}
            if args:
                head += f" <span style='color:{MUTED}'>" + html.escape(
                    ", ".join(f"{k}={v}" for k, v in args.items())) + "</span>"
            if data.get("auto"):
                head += f" <span style='color:{MUTED}'>[auto]</span>"
            result = data.get("result") or text
            for prefix in ("ok:", "error:"):
                if result.startswith(prefix):
                    result = result[len(prefix):].strip()
            body = head + "<br>" + (html.escape(result) if ok else f"<span style='color:{ERR}'>{html.escape(result)}</span>")
            self.append(self.line(OK if ok else ERR, "✓" if ok else "✗", body))
        elif kind == "model":
            self.append(f"<table width='100%' cellpadding='7' style='margin:4px 0; background-color:{self.bubble}'>"
                        f"<tr><td><span style='color:{MODEL}'><b>Model</b></span><br>"
                        f"{html.escape(text).replace(chr(10), '<br>')}</td></tr></table>")
        elif kind in ("warn", "error"):
            color = WARN if kind == "warn" else ERR
            self.append(self.line(color, "!", f"<span style='color:{color}'>{html.escape(text)}</span>"))
        else:
            self.append(self.line(MUTED, "•", f"<span style='color:{MUTED}'>{html.escape(text)}</span>"))

    @staticmethod
    def line(color, icon, body):
        return (f"<table cellpadding='2' style='margin:2px 0'><tr><td width='20' valign='top' "
                f"style='color:{color}'><b>{icon}</b></td><td>{body}</td></tr></table>")

    def append(self, fragment):
        if self.feed.document().toPlainText().startswith("Pick a model"):
            self.feed.clear()
        bar = self.feed.verticalScrollBar()
        cursor = self.feed.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(fragment)
        cursor.insertBlock()
        if self.follow.isChecked():
            bar.setValue(bar.maximum())

    def show_turn(self, d, text):
        self.turn_label.setText(f"Turn {d.get('turn')}")
        self.civ_label.setText(d.get("civ", ""))

        def signed(n):
            return f"{n:+}" if isinstance(n, (int, float)) else str(n)

        values = {"Gold": (f"{d.get('gold')} ({signed(d.get('gold_rate'))})", (d.get("gold_rate") or 0) < 0),
                  "Science": (f"+{d.get('science')}", False), "Culture": (f"+{d.get('culture')}", False),
                  "Faith": (f"+{d.get('faith')}", False),
                  "Happiness": (signed(d.get("happiness")), (d.get("happiness") or 0) < 0),
                  "Units": (str(len(d.get("units", []))), False)}
        for key, (value, bad) in values.items():
            self.stat_values[key].setText(value)
            self.stat_values[key].setStyleSheet(f"color:{ERR}" if bad else "")
        research = d.get("research")
        self.research.setText(f"Researching {research.replace('TECH_', '').replace('_', ' ').title()} "
                              f"({d.get('research_turns')} turns)" if research else "Researching nothing")
        set_bullets(self.lists["todo"], d.get("todo"), "nothing required")
        set_bullets(self.lists["threats"], d.get("threats"), "none", ERR)
        set_bullets(self.lists["opportunities"], d.get("opportunities"), "none", OK)
        set_bullets(self.lists["victory"], d.get("victory"), "–")
        set_bullets(self.lists["cities"], [
            f"{c['name']} — pop {c['pop']}, " + (f"building {c['producing']} ({c['turns']}t)" if c["producing"]
                                                  else "building nothing") for c in d.get("cities", [])], "none yet")
        set_bullets(self.lists["units"], [f"{u['type']} #{u['id']} at {u['where']}, {u['hp']} hp"
                                          for u in d.get("units", [])], "none")
        if "plan" in d:
            self.show_plan(d["plan"])
        if d.get("lessons"):
            self.show_lessons(d["lessons"])
        self.prompts[d.get("turn")] = text
        self.prompt_turn.blockSignals(True)
        self.prompt_turn.insertItem(0, f"Turn {d.get('turn')}", d.get("turn"))
        self.prompt_turn.setCurrentIndex(0)
        self.prompt_turn.blockSignals(False)
        self.show_prompt()

    def closeEvent(self, e):
        if self.running:
            answer = QMessageBox.question(self, "Quit", "The agent is still playing. Stop it and quit?")
            if answer != QMessageBox.StandardButton.Yes:
                e.ignore()
                return
            self.runner.request_stop(now=True)
            self.thread.join(timeout=15)
        e.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # follows Windows light/dark mode
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
