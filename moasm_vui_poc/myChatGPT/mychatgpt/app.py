from __future__ import annotations

import threading
import tkinter as tk
from copy import deepcopy
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Callable

from PIL import Image, ImageGrab

from .config import AppConfig, ConfigStore, PROVIDER_NAMES, environment_api_key
from .llm_client import ChatRequest, ChatResult, ProviderError, run_agentic_completion
from .markdown_view import MarkdownRenderer
from .storage import Attachment, Conversation, ConversationStore, Message, now_iso
from .voice import listen_once, speak


class ChatApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("myChatGPT")
        self.root.geometry("1180x760")
        self.root.minsize(820, 520)

        self.config_store = ConfigStore()
        self.store = ConversationStore()
        self.config = self.config_store.load()
        self.conversation = Conversation.new(self.config.workspace)
        self.pending_attachments: list[Attachment] = []
        self.input_drafts: dict[str, str] = {}
        self.busy_conversation_ids: set[str] = set()
        self.is_busy = False
        self.loading_after_id: str | None = None
        self.loading_phase = 0
        self.loading_frame: tk.Frame | None = None
        self.loading_canvas: tk.Canvas | None = None
        self.live_reasoning_parts: dict[str, list[str]] = {}
        self.settings_visible = False

        self._init_style()
        self._build_ui()
        self._load_conversations()
        if self.conversations:
            self._select_conversation(self.conversations[0].id)
        else:
            self._new_conversation(save=False)

    def _init_style(self) -> None:
        self.root.configure(bg="#faf8f2")
        self.root.option_add("*Font", "{Segoe UI} 10")
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")

        style.configure("TFrame", background="#faf8f2")
        style.configure("App.TFrame", background="#faf8f2")
        style.configure("Sidebar.TFrame", background="#f0ece4")
        style.configure("Top.TFrame", background="#faf8f2")
        style.configure("Settings.TFrame", background="#f4efe7")
        style.configure("Chat.TFrame", background="#faf8f2")
        style.configure("Composer.TFrame", background="#faf8f2")
        style.configure("Input.TFrame", background="#fffdf8")

        style.configure("TLabel", background="#faf8f2", foreground="#342f29")
        style.configure("Brand.TLabel", background="#f0ece4", foreground="#302a24", font=("Segoe UI", 15, "bold"))
        style.configure("Sidebar.TLabel", background="#f0ece4", foreground="#6f6254")
        style.configure("Title.TLabel", background="#faf8f2", foreground="#302a24", font=("Segoe UI", 14, "bold"))
        style.configure("Status.TLabel", background="#faf8f2", foreground="#867a6d")
        style.configure("Muted.TLabel", background="#faf8f2", foreground="#867a6d")
        style.configure("Pill.TLabel", background="#eee8dc", foreground="#5d5145", padding=(10, 5))
        style.configure("Top.TLabel", background="#faf8f2", foreground="#5d5145")
        style.configure("Settings.TLabel", background="#f4efe7", foreground="#5d5145")
        style.configure("Chip.TLabel", background="#eee8dc", foreground="#4a4036", padding=(9, 4))

        style.configure("TButton", padding=(10, 6), borderwidth=1, focusthickness=0)
        style.configure("Ghost.TButton", padding=(10, 6), foreground="#433a31", background="#f2ede5", bordercolor="#ded6ca")
        style.map("Ghost.TButton", background=[("active", "#e8e0d5")])
        style.configure("Sidebar.TButton", padding=(10, 7), foreground="#362f28", background="#e6ded2", bordercolor="#d8d0c2")
        style.map("Sidebar.TButton", background=[("active", "#dbd2c4")])
        style.configure("Accent.TButton", padding=(14, 8), foreground="#fffdf8", background="#2f2a24", bordercolor="#2f2a24")
        style.map("Accent.TButton", background=[("active", "#463d34"), ("disabled", "#b9afa2")])
        style.configure("Tiny.TButton", padding=(6, 3), foreground="#5d5145", background="#eee8dc", bordercolor="#ded6ca")
        style.map("Tiny.TButton", background=[("active", "#e1d8cb")])

        style.configure("TCheckbutton", background="#f4efe7", foreground="#5d5145")
        style.map("TCheckbutton", background=[("active", "#f4efe7")])
        style.configure("TEntry", fieldbackground="#fffdf8", foreground="#302a24", bordercolor="#d8d0c2", lightcolor="#d8d0c2", darkcolor="#d8d0c2", padding=(7, 5))
        style.configure("TCombobox", fieldbackground="#fffdf8", foreground="#302a24", bordercolor="#d8d0c2", arrowcolor="#6f6254", padding=(7, 5))

    def _build_ui(self) -> None:
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        sidebar = ttk.Frame(self.root, style="Sidebar.TFrame", width=292)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.rowconfigure(2, weight=1)

        side_header = ttk.Frame(sidebar, style="Sidebar.TFrame")
        side_header.grid(row=0, column=0, sticky="ew", padx=16, pady=(18, 12))
        side_header.columnconfigure(0, weight=1)
        ttk.Label(side_header, text="myChatGPT", style="Brand.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(side_header, text="\u65b0\u5efa", command=self._new_conversation, style="Sidebar.TButton").grid(row=0, column=1, sticky="e")

        actions = ttk.Frame(sidebar, style="Sidebar.TFrame")
        actions.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 12))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        ttk.Button(actions, text="\u91cd\u547d\u540d", command=self._rename_current, style="Sidebar.TButton").grid(row=0, column=0, sticky="ew", padx=(0, 4), pady=(0, 6))
        ttk.Button(actions, text="\u5bfc\u51fa MD", command=self._export_current_markdown, style="Sidebar.TButton").grid(row=0, column=1, sticky="ew", padx=(4, 0), pady=(0, 6))
        ttk.Button(actions, text="\u5220\u9664\u5f53\u524d\u5bf9\u8bdd", command=self._delete_current, style="Sidebar.TButton").grid(row=1, column=0, columnspan=2, sticky="ew")

        list_frame = ttk.Frame(sidebar, style="Sidebar.TFrame")
        list_frame.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 16))
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)
        self.history_list = tk.Listbox(
            list_frame,
            bd=0,
            highlightthickness=0,
            activestyle="none",
            bg="#f0ece4",
            fg="#332c25",
            selectbackground="#ded5c7",
            selectforeground="#251f1a",
            font=("Segoe UI", 10),
            relief="flat",
            exportselection=False,
        )
        self.history_list.grid(row=0, column=0, sticky="nsew")
        history_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.history_list.yview)
        history_scroll.grid(row=0, column=1, sticky="ns")
        self.history_list.configure(yscrollcommand=history_scroll.set)
        self.history_list.bind("<<ListboxSelect>>", self._on_history_select)

        main = ttk.Frame(self.root, style="App.TFrame")
        main.grid(row=0, column=1, sticky="nsew")
        main.rowconfigure(1, weight=1)
        main.columnconfigure(0, weight=1)

        self._build_topbar(main)
        self._build_chat_area(main)
        self._build_composer(main)

    def _build_topbar(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent, style="Top.TFrame", padding=(28, 16, 28, 8))
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)

        self.provider_var = tk.StringVar(value=self.config.provider)
        self.model_var = tk.StringVar(value=self.config.model)
        self.base_url_var = tk.StringVar(value=self.config.base_url)
        self.api_key_var = tk.StringVar(value=self.config.api_key)
        self.workspace_var = tk.StringVar(value=self.config.workspace)
        self.use_workspace_var = tk.BooleanVar(value=self.config.use_workspace)
        self.agent_mode_var = tk.BooleanVar(value=self.config.agent_mode)
        self.allow_write_var = tk.BooleanVar(value=self.config.allow_write_tools)
        self.auto_speak_var = tk.BooleanVar(value=self.config.auto_speak)
        self.enable_web_search_var = tk.BooleanVar(value=self.config.enable_web_search)
        self.status_var = tk.StringVar(value="\u5c31\u7eea")
        self.chat_title_var = tk.StringVar(value="\u65b0\u5bf9\u8bdd")
        self.model_badge_var = tk.StringVar(value=self._model_badge_text())

        header = ttk.Frame(top, style="Top.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, textvariable=self.chat_title_var, style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, textvariable=self.model_badge_var, style="Pill.TLabel").grid(row=0, column=1, padx=(10, 8), sticky="e")
        ttk.Label(header, textvariable=self.status_var, style="Status.TLabel").grid(row=0, column=2, padx=(0, 8), sticky="e")
        self.settings_button = ttk.Button(header, text="\u8bbe\u7f6e", command=self._toggle_settings, style="Ghost.TButton")
        self.settings_button.grid(row=0, column=3, sticky="e")

        self.settings_panel = ttk.Frame(top, style="Settings.TFrame", padding=(14, 12, 14, 12))
        self.settings_panel.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        self.settings_panel.columnconfigure(3, weight=1)
        self.settings_panel.columnconfigure(5, weight=1)

        ttk.Label(self.settings_panel, text="Provider", style="Settings.TLabel").grid(row=0, column=0, padx=(0, 6), pady=(0, 8), sticky="w")
        provider = ttk.Combobox(
            self.settings_panel,
            textvariable=self.provider_var,
            values=PROVIDER_NAMES,
            width=17,
            state="readonly",
        )
        provider.grid(row=0, column=1, padx=(0, 14), pady=(0, 8), sticky="w")
        provider.bind("<<ComboboxSelected>>", self._on_provider_changed)

        ttk.Label(self.settings_panel, text="Model", style="Settings.TLabel").grid(row=0, column=2, padx=(0, 6), pady=(0, 8), sticky="w")
        ttk.Entry(self.settings_panel, textvariable=self.model_var, width=28).grid(row=0, column=3, padx=(0, 14), pady=(0, 8), sticky="ew")

        ttk.Label(self.settings_panel, text="API Key", style="Settings.TLabel").grid(row=0, column=4, padx=(0, 6), pady=(0, 8), sticky="w")
        ttk.Entry(self.settings_panel, textvariable=self.api_key_var, show="*", width=34).grid(row=0, column=5, padx=(0, 10), pady=(0, 8), sticky="ew")
        ttk.Button(self.settings_panel, text="\u4fdd\u5b58", command=self._save_settings, style="Accent.TButton").grid(row=0, column=6, pady=(0, 8), sticky="ew")

        ttk.Label(self.settings_panel, text="Base URL", style="Settings.TLabel").grid(row=1, column=0, padx=(0, 6), pady=(0, 8), sticky="w")
        ttk.Entry(self.settings_panel, textvariable=self.base_url_var, width=44).grid(row=1, column=1, columnspan=3, padx=(0, 14), pady=(0, 8), sticky="ew")

        ttk.Label(self.settings_panel, text="\u5de5\u4f5c\u6587\u4ef6\u5939", style="Settings.TLabel").grid(row=1, column=4, padx=(0, 6), pady=(0, 8), sticky="w")
        ttk.Entry(self.settings_panel, textvariable=self.workspace_var, width=36).grid(row=1, column=5, padx=(0, 10), pady=(0, 8), sticky="ew")
        ttk.Button(self.settings_panel, text="\u9009\u62e9", command=self._choose_workspace, style="Ghost.TButton").grid(row=1, column=6, pady=(0, 8), sticky="ew")

        toggles = ttk.Frame(self.settings_panel, style="Settings.TFrame")
        toggles.grid(row=2, column=0, columnspan=7, sticky="ew")
        ttk.Checkbutton(toggles, text="\u4f7f\u7528\u5de5\u4f5c\u6587\u4ef6\u5939", variable=self.use_workspace_var, command=self._save_settings).grid(row=0, column=0, padx=(0, 14), sticky="w")
        ttk.Checkbutton(toggles, text="\u4ee3\u7406\u6a21\u5f0f", variable=self.agent_mode_var, command=self._save_settings).grid(row=0, column=1, padx=(0, 14), sticky="w")
        ttk.Checkbutton(toggles, text="\u5141\u8bb8\u5199\u5165/\u547d\u4ee4", variable=self.allow_write_var, command=self._save_settings).grid(row=0, column=2, padx=(0, 14), sticky="w")
        ttk.Checkbutton(toggles, text="\u8054\u7f51\u641c\u7d22", variable=self.enable_web_search_var, command=self._save_settings).grid(row=0, column=3, padx=(0, 14), sticky="w")
        ttk.Checkbutton(toggles, text="\u81ea\u52a8\u6717\u8bfb", variable=self.auto_speak_var, command=self._save_settings).grid(row=0, column=4, padx=(0, 14), sticky="w")

        self.settings_panel.grid_remove()

    def _model_badge_text(self) -> str:
        provider = self.provider_var.get() if hasattr(self, "provider_var") else self.config.provider
        model = self.model_var.get() if hasattr(self, "model_var") else self.config.model
        return f"{provider} / {model or 'model'}"

    def _toggle_settings(self) -> None:
        self.settings_visible = not self.settings_visible
        if self.settings_visible:
            self.settings_panel.grid()
            self.settings_button.configure(text="\u6536\u8d77")
        else:
            self.settings_panel.grid_remove()
            self.settings_button.configure(text="\u8bbe\u7f6e")

    def _build_chat_area(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent, style="Chat.TFrame")
        frame.grid(row=1, column=0, sticky="nsew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        self.chat_text = tk.Text(
            frame,
            wrap="word",
            bd=0,
            highlightthickness=0,
            padx=0,
            pady=18,
            bg="#faf8f2",
            fg="#2f2a24",
            insertbackground="#302a24",
            selectbackground="#b88a55",
            selectforeground="#fffdf8",
            font=("Segoe UI", 11),
            relief="flat",
            exportselection=False,
        )
        self.chat_text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.chat_text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.chat_text.configure(yscrollcommand=scroll.set)
        self._setup_chat_readonly_bindings()
        self.renderer = MarkdownRenderer(self.chat_text)

    def _setup_chat_readonly_bindings(self) -> None:
        self.chat_text.bind("<Control-c>", self._copy_chat_selection)
        self.chat_text.bind("<Control-C>", self._copy_chat_selection)
        self.chat_text.bind("<Control-Insert>", self._copy_chat_selection)
        self.chat_text.bind("<Control-a>", self._select_all_chat)
        self.chat_text.bind("<Control-A>", self._select_all_chat)
        self.chat_text.bind("<Key>", self._block_chat_edit)

    def _copy_chat_selection(self, _event=None) -> str:
        try:
            selected = self.chat_text.get("sel.first", "sel.last")
        except tk.TclError:
            return "break"
        self.root.clipboard_clear()
        self.root.clipboard_append(selected)
        return "break"

    def _select_all_chat(self, _event=None) -> str:
        self.chat_text.tag_add(tk.SEL, "1.0", "end-1c")
        self.chat_text.mark_set(tk.INSERT, "1.0")
        self.chat_text.see(tk.INSERT)
        return "break"

    def _block_chat_edit(self, event) -> str | None:
        allowed = {
            "Left", "Right", "Up", "Down", "Prior", "Next", "Home", "End",
            "Shift_L", "Shift_R", "Control_L", "Control_R", "Escape",
        }
        if event.keysym in allowed:
            return None
        if event.state & 0x0004 and event.keysym.lower() in {"c", "a"}:
            return None
        return "break"

    def _build_composer(self, parent: ttk.Frame) -> None:
        outer = ttk.Frame(parent, style="Composer.TFrame", padding=(32, 0, 32, 24))
        outer.grid(row=2, column=0, sticky="ew")
        outer.columnconfigure(0, weight=1)

        self.attachments_frame = ttk.Frame(outer, style="Composer.TFrame")
        self.attachments_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        input_frame = tk.Frame(
            outer,
            bg="#fffdf8",
            highlightthickness=1,
            highlightbackground="#d8d0c2",
            highlightcolor="#b7a58f",
            bd=0,
        )
        input_frame.grid(row=1, column=0, sticky="ew")
        input_frame.columnconfigure(1, weight=1)
        input_frame.rowconfigure(0, weight=1)

        ttk.Button(input_frame, text="\u9644\u4ef6", command=self._add_files, style="Ghost.TButton").grid(row=0, column=0, padx=(10, 6), pady=10, sticky="ns")
        self.input_text = tk.Text(
            input_frame,
            height=4,
            wrap="word",
            bd=0,
            relief="flat",
            highlightthickness=0,
            bg="#fffdf8",
            fg="#2f2a24",
            insertbackground="#2f2a24",
            selectbackground="#b88a55",
            selectforeground="#fffdf8",
            padx=8,
            pady=10,
            font=("Segoe UI", 11),
            undo=True,
        )
        self.input_text.grid(row=0, column=1, sticky="ew")
        self.input_text.bind("<Return>", self._on_enter)
        self.input_text.bind("<Shift-Return>", self._on_shift_enter)
        self.input_text.bind("<Control-v>", self._on_paste)
        self.input_text.bind("<Control-V>", self._on_paste)

        right = ttk.Frame(input_frame, style="Input.TFrame")
        right.grid(row=0, column=2, padx=(8, 10), pady=10, sticky="ns")
        self.listen_button = ttk.Button(right, text="\u542c\u5199", command=self._listen, style="Ghost.TButton")
        self.listen_button.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.send_button = ttk.Button(right, text="\u53d1\u9001", style="Accent.TButton", command=self._send)
        self.send_button.grid(row=1, column=0, sticky="ew")

    def _load_conversations(self) -> None:
        self.conversations = self.store.list_conversations()
        self.history_list.delete(0, tk.END)
        for item in self.conversations:
            title = " ".join(item.title.replace("\n", " ").split())[:30] or "\u65b0\u5bf9\u8bdd"
            stamp = item.updated_at[5:16].replace("T", " ") if len(item.updated_at) >= 16 else item.updated_at
            self.history_list.insert(tk.END, f"{title}  {stamp}")

    def _sync_header_title(self) -> None:
        if not hasattr(self, "chat_title_var"):
            return
        title = " ".join((self.conversation.title or "\u65b0\u5bf9\u8bdd").split())
        self.chat_title_var.set(title[:64] or "\u65b0\u5bf9\u8bdd")

    def _save_current_draft(self) -> None:
        if not hasattr(self, "input_text") or not self.conversation:
            return
        draft = self.input_text.get("1.0", "end-1c")
        if draft:
            self.input_drafts[self.conversation.id] = draft
        else:
            self.input_drafts.pop(self.conversation.id, None)

    def _restore_current_draft(self) -> None:
        if not hasattr(self, "input_text"):
            return
        self.input_text.delete("1.0", tk.END)
        draft = self.input_drafts.get(self.conversation.id, "")
        if draft:
            self.input_text.insert("1.0", draft)

    def _is_conversation_busy(self, conversation_id: str | None = None) -> bool:
        target_id = conversation_id or self.conversation.id
        return target_id in self.busy_conversation_ids

    def _new_conversation(self, save: bool = True) -> None:
        self._save_current_draft()
        self._save_settings(silent=True)
        self.conversation = Conversation.new(self.workspace_var.get().strip())
        self.pending_attachments.clear()
        self._render_conversation()
        self._render_attachments()
        self._restore_current_draft()
        self._sync_header_title()
        self._sync_busy_controls()
        if save:
            self.store.save(self.conversation)
            self._load_conversations()
            self._highlight_current()

    def _select_conversation(self, conversation_id: str) -> None:
        self._save_current_draft()
        conversation = self.store.load(conversation_id)
        if not conversation:
            return
        self.conversation = conversation
        if conversation.workspace:
            self.workspace_var.set(conversation.workspace)
        self.pending_attachments.clear()
        self._render_conversation()
        self._render_attachments()
        self._restore_current_draft()
        self._sync_header_title()
        self._highlight_current()
        self._sync_busy_controls()

    def _on_history_select(self, _event=None) -> None:
        selection = self.history_list.curselection()
        if not selection:
            return
        index = selection[0]
        if 0 <= index < len(self.conversations):
            self._select_conversation(self.conversations[index].id)

    def _highlight_current(self) -> None:
        for index, item in enumerate(self.conversations):
            if item.id == self.conversation.id:
                self.history_list.selection_clear(0, tk.END)
                self.history_list.selection_set(index)
                self.history_list.see(index)
                break

    def _delete_current(self) -> None:
        if not self.conversation:
            return
        if not messagebox.askyesno(
            "\u5220\u9664\u5bf9\u8bdd",
            "\u786e\u5b9a\u5220\u9664\u5f53\u524d\u5bf9\u8bdd\u5417\uff1f",
            parent=self.root,
        ):
            return
        deleted_id = self.conversation.id
        self.input_drafts.pop(deleted_id, None)
        self.busy_conversation_ids.discard(deleted_id)
        self.store.delete(deleted_id)
        self._clear_loading()
        self._sync_busy_controls()
        self._load_conversations()
        if self.conversations:
            self._select_conversation(self.conversations[0].id)
        else:
            self._new_conversation(save=True)

    def _clear_current_conversation(self) -> None:
        if self._is_conversation_busy():
            return
        self.conversation.messages.clear()
        self.conversation.title = "\u65b0\u5bf9\u8bdd"
        self.conversation.updated_at = now_iso()
        self.pending_attachments.clear()
        self.input_drafts.pop(self.conversation.id, None)
        self.input_text.delete("1.0", tk.END)
        self.store.save(self.conversation)
        self._render_conversation()
        self._render_attachments()
        self._load_conversations()
        self._highlight_current()
        self._sync_header_title()
        self._set_status("\u5df2\u6e05\u7a7a\u5f53\u524d\u5bf9\u8bdd")

    def _rename_current(self) -> None:
        if not self.conversation:
            return
        title = simpledialog.askstring(
            "\u91cd\u547d\u540d\u5bf9\u8bdd",
            "\u8f93\u5165\u65b0\u7684\u5bf9\u8bdd\u540d\u79f0\uff1a",
            initialvalue=self.conversation.title,
            parent=self.root,
        )
        if title is None:
            return
        clean_title = " ".join(title.split())[:80]
        if not clean_title:
            return
        self.conversation.title = clean_title
        self.conversation.updated_at = now_iso()
        self.store.save(self.conversation)
        self._load_conversations()
        self._highlight_current()
        self._sync_header_title()
        self._set_status("\u5df2\u91cd\u547d\u540d\u5bf9\u8bdd")

    def _export_current_markdown(self) -> None:
        if not self.conversation:
            return
        default_name = self._default_export_file_name()
        path_text = filedialog.asksaveasfilename(
            title="\u5bfc\u51fa\u5bf9\u8bdd\u4e3a Markdown",
            defaultextension=".md",
            initialfile=default_name,
            filetypes=(("Markdown", "*.md"), ("Text", "*.txt"), ("All files", "*.*")),
            parent=self.root,
        )
        if not path_text:
            return
        path = Path(path_text)
        try:
            path.write_text(self._conversation_to_markdown(), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("\u5bfc\u51fa\u5931\u8d25", str(exc), parent=self.root)
            return
        self._set_status(f"\u5df2\u5bfc\u51fa\uff1a{path}")

    def _default_export_file_name(self) -> str:
        title = " ".join((self.conversation.title or "myChatGPT").split()) or "myChatGPT"
        invalid = '<>:"/\\|?*'
        safe = "".join("-" if ch in invalid else ch for ch in title).strip(" .")
        return f"{safe[:60] or 'myChatGPT'}.md"

    def _conversation_to_markdown(self) -> str:
        lines = [f"# {self.conversation.title or 'myChatGPT'}", ""]
        if self.conversation.workspace:
            lines.extend([f"- Workspace: `{self.conversation.workspace}`", ""])
        lines.extend([f"- Created: {self.conversation.created_at}", f"- Updated: {self.conversation.updated_at}", ""])
        for message in self.conversation.messages:
            role = "\u4f60" if message.role == "user" else "myChatGPT"
            lines.extend(["---", "", f"## {role}  {message.created_at}", ""])
            if message.reasoning:
                lines.extend(["### \u5904\u7406\u8fc7\u7a0b", ""])
                lines.extend(
                    ">" if not line.strip() else f"> {line}"
                    for line in message.reasoning.splitlines()
                )
                lines.append("")
            if message.content:
                lines.extend([message.content.rstrip(), ""])
            if message.attachments:
                lines.extend(["### \u9644\u4ef6", ""])
                for item in message.attachments:
                    lines.append(f"- `{item.name}` ({item.kind}, {item.mime}, {item.size} bytes)")
                lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def _render_conversation(self) -> None:
        self._clear_loading()
        self._clear_live_reasoning()
        self.chat_text.delete("1.0", tk.END)
        for message in self.conversation.messages:
            self._append_message_to_chat(message)
        if self._is_conversation_busy():
            if self.live_reasoning_parts.get(self.conversation.id):
                self._render_live_reasoning(self.conversation.id)
            else:
                self._show_loading()

    def _append_message_to_chat(self, message: Message) -> None:
        if message.role == "user":
            content = message.content or ("\u4ec5\u9644\u4ef6" if message.attachments else "")
            self.renderer.append_user_message(content, message.created_at)
            if message.attachments:
                for item in message.attachments:
                    self.renderer.append_plain(f"[{item.kind}] {item.name}  {item.mime}  {item.size} bytes\n", "meta")
                self.renderer.append_plain("\n", "meta")
            return

        self.renderer.append_role_header(message.role, message.created_at)
        if message.attachments:
            for item in message.attachments:
                self.renderer.append_plain(f"[{item.kind}] {item.name}  {item.mime}  {item.size} bytes\n", "meta")
            self.renderer.append_plain("\n", "meta")
        if message.reasoning:
            self.renderer.append_reasoning(message.reasoning, collapsed=True)
        if message.content:
            self.renderer.append_markdown(message.content)
        elif message.attachments:
            self.renderer.append_plain("[\u4ec5\u9644\u4ef6]\n", "meta")

    def _append_live_message(self, message: Message) -> None:
        self._append_message_to_chat(message)
        self.chat_text.see(tk.END)

    def _on_provider_changed(self, _event=None) -> None:
        cfg = self._config_from_form()
        old_model = self.model_var.get().strip()
        old_base = self.base_url_var.get().strip()
        cfg.apply_provider_defaults()
        if not old_model or old_model.startswith(("gpt-", "gemini", "claude")):
            self.model_var.set(cfg.model)
        if not old_base or any(value in old_base for value in ("openai", "googleapis", "anthropic", "aitogit")):
            self.base_url_var.set(cfg.base_url)
        self._save_settings(silent=True)

    def _choose_workspace(self) -> None:
        path = filedialog.askdirectory(title="选择工作文件夹")
        if not path:
            return
        self.workspace_var.set(path)
        self.conversation.workspace = path
        self._save_settings(silent=True)
        self.store.save(self.conversation)
        self._set_status(f"工作文件夹：{path}")

    def _config_from_form(self) -> AppConfig:
        cfg = AppConfig(
            provider=self.provider_var.get().strip().lower() or "openai",
            api_key=self.api_key_var.get().strip(),
            model=self.model_var.get().strip(),
            base_url=self.base_url_var.get().strip(),
            workspace=self.workspace_var.get().strip(),
            use_workspace=self.use_workspace_var.get(),
            agent_mode=self.agent_mode_var.get(),
            allow_write_tools=self.allow_write_var.get(),
            auto_speak=self.auto_speak_var.get(),
            enable_web_search=self.enable_web_search_var.get(),
        )
        cfg.apply_provider_defaults()
        return cfg

    def _save_settings(self, silent: bool = False) -> None:
        self.config = self._config_from_form()
        self.config_store.save(self.config)
        if self.conversation:
            self.conversation.workspace = self.config.workspace
        if hasattr(self, "model_badge_var"):
            self.model_badge_var.set(self._model_badge_text())
        if not silent:
            if not self.config.api_key and environment_api_key(self.config.provider):
                self._set_status("设置已保存；API Key 来自环境变量")
            else:
                self._set_status("设置已保存")

    def _add_files(self) -> None:
        paths = filedialog.askopenfilenames(title="添加附件")
        if not paths:
            return
        self._ensure_conversation_saved()
        for path_text in paths:
            path = Path(path_text)
            if path.exists():
                self.pending_attachments.append(self.store.copy_attachment(path, self.conversation.id))
        self._render_attachments()
        self._set_status(f"已添加 {len(paths)} 个附件")

    def _on_paste(self, _event=None):
        grabbed = None
        try:
            grabbed = ImageGrab.grabclipboard()
        except Exception:
            grabbed = None
        if isinstance(grabbed, Image.Image):
            self._ensure_conversation_saved()
            attachment = self.store.save_image_attachment(grabbed, self.conversation.id)
            self.pending_attachments.append(attachment)
            self._render_attachments()
            self._set_status("已从剪贴板添加截图")
            return "break"
        if isinstance(grabbed, list):
            files = [Path(item) for item in grabbed if Path(item).exists()]
            if files:
                self._ensure_conversation_saved()
                for file_path in files:
                    self.pending_attachments.append(self.store.copy_attachment(file_path, self.conversation.id))
                self._render_attachments()
                self._set_status(f"已从剪贴板添加 {len(files)} 个文件")
                return "break"
        return None

    def _render_attachments(self) -> None:
        for child in self.attachments_frame.winfo_children():
            child.destroy()
        if not self.pending_attachments:
            return
        ttk.Label(self.attachments_frame, text="\u5f85\u53d1\u9001\u9644\u4ef6", style="Muted.TLabel").grid(row=0, column=0, padx=(0, 8), sticky="w")
        for index, item in enumerate(self.pending_attachments, start=1):
            label = ttk.Label(self.attachments_frame, text=f"{item.name}", style="Chip.TLabel")
            label.grid(row=0, column=index * 2 - 1, padx=(0, 4), sticky="w")
            button = ttk.Button(self.attachments_frame, text="\u79fb\u9664", command=self._remove_attachment_factory(index - 1), style="Tiny.TButton")
            button.grid(row=0, column=index * 2, padx=(0, 8), sticky="w")

    def _remove_attachment_factory(self, index: int) -> Callable[[], None]:
        def remove() -> None:
            if 0 <= index < len(self.pending_attachments):
                self.pending_attachments.pop(index)
                self._render_attachments()
        return remove

    def _on_enter(self, event) -> str | None:
        if event.state & 0x0001:
            return None
        self._send()
        return "break"

    def _on_shift_enter(self, _event) -> None:
        self.input_text.insert(tk.INSERT, "\n")
        return "break"

    def _send(self) -> None:
        if self._is_conversation_busy():
            return
        text = self.input_text.get("1.0", "end-1c")
        if text.strip().lower() == "/clear":
            self._clear_current_conversation()
            return
        if not text.strip() and not self.pending_attachments:
            return
        self._save_settings(silent=True)
        self._ensure_conversation_saved()
        attachments = [deepcopy(item) for item in self.pending_attachments]
        user_message = Message(role="user", content=text.strip(), attachments=attachments)
        history = [deepcopy(item) for item in self.conversation.messages]
        self.conversation.add_message(user_message)
        self.store.save(self.conversation)
        self._append_live_message(user_message)
        self.pending_attachments.clear()
        self._render_attachments()
        self.input_text.delete("1.0", tk.END)
        self.input_drafts.pop(self.conversation.id, None)
        self._load_conversations()
        self._highlight_current()
        self._sync_header_title()

        cfg = deepcopy(self.config)
        workspace = cfg.workspace if cfg.use_workspace else ""
        request = ChatRequest(config=cfg, history=history, user_message=user_message, workspace=workspace)
        conversation_id = self.conversation.id
        self.busy_conversation_ids.add(conversation_id)
        self._sync_busy_controls()
        self._set_status("\u6b63\u5728\u8bf7\u6c42\u6a21\u578b...")
        self.live_reasoning_parts[conversation_id] = []
        self._show_loading()
        thread = threading.Thread(target=self._send_worker, args=(conversation_id, request), daemon=True)
        thread.start()

    def _show_loading(self) -> None:
        self._clear_loading()
        self.loading_phase = 0
        self.loading_frame = tk.Frame(self.chat_text, bg="#faf8f2", bd=0, highlightthickness=0)
        self.loading_canvas = tk.Canvas(
            self.loading_frame,
            width=76,
            height=28,
            bg="#faf8f2",
            bd=0,
            highlightthickness=0,
        )
        self.loading_canvas.pack(anchor="w")
        try:
            self.chat_text.mark_set("loading_start", "end-1c")
            self.chat_text.mark_gravity("loading_start", tk.LEFT)
            self.renderer.append_role_header("assistant", now_iso())
            self.chat_text.window_create(tk.END, window=self.loading_frame, padx=64, pady=4)
            self.chat_text.insert(tk.END, "\n")
            self.chat_text.mark_set("loading_end", "end-1c")
            self.chat_text.see(tk.END)
        except tk.TclError:
            if self.loading_frame:
                self.loading_frame.destroy()
            self.loading_frame = None
            self.loading_canvas = None
            return
        self._animate_loading()

    def _animate_loading(self) -> None:
        if not self.loading_canvas or not self._is_conversation_busy():
            return
        self._draw_loading_dots()
        self.loading_phase += 1
        self.loading_after_id = self.root.after(180, self._animate_loading)

    def _draw_loading_dots(self) -> None:
        canvas = self.loading_canvas
        if not canvas:
            return
        canvas.delete("all")
        active = self.loading_phase % 6
        centers = (17, 36, 55)
        for index, x in enumerate(centers):
            distance = min((active - index * 2) % 6, (index * 2 - active) % 6)
            radius = 5 if distance == 0 else 4
            y = 14 - (3 if distance == 0 else 0)
            color = "#6f5740" if distance == 0 else "#b6a590" if distance <= 2 else "#d8cec0"
            canvas.create_oval(x - radius, y - radius, x + radius, y + radius, fill=color, outline="")

    def _clear_loading(self) -> None:
        if self.loading_after_id:
            try:
                self.root.after_cancel(self.loading_after_id)
            except tk.TclError:
                pass
            self.loading_after_id = None
        try:
            marks = set(self.chat_text.mark_names())
            if {"loading_start", "loading_end"}.issubset(marks):
                self.chat_text.delete("loading_start", "loading_end")
                for mark in ("loading_start", "loading_end"):
                    if mark in self.chat_text.mark_names():
                        self.chat_text.mark_unset(mark)
        except tk.TclError:
            pass
        if self.loading_frame:
            try:
                self.loading_frame.destroy()
            except tk.TclError:
                pass
        self.loading_frame = None
        self.loading_canvas = None

    def _clear_live_reasoning(self) -> None:
        try:
            marks = set(self.chat_text.mark_names())
            if {"live_reasoning_start", "live_reasoning_end"}.issubset(marks):
                self.chat_text.delete("live_reasoning_start", "live_reasoning_end")
                self.chat_text.mark_unset("live_reasoning_start")
                self.chat_text.mark_unset("live_reasoning_end")
        except tk.TclError:
            pass

    def _receive_progress(self, conversation_id: str, text: str) -> None:
        if conversation_id not in self.busy_conversation_ids:
            return
        clean = text.strip()
        if not clean:
            return
        parts = self.live_reasoning_parts.setdefault(conversation_id, [])
        if clean not in parts:
            parts.append(clean)
        if self.conversation.id != conversation_id:
            return
        self._render_live_reasoning(conversation_id)

    def _render_live_reasoning(self, conversation_id: str) -> None:
        parts = self.live_reasoning_parts.get(conversation_id) or []
        if not parts:
            return
        self._clear_loading()
        self._clear_live_reasoning()
        self.chat_text.mark_set("live_reasoning_start", tk.END)
        self.chat_text.mark_gravity("live_reasoning_start", tk.LEFT)
        self.renderer.append_role_header("assistant", now_iso())
        self.renderer.append_reasoning("\n\n".join(parts), collapsed=False)
        self.chat_text.mark_set("live_reasoning_end", tk.END)
        self.chat_text.mark_gravity("live_reasoning_end", tk.RIGHT)
        self.chat_text.see(tk.END)

    def _send_worker(self, conversation_id: str, request: ChatRequest) -> None:
        def progress(text: str) -> None:
            self.root.after(0, lambda value=text: self._receive_progress(conversation_id, value))

        try:
            answer = run_agentic_completion(request, progress_callback=progress)
            self.root.after(0, lambda: self._receive_answer(conversation_id, answer))
        except ProviderError as exc:
            self.root.after(0, lambda err=str(exc): self._receive_error(conversation_id, err))
        except Exception as exc:
            self.root.after(0, lambda err=f"\u8bf7\u6c42\u5931\u8d25\uff1a{exc}": self._receive_error(conversation_id, err))

    def _receive_answer(self, conversation_id: str, answer: ChatResult) -> None:
        message = Message(
            role="assistant",
            content=answer.content or "[\u6a21\u578b\u6ca1\u6709\u8fd4\u56de\u6587\u672c]",
            created_at=now_iso(),
            reasoning=answer.reasoning,
        )
        self._finish_pending_message(conversation_id, message, "\u5b8c\u6210")
        if self.auto_speak_var.get():
            threading.Thread(target=speak, args=(message.content,), daemon=True).start()

    def _receive_error(self, conversation_id: str, error: str) -> None:
        message = Message(role="assistant", content=f"\u8bf7\u6c42\u51fa\u9519\uff1a\n\n```text\n{error}\n```", created_at=now_iso())
        self._finish_pending_message(conversation_id, message, "\u8bf7\u6c42\u5931\u8d25")

    def _finish_pending_message(self, conversation_id: str, message: Message, status: str) -> None:
        active_conversation = self.conversation.id == conversation_id
        if active_conversation:
            self._clear_loading()
            self._clear_live_reasoning()
            conversation = self.conversation
        else:
            conversation = self.store.load(conversation_id)

        if conversation is not None:
            conversation.add_message(message)
            self.store.save(conversation)
            if active_conversation:
                self.conversation = conversation
                self._append_live_message(message)
                self._sync_header_title()

        self.busy_conversation_ids.discard(conversation_id)
        self.live_reasoning_parts.pop(conversation_id, None)
        self._load_conversations()
        self._highlight_current()
        self._sync_busy_controls()
        if active_conversation:
            self._set_status(status)

    def _listen(self) -> None:
        if self._is_conversation_busy():
            return
        self._set_status("\u6b63\u5728\u542c\u5199...")
        thread = threading.Thread(target=self._listen_worker, daemon=True)
        thread.start()

    def _listen_worker(self) -> None:
        try:
            text = listen_once()
            self.root.after(0, lambda: self._insert_dictation(text))
        except Exception as exc:
            self.root.after(0, lambda err=f"\u542c\u5199\u5931\u8d25\uff1a{exc}": self._set_status(err))

    def _insert_dictation(self, text: str) -> None:
        if text:
            if self.input_text.get("1.0", "end-1c").strip():
                self.input_text.insert(tk.INSERT, "\n")
            self.input_text.insert(tk.INSERT, text)
            self._set_status("\u542c\u5199\u5b8c\u6210")
        else:
            self._set_status("\u6ca1\u6709\u8bc6\u522b\u5230\u8bed\u97f3")

    def _ensure_conversation_saved(self) -> None:
        if not self.conversation.workspace:
            self.conversation.workspace = self.workspace_var.get().strip()
        self.store.save(self.conversation)

    def _sync_busy_controls(self) -> None:
        value = self._is_conversation_busy() if self.conversation else False
        self.is_busy = value
        state = "disabled" if value else "normal"
        self.send_button.configure(state=state, text="\u7b49\u5f85\u4e2d" if value else "\u53d1\u9001")
        if hasattr(self, "listen_button"):
            self.listen_button.configure(state=state)

    def _set_busy(self, value: bool) -> None:
        if not self.conversation:
            return
        if value:
            self.busy_conversation_ids.add(self.conversation.id)
        else:
            self.busy_conversation_ids.discard(self.conversation.id)
        self._sync_busy_controls()

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)


def main() -> None:
    root = tk.Tk()
    app = ChatApp(root)
    root.mainloop()


__all__ = ["ChatApp", "main"]





