"""
PDF Diff Tool - Windows 11 single-file GUI application
Compares two PDFs page-by-page and shows GitHub-style text diffs.
"""

import sys
import os
import re
import difflib
import threading
import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable

# PyInstaller frozen bundle: resolve tkinterdnd2 native DLL path
if getattr(sys, 'frozen', False):
    _bundle_dir = sys._MEIPASS
    os.environ['TKDND_LIBRARY'] = os.path.join(_bundle_dir, 'tkinterdnd2', 'tkdnd')

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    import tkinterdnd2 as tkdnd
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _DND_AVAILABLE = True
except ImportError:
    _DND_AVAILABLE = False

try:
    import fitz  # PyMuPDF
except ImportError:
    messagebox.showerror("Error", "PyMuPDF is not installed.\nRun: pip install PyMuPDF")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class PageStatus(Enum):
    ADDED     = "added"
    DELETED   = "deleted"
    CHANGED   = "changed"
    UNCHANGED = "unchanged"


@dataclass
class PageDiff:
    page_index: int
    page_num: int
    status: PageStatus
    old_text: Optional[str]
    new_text: Optional[str]
    unified_diff_lines: list = field(default_factory=list)


@dataclass
class DiffResult:
    old_path: str
    new_path: str
    old_page_count: int
    new_page_count: int
    pages: list

    def summary(self) -> dict:
        counts = {s: 0 for s in PageStatus}
        for p in self.pages:
            counts[p.status] += 1
        return counts


# ---------------------------------------------------------------------------
# PDF logic
# ---------------------------------------------------------------------------

def load_pdf_texts(path: str) -> list:
    doc = fitz.open(path)
    texts = [page.get_text("text") for page in doc]
    doc.close()
    return texts


def compute_page_diff_lines(
    old_text: Optional[str],
    new_text: Optional[str],
    page_num: int,
    old_path: str,
    new_path: str,
) -> list:
    a_lines = (old_text or "").splitlines(keepends=True)
    b_lines = (new_text or "").splitlines(keepends=True)

    old_label = f"{os.path.basename(old_path)} (page {page_num})"
    new_label = f"{os.path.basename(new_path)} (page {page_num})"

    if old_text is None:
        old_label = "/dev/null"
    if new_text is None:
        new_label = "/dev/null"

    result = list(difflib.unified_diff(
        a_lines, b_lines,
        fromfile=old_label,
        tofile=new_label,
        lineterm="",
        n=3,
    ))
    return result


def compare_pdfs(old_path: str, new_path: str) -> DiffResult:
    old_texts = load_pdf_texts(old_path)
    new_texts = load_pdf_texts(new_path)

    max_pages = max(len(old_texts), len(new_texts))
    pages = []

    for i in range(max_pages):
        old_text = old_texts[i] if i < len(old_texts) else None
        new_text = new_texts[i] if i < len(new_texts) else None

        if old_text is None:
            status = PageStatus.ADDED
        elif new_text is None:
            status = PageStatus.DELETED
        elif old_text.strip() == new_text.strip():
            status = PageStatus.UNCHANGED
        else:
            status = PageStatus.CHANGED

        pages.append(PageDiff(
            page_index=i,
            page_num=i + 1,
            status=status,
            old_text=old_text,
            new_text=new_text,
        ))

    return DiffResult(
        old_path=old_path,
        new_path=new_path,
        old_page_count=len(old_texts),
        new_page_count=len(new_texts),
        pages=pages,
    )


def export_diff_file(result: DiffResult, output_path: str) -> None:
    lines = []
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    summary = result.summary()

    lines.append("# PDF Diff Report")
    lines.append(f"# Generated: {now}")
    lines.append(f"# Old PDF: {result.old_path} ({result.old_page_count} pages)")
    lines.append(f"# New PDF: {result.new_path} ({result.new_page_count} pages)")
    lines.append(
        f"# Summary: {summary[PageStatus.ADDED]} added, "
        f"{summary[PageStatus.DELETED]} deleted, "
        f"{summary[PageStatus.CHANGED]} changed, "
        f"{summary[PageStatus.UNCHANGED]} unchanged"
    )
    lines.append("#")

    for pd in result.pages:
        lines.append("#")
        lines.append("# " + "=" * 60)
        lines.append(f"# Page {pd.page_num}: {pd.status.value}")
        lines.append("# " + "=" * 60)

        if pd.status == PageStatus.UNCHANGED:
            continue

        if not pd.unified_diff_lines:
            pd.unified_diff_lines = compute_page_diff_lines(
                pd.old_text, pd.new_text, pd.page_num,
                result.old_path, result.new_path,
            )

        lines.extend(pd.unified_diff_lines)

    with open(output_path, "w", encoding="utf-8", errors="replace") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# GUI helpers
# ---------------------------------------------------------------------------

STATUS_COLORS = {
    PageStatus.ADDED:     "#2da44e",
    PageStatus.DELETED:   "#cf222e",
    PageStatus.CHANGED:   "#bf8700",
    PageStatus.UNCHANGED: "#6e7781",
}

STATUS_ICONS = {
    PageStatus.ADDED:     "+",
    PageStatus.DELETED:   "-",
    PageStatus.CHANGED:   "~",
    PageStatus.UNCHANGED: "=",
}


def parse_drop_path(event_data: str) -> str:
    data = event_data.strip()
    if data.startswith('{'):
        end = data.index('}')
        return data[1:end]
    return data.split()[0]


def render_diff_in_text_widget(text_widget: tk.Text, diff_lines: list) -> None:
    text_widget.config(state=tk.NORMAL)
    text_widget.delete("1.0", tk.END)

    # Parse hunk header to track line numbers
    old_lineno = 0
    new_lineno = 0

    _hunk_re = re.compile(r'^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@')

    def ins(text, *tags):
        text_widget.insert(tk.END, text, tags)

    for raw in diff_lines:
        m = _hunk_re.match(raw)
        if m:
            old_lineno = int(m.group(1))
            new_lineno = int(m.group(2))
            ins(f"{'':>6} | ", 'lineno')
            ins(raw + "\n", 'hunk_header')
        elif raw.startswith('---') or raw.startswith('+++'):
            ins(f"{'':>6} | ", 'lineno')
            ins(raw + "\n", 'file_header')
        elif raw.startswith('+'):
            ins(f"{new_lineno:>6} | ", 'lineno')
            ins(raw + "\n", 'addition')
            new_lineno += 1
        elif raw.startswith('-'):
            ins(f"{old_lineno:>6} | ", 'lineno')
            ins(raw + "\n", 'deletion')
            old_lineno += 1
        else:
            ins(f"{old_lineno:>6} | ", 'lineno')
            ins(raw + "\n", 'context')
            old_lineno += 1
            new_lineno += 1

    text_widget.config(state=tk.DISABLED)


# ---------------------------------------------------------------------------
# Main application class
# ---------------------------------------------------------------------------

class PDFDiffApp:
    def __init__(self, root):
        self.root = root
        self.old_path: Optional[str] = None
        self.new_path: Optional[str] = None
        self.diff_result: Optional[DiffResult] = None
        self.selected_page_index: Optional[int] = None
        self.page_row_frames: list = []
        self._comparing = False

        self._build_ui()
        if _DND_AVAILABLE:
            self._setup_drag_and_drop()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)

        self._build_menu()
        self._build_toolbar()
        self._build_action_bar()
        self._build_main_pane()
        self._build_status_bar()

    def _build_menu(self):
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="旧PDFを開く...", command=self._browse_old)
        file_menu.add_command(label="新PDFを開く...", command=self._browse_new)
        file_menu.add_separator()
        file_menu.add_command(label=".diffをエクスポート...", command=self._export_diff)
        file_menu.add_separator()
        file_menu.add_command(label="終了", command=self.root.quit)
        menubar.add_cascade(label="ファイル", menu=file_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="バージョン情報", command=self._show_about)
        menubar.add_cascade(label="ヘルプ", menu=help_menu)

        self.root.config(menu=menubar)

    def _build_toolbar(self):
        toolbar = tk.Frame(self.root, bg="#f6f8fa", bd=1, relief=tk.SOLID)
        toolbar.grid(row=0, column=0, sticky="ew", padx=0, pady=0)
        toolbar.columnconfigure(0, weight=1)
        toolbar.columnconfigure(1, weight=1)

        # Old PDF drop zone
        self.old_drop = self._make_drop_zone(
            toolbar, "OLD PDF（旧）", self._browse_old
        )
        self.old_drop.grid(row=0, column=0, sticky="ew", padx=8, pady=8)

        # New PDF drop zone
        self.new_drop = self._make_drop_zone(
            toolbar, "NEW PDF（新）", self._browse_new
        )
        self.new_drop.grid(row=0, column=1, sticky="ew", padx=8, pady=8)

    def _make_drop_zone(self, parent, label_text: str, browse_cmd: Callable) -> tk.Frame:
        frame = tk.Frame(
            parent, bg="#ffffff", bd=2, relief=tk.GROOVE,
            padx=8, pady=6,
        )
        frame.columnconfigure(0, weight=1)

        header = tk.Label(
            frame, text=label_text, bg="#ffffff",
            font=("Segoe UI", 9, "bold"), fg="#57606a",
        )
        header.grid(row=0, column=0, sticky="w")

        file_lbl = tk.Label(
            frame, text="ここにPDFをドロップ、または参照...",
            bg="#ffffff", fg="#57606a",
            font=("Segoe UI", 9), anchor="w", wraplength=350,
        )
        file_lbl.grid(row=1, column=0, sticky="ew")

        browse_btn = tk.Button(
            frame, text="参照...", command=browse_cmd,
            relief=tk.FLAT, bg="#f6f8fa", fg="#24292f",
            font=("Segoe UI", 9), padx=6, pady=2,
            cursor="hand2",
        )
        browse_btn.grid(row=0, column=1, rowspan=2, padx=(4, 0))

        frame._file_label = file_lbl
        return frame

    def _build_action_bar(self):
        bar = tk.Frame(self.root, bg="#f6f8fa", bd=1, relief=tk.SOLID)
        bar.grid(row=1, column=0, sticky="ew")

        self.compare_btn = tk.Button(
            bar, text="比較する", command=self._run_comparison,
            bg="#0969da", fg="white", font=("Segoe UI", 10, "bold"),
            relief=tk.FLAT, padx=16, pady=6, cursor="hand2",
            state=tk.DISABLED,
        )
        self.compare_btn.pack(side=tk.LEFT, padx=8, pady=6)

        self.export_btn = tk.Button(
            bar, text=".diff エクスポート", command=self._export_diff,
            bg="#ffffff", fg="#24292f", font=("Segoe UI", 10),
            relief=tk.SOLID, padx=12, pady=6, cursor="hand2",
            state=tk.DISABLED,
        )
        self.export_btn.pack(side=tk.LEFT, padx=4, pady=6)

    def _build_main_pane(self):
        paned = tk.PanedWindow(
            self.root, orient=tk.HORIZONTAL,
            sashrelief=tk.RAISED, sashwidth=5, bg="#d0d7de",
        )
        paned.grid(row=2, column=0, sticky="nsew")

        # Left: page list
        left = tk.Frame(paned, bg="#f6f8fa", width=240)
        left.pack_propagate(False)
        paned.add(left, minsize=180)

        lbl = tk.Label(
            left, text="ページ一覧", bg="#f6f8fa",
            font=("Segoe UI", 10, "bold"), fg="#24292f",
            pady=6,
        )
        lbl.pack(fill=tk.X, padx=8)

        # Legend
        legend = tk.Frame(left, bg="#f6f8fa")
        legend.pack(fill=tk.X, padx=8, pady=(0, 4))
        for status, color in STATUS_COLORS.items():
            icon = STATUS_ICONS[status]
            tk.Label(
                legend, text=f"{icon} {status.value.capitalize()}",
                bg="#f6f8fa", fg=color, font=("Segoe UI", 8),
            ).pack(side=tk.LEFT, padx=(0, 6))

        tk.Frame(left, bg="#d0d7de", height=1).pack(fill=tk.X)

        # Scrollable canvas for page rows
        self._page_canvas = tk.Canvas(left, bg="#ffffff", highlightthickness=0)
        scrollbar = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self._page_canvas.yview)
        self._page_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._page_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._page_inner = tk.Frame(self._page_canvas, bg="#ffffff")
        self._page_canvas_window = self._page_canvas.create_window(
            (0, 0), window=self._page_inner, anchor="nw"
        )

        self._page_inner.bind("<Configure>", self._on_page_inner_configure)
        self._page_canvas.bind("<Configure>", self._on_canvas_configure)
        self._page_canvas.bind("<MouseWheel>", self._on_mousewheel)
        self._page_inner.bind("<MouseWheel>", self._on_mousewheel)

        # Right: diff view
        right = tk.Frame(paned, bg="#ffffff")
        paned.add(right, minsize=400)

        self.diff_title = tk.Label(
            right, text="PDFを選択して「比較する」を押してください",
            bg="#f6f8fa", fg="#57606a", font=("Segoe UI", 10),
            pady=6, anchor="w", padx=8,
        )
        self.diff_title.pack(fill=tk.X)

        tk.Frame(right, bg="#d0d7de", height=1).pack(fill=tk.X)

        text_frame = tk.Frame(right, bg="#ffffff")
        text_frame.pack(fill=tk.BOTH, expand=True)

        self.diff_text = tk.Text(
            text_frame,
            font=("Consolas", 10),
            state=tk.DISABLED,
            wrap=tk.NONE,
            bg="#ffffff",
            fg="#24292f",
            cursor="arrow",
            padx=4,
        )

        v_scroll = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self.diff_text.yview)
        h_scroll = ttk.Scrollbar(text_frame, orient=tk.HORIZONTAL, command=self.diff_text.xview)
        self.diff_text.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.diff_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._configure_diff_tags()

    def _configure_diff_tags(self):
        t = self.diff_text
        t.tag_configure('addition',    background='#e6ffec', foreground='#1a7f37')
        t.tag_configure('deletion',    background='#ffebe9', foreground='#cf222e')
        t.tag_configure('hunk_header', background='#ddf4ff', foreground='#0550ae',
                        font=('Consolas', 10, 'bold'))
        t.tag_configure('file_header', background='#f6f8fa', foreground='#57606a',
                        font=('Consolas', 10, 'bold'))
        t.tag_configure('context',     background='#ffffff', foreground='#24292f')
        t.tag_configure('lineno',      background='#f6f8fa', foreground='#6e7781')

    def _build_status_bar(self):
        bar = tk.Frame(self.root, bg="#f6f8fa", bd=1, relief=tk.SUNKEN)
        bar.grid(row=3, column=0, sticky="ew")

        self.status_label = tk.Label(
            bar, text="準備完了", bg="#f6f8fa", fg="#57606a",
            font=("Segoe UI", 9), anchor="w",
        )
        self.status_label.pack(side=tk.LEFT, padx=8, pady=2)

    # ------------------------------------------------------------------
    # Drag & drop
    # ------------------------------------------------------------------

    def _setup_drag_and_drop(self):
        for widget, callback in [
            (self.old_drop, self._handle_old_drop),
            (self.new_drop, self._handle_new_drop),
        ]:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind('<<Drop>>', callback)
            widget.dnd_bind('<<DragEnter>>', lambda e, w=widget: w.config(bg='#ddf4ff'))
            widget.dnd_bind('<<DragLeave>>', lambda e, w=widget: w.config(bg='#ffffff'))

            for child in widget.winfo_children():
                try:
                    child.drop_target_register(DND_FILES)
                    child.dnd_bind('<<Drop>>', callback)
                except Exception:
                    pass

    def _handle_old_drop(self, event):
        path = parse_drop_path(event.data)
        self.old_drop.config(bg='#ffffff')
        if path.lower().endswith('.pdf'):
            self._set_old_pdf(path)
        else:
            messagebox.showerror("エラー", "PDFファイルをドロップしてください。")

    def _handle_new_drop(self, event):
        path = parse_drop_path(event.data)
        self.new_drop.config(bg='#ffffff')
        if path.lower().endswith('.pdf'):
            self._set_new_pdf(path)
        else:
            messagebox.showerror("エラー", "PDFファイルをドロップしてください。")

    # ------------------------------------------------------------------
    # File selection
    # ------------------------------------------------------------------

    def _browse_old(self):
        path = filedialog.askopenfilename(
            title="旧PDFを選択",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if path:
            self._set_old_pdf(path)

    def _browse_new(self):
        path = filedialog.askopenfilename(
            title="新PDFを選択",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if path:
            self._set_new_pdf(path)

    def _set_old_pdf(self, path: str):
        self.old_path = path
        self.old_drop._file_label.config(
            text=os.path.basename(path), fg="#24292f"
        )
        self._update_compare_btn()

    def _set_new_pdf(self, path: str):
        self.new_path = path
        self.new_drop._file_label.config(
            text=os.path.basename(path), fg="#24292f"
        )
        self._update_compare_btn()

    def _update_compare_btn(self):
        if self.old_path and self.new_path:
            self.compare_btn.config(state=tk.NORMAL)
        else:
            self.compare_btn.config(state=tk.DISABLED)

    # ------------------------------------------------------------------
    # Comparison
    # ------------------------------------------------------------------

    def _run_comparison(self):
        if self._comparing:
            return
        self._comparing = True
        self.compare_btn.config(state=tk.DISABLED, text="比較中...")
        self.export_btn.config(state=tk.DISABLED)
        self._clear_page_list()
        self.diff_title.config(text="比較中...")
        self.status_label.config(text="PDFを比較しています...")
        self.diff_text.config(state=tk.NORMAL)
        self.diff_text.delete("1.0", tk.END)
        self.diff_text.config(state=tk.DISABLED)

        thread = threading.Thread(target=self._compare_worker, daemon=True)
        thread.start()

    def _compare_worker(self):
        try:
            result = compare_pdfs(self.old_path, self.new_path)
            self.root.after(0, self._on_comparison_done, result, None)
        except Exception as e:
            self.root.after(0, self._on_comparison_done, None, str(e))

    def _on_comparison_done(self, result: Optional[DiffResult], error: Optional[str]):
        self._comparing = False
        self.compare_btn.config(state=tk.NORMAL, text="比較する")

        if error:
            messagebox.showerror("比較エラー", f"比較中にエラーが発生しました:\n{error}")
            self.status_label.config(text="エラーが発生しました")
            return

        self.diff_result = result
        self.export_btn.config(state=tk.NORMAL)

        summary = result.summary()
        self.status_label.config(
            text=f"合計 {len(result.pages)} ページ | "
                 f"変更: {summary[PageStatus.CHANGED]}  "
                 f"追加: {summary[PageStatus.ADDED]}  "
                 f"削除: {summary[PageStatus.DELETED]}  "
                 f"同一: {summary[PageStatus.UNCHANGED]}"
        )

        self._populate_page_list(result)
        self.diff_title.config(text="ページを選択して差分を表示")

    # ------------------------------------------------------------------
    # Page list
    # ------------------------------------------------------------------

    def _clear_page_list(self):
        for w in self._page_inner.winfo_children():
            w.destroy()
        self.page_row_frames = []
        self.selected_page_index = None

    def _populate_page_list(self, result: DiffResult):
        self._clear_page_list()
        for pd in result.pages:
            row = self._create_page_row(pd)
            row.pack(fill=tk.X, pady=1)
            self.page_row_frames.append(row)

    def _create_page_row(self, pd: PageDiff) -> tk.Frame:
        color = STATUS_COLORS[pd.status]
        icon = STATUS_ICONS[pd.status]

        row = tk.Frame(self._page_inner, bg="#ffffff", cursor="hand2")

        indicator = tk.Frame(row, bg="#ffffff", width=3)
        indicator.pack(side=tk.LEFT, fill=tk.Y)
        row._indicator = indicator

        icon_lbl = tk.Label(
            row, text=icon, fg=color, bg="#ffffff",
            font=("Consolas", 11, "bold"), width=2,
        )
        icon_lbl.pack(side=tk.LEFT, padx=(4, 2), pady=4)

        page_lbl = tk.Label(
            row, text=f"Page {pd.page_num}", bg="#ffffff", fg="#24292f",
            font=("Segoe UI", 9), anchor="w",
        )
        page_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=4)

        status_lbl = tk.Label(
            row, text=pd.status.value.capitalize(), fg=color, bg="#ffffff",
            font=("Segoe UI", 8), padx=6,
        )
        status_lbl.pack(side=tk.RIGHT, pady=4)

        def on_click(event, idx=pd.page_index):
            self._on_page_selected(idx)

        def on_enter(event, r=row):
            if self.selected_page_index != pd.page_index:
                r.config(bg="#f6f8fa")
                for c in r.winfo_children():
                    try:
                        c.config(bg="#f6f8fa")
                    except Exception:
                        pass

        def on_leave(event, r=row):
            if self.selected_page_index != pd.page_index:
                r.config(bg="#ffffff")
                for c in r.winfo_children():
                    try:
                        c.config(bg="#ffffff")
                    except Exception:
                        pass

        for w in [row, icon_lbl, page_lbl, status_lbl]:
            w.bind("<Button-1>", on_click)
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)

        return row

    def _on_page_selected(self, page_index: int):
        # Deselect previous
        if self.selected_page_index is not None:
            prev = self.page_row_frames[self.selected_page_index]
            prev.config(bg="#ffffff")
            prev._indicator.config(bg="#ffffff")
            for c in prev.winfo_children():
                try:
                    c.config(bg="#ffffff")
                except Exception:
                    pass

        self.selected_page_index = page_index
        row = self.page_row_frames[page_index]
        row.config(bg="#ddf4ff")
        row._indicator.config(bg="#0969da")
        for c in row.winfo_children():
            try:
                c.config(bg="#ddf4ff")
            except Exception:
                pass

        pd = self.diff_result.pages[page_index]
        self._show_diff_for_page(pd)

    def _show_diff_for_page(self, pd: PageDiff):
        self.diff_title.config(
            text=f"Page {pd.page_num} — {pd.status.value.capitalize()}"
        )

        if pd.status == PageStatus.UNCHANGED:
            self.diff_text.config(state=tk.NORMAL)
            self.diff_text.delete("1.0", tk.END)
            self.diff_text.insert(tk.END, f"  Page {pd.page_num}: 変更なし", 'context')
            self.diff_text.config(state=tk.DISABLED)
            return

        if not pd.unified_diff_lines:
            pd.unified_diff_lines = compute_page_diff_lines(
                pd.old_text, pd.new_text, pd.page_num,
                self.diff_result.old_path, self.diff_result.new_path,
            )

        render_diff_in_text_widget(self.diff_text, pd.unified_diff_lines)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def _export_diff(self):
        if not self.diff_result:
            messagebox.showwarning("警告", "先に比較を実行してください。")
            return

        path = filedialog.asksaveasfilename(
            title=".diffファイルを保存",
            defaultextension=".diff",
            filetypes=[("Diff files", "*.diff"), ("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            export_diff_file(self.diff_result, path)
            messagebox.showinfo("完了", f"エクスポートしました:\n{path}")
        except Exception as e:
            messagebox.showerror("エラー", f"エクスポートに失敗しました:\n{e}")

    # ------------------------------------------------------------------
    # Canvas scroll helpers
    # ------------------------------------------------------------------

    def _on_page_inner_configure(self, event):
        self._page_canvas.configure(scrollregion=self._page_canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self._page_canvas.itemconfig(self._page_canvas_window, width=event.width)

    def _on_mousewheel(self, event):
        self._page_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def _show_about(self):
        messagebox.showinfo(
            "バージョン情報",
            "PDF Diff Tool v1.0\n\n"
            "2つのPDFファイルのページ単位・テキスト差分を表示します。\n\n"
            "使用ライブラリ: PyMuPDF, tkinterdnd2, difflib",
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    if _DND_AVAILABLE:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()

    root.title("PDF Diff Tool")
    root.geometry("1280x800")
    root.minsize(900, 600)

    try:
        root.tk.call('tk', 'scaling', 1.0)
    except Exception:
        pass

    app = PDFDiffApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
