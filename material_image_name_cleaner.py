from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue

try:
    import tkinter as tk
    from tkinter import filedialog
    from tkinter import messagebox
    from tkinter import ttk
    from tkinter.scrolledtext import ScrolledText
except ModuleNotFoundError as error:  # pragma: no cover - GUI availability depends on the runtime
    tk = None
    filedialog = None
    messagebox = None
    ttk = None
    ScrolledText = None
    TK_IMPORT_ERROR = error
else:
    TK_IMPORT_ERROR = None


APP_TITLE = "素材图名清洗助手"
APP_SUBTITLE = "递归扫描素材目录，按默认规则或正则规则批量清洗图片文件名"
FOOTER_TEXT = "需求及bug提交｜项目合作｜微信：tktk6622"
OUTPUT_SUFFIX = "处理结果"
DEFAULT_RULE_LABEL = "默认规则：删除扩展名前常见尾缀 -1 / -2 / (1) / -(1)"
DEFAULT_PATTERN_TEXT = r"-\d+|-\(\d+\)|\(\d+\)"
TRAILING_SEPARATORS_RE = re.compile(r"[\s._-]+$")
IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".gif",
    ".webp",
    ".tif",
    ".tiff",
    ".jfif",
}
IGNORED_DIR_NAMES = {
    ".git",
    ".github",
    "__pycache__",
    "build",
    "dist",
    "release",
}
BASE_DIR = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent


@dataclass
class ScanSummary:
    total_images: int
    matched_images: int
    folder_count: int


@dataclass
class ProcessSummary:
    total_images: int
    renamed_images: int
    unchanged_images: int
    duplicate_images: int
    output_dir: Path


def should_skip_dir_name(name: str) -> bool:
    return name.startswith(".") or name in IGNORED_DIR_NAMES


def is_image_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS and not path.name.startswith(".")


def collect_image_files(root: Path) -> tuple[list[Path], int]:
    image_files: list[Path] = []
    folder_count = 0

    for current_dir, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if not should_skip_dir_name(name))
        current_path = Path(current_dir)
        if current_path != root:
            folder_count += 1

        for filename in sorted(filenames, key=str.casefold):
            if filename.startswith("."):
                continue
            file_path = current_path / filename
            if is_image_file(file_path):
                image_files.append(file_path)

    image_files.sort(key=lambda path: str(path.relative_to(root)).casefold())
    return image_files, folder_count


def build_regex(use_default_rule: bool, custom_expression: str) -> re.Pattern[str]:
    expressions: list[str] = []
    if use_default_rule:
        expressions.append(f"(?:{DEFAULT_PATTERN_TEXT})")

    cleaned_expression = custom_expression.strip()
    if cleaned_expression:
        expressions.append(f"(?:{cleaned_expression})")

    if not expressions:
        raise ValueError("请至少启用默认规则，或输入一个正则表达式。")

    combined = "|".join(expressions)
    try:
        return re.compile(f"(?:{combined})(?=$)")
    except re.error as error:
        raise ValueError(f"正则表达式无效：{error}") from error


def clean_stem(stem: str, pattern: re.Pattern[str]) -> str:
    original = stem.strip() or stem
    current = original

    while current:
        updated = pattern.sub("", current, count=1)
        if updated == current:
            break
        current = TRAILING_SEPARATORS_RE.sub("", updated).strip()

    return current or original or stem


def build_output_dir(source_root: Path) -> Path:
    base_name = f"{source_root.name}_{OUTPUT_SUFFIX}"
    candidate = source_root.parent / base_name
    if not candidate.exists():
        return candidate

    counter = 1
    while True:
        candidate = source_root.parent / f"{source_root.name}_{OUTPUT_SUFFIX}_{counter:02d}"
        if not candidate.exists():
            return candidate
        counter += 1


def build_unique_destination(destination_dir: Path, cleaned_stem: str, suffix: str) -> tuple[Path, bool]:
    candidate = destination_dir / f"{cleaned_stem}{suffix}"
    if not candidate.exists():
        return candidate, False

    counter = 1
    while True:
        candidate = destination_dir / f"{cleaned_stem}_重名{counter:02d}{suffix}"
        if not candidate.exists():
            return candidate, True
        counter += 1


def scan_source_folder(source_root: Path, pattern: re.Pattern[str]) -> ScanSummary:
    image_files, folder_count = collect_image_files(source_root)
    matched_images = sum(1 for path in image_files if clean_stem(path.stem, pattern) != path.stem)
    return ScanSummary(total_images=len(image_files), matched_images=matched_images, folder_count=folder_count)


def process_source_folder(
    source_root: Path,
    pattern: re.Pattern[str],
    progress_callback,
    log_callback,
) -> ProcessSummary:
    image_files, _folder_count = collect_image_files(source_root)
    if not image_files:
        raise ValueError("所选文件夹及其子文件夹下没有可处理的图片。")

    output_dir = build_output_dir(source_root)
    output_dir.mkdir(parents=True, exist_ok=False)

    renamed_images = 0
    unchanged_images = 0
    duplicate_images = 0
    total_images = len(image_files)

    for index, image_path in enumerate(image_files, start=1):
        relative_path = image_path.relative_to(source_root)
        relative_dir = relative_path.parent
        destination_dir = output_dir if str(relative_dir) == "." else output_dir / relative_dir
        destination_dir.mkdir(parents=True, exist_ok=True)

        cleaned_stem = clean_stem(image_path.stem, pattern)
        if cleaned_stem != image_path.stem:
            renamed_images += 1
        else:
            unchanged_images += 1

        destination_path, was_duplicate = build_unique_destination(destination_dir, cleaned_stem, image_path.suffix)
        shutil.copy2(image_path, destination_path)

        if was_duplicate:
            duplicate_images += 1
            log_callback(f"检测到重名，已自动避让：{relative_path} -> {destination_path.relative_to(output_dir)}", "warn")

        if index <= 20 and cleaned_stem != image_path.stem:
            log_callback(f"重命名：{relative_path.name} -> {destination_path.name}")
        elif index % 100 == 0 or index == total_images:
            log_callback(f"已处理 {index}/{total_images} 张图片。")

        progress_callback(index, total_images)

    return ProcessSummary(
        total_images=total_images,
        renamed_images=renamed_images,
        unchanged_images=unchanged_images,
        duplicate_images=duplicate_images,
        output_dir=output_dir,
    )


class MaterialImageNameCleanerApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.geometry("940x700")
        self.root.minsize(860, 640)

        self.event_queue: Queue[tuple[str, object]] = Queue()
        self.worker: threading.Thread | None = None
        self.current_action = ""

        self.source_var = tk.StringVar(value=str(BASE_DIR))
        self.status_var = tk.StringVar(value="等待扫描")
        self.summary_var = tk.StringVar(value="请选择素材文件夹，或直接使用当前目录开始扫描。")
        self.progress_var = tk.StringVar(value="0 / 0")
        self.output_var = tk.StringVar(value=self.build_output_preview())
        self.custom_regex_var = tk.StringVar(value="")
        self.use_default_rule_var = tk.BooleanVar(value=True)

        self.setup_ui()
        self.root.after(120, self.flush_events)
        self.start_scan()

    def setup_ui(self) -> None:
        self.root.configure(bg="#edf2f7")

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Shell.TFrame", background="#ffffff")
        style.configure("Panel.TFrame", background="#ffffff")
        style.configure("Title.TLabel", background="#ffffff", foreground="#132238", font=("Microsoft YaHei", 18, "bold"))
        style.configure("Muted.TLabel", background="#ffffff", foreground="#62748a", font=("Microsoft YaHei", 9))
        style.configure("Body.TLabel", background="#ffffff", foreground="#1f2937", font=("Microsoft YaHei", 10))
        style.configure("Status.TLabel", background="#ffffff", foreground="#2158d6", font=("Microsoft YaHei", 10, "bold"))
        style.configure("Primary.TButton", font=("Microsoft YaHei", 10, "bold"), padding=(16, 9))
        style.configure("TCheckbutton", background="#ffffff", font=("Microsoft YaHei", 10))
        style.configure(
            "Horizontal.TProgressbar",
            troughcolor="#dbe4f0",
            background="#2f6fed",
            bordercolor="#dbe4f0",
            lightcolor="#2f6fed",
            darkcolor="#2f6fed",
        )

        shell = ttk.Frame(self.root, style="Shell.TFrame", padding=18)
        shell.pack(fill="both", expand=True, padx=18, pady=18)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(3, weight=1)

        header = ttk.Frame(shell, style="Panel.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        ttk.Label(header, text=APP_TITLE, style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, textvariable=self.status_var, style="Status.TLabel").grid(row=0, column=1, sticky="e")
        ttk.Label(header, text=APP_SUBTITLE, style="Muted.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

        config = ttk.Frame(shell, style="Panel.TFrame", padding=(0, 18, 0, 0))
        config.grid(row=1, column=0, sticky="ew")
        config.columnconfigure(1, weight=1)

        ttk.Label(config, text="素材文件夹", style="Body.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 10))
        source_entry = ttk.Entry(config, textvariable=self.source_var)
        source_entry.grid(row=0, column=1, sticky="ew", padx=(12, 10), pady=(0, 10))
        source_entry.bind("<FocusOut>", lambda _event: self.refresh_output_preview())

        ttk.Button(config, text="浏览", command=self.choose_source_folder).grid(row=0, column=2, sticky="ew", pady=(0, 10))
        self.scan_button = ttk.Button(config, text="扫描图片", command=self.start_scan)
        self.scan_button.grid(row=0, column=3, sticky="ew", padx=(10, 0), pady=(0, 10))

        ttk.Checkbutton(
            config,
            text=DEFAULT_RULE_LABEL,
            variable=self.use_default_rule_var,
            command=self.refresh_output_preview,
        ).grid(row=1, column=0, columnspan=4, sticky="w")

        ttk.Label(config, text="自定义正则", style="Body.TLabel").grid(row=2, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(config, textvariable=self.custom_regex_var).grid(row=2, column=1, columnspan=3, sticky="ew", padx=(12, 0), pady=(12, 0))
        ttk.Label(
            config,
            text="支持多个正则，用 | 连接。规则只会从扩展名前开始，向左清理文件名尾部。",
            style="Muted.TLabel",
        ).grid(row=3, column=0, columnspan=4, sticky="w", pady=(8, 0))

        stats = ttk.Frame(shell, style="Panel.TFrame", padding=(0, 18, 0, 0))
        stats.grid(row=2, column=0, sticky="ew")
        stats.columnconfigure(0, weight=1)

        ttk.Label(stats, textvariable=self.summary_var, style="Body.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(stats, textvariable=self.output_var, style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(6, 0))

        progress_row = ttk.Frame(stats, style="Panel.TFrame")
        progress_row.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        progress_row.columnconfigure(0, weight=1)

        self.progress_bar = ttk.Progressbar(progress_row, mode="determinate", maximum=100, value=0)
        self.progress_bar.grid(row=0, column=0, sticky="ew")
        ttk.Label(progress_row, textvariable=self.progress_var, style="Muted.TLabel").grid(row=0, column=1, sticky="e", padx=(10, 0))

        actions = ttk.Frame(stats, style="Panel.TFrame")
        actions.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        actions.columnconfigure(4, weight=1)

        self.process_button = ttk.Button(actions, text="处理", style="Primary.TButton", command=self.start_process)
        self.process_button.grid(row=0, column=0, sticky="w")
        ttk.Button(actions, text="清空日志", command=self.clear_logs).grid(row=0, column=1, sticky="w", padx=(10, 0))
        ttk.Button(actions, text="打开结果目录", command=self.open_output_dir).grid(row=0, column=2, sticky="w", padx=(10, 0))
        ttk.Button(actions, text="退出", command=self.root.destroy).grid(row=0, column=3, sticky="w", padx=(10, 0))

        self.log_box = ScrolledText(
            shell,
            wrap="word",
            font=("Consolas", 10),
            bg="#0f172a",
            fg="#dde6f4",
            insertbackground="#dde6f4",
            relief="flat",
            padx=12,
            pady=12,
        )
        self.log_box.grid(row=3, column=0, sticky="nsew", pady=(18, 0))
        self.log_box.configure(state="disabled")

        footer = ttk.Frame(shell, style="Panel.TFrame")
        footer.grid(row=4, column=0, sticky="ew", pady=(14, 0))
        ttk.Label(footer, text=FOOTER_TEXT, style="Muted.TLabel").grid(row=0, column=0, sticky="w")

    def build_output_preview(self) -> str:
        source_root = Path(self.source_var.get().strip() or BASE_DIR)
        if not source_root.name:
            return "结果目录：未选择素材文件夹"
        return f"结果目录：{source_root.parent / f'{source_root.name}_{OUTPUT_SUFFIX}'}"

    def refresh_output_preview(self) -> None:
        self.output_var.set(self.build_output_preview())

    def choose_source_folder(self) -> None:
        initial_dir = self.source_var.get().strip() or str(BASE_DIR)
        selected = filedialog.askdirectory(initialdir=initial_dir)
        if not selected:
            return
        self.source_var.set(selected)
        self.refresh_output_preview()
        self.start_scan()

    def resolve_source_root(self) -> Path:
        source_text = self.source_var.get().strip()
        if not source_text:
            raise ValueError("请先选择素材文件夹。")
        source_root = Path(source_text).expanduser().resolve()
        if not source_root.exists() or not source_root.is_dir():
            raise ValueError(f"素材文件夹不存在：{source_root}")
        return source_root

    def compile_rules(self) -> re.Pattern[str]:
        return build_regex(self.use_default_rule_var.get(), self.custom_regex_var.get())

    def set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.scan_button.configure(state=state)
        self.process_button.configure(state=state)

    def start_scan(self) -> None:
        if self.worker and self.worker.is_alive():
            self.log("当前任务尚未完成，请等待。", "warn")
            return

        try:
            source_root = self.resolve_source_root()
            pattern = self.compile_rules()
        except Exception as error:  # noqa: BLE001
            messagebox.showerror("扫描失败", str(error))
            return

        self.current_action = "scan"
        self.status_var.set("扫描中")
        self.summary_var.set("正在扫描图片数量，请稍候。")
        self.progress_var.set("扫描中")
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start(12)
        self.set_busy(True)
        self.log(f"开始扫描：{source_root}")

        self.worker = threading.Thread(target=self.run_scan, args=(source_root, pattern), daemon=True)
        self.worker.start()

    def run_scan(self, source_root: Path, pattern: re.Pattern[str]) -> None:
        try:
            summary = scan_source_folder(source_root, pattern)
            self.event_queue.put(("scan_done", summary))
            self.log(
                f"扫描完成，共找到 {summary.total_images} 张图片，预计会改名 {summary.matched_images} 张，涉及 {summary.folder_count} 个子目录。"
            )
        except Exception as error:  # noqa: BLE001
            self.event_queue.put(("error", ("扫描失败", str(error))))
            self.log(traceback.format_exc().strip(), "error")
        finally:
            self.event_queue.put(("unlock", None))

    def start_process(self) -> None:
        if self.worker and self.worker.is_alive():
            self.log("当前任务尚未完成，请等待。", "warn")
            return

        try:
            source_root = self.resolve_source_root()
            pattern = self.compile_rules()
        except Exception as error:  # noqa: BLE001
            messagebox.showerror("处理失败", str(error))
            return

        self.current_action = "process"
        self.status_var.set("处理中")
        self.progress_var.set("0 / 0")
        self.progress_bar.stop()
        self.progress_bar.configure(mode="determinate", maximum=100, value=0)
        self.set_busy(True)
        self.log(f"开始处理：{source_root}")

        self.worker = threading.Thread(target=self.run_process, args=(source_root, pattern), daemon=True)
        self.worker.start()

    def run_process(self, source_root: Path, pattern: re.Pattern[str]) -> None:
        try:
            summary = process_source_folder(
                source_root,
                pattern,
                progress_callback=lambda current, total: self.event_queue.put(("progress", (current, total))),
                log_callback=self.log,
            )
            self.event_queue.put(("done", summary))
        except Exception as error:  # noqa: BLE001
            self.event_queue.put(("error", ("处理失败", str(error))))
            self.log(traceback.format_exc().strip(), "error")
        finally:
            self.event_queue.put(("unlock", None))

    def open_output_dir(self) -> None:
        preview_text = self.output_var.get().removeprefix("结果目录：")
        output_path = Path(preview_text.strip())
        if not output_path.exists():
            messagebox.showinfo("打开结果目录", "当前预览目录还不存在，请先执行处理。")
            return
        try:
            if sys.platform.startswith("darwin"):
                subprocess.run(["open", str(output_path)], check=False)
            elif os.name == "nt":
                os.startfile(output_path)  # type: ignore[attr-defined]
            else:
                subprocess.run(["xdg-open", str(output_path)], check=False)
        except Exception as error:  # noqa: BLE001
            messagebox.showerror("打开失败", f"无法打开结果目录：{error}")

    def clear_logs(self) -> None:
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def flush_events(self) -> None:
        try:
            while True:
                event, payload = self.event_queue.get_nowait()
                if event == "log":
                    self.append_log(payload)
                elif event == "scan_done":
                    self.handle_scan_done(payload)
                elif event == "progress":
                    self.handle_progress(payload)
                elif event == "done":
                    self.handle_done(payload)
                elif event == "error":
                    title, message = payload
                    self.status_var.set("执行失败")
                    self.progress_bar.stop()
                    self.progress_bar.configure(mode="determinate", maximum=100, value=0)
                    self.progress_var.set("0 / 0")
                    messagebox.showerror(title, message)
                elif event == "unlock":
                    self.set_busy(False)
        except Empty:
            pass
        finally:
            self.root.after(120, self.flush_events)

    def handle_scan_done(self, summary: ScanSummary) -> None:
        self.status_var.set("扫描完成")
        self.progress_bar.stop()
        self.progress_bar.configure(mode="determinate", maximum=100, value=0)
        self.progress_var.set(f"{summary.total_images} 张图片")
        self.summary_var.set(
            f"共检测到 {summary.total_images} 张图片，预计会改名 {summary.matched_images} 张，扫描到 {summary.folder_count} 个子目录。"
        )

    def handle_progress(self, progress_data: tuple[int, int]) -> None:
        current, total = progress_data
        maximum = total if total > 0 else 100
        self.progress_bar.configure(maximum=maximum, value=current)
        self.progress_var.set(f"{current} / {total}")

    def handle_done(self, summary: ProcessSummary) -> None:
        self.status_var.set("处理完成")
        self.progress_bar.configure(mode="determinate", maximum=summary.total_images, value=summary.total_images)
        self.progress_var.set(f"{summary.total_images} / {summary.total_images}")
        self.summary_var.set(
            f"本次处理 {summary.total_images} 张图片，成功改名 {summary.renamed_images} 张，未改动 {summary.unchanged_images} 张。"
        )
        self.output_var.set(f"结果目录：{summary.output_dir}")
        self.log(
            f"处理完成，结果目录：{summary.output_dir}；改名 {summary.renamed_images} 张，重名避让 {summary.duplicate_images} 张。",
            "success",
        )
        messagebox.showinfo(
            "处理完成",
            "\n".join(
                [
                    f"结果目录：{summary.output_dir}",
                    f"图片总数：{summary.total_images}",
                    f"成功改名：{summary.renamed_images}",
                    f"未改动：{summary.unchanged_images}",
                    f"重名避让：{summary.duplicate_images}",
                ]
            ),
        )

    def append_log(self, message: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"{message}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def log(self, message: str, level: str = "info") -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.event_queue.put(("log", f"[{stamp}] [{level.upper()}] {message}"))

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    if TK_IMPORT_ERROR is not None:
        raise SystemExit(f"当前 Python 缺少 tkinter，无法启动 GUI：{TK_IMPORT_ERROR}")

    app = MaterialImageNameCleanerApp()
    app.run()


if __name__ == "__main__":
    main()
