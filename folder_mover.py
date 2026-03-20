from __future__ import annotations

import csv
import shutil
import sys
import threading
import traceback
from datetime import datetime
from io import StringIO
from pathlib import Path
from queue import Empty, Queue
import tkinter as tk
from tkinter import messagebox
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText


BASE_DIR = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
SOURCE_ROOT = BASE_DIR
MAPPING_FILE = BASE_DIR / "映射关系模板.csv"
DEST_ROOT = BASE_DIR / "迁移结果"

SOURCE_HEADER_CANDIDATES = ("产品文件夹", "源文件夹", "source", "source_folder")
TARGET_HEADER_CANDIDATES = ("材质文件夹", "目标文件夹", "target", "target_folder")
IGNORED_DIR_NAMES = {
    DEST_ROOT.name,
    ".git",
    ".github",
    "__pycache__",
    "build",
    "dist",
    "release",
}


class FolderMoverApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("文件夹映射搬运工具")
        self.root.geometry("860x580")
        self.root.minsize(760, 500)

        self.log_queue: Queue[tuple[str, str]] = Queue()
        self.worker: threading.Thread | None = None

        self.status_var = tk.StringVar(value="等待执行")
        self.summary_var = tk.StringVar(value=self.build_summary_text())

        self.setup_ui()
        self.root.after(120, self.flush_logs)
        self.log("程序已启动。")

    def setup_ui(self) -> None:
        self.root.configure(bg="#f3f6fb")

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Card.TFrame", background="#ffffff", relief="flat")
        style.configure("Primary.TButton", font=("Microsoft YaHei", 10, "bold"), padding=(16, 10))
        style.configure("Muted.TLabel", foreground="#5f6b7a", background="#ffffff", font=("Microsoft YaHei", 9))
        style.configure("Title.TLabel", foreground="#17212f", background="#ffffff", font=("Microsoft YaHei", 14, "bold"))
        style.configure("Status.TLabel", foreground="#2457d6", background="#ffffff", font=("Microsoft YaHei", 10, "bold"))

        shell = ttk.Frame(self.root, padding=16, style="Card.TFrame")
        shell.pack(fill="both", expand=True, padx=16, pady=16)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(1, weight=1)

        head = ttk.Frame(shell, style="Card.TFrame")
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(0, weight=1)

        ttk.Label(head, text="文件夹映射搬运工具", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(head, textvariable=self.status_var, style="Status.TLabel").grid(row=0, column=1, sticky="e")
        ttk.Label(head, textvariable=self.summary_var, style="Muted.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

        actions = ttk.Frame(shell, style="Card.TFrame")
        actions.grid(row=2, column=0, sticky="ew", pady=(14, 12))
        actions.columnconfigure(3, weight=1)

        self.start_btn = ttk.Button(actions, text="开始执行", style="Primary.TButton", command=self.start_run)
        self.start_btn.grid(row=0, column=0, sticky="w")

        ttk.Button(actions, text="清空日志", command=self.clear_logs).grid(row=0, column=1, sticky="w", padx=(10, 0))
        ttk.Button(actions, text="退出", command=self.root.destroy).grid(row=0, column=2, sticky="w", padx=(10, 0))

        self.log_box = ScrolledText(
            shell,
            wrap="word",
            font=("Consolas", 10),
            bg="#0f1722",
            fg="#d8e1eb",
            insertbackground="#d8e1eb",
            relief="flat",
            padx=12,
            pady=12,
        )
        self.log_box.grid(row=1, column=0, sticky="nsew", pady=(16, 0))
        self.log_box.configure(state="disabled")

    def build_summary_text(self) -> str:
        return f"当前目录：{SOURCE_ROOT}    映射表：{MAPPING_FILE.name}    输出目录：{DEST_ROOT.name}"

    def start_run(self) -> None:
        if self.worker and self.worker.is_alive():
            self.log("任务仍在执行，请等待当前任务结束。", "warn")
            return

        self.start_btn.configure(state="disabled")
        self.status_var.set("执行中")
        self.log("开始执行文件夹搬运。")

        self.worker = threading.Thread(target=self.run_task, daemon=True)
        self.worker.start()

    def run_task(self) -> None:
        try:
            result = execute_migration(self.log)
            self.log(
                f"执行完成。成功 {result['moved']} 个，跳过 {result['skipped']} 个，失败 {result['failed']} 个。",
                "success",
            )
            self.log_queue.put(("status", "已完成"))
            if result["failed"] > 0:
                self.log_queue.put(("message", "本次执行包含失败项，请查看日志。"))
        except Exception as error:  # noqa: BLE001
            self.log(f"执行失败：{error}", "error")
            self.log(traceback.format_exc().strip(), "error")
            self.log_queue.put(("status", "执行失败"))
            self.log_queue.put(("message", f"执行失败：{error}"))
        finally:
            self.log_queue.put(("unlock", ""))

    def clear_logs(self) -> None:
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def flush_logs(self) -> None:
        try:
            while True:
                event, payload = self.log_queue.get_nowait()
                if event == "log":
                    self.append_log(payload)
                elif event == "status":
                    self.status_var.set(payload)
                elif event == "unlock":
                    self.start_btn.configure(state="normal")
                elif event == "message":
                    messagebox.showinfo("执行结果", payload)
        except Empty:
            pass
        finally:
            self.root.after(120, self.flush_logs)

    def append_log(self, message: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"{message}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def log(self, message: str, level: str = "info") -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_queue.put(("log", f"[{stamp}] [{level.upper()}] {message}"))

    def run(self) -> None:
        self.root.mainloop()


def execute_migration(log) -> dict[str, int]:
    if not SOURCE_ROOT.exists():
        raise FileNotFoundError(f"当前目录不存在：{SOURCE_ROOT}")
    if not MAPPING_FILE.exists():
        raise FileNotFoundError(f"未找到映射表：{MAPPING_FILE}")

    log(f"当前目录：{SOURCE_ROOT}")
    log(f"加载映射表：{MAPPING_FILE.name}")
    mapping = load_mapping(MAPPING_FILE)
    if not mapping:
        raise ValueError("映射表为空，或没有可识别的列。")

    DEST_ROOT.mkdir(parents=True, exist_ok=True)

    moved = 0
    skipped = 0
    failed = 0
    source_folders = [
        item
        for item in SOURCE_ROOT.iterdir()
        if item.is_dir() and item.name not in IGNORED_DIR_NAMES and not item.name.startswith(".")
    ]

    if not source_folders:
        log("当前目录下没有可处理的子文件夹。", "warn")
        return {"moved": 0, "skipped": 0, "failed": 0}

    log(f"检测到 {len(source_folders)} 个候选文件夹。")

    for folder in sorted(source_folders, key=lambda item: item.name.lower()):
        target_group = mapping.get(folder.name.casefold())
        if not target_group:
            skipped += 1
            log(f"跳过：{folder.name}，映射表中未找到对应目标。", "warn")
            continue

        destination = DEST_ROOT / target_group / folder.name
        try:
            log(f"开始：{folder.name} -> {target_group}/{folder.name}")
            move_folder(folder, destination)
            moved += 1
            log(f"完成：{folder.name}", "success")
        except Exception as error:  # noqa: BLE001
            failed += 1
            log(f"失败：{folder.name}，原因：{error}", "error")

    return {"moved": moved, "skipped": skipped, "failed": failed}


def load_mapping(path: Path) -> dict[str, str]:
    text = read_text_with_fallback(path)
    reader = csv.DictReader(StringIO(text))
    if not reader.fieldnames:
        return {}

    headers = [normalize_header(item) for item in reader.fieldnames]
    source_col = pick_column(headers, SOURCE_HEADER_CANDIDATES)
    target_col = pick_column(headers, TARGET_HEADER_CANDIDATES)

    if not source_col or not target_col:
        if len(headers) >= 2:
            source_col = source_col or headers[0]
            target_col = target_col or headers[1]
        else:
            return {}

    mapping: dict[str, str] = {}
    for row in reader:
        source_name = (row.get(source_col, "") or "").strip()
        target_name = (row.get(target_col, "") or "").strip()
        if not source_name or not target_name:
            continue
        mapping[source_name.casefold()] = target_name

    return mapping


def read_text_with_fallback(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def normalize_header(value: str) -> str:
    return value.strip().lstrip("\ufeff")


def pick_column(headers: list[str], candidates: tuple[str, ...]) -> str | None:
    normalized = {header.lower(): header for header in headers}
    for candidate in candidates:
        if candidate in headers:
            return candidate
        match = normalized.get(candidate.lower())
        if match:
            return match
    return None


def move_folder(source_folder: Path, destination_folder: Path) -> None:
    destination_folder.parent.mkdir(parents=True, exist_ok=True)

    if not destination_folder.exists():
        shutil.move(str(source_folder), str(destination_folder))
        return

    if destination_folder.is_file():
        destination_folder = unique_path(destination_folder)
        shutil.move(str(source_folder), str(destination_folder))
        return

    merge_directories(source_folder, destination_folder)
    remove_empty_tree(source_folder)


def merge_directories(source_dir: Path, destination_dir: Path) -> None:
    for entry in sorted(source_dir.iterdir(), key=lambda item: item.name.lower()):
        target_entry = destination_dir / entry.name
        if entry.is_dir():
            if target_entry.exists():
                if target_entry.is_dir():
                    merge_directories(entry, target_entry)
                    remove_empty_tree(entry)
                else:
                    shutil.move(str(entry), str(unique_path(target_entry)))
            else:
                shutil.move(str(entry), str(target_entry))
            continue

        if target_entry.exists():
            target_entry = unique_path(target_entry)
        shutil.move(str(entry), str(target_entry))


def remove_empty_tree(path: Path) -> None:
    current = path
    while current.exists() and current.is_dir():
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    parent = path.parent

    for index in range(1, 10000):
        candidate = parent / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate

    raise RuntimeError(f"Unable to resolve unique path for {path}")


def main() -> int:
    app = FolderMoverApp()
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
