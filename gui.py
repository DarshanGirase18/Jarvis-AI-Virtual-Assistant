import queue
import time
import tkinter as tk
from tkinter import ttk


class JarvisGUI:
    """Futuristic control-panel interface for the assistant."""

    COLORS = {
        "bg": "#040b14",
        "panel": "#091624",
        "panel_alt": "#0b1c2d",
        "border": "#1d4d68",
        "accent": "#6ef2ff",
        "accent_soft": "#37b9d6",
        "warning": "#ffb454",
        "text": "#e9fbff",
        "muted": "#6f98ad",
        "success": "#66f7c5",
        "danger": "#ff7a8d",
        "console": "#06111d",
    }

    def __init__(
        self,
        on_start,
        on_stop,
        on_hide,
        on_show,
        on_test_mic,
        on_select_mic,
        on_test_voice,
        on_wake_test,
    ) -> None:
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_hide = on_hide
        self.on_show = on_show
        self.on_test_mic = on_test_mic
        self.on_select_mic = on_select_mic
        self.on_test_voice = on_test_voice
        self.on_wake_test = on_wake_test

        self.root = tk.Tk()
        self.root.title("JARVIS AI Assistant")
        self.root.geometry("1180x760")
        self.root.minsize(980, 640)
        self.root.configure(bg=self.COLORS["bg"])
        self.root.protocol("WM_DELETE_WINDOW", self._close_to_background)

        self._events: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self._listening = False
        self._current_status = "Stopped"
        self._glow_phase = 0
        self._scan_offset = 0

        self.mic_var = tk.StringVar(value="")
        self.command_var = tk.StringVar(value="Awaiting wake word...")
        self.status_var = tk.StringVar(value="Stopped")
        self.clock_var = tk.StringVar(value="")
        self.mode_var = tk.StringVar(value="WAKE MODE // STANDBY")

        self._build_styles()
        self._build_layout()
        self.root.after(35, self._process_events)
        self.root.after(80, self._animate_indicator)
        self.root.after(200, self._update_clock)

    def _build_styles(self) -> None:
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.style.configure("Jarvis.TFrame", background=self.COLORS["bg"])
        self.style.configure("Panel.TFrame", background=self.COLORS["panel"])
        self.style.configure("PanelAlt.TFrame", background=self.COLORS["panel_alt"])
        self.style.configure(
            "Title.TLabel",
            background=self.COLORS["bg"],
            foreground=self.COLORS["accent"],
            font=("Bahnschrift SemiBold", 28),
        )
        self.style.configure(
            "SubTitle.TLabel",
            background=self.COLORS["bg"],
            foreground=self.COLORS["muted"],
            font=("Consolas", 11),
        )
        self.style.configure(
            "Section.TLabel",
            background=self.COLORS["panel"],
            foreground=self.COLORS["accent"],
            font=("Bahnschrift SemiBold", 12),
        )
        self.style.configure(
            "PanelText.TLabel",
            background=self.COLORS["panel"],
            foreground=self.COLORS["text"],
            font=("Segoe UI", 11),
        )
        self.style.configure(
            "PanelMuted.TLabel",
            background=self.COLORS["panel"],
            foreground=self.COLORS["muted"],
            font=("Consolas", 10),
        )
        self.style.configure(
            "Jarvis.TButton",
            background="#10283b",
            foreground=self.COLORS["text"],
            borderwidth=1,
            focusthickness=0,
            font=("Bahnschrift SemiBold", 10),
            padding=9,
        )
        self.style.map(
            "Jarvis.TButton",
            background=[("active", "#174460")],
            foreground=[("active", "#ffffff")],
        )
        self.style.configure(
            "Jarvis.TCombobox",
            fieldbackground="#0d2132",
            background="#0d2132",
            foreground=self.COLORS["text"],
            arrowcolor=self.COLORS["accent"],
            bordercolor=self.COLORS["border"],
        )

    def _build_layout(self) -> None:
        outer = tk.Frame(self.root, bg=self.COLORS["bg"], padx=20, pady=20)
        outer.pack(fill="both", expand=True)

        self._build_header(outer)

        content = tk.Frame(outer, bg=self.COLORS["bg"])
        content.pack(fill="both", expand=True, pady=(18, 0))
        content.grid_columnconfigure(0, weight=0, minsize=355)
        content.grid_columnconfigure(1, weight=1)
        content.grid_rowconfigure(0, weight=1)

        left_panel = self._make_panel(content, width=355)
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        left_panel.grid_propagate(False)

        right_panel = self._make_panel(content)
        right_panel.grid(row=0, column=1, sticky="nsew")
        right_panel.grid_columnconfigure(0, weight=1)
        right_panel.grid_rowconfigure(3, weight=1)

        self._build_left_panel(left_panel)
        self._build_right_panel(right_panel)

    def _build_header(self, parent) -> None:
        header = tk.Frame(parent, bg=self.COLORS["bg"])
        header.pack(fill="x")

        title_wrap = tk.Frame(header, bg=self.COLORS["bg"])
        title_wrap.pack(side="left", anchor="w")

        ttk.Label(title_wrap, text="JARVIS", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            title_wrap,
            text="NEURAL DESKTOP INTERFACE // WAKE WORD LOCKED TO JARVIS",
            style="SubTitle.TLabel",
        ).pack(anchor="w", pady=(3, 0))

        clock_wrap = tk.Frame(header, bg=self.COLORS["bg"])
        clock_wrap.pack(side="right", anchor="e")
        self.clock_label = tk.Label(
            clock_wrap,
            textvariable=self.clock_var,
            bg=self.COLORS["bg"],
            fg=self.COLORS["accent"],
            font=("Consolas", 16, "bold"),
        )
        self.clock_label.pack(anchor="e")
        self.status_chip = tk.Label(
            clock_wrap,
            textvariable=self.status_var,
            bg="#10283b",
            fg=self.COLORS["accent"],
            font=("Bahnschrift SemiBold", 10),
            padx=14,
            pady=6,
            relief="flat",
        )
        self.status_chip.pack(anchor="e", pady=(8, 0))

    def _build_left_panel(self, parent) -> None:
        parent.grid_columnconfigure(0, weight=1)

        ttk.Label(parent, text="Audio Core", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", padx=16, pady=(16, 8)
        )

        self.status_text = tk.Label(
            parent,
            text="SYSTEM OFFLINE",
            bg=self.COLORS["panel"],
            fg=self.COLORS["accent"],
            font=("Consolas", 15, "bold"),
        )
        self.status_text.grid(row=1, column=0, sticky="w", padx=16)

        self.indicator = tk.Canvas(
            parent,
            width=300,
            height=190,
            bg=self.COLORS["panel"],
            highlightthickness=0,
        )
        self.indicator.grid(row=2, column=0, padx=16, pady=(10, 12))
        self._draw_indicator_base()

        controls = tk.Frame(parent, bg=self.COLORS["panel"])
        controls.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 12))
        for col in range(2):
            controls.grid_columnconfigure(col, weight=1)

        buttons = [
            ("Start", self.on_start, 0, 0),
            ("Stop", self.on_stop, 0, 1),
            ("Wake Test", self.on_wake_test, 1, 0),
            ("Test Voice", self.on_test_voice, 1, 1),
            ("Test Mic", self.on_test_mic, 2, 0),
            ("Hide UI", self.on_hide, 2, 1),
            ("Show UI", self.on_show, 3, 0),
        ]

        for text, command, row, col in buttons:
            ttk.Button(controls, text=text, command=command, style="Jarvis.TButton").grid(
                row=row,
                column=col,
                sticky="ew",
                padx=4,
                pady=4,
            )

        ttk.Label(parent, text="Input Device", style="Section.TLabel").grid(
            row=4, column=0, sticky="w", padx=16, pady=(6, 8)
        )

        mic_wrap = tk.Frame(parent, bg=self.COLORS["panel"])
        mic_wrap.grid(row=5, column=0, sticky="ew", padx=16, pady=(0, 14))
        mic_wrap.grid_columnconfigure(0, weight=1)

        self.mic_combo = ttk.Combobox(
            mic_wrap,
            textvariable=self.mic_var,
            state="readonly",
            style="Jarvis.TCombobox",
            font=("Consolas", 10),
        )
        self.mic_combo.grid(row=0, column=0, sticky="ew")
        self.mic_combo.bind("<<ComboboxSelected>>", self._on_mic_selected)

        self.mic_hint = tk.Label(
            mic_wrap,
            text="Select a microphone if auto-detection chooses the wrong one.",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            font=("Consolas", 9),
            anchor="w",
            justify="left",
        )
        self.mic_hint.grid(row=1, column=0, sticky="ew", pady=(8, 0))

    def _build_right_panel(self, parent) -> None:
        ttk.Label(parent, text="Command Stream", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", padx=18, pady=(16, 8)
        )

        self.command_card = tk.Label(
            parent,
            textvariable=self.command_var,
            bg="#0f2233",
            fg=self.COLORS["text"],
            font=("Consolas", 13),
            anchor="w",
            justify="left",
            padx=14,
            pady=14,
            relief="flat",
        )
        self.command_card.grid(row=1, column=0, sticky="ew", padx=18)

        info_strip = tk.Frame(parent, bg=self.COLORS["panel"])
        info_strip.grid(row=2, column=0, sticky="ew", padx=18, pady=(12, 10))
        info_strip.grid_columnconfigure(0, weight=1)
        info_strip.grid_columnconfigure(1, weight=1)

        self.mode_label = tk.Label(
            info_strip,
            textvariable=self.mode_var,
            bg=self.COLORS["panel"],
            fg=self.COLORS["accent_soft"],
            font=("Consolas", 10, "bold"),
            anchor="w",
        )
        self.mode_label.grid(row=0, column=0, sticky="w")

        self.latency_label = tk.Label(
            info_strip,
            text="OPTIMIZED RESPONSE PATH",
            bg=self.COLORS["panel"],
            fg=self.COLORS["success"],
            font=("Consolas", 10, "bold"),
            anchor="e",
        )
        self.latency_label.grid(row=0, column=1, sticky="e")

        console_frame = tk.Frame(parent, bg=self.COLORS["panel"])
        console_frame.grid(row=3, column=0, sticky="nsew", padx=18, pady=(0, 18))
        console_frame.grid_rowconfigure(0, weight=1)
        console_frame.grid_columnconfigure(0, weight=1)

        self.response_box = tk.Text(
            console_frame,
            bg=self.COLORS["console"],
            fg=self.COLORS["text"],
            insertbackground=self.COLORS["accent"],
            relief="flat",
            font=("Consolas", 11),
            padx=16,
            pady=16,
            wrap="word",
            spacing2=3,
        )
        self.response_box.grid(row=0, column=0, sticky="nsew")
        self.response_box.insert("end", "System ready.\n")
        self.response_box.configure(state="disabled")

        scrollbar = ttk.Scrollbar(console_frame, orient="vertical", command=self.response_box.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.response_box.configure(yscrollcommand=scrollbar.set)

    def _make_panel(self, parent, width: int | None = None):
        frame = tk.Frame(
            parent,
            bg=self.COLORS["panel"],
            highlightbackground=self.COLORS["border"],
            highlightcolor=self.COLORS["border"],
            highlightthickness=1,
            bd=0,
        )
        if width is not None:
            frame.configure(width=width)
        return frame

    def _draw_indicator_base(self) -> None:
        self.indicator.delete("all")
        width = 300
        height = 190
        center_x = width / 2
        center_y = height / 2

        for x in range(0, width, 24):
            self.indicator.create_line(x, 0, x, height, fill="#0d2638", width=1)
        for y in range(0, height, 24):
            self.indicator.create_line(0, y, width, y, fill="#0d2638", width=1)

        self.indicator.create_oval(55, 20, 245, 170, outline="#12354d", width=2)
        self.indicator.create_oval(85, 50, 215, 140, outline="#173f59", width=2)
        self.indicator.create_line(center_x, 12, center_x, 178, fill="#14344b", width=1)
        self.indicator.create_line(25, center_y, 275, center_y, fill="#14344b", width=1)
        self.indicator.create_text(
            18,
            14,
            text="WAKE CORE",
            fill=self.COLORS["muted"],
            anchor="nw",
            font=("Consolas", 9, "bold"),
        )

        self.scan_line = self.indicator.create_line(
            26, center_y, 274, center_y, fill=self.COLORS["accent_soft"], width=2
        )
        self.outer_ring = self.indicator.create_oval(
            96, 61, 204, 129, outline="#1f5670", width=3
        )
        self.inner_core = self.indicator.create_oval(
            132, 82, 168, 118, outline=self.COLORS["accent"], fill="#153f56", width=2
        )

    def set_status(self, status: str) -> None:
        self._events.put(("status", status))

    def set_command(self, command: str) -> None:
        self._events.put(("command", command))

    def append_response(self, message: str) -> None:
        self._events.put(("response", message))

    def set_mode(self, mode: str) -> None:
        self._events.put(("mode", mode))

    def set_microphones(self, names) -> None:
        self._events.put(("microphones", list(names)))

    def set_selected_microphone(self, name: str) -> None:
        self._events.put(("selected_microphone", name))

    def hide_window(self) -> None:
        self.root.withdraw()

    def show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()

    def _close_to_background(self) -> None:
        self.hide_window()

    def _process_events(self) -> None:
        while not self._events.empty():
            event_type, payload = self._events.get()

            if event_type == "status":
                status_text = str(payload)
                self._current_status = status_text
                self.status_var.set(status_text.upper())
                self._listening = status_text.lower() in {"listening", "armed"}
                self.status_text.config(text=f"SYSTEM {status_text.upper()}")
                self._apply_status_palette(status_text)
            elif event_type == "command":
                self.command_var.set(str(payload))
            elif event_type == "response":
                self.response_box.configure(state="normal")
                timestamp = time.strftime("%H:%M:%S")
                self.response_box.insert("end", f"[{timestamp}] {payload}\n")
                self.response_box.see("end")
                self.response_box.configure(state="disabled")
            elif event_type == "mode":
                self.mode_var.set(str(payload))
            elif event_type == "microphones":
                self.mic_combo["values"] = payload
                if payload and not self.mic_var.get():
                    self.mic_var.set(payload[0])
            elif event_type == "selected_microphone":
                self.mic_var.set(str(payload))

        self.root.after(35, self._process_events)

    def _apply_status_palette(self, status: str) -> None:
        lowered = status.lower()
        if lowered == "processing":
            bg = "#3a2810"
            fg = self.COLORS["warning"]
        elif lowered == "speaking":
            bg = "#1d203c"
            fg = "#b3bcff"
        elif lowered in {"listening", "armed"}:
            bg = "#0f2b2f"
            fg = self.COLORS["success"]
        elif "error" in lowered:
            bg = "#3b1320"
            fg = self.COLORS["danger"]
        else:
            bg = "#10283b"
            fg = self.COLORS["accent"]

        self.status_chip.config(bg=bg, fg=fg)

    def _on_mic_selected(self, _event) -> None:
        selected = self.mic_var.get().strip()
        if selected:
            self.on_select_mic(selected)

    def _animate_indicator(self) -> None:
        self._scan_offset = (self._scan_offset + 8) % 132
        y = 28 + self._scan_offset
        self.indicator.coords(self.scan_line, 26, y, 274, y)

        if self._listening:
            pulse_palette = ["#215772", "#2d89a9", "#6ef2ff", "#2d89a9"]
            ring_color = pulse_palette[self._glow_phase % len(pulse_palette)]
            core_fill = ["#123b4f", "#17536c", "#1b6a88", "#17536c"][self._glow_phase % 4]
            self._glow_phase += 1
        else:
            ring_color = "#1f5670"
            core_fill = "#153f56"

        self.indicator.itemconfig(self.outer_ring, outline=ring_color)
        self.indicator.itemconfig(self.inner_core, fill=core_fill, outline=self.COLORS["accent"])
        self.root.after(80, self._animate_indicator)

    def _update_clock(self) -> None:
        self.clock_var.set(time.strftime("%H:%M:%S"))
        self.root.after(200, self._update_clock)

    def run(self) -> None:
        self.root.mainloop()
