"""A small native desktop app for the Spanish drill.

    python3 -m drill gui

Deliberately stdlib-only (tkinter), so it runs from a clone with no install
step. One window, one job: show an English prompt, take typed Spanish,
grade it, move on.

Two design choices worth knowing about:

* **Enter does everything.** Type, Enter to answer, Enter to advance. A
  drill you use for fifteen minutes a day should never need the mouse.
* **There is an accent bar.** The grader deliberately never folds ñ
  (`ano`/`año`), and accents are otherwise forgiven but still shown. On a
  US keyboard that combination is punishing, so the characters are one
  click -- or one Ctrl-key -- away.
"""

from __future__ import annotations

import sys
import time
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk

from drill import cloze, speech, store
from drill.grader import grade as grade_attempt
from drill.scheduler import Grade, SchedState, review as reschedule

# --- palette ---------------------------------------------------------------

BG = "#1c1c1e"
CARD = "#2c2c2e"
FG = "#f2f2f7"
MUTED = "#8e8e93"
ACCENT = "#0a84ff"
OK = "#30d158"
BAD = "#ff453a"
WARN = "#ffd60a"

ACCENT_CHARS = ["á", "é", "í", "ó", "ú", "ñ", "ü", "¿", "¡"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


_LAYER_GRADE = {"L2_exact": Grade.GOOD, "L3_accent": Grade.HARD, "L4_close": Grade.HARD}


class DrillApp:
    def __init__(
        self, root: tk.Tk, db_path: Path, deck: str | None, limit: int,
        new_per_day: int | None = None,
    ) -> None:
        self.root = root
        self.conn = store.connect(db_path)
        self.deck = deck
        self.limit = limit
        self.new_per_day = new_per_day
        self.plan: store.DailyQueue | None = None

        self.queue: list[tuple[store.Card, store.SchedRow]] = []
        self.index = 0
        self.correct = 0
        self.answered = 0
        self.awaiting_next = False
        self.started = 0.0
        self.view = "drill"
        self._cloze: cloze.Cloze | None = None

        self._build_ui()
        self._refresh_deck_choices()
        self._load_queue()

    # --- ui ---------------------------------------------------------------

    def _build_ui(self) -> None:
        r = self.root
        r.title("Drill — español")
        r.configure(bg=BG)
        r.minsize(720, 520)

        base = "SF Pro Text" if sys.platform == "darwin" else "Helvetica"
        self.f_prompt = tkfont.Font(family=base, size=26, weight="bold")
        self.f_body = tkfont.Font(family=base, size=15)
        self.f_small = tkfont.Font(family=base, size=12)
        self.f_entry = tkfont.Font(family=base, size=20)

        # header
        head = tk.Frame(r, bg=BG)
        head.pack(fill="x", padx=28, pady=(22, 0))

        self.lbl_deck = tk.Label(head, text="", font=self.f_small, fg=MUTED, bg=BG)
        self.lbl_deck.pack(side="left")

        style = ttk.Style(r)
        style.configure(
            "Deck.TCombobox", fieldbackground=CARD, background=CARD, foreground=FG,
            arrowcolor=FG, bordercolor=CARD, lightcolor=CARD, darkcolor=CARD,
        )
        style.map(
            "Deck.TCombobox",
            fieldbackground=[("readonly", CARD)],
            foreground=[("readonly", FG)],
            background=[("readonly", CARD)],
        )
        r.option_add("*TCombobox*Listbox.background", CARD)
        r.option_add("*TCombobox*Listbox.foreground", FG)
        r.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        r.option_add("*TCombobox*Listbox.selectForeground", FG)

        self.deck_picker = ttk.Combobox(
            head, state="readonly", font=self.f_small, width=18, style="Deck.TCombobox",
        )
        self.deck_picker.pack(side="left", padx=(12, 0))
        self.deck_picker.bind("<<ComboboxSelected>>", self._on_deck_change)

        self.lbl_score = tk.Label(head, text="", font=self.f_small, fg=MUTED, bg=BG)
        self.lbl_score.pack(side="right")

        self.bar = ttk.Progressbar(r, mode="determinate", maximum=100)
        self.bar.pack(fill="x", padx=28, pady=(10, 0))

        # prompt card
        body = tk.Frame(r, bg=CARD, highlightthickness=0)
        body.pack(fill="both", expand=True, padx=28, pady=20)
        self.drill_frame = body

        self.lbl_tag = tk.Label(body, text="", font=self.f_small, fg=MUTED, bg=CARD)
        self.lbl_tag.pack(anchor="w", padx=24, pady=(20, 0))

        self.lbl_prompt = tk.Label(
            body, text="", font=self.f_prompt, fg=FG, bg=CARD,
            wraplength=600, justify="left",
        )
        self.lbl_prompt.pack(anchor="w", padx=24, pady=(10, 18), fill="x")

        # English meaning for a cloze card -- dimmed, shown below the gapped
        # Spanish sentence, before the learner answers. Empty (and takes no
        # visible space) for every other card kind.
        self.lbl_meaning = tk.Label(
            body, text="", font=self.f_small, fg=MUTED, bg=CARD,
            wraplength=600, justify="left",
        )
        self.lbl_meaning.pack(anchor="w", padx=24, pady=(0, 8), fill="x")

        self.entry = tk.Entry(
            body, font=self.f_entry, bg="#3a3a3c", fg=FG, insertbackground=FG,
            relief="flat", highlightthickness=2, highlightbackground="#3a3a3c",
            highlightcolor=ACCENT,
        )
        self.entry.pack(fill="x", padx=24, ipady=10)
        self.entry.bind("<Return>", self._on_enter)
        self.entry.bind("<Tab>", self._toggle_view)

        # accent bar
        acc = tk.Frame(body, bg=CARD)
        acc.pack(anchor="w", padx=22, pady=(12, 0))
        for i, ch in enumerate(ACCENT_CHARS):
            b = tk.Button(
                acc, text=ch, font=self.f_body, fg=FG, bg="#3a3a3c",
                activebackground=ACCENT, activeforeground=FG, relief="flat",
                width=3, highlightthickness=0, bd=0,
                command=lambda c=ch: self._insert(c),
            )
            b.pack(side="left", padx=2)
            self.root.bind(f"<Control-Key-{i+1}>", lambda _e, c=ch: self._insert(c))

        # On-demand audio hint -- never autoplays, this stays a typing drill.
        self.btn_speak = None
        if speech.is_available():
            self.btn_speak = tk.Button(
                acc, text="🔊", font=self.f_body, fg=FG, bg="#3a3a3c",
                activebackground=ACCENT, activeforeground=FG, relief="flat",
                width=3, highlightthickness=0, bd=0,
                command=self._speak_current,
            )
            self.btn_speak.pack(side="left", padx=(10, 2))
            self.root.bind("<Control-r>", lambda _e: self._speak_current())

        self.lbl_verdict = tk.Label(
            body, text="", font=self.f_body, fg=FG, bg=CARD,
            wraplength=600, justify="left",
        )
        self.lbl_verdict.pack(anchor="w", padx=24, pady=(16, 0), fill="x")

        self.lbl_target = tk.Label(
            body, text="", font=self.f_body, fg=ACCENT, bg=CARD,
            wraplength=600, justify="left",
        )
        self.lbl_target.pack(anchor="w", padx=24, pady=(4, 0), fill="x")

        self.lbl_note = tk.Label(
            body, text="", font=self.f_small, fg=MUTED, bg=CARD,
            wraplength=600, justify="left",
        )
        self.lbl_note.pack(anchor="w", padx=24, pady=(6, 20), fill="x")

        self.lbl_hint = tk.Label(
            r, text="Enter para responder · Ctrl-1..9 para acentos · Tab para progreso",
            font=self.f_small, fg=MUTED, bg=BG,
        )
        self.lbl_hint.pack(pady=(0, 16))

        self.entry.focus_set()

        self._build_progress_view()
        r.bind("<Tab>", self._toggle_view)

    def _insert(self, ch: str) -> str:
        self.entry.insert(tk.INSERT, ch)
        self.entry.focus_set()
        return "break"

    def _speak_current(self) -> None:
        if not self.queue or self.index >= len(self.queue):
            return
        card, _row = self.queue[self.index]
        if card.accept:
            speech.speak(card.accept[0])

    # --- queue ------------------------------------------------------------

    def _load_queue(self) -> None:
        # Same pacing as `drill daily`. Using due_cards here would re-introduce
        # a fresh batch of new cards every time the window is opened, with no
        # per-day cap -- which is the wall this pacing exists to prevent.
        now = _now()
        per_day = self.new_per_day
        if per_day is None:
            per_day = store.suggested_new_per_day(self.conn, now, deck=self.deck)
        q = store.daily_queue(
            self.conn, now, deck=self.deck, new_per_day=per_day,
            max_cards=self.limit,
        )
        self.queue = list(q.items)
        self.plan = q
        self.index = 0
        if not self.queue:
            self._show_empty()
        else:
            self._show_card()

    def _show_empty(self) -> None:
        stats = store.deck_stats(self.conn, self.deck)
        self._cloze = None
        self.lbl_tag.config(text="")
        self.lbl_meaning.config(text="")
        if stats.get("total", 0) == 0:
            self.lbl_prompt.config(text="No hay tarjetas")
            self.lbl_verdict.config(
                text="Importa una baraja primero:\n"
                "python3 -m drill import data/peninsular_contrast.jsonl",
                fg=MUTED,
            )
        else:
            self.lbl_prompt.config(text="¡Nada pendiente!")
            self.lbl_verdict.config(
                text=f"{stats['total']} tarjetas · {stats['new']} nuevas · "
                f"{stats['learning']} aprendiendo",
                fg=MUTED,
            )
        self.lbl_target.config(text="")
        self.lbl_note.config(text="")
        self.entry.pack_forget()
        self.bar["value"] = 100

    def _show_card(self) -> None:
        card, _row = self.queue[self.index]
        self.awaiting_next = False
        plan = ""
        if self.plan is not None and self.plan.new_introduced:
            reviews = len(self.queue) - self.plan.new_introduced
            plan = f"  ·  {reviews} repaso + {self.plan.new_introduced} nuevas"
        self.lbl_deck.config(
            text=f"{card.deck}  ·  {self.index + 1}/{len(self.queue)}{plan}"
        )
        self.lbl_tag.config(text="  ".join(f"#{t}" for t in card.tags))
        if cloze.is_cloze(card.kind):
            self._cloze = cloze.parse(card.prompt_en)
            self.lbl_prompt.config(text=cloze.render_question(self._cloze))
            self.lbl_meaning.config(text=self._cloze.meaning_en or "")
        else:
            self._cloze = None
            self.lbl_prompt.config(text=card.prompt_en)
            self.lbl_meaning.config(text="")
        self.lbl_verdict.config(text="")
        self.lbl_target.config(text="")
        self.lbl_note.config(text="")
        self.entry.delete(0, tk.END)
        self.entry.config(highlightbackground="#3a3a3c")
        self.entry.focus_set()
        self.bar["value"] = 100.0 * self.index / max(1, len(self.queue))
        self._update_score()
        self.started = time.monotonic()

    def _update_score(self) -> None:
        if self.answered:
            pct = 100.0 * self.correct / self.answered
            self.lbl_score.config(text=f"{self.correct}/{self.answered}  ·  {pct:.0f}%")
        else:
            self.lbl_score.config(text="")

    # --- interaction ------------------------------------------------------

    def _on_enter(self, _event: object = None) -> str:
        if self.awaiting_next:
            self._advance()
        else:
            self._submit()
        return "break"

    def _submit(self) -> None:
        if not self.queue:
            return
        card, row = self.queue[self.index]
        attempt = self.entry.get().strip()
        if not attempt:
            return

        latency_ms = int((time.monotonic() - self.started) * 1000)
        verdict = grade_attempt(attempt, accept=card.accept, reject=card.reject)
        sched_grade = (
            Grade.AGAIN if not verdict.accepted else _LAYER_GRADE.get(verdict.layer, Grade.GOOD)
        )

        self.answered += 1
        if verdict.accepted:
            self.correct += 1

        colour = OK if verdict.accepted else BAD
        if verdict.accepted and verdict.layer in ("L3_accent", "L4_close"):
            colour = WARN
        self.entry.config(highlightbackground=colour)
        self.lbl_verdict.config(text=verdict.reason, fg=colour)
        if self._cloze is not None:
            # The whole point of a cloze is reading the completed sentence,
            # win or lose -- fill with what they typed when accepted, with
            # the reference answer when not.
            filled = cloze.render_filled(
                self._cloze, attempt if verdict.accepted else card.accept[0]
            )
            self.lbl_target.config(text=filled)
        else:
            self.lbl_target.config(
                text="" if verdict.accepted else card.accept[0]
            )
        note_bits = [b for b in (verdict.detail, card.note) if b]
        self.lbl_note.config(text="\n".join(note_bits))

        before = row.interval_days
        nxt = reschedule(
            SchedState(
                due_at=row.due_at, interval_days=row.interval_days, ease=row.ease,
                reps=row.reps, lapses=row.lapses, state=row.state,
                last_reviewed_at=row.last_reviewed_at,
            ),
            sched_grade,
            _now(),
        )
        store.save_sched(self.conn, store.SchedRow(card_id=card.card_id, **nxt.__dict__))
        store.record_review(
            self.conn,
            card_id=card.card_id,
            reviewed_at=_now(),
            grade=int(sched_grade),
            latency_ms=latency_ms,
            raw_text=attempt,
            accepted=verdict.accepted,
            layer=verdict.layer,
            interval_before=before,
            interval_after=nxt.interval_days,
        )
        self.conn.commit()

        self.awaiting_next = True
        self._update_score()
        self.lbl_hint.config(text="Enter para continuar")

    def _advance(self) -> None:
        self.index += 1
        self.lbl_hint.config(text="Enter para responder · Ctrl-1..9 para acentos")
        if self.index >= len(self.queue):
            self._finish()
        else:
            self._show_card()

    def _finish(self) -> None:
        pct = 100.0 * self.correct / max(1, self.answered)
        self.lbl_deck.config(text="")
        self.lbl_tag.config(text="")
        self.lbl_prompt.config(text="¡Hecho!")
        self.lbl_verdict.config(
            text=f"{self.correct} de {self.answered} correctas ({pct:.0f}%)", fg=FG
        )
        self.lbl_target.config(text="")
        tail = "Cierra la ventana o vuelve a abrir para más."
        if self.plan is not None and self.plan.backlog:
            tail = f"Quedan {self.plan.backlog} repasos pendientes — vuelve a abrir."
        self.lbl_note.config(text=tail)
        self.entry.pack_forget()
        self.bar["value"] = 100

    # --- progress view ------------------------------------------------------

    def _build_progress_view(self) -> None:
        prog = tk.Frame(self.root, bg=CARD, highlightthickness=0)
        self.progress_frame = prog

        tk.Label(
            prog, text="Progreso", font=self.f_prompt, fg=FG, bg=CARD,
        ).pack(anchor="w", padx=24, pady=(20, 12))

        self.lbl_prog_session = tk.Label(
            prog, text="", font=self.f_body, fg=FG, bg=CARD, justify="left",
        )
        self.lbl_prog_session.pack(anchor="w", padx=24, pady=(0, 4))

        self.lbl_prog_collection = tk.Label(
            prog, text="", font=self.f_small, fg=MUTED, bg=CARD, justify="left",
        )
        self.lbl_prog_collection.pack(anchor="w", padx=24, pady=(0, 18))

        tk.Label(
            prog, text="Etiquetas más débiles", font=self.f_body, fg=FG, bg=CARD,
        ).pack(anchor="w", padx=24)

        self.lbl_tags_empty = tk.Label(
            prog, text="", font=self.f_small, fg=MUTED, bg=CARD,
            wraplength=600, justify="left",
        )
        self.lbl_tags_empty.pack(anchor="w", padx=24, pady=(4, 4))

        tags_frame = tk.Frame(prog, bg=CARD)
        tags_frame.pack(anchor="w", padx=24, fill="x", pady=(0, 18))
        self.tag_rows: list[tk.Label] = []
        for i in range(8):
            lbl = tk.Label(tags_frame, text="", font=self.f_small, fg=FG, bg=CARD, anchor="w")
            lbl.grid(row=i, column=0, sticky="w")
            self.tag_rows.append(lbl)

        tk.Label(
            prog, text="Tarjetas más difíciles", font=self.f_body, fg=FG, bg=CARD,
        ).pack(anchor="w", padx=24)

        self.lbl_cards_empty = tk.Label(
            prog, text="", font=self.f_small, fg=MUTED, bg=CARD,
            wraplength=600, justify="left",
        )
        self.lbl_cards_empty.pack(anchor="w", padx=24, pady=(4, 4))

        cards_frame = tk.Frame(prog, bg=CARD)
        cards_frame.pack(anchor="w", padx=24, fill="x", pady=(0, 20))
        self.card_rows: list[tk.Label] = []
        for i in range(5):
            lbl = tk.Label(cards_frame, text="", font=self.f_small, fg=FG, bg=CARD, anchor="w")
            lbl.grid(row=i, column=0, sticky="w")
            self.card_rows.append(lbl)

    def _refresh_progress(self) -> None:
        self.lbl_prog_session.config(
            text=f"Sesión: {self.correct}/{self.answered} correctas"
        )
        stats = store.deck_stats(self.conn, self.deck)
        self.lbl_prog_collection.config(
            text=f"Colección: {stats['total']} total · {stats['new']} nuevas · "
            f"{stats['learning']} aprendiendo · {stats['review']} repaso · "
            f"{stats['lapsed']} atrasadas"
        )

        # Same >=3-attempts floor as the CLI (`drill stats`) -- a ranking
        # built on one or two answers isn't honest, so below that floor we
        # say so instead of pretending we know the weak spots.
        tag_stats = [
            t for t in store.tag_performance(self.conn, deck=self.deck) if t.attempts >= 3
        ][:8]
        if tag_stats:
            self.lbl_tags_empty.config(text="")
            for i, lbl in enumerate(self.tag_rows):
                if i < len(tag_stats):
                    t = tag_stats[i]
                    lbl.config(text=f"{t.tag:<16}{t.accuracy:>5.0%}   {t.correct}/{t.attempts}")
                    lbl.grid()
                else:
                    lbl.grid_remove()
        else:
            self.lbl_tags_empty.config(
                text="Sigue practicando — aún no hay datos suficientes"
            )
            for lbl in self.tag_rows:
                lbl.grid_remove()

        hard = store.hardest_cards(self.conn, deck=self.deck, limit=5)
        if hard:
            self.lbl_cards_empty.config(text="")
            for i, lbl in enumerate(self.card_rows):
                if i < len(hard):
                    card, attempts, misses = hard[i]
                    prompt = card.prompt_en
                    if len(prompt) > 40:
                        prompt = prompt[:37] + "..."
                    lbl.config(text=f"{prompt}   ·   {misses}/{attempts} fallos")
                    lbl.grid()
                else:
                    lbl.grid_remove()
        else:
            self.lbl_cards_empty.config(
                text="Sigue practicando — aún no hay datos suficientes"
            )
            for lbl in self.card_rows:
                lbl.grid_remove()

    def _toggle_view(self, _event: object = None) -> str:
        if self.view == "drill":
            self.view = "progress"
            self.drill_frame.pack_forget()
            self._refresh_progress()
            self.progress_frame.pack(fill="both", expand=True, padx=28, pady=20)
            self.root.focus_set()
            self.lbl_hint.config(text="Tab para volver al ejercicio")
        else:
            self.view = "drill"
            self.progress_frame.pack_forget()
            self.drill_frame.pack(fill="both", expand=True, padx=28, pady=20)
            if self.queue:
                self.entry.focus_set()
            self.lbl_hint.config(
                text="Enter para continuar" if self.awaiting_next
                else "Enter para responder · Ctrl-1..9 para acentos · Tab para progreso"
            )
        return "break"

    # --- deck picker ---------------------------------------------------------

    def _deck_names(self) -> list[str]:
        rows = self.conn.execute("SELECT DISTINCT deck FROM card ORDER BY deck").fetchall()
        return [row[0] for row in rows]

    def _refresh_deck_choices(self) -> None:
        names = self._deck_names()
        self.deck_picker["values"] = ["Todas"] + names
        self.deck_picker.set(self.deck if self.deck is not None else "Todas")

    def _on_deck_change(self, _event: object = None) -> None:
        value = self.deck_picker.get()
        self.deck = None if value == "Todas" else value
        self._load_queue()
        if self.view == "progress":
            self._refresh_progress()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass


def run(
    db_path: Path | None = None, deck: str | None = None, limit: int = 40,
    new_per_day: int | None = None,
) -> int:
    root = tk.Tk()
    app = DrillApp(root, db_path or store.DEFAULT_DB, deck, limit, new_per_day)

    def on_close() -> None:
        app.close()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.bind("<Escape>", lambda _e: on_close())
    # macOS opens Tk windows behind the terminal; force it forward once.
    root.lift()
    root.attributes("-topmost", True)
    root.after(200, lambda: root.attributes("-topmost", False))
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
