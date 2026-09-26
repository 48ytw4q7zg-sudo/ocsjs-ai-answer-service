"""Native configuration and question interface; no browser is required."""

import json
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
import webbrowser

from portable_settings import FIELD_LABELS, PreferenceError, Preferences, ProfileStore

CLIPBOARD_CLEAR_MS = 60000


class PortableWindow:
    def __init__(self, root, controller, store, *, startup_notice=""):
        self.root, self.controller, self.store = root, controller, store
        self.results = queue.Queue()
        self.busy = False
        self.closing = False
        self.variables = {}
        self.widgets = {}
        self._generation = 0
        self._cancellable = False
        self._clipboard_secret = None
        self.root.title("EduBrain 便携答题服务")
        self.root.geometry("960x740")
        self.root.minsize(760, 600)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        outer = ttk.Frame(root, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="EduBrain 便携答题服务", font=("Microsoft YaHei UI", 17, "bold")).pack(anchor="w")
        self.address = tk.StringVar(value=controller.url)
        ttk.Label(outer, textvariable=self.address).pack(anchor="w", pady=(4, 8))
        self.notebook = ttk.Notebook(outer)
        self.notebook.pack(fill="both", expand=True)
        config_page = ttk.Frame(self.notebook, padding=12)
        question_page = ttk.Frame(self.notebook, padding=12)
        records_page = ttk.Frame(self.notebook, padding=12)
        help_page = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(config_page, text="连接与设置")
        self.notebook.add(question_page, text="手动问答")
        self.notebook.add(records_page, text="运行记录")
        self.notebook.add(help_page, text="便携说明")
        self._configuration(config_page)
        self._questions(question_page)
        self._records(records_page)
        self._help(help_page)
        self.status = tk.StringVar(value=startup_notice or controller.notice or "本地服务已启动；请填写自己的模型服务配置，然后应用。")
        ttk.Label(outer, textvariable=self.status, wraplength=880).pack(anchor="w", pady=(10, 0))
        self.root.after(100, self._drain)

    def _entry(self, parent, row, name, label, value, *, values=None, secret=False):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 12))
        variable = tk.StringVar(value=str(value))
        self.variables[name] = variable
        if values is not None:
            widget = ttk.Combobox(parent, textvariable=variable, values=values, state="readonly")
        else:
            widget = ttk.Entry(parent, textvariable=variable, show="*" if secret else "")
        widget.grid(row=row, column=1, sticky="ew", pady=4)
        self.widgets[name] = widget
        return widget

    def _configuration(self, page):
        page.columnconfigure(1, weight=1)
        prefs = self.controller.preferences
        self._entry(page, 0, "protocol", "接口协议", prefs.protocol,
                    values=("anthropic", "openai_responses", "openai_chat"))
        self._entry(page, 1, "base_url", "接口基础地址", prefs.base_url)
        self._entry(page, 2, "model", "模型标识", prefs.model)
        self._entry(page, 3, "api_key", "API Key", "", secret=True)
        self._entry(page, 4, "access_token", "本地访问口令", self.controller.access_token, secret=True)
        self._entry(page, 5, "port", "本地端口（0 表示自动）", prefs.port)
        self._entry(page, 6, "reasoning_effort", "推理强度（由服务商支持）", prefs.reasoning_effort,
                    values=("auto", "low", "medium", "high", "xhigh", "max"))
        advanced = ttk.Frame(page)
        advanced.grid(row=7, column=0, columnspan=2, sticky="ew", pady=6)
        for i, (name, label, value) in enumerate((
            ("max_tokens", "输出上限", prefs.max_tokens), ("temperature", "温度（选择/判断/填空最高 0.3）", prefs.temperature),
            ("timeout", "单次超时秒", prefs.timeout), ("max_retries", "重试次数", prefs.max_retries),
            ("cache_expiration", "缓存有效秒", prefs.cache_expiration),
        )):
            ttk.Label(advanced, text=label).grid(row=i // 3 * 2, column=i % 3, sticky="w")
            variable = tk.StringVar(value=str(value))
            self.variables[name] = variable
            entry = ttk.Entry(advanced, textvariable=variable, width=18)
            entry.grid(row=i // 3 * 2 + 1, column=i % 3, sticky="ew", padx=(0, 12), pady=(2, 6))
            self.widgets[name] = entry
            advanced.columnconfigure(i % 3, weight=1)
        self.cache_enabled = tk.BooleanVar(value=prefs.cache_enabled)
        ttk.Checkbutton(page, text="启用本次运行的答案缓存", variable=self.cache_enabled).grid(row=8, column=0, columnspan=2, sticky="w")
        self.remember = tk.BooleanVar(value=False)
        ttk.Checkbutton(page, text="保存时用密码加密记住密钥和本地访问口令", variable=self.remember).grid(row=9, column=0, columnspan=2, sticky="w")
        buttons = ttk.Frame(page)
        buttons.grid(row=10, column=0, columnspan=2, sticky="w", pady=12)
        for text, command in (("应用到本次运行", self.apply), ("保存便携配置", self.save),
                              ("解锁已保存密钥", self.unlock), ("打开网页", self.open_browser),
                              ("复制接入配置", self.copy_config), ("复制访问口令", self.copy_access_token),
                              ("生成新口令", self.regenerate_access_token)):
            ttk.Button(buttons, text=text, command=command).pack(side="left", padx=(0, 6))
        ttk.Label(page, text="基础地址通常包含 /v1；程序只追加该协议的接口路径。应用配置不会发送模型请求，也不代表账号可用。\n端口修改需保存后重启。网页是可选入口；基本问答可以直接在本窗口完成。",
                  wraplength=840).grid(row=11, column=0, columnspan=2, sticky="w")

    def _questions(self, page):
        ttk.Label(page, text="题目").pack(anchor="w")
        self.question = tk.Text(page, height=5, wrap="word", font=("Microsoft YaHei UI", 10))
        self.question.pack(fill="x", pady=(4, 8))
        ttk.Label(page, text="选项（每行一个；非选择题可留空）").pack(anchor="w")
        self.options = tk.Text(page, height=4, wrap="word", font=("Microsoft YaHei UI", 10))
        self.options.pack(fill="x", pady=(4, 8))
        controls = ttk.Frame(page)
        controls.pack(fill="x", pady=(0, 8))
        ttk.Label(controls, text="题型").pack(side="left")
        self.question_type = tk.StringVar(value="single")
        ttk.Combobox(controls, textvariable=self.question_type, state="readonly", width=18,
                     values=("single", "multiple", "judgement", "completion", "short-answer")).pack(side="left", padx=8)
        ttk.Button(controls, text="提交问答", command=self.ask).pack(side="left")
        ttk.Button(controls, text="取消等待", command=self.cancel_wait).pack(side="left", padx=8)
        ttk.Label(page, text="回答与请求结果").pack(anchor="w")
        self.answer = tk.Text(page, height=10, wrap="word", state="disabled", font=("Microsoft YaHei UI", 10))
        self.answer.pack(fill="both", expand=True, pady=(4, 0))

    def _records(self, page):
        bar = ttk.Frame(page)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Button(bar, text="刷新状态", command=lambda: self._run("正在读取状态", self.controller.stats,
                   lambda result: self._replace_text(self.records, json.dumps(result, ensure_ascii=False, indent=2)))).pack(side="left")
        ttk.Button(bar, text="清空答案缓存", command=self.clear_cache).pack(side="left", padx=8)
        self.records = tk.Text(page, wrap="word", state="disabled", font=("Consolas", 10))
        self.records.pack(fill="both", expand=True)

    def _help(self, page):
        text = (
            "适用系统：Windows 10 / 11，64 位（x64）。\n\n"
            "将整个 EduBrain 文件夹解压到 U 盘或可写目录，双击 EduBrain.exe。"
            "不要只复制 exe；_internal 保存了随包运行环境，data 保存你选择保存的配置与日志。\n\n"
            "不需要安装 Python、Node、Docker，也不需要管理员权限。默认只监听本机 127.0.0.1。"
            "不读取本机 .env、cc-switch、系统代理或已有模型登录信息。\n\n"
            "首次使用请填入你自己的服务地址、模型名称和 API Key。"
            "模型请求通常需要网络与有效额度；离线可以打开界面，但不能凭空生成在线模型的答案。"
            "接入本地模型服务时，由你提供该服务。\n\n"
            "默认不保存密钥。选择密码加密保存后，可在另一台电脑用同一密码解锁；"
            "密码不随包保存，遗忘后无法恢复。普通连接参数仍以明文保存，请勿把密钥放在地址或模型名称里。\n\n"
            "本地访问口令用于保护本机答题接口。未加密保存时，每次启动会生成新的口令，"
            "接入脚本需要重新复制配置。复制的接入配置把口令放在 headers（请求头）里，不出现在网址中；"
            "它仍然是凭据，不要公开分享。复制到剪贴板的口令或配置会在 60 秒后或关闭窗口时自动清除；"
            "若开启了 Windows 剪贴板历史（Win+V），历史里的副本需要你手动删除。"
            "怀疑泄露时点击“生成新口令”，再点“应用到本次运行”，旧口令立即失效。\n\n"
            "关闭窗口会停止本地服务。退出完成后再拔出 U 盘。"
            "程序未进行商业代码签名；系统可能提示来源未知。不要关闭系统安全防护。\n\n"
            "‘运行时已就绪’仅表示配置已装载；以一次实际问答成功判断模型服务是否可用。"
        )
        box = tk.Text(page, wrap="word", font=("Microsoft YaHei UI", 11), relief="flat")
        box.pack(fill="both", expand=True)
        box.insert("1.0", text)
        box.configure(state="disabled")

    def _preferences(self):
        values = {name: variable.get().strip() for name, variable in self.variables.items()
                  if name not in ("api_key", "access_token")}
        for name, kind in (("port", int), ("max_tokens", int), ("max_retries", int), ("cache_expiration", int),
                           ("temperature", float), ("timeout", float)):
            try:
                values[name] = kind(values[name])
            except ValueError:
                expected = "整数" if kind is int else "数字"
                raise PreferenceError(name, f"{FIELD_LABELS[name]}应为有效{expected}。") from None
        values["cache_enabled"] = self.cache_enabled.get()
        return Preferences.from_mapping(values)

    def _focus_field(self, field):
        widget = self.widgets.get(field)
        if widget is None:
            return
        self.notebook.select(0)
        widget.focus_set()
        try:
            widget.selection_range(0, "end")
        except (tk.TclError, AttributeError):
            pass

    def _run(self, message, work, callback=None, *, cancellable=False):
        if self.busy or self.closing:
            self.status.set("当前操作尚未结束，请稍候。")
            return
        self.busy = True
        self._cancellable = cancellable
        self._generation += 1
        generation = self._generation
        self.status.set(message)
        def run():
            try:
                self.results.put((True, work(), callback, generation))
            except Exception as exc:
                self.results.put((False, str(exc), None, generation))
        threading.Thread(target=run, daemon=True, name="portable-ui-work").start()

    def cancel_wait(self):
        """放弃等待问答：界面立即可用，后台请求结束后结果被丢弃。

        保存、应用、解锁、清缓存必须等它们完成，否则界面会以为没做而后台其实已经生效。
        """
        if not self.busy or self.closing:
            return
        if not self._cancellable:
            self.status.set("只有问答可以取消等待；保存、应用配置等操作请等待完成。")
            return
        self._generation += 1
        self.busy = False
        self.status.set("已取消等待；后台请求结束后其结果会被丢弃（模型侧可能仍会计费）。")

    def _drain(self):
        try:
            while True:
                successful, result, callback, generation = self.results.get_nowait()
                if generation != self._generation:
                    continue
                self.busy = False
                if self.closing:
                    continue
                if successful:
                    self.status.set("操作完成。配置加载成功不等于模型请求成功。")
                    if callback:
                        callback(result)
                else:
                    self.status.set("操作未完成：" + result)
                    messagebox.showerror("操作未完成", result, parent=self.root)
        except queue.Empty:
            pass
        if not self.closing:
            self.root.after(100, self._drain)

    def _guard(self, work):
        if self.busy or self.closing:
            self.status.set("当前操作尚未结束，请稍候。")
            return
        try:
            work()
        except PreferenceError as exc:
            self._focus_field(exc.field)
            self.status.set("请修改高亮的输入项：" + str(exc))
            messagebox.showerror("请检查设置", str(exc), parent=self.root)
        except (ValueError, OSError, RuntimeError) as exc:
            messagebox.showerror("请检查设置", str(exc), parent=self.root)

    def apply(self):
        def prepare():
            preferences = self._preferences()
            key, token = self.variables["api_key"].get(), self.variables["access_token"].get()
            self._run("正在应用配置；此操作不访问模型服务", lambda: self.controller.apply(preferences, key, token))
        self._guard(prepare)

    def save(self):
        def prepare():
            preferences = self._preferences()
            credentials = password = None
            if self.remember.get():
                credentials = {
                    "api_key": self.controller._credential(self.variables["api_key"].get(), "API Key", 4096),
                    "access_token": self.controller._credential(self.variables["access_token"].get(), "本地访问口令", 512),
                }
                password = simpledialog.askstring("加密保存", "设置解锁密码（8 至 256 个字符；不会保存密码）：", show="*", parent=self.root)
                if password is None:
                    return
                confirmation = simpledialog.askstring("确认密码", "再次输入解锁密码：", show="*", parent=self.root)
                if confirmation is None:
                    return
                if password != confirmation:
                    raise ValueError("两次输入的密码不一致。")
            elif self.store.has_credentials() and not messagebox.askyesno(
                    "仅保存普通设置", "这会删除此前保存的加密密钥。是否继续？", parent=self.root):
                return
            self._run("正在保存到程序旁的 data 文件夹", lambda: self.store.save(preferences, credentials=credentials, password=password),
                      lambda _: self.status.set("便携配置已保存。端口修改在重新启动后生效。"))
        self._guard(prepare)

    def unlock(self):
        def prepare():
            if not self.store.has_credentials():
                raise ValueError("尚未保存加密密钥。")
            password = simpledialog.askstring("解锁便携配置", "输入保存时设置的密码：", show="*", parent=self.root)
            if password is None:
                return
            def fill(credentials):
                for name in ("api_key", "access_token"):
                    if credentials.get(name):
                        self.variables[name].set(credentials[name])
                self.remember.set(True)
                self.status.set("密钥已解锁到窗口。点击‘应用到本次运行’后生效。")
            self._run("正在解锁便携配置", lambda: self.store.unlock(password), fill)
        self._guard(prepare)

    def ask(self):
        question = self.question.get("1.0", "end").strip()
        options = [line.strip() for line in self.options.get("1.0", "end").splitlines() if line.strip()]
        question_type = self.question_type.get()
        if not question:
            messagebox.showwarning("缺少题目", "请先输入题目。", parent=self.root)
            return
        self._run("正在等待模型回答，请勿重复提交", lambda: self.controller.ask(question, options, question_type),
                  lambda result: self._replace_text(self.answer, json.dumps(result, ensure_ascii=False, indent=2)),
                  cancellable=True)

    def clear_cache(self):
        if self.busy or self.closing:
            return
        if messagebox.askyesno("清空缓存", "仅清空当前运行的答案缓存，是否继续？", parent=self.root):
            self._run("正在清空答案缓存", self.controller.clear_cache)

    def _copy_secret(self, value):
        self.root.clipboard_clear()
        self.root.clipboard_append(value)
        self._clipboard_secret = value
        # 公共电脑上剪贴板可被其它程序读取：到时仍未被覆盖就清空；关闭窗口时也会清空。
        self.root.after(CLIPBOARD_CLEAR_MS, lambda: self._clear_clipboard_if(value))

    def _clear_clipboard_if(self, value):
        if self.closing:
            return
        self._clear_copied_secret(value)

    def _clear_copied_secret(self, value=None):
        value = self._clipboard_secret if value is None else value
        if not value:
            return
        try:
            if self.root.clipboard_get() == value:
                self.root.clipboard_clear()
        except tk.TclError:
            pass
        if value == self._clipboard_secret:
            self._clipboard_secret = None

    def copy_config(self):
        if self.closing:
            return
        self._copy_secret(json.dumps(self.controller.integration_config(), ensure_ascii=False, indent=2))
        self.status.set("接入参数已复制（口令在 headers 中），60 秒后或关闭窗口时从剪贴板清除"
                        "（Win+V 剪贴板历史里的副本需手动删除）。请勿公开分享。")

    def open_browser(self):
        if not webbrowser.open(self.controller.url):
            messagebox.showinfo("浏览器未打开", "仍可使用本窗口问答。也可自行打开：\n" + self.controller.url, parent=self.root)

    def copy_access_token(self):
        if self.closing:
            return
        self._copy_secret(self.controller.access_token)
        self.status.set("本次运行的访问口令已复制，60 秒后或关闭窗口时从剪贴板清除"
                        "（Win+V 剪贴板历史里的副本需手动删除）。它不是模型 API Key，请勿公开分享。")

    def regenerate_access_token(self):
        if self.closing:
            return
        self.variables["access_token"].set(self.controller.generate_access_token())
        self.status.set("已生成新口令：点击“应用到本次运行”后生效，旧口令和已登录的网页会话随即失效。")

    @staticmethod
    def _replace_text(widget, value):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def close(self):
        if self.closing:
            return
        if self.busy and not messagebox.askyesno("退出", "仍有操作进行中。退出会中断等待，是否继续？", parent=self.root):
            return
        # 退出后 Tk 不再管理剪贴板，复制过的口令要在退出前清掉。
        self._clear_copied_secret()
        self.closing = True
        self.status.set("正在停止本地服务，请稍候再拔出 U 盘。")
        finished = threading.Event()
        def stop():
            try:
                self.controller.close()
            finally:
                finished.set()
        threading.Thread(target=stop, daemon=True, name="portable-shutdown").start()
        def finish():
            if finished.is_set():
                self.root.destroy()
            else:
                self.root.after(100, finish)
        self.root.after(100, finish)


def main():
    import portable_paths
    from portable_controller import PortableController
    portable_paths.activate()
    store = ProfileStore(portable_paths.data_root() / "profile.json")
    notice = ""
    try:
        preferences = store.load_preferences()
    except (ValueError, OSError) as exc:
        preferences = Preferences()
        notice = "原配置未能读取，已用临时默认设置启动；原文件未覆盖。" + str(exc)
    controller = PortableController(preferences)
    try:
        root = tk.Tk()
        PortableWindow(root, controller, store, startup_notice=notice)
        root.mainloop()
    finally:
        controller.close()
