"""Loopback-only service lifecycle for the self-contained Windows application."""

from dataclasses import replace
import importlib
import json
import secrets
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

import portable_paths
from portable_settings import Preferences


class PortableController:
    def __init__(self, preferences=None, *, root=None, data=None):
        portable_paths.activate(root=root, data=data)
        self.preferences = preferences or Preferences()
        self.preferences.validate()
        self.access_token = secrets.token_urlsafe(24)
        self.api_key = ""
        self.notice = ""
        self._lock = threading.RLock()
        self._servers = []
        self._closed = False
        config = importlib.import_module("config")
        self.config = config.Config
        self._set_config(self.preferences, "", self.access_token)
        self.module = importlib.import_module("app")
        self.application = self.module.app
        self.application.static_folder = str(portable_paths.resource_path("static"))
        self.application.template_folder = str(portable_paths.resource_path("templates"))
        from jinja2 import FileSystemLoader
        self.application.jinja_loader = FileSystemLoader(self.application.template_folder)
        self.server, self.thread, self.server_map = self._new_server(self.preferences.port)
        self.port = int(self.server.effective_port)
        self.thread.start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def _set_config(self, preferences, api_key, access_token):
        values = {
            "ANTHROPIC_API_KEY": api_key,
            "ANTHROPIC_BASE_URL": preferences.base_url,
            "ANTHROPIC_MODEL": preferences.model,
            "API_PROTOCOL": preferences.protocol,
            "REASONING_EFFORT": preferences.reasoning_effort,
            "MAX_TOKENS": preferences.max_tokens,
            "TEMPERATURE": preferences.temperature,
            "API_TIMEOUT": preferences.timeout,
            "API_MAX_RETRIES": preferences.max_retries,
            "ENABLE_CACHE": preferences.cache_enabled,
            "CACHE_EXPIRATION": preferences.cache_expiration,
            "ACCESS_TOKEN": access_token,
            "HOST": "127.0.0.1",
            "PORT": preferences.port,
            "DEBUG": False,
            "CONFIG_SOURCE": "portable",
            "CONFIG_LOADED_AT": time.time(),
            "CCSWITCH_IS_PROXY": False,
            "EXTRA_ENV": {},
        }
        for key, value in values.items():
            setattr(self.config, key, value)

    def _new_server(self, port):
        from waitress import create_server
        server_map = {}
        try:
            server = create_server(
                self.application, host="127.0.0.1", port=port,
                threads=4, connection_limit=32, backlog=32,
                channel_timeout=120, asyncore_loop_timeout=0.2, map=server_map,
            )
        except OSError:
            if not port:
                raise
            # Only the initial launch may choose another port. The UI exposes it.
            server_map = {}
            server = create_server(
                self.application, host="127.0.0.1", port=0,
                threads=4, connection_limit=32, backlog=32,
                channel_timeout=120, asyncore_loop_timeout=0.2, map=server_map,
            )
            self.notice = "指定端口不可用，已使用空闲端口；请以窗口显示的地址为准。"
        thread = threading.Thread(target=server.run, name="portable-http", daemon=True)
        self._servers.append((server, thread, server_map))
        return server, thread, server_map

    def apply(self, preferences, api_key, access_token):
        preferences.validate()
        api_key = self._credential(api_key, "API Key", 4096)
        access_token = self._credential(access_token, "本地访问口令", 512)
        with self._lock:
            if self._closed:
                raise RuntimeError("服务已经关闭。")
            if preferences.port != self.preferences.port:
                raise ValueError("端口修改会在保存设置并重新启动程序后生效；本次请保留原端口。")
            with self.module._runtime_lock:
                previous = {k: v for k, v in vars(self.config).items() if k.isupper()}
                old_client = self.module.client
                old_error = self.module._runtime_init_error
                try:
                    self._set_config(preferences, api_key, access_token)
                    self.module._runtime_initialize()
                    if self.module.client is None or self.module.client is old_client:
                        raise RuntimeError("运行时未更新")
                except Exception:
                    for key, value in previous.items():
                        setattr(self.config, key, value)
                    self.module._runtime_init_error = old_error
                    raise RuntimeError("配置未能载入，原配置保持不变。请检查协议、地址和参数。") from None
            self.preferences = replace(preferences)
            self.api_key = api_key
            self.access_token = access_token
        return self.status()

    @staticmethod
    def _credential(value, name, maximum):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"请填写{name}。")
        value = value.strip()
        if len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError(f"{name}包含无效字符或过长。")
        return value

    def request(self, path, payload=None, *, timeout=15):
        with self._lock:
            if self._closed:
                raise RuntimeError("服务已经关闭。")
            token, url = self.access_token, self.url
        if payload is None:
            request = Request(url + path + "?" + urlencode({"token": token}))
        else:
            body = dict(payload)
            body["token"] = token
            request = Request(url + path, json.dumps(body, ensure_ascii=False).encode("utf-8"),
                              {"Content-Type": "application/json"}, method="POST")
        opener = build_opener(ProxyHandler({}))
        try:
            with opener.open(request, timeout=timeout) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
        except HTTPError as exc:
            raw = exc.read(2 * 1024 * 1024 + 1)
            try:
                body = json.loads(raw)
                message = body.get("msg") or body.get("message") or body.get("error") or f"请求失败 (HTTP {exc.code})"
            except (ValueError, AttributeError):
                message = f"请求失败 (HTTP {exc.code})"
            message = str(message).replace(self.api_key, "[hidden]") if self.api_key else str(message)
            raise RuntimeError(message.replace(token, "[hidden]")) from None
        except (URLError, TimeoutError, OSError):
            raise RuntimeError("无法连接本地服务，或请求等待超时。") from None
        if len(raw) > 2 * 1024 * 1024:
            raise RuntimeError("服务响应过大。")
        try:
            return json.loads(raw)
        except ValueError:
            raise RuntimeError("本地服务返回了无效响应。") from None

    def status(self):
        return self.request("/api/health")

    def stats(self):
        return self.request("/api/stats")

    def ask(self, question, options, question_type):
        return self.request("/api/search", {
            "question": question, "options": options, "type": question_type,
        }, timeout=max(120, (self.preferences.timeout + 2) * (self.preferences.max_retries + 1) * 2 + 30))

    def clear_cache(self):
        return self.request("/api/cache/clear", {})

    def integration_config(self):
        return [{
            "name": "EduBrain Portable",
            "homepage": self.url,
            "url": self.url + "/api/search",
            "method": "get",
            "contentType": "json",
            "data": {"title": "${title}", "options": "${options}", "type": "${type}",
                     "token": self.access_token},
            "handler": "return (res)=> res.code === 1 ? [res.question, res.answer] : [res.msg, undefined]",
        }]

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
        for server, thread, server_map in self._servers:
            server.close()
            server.task_dispatcher.shutdown(cancel_pending=True, timeout=2)
            for channel in list(server_map.values()):
                try:
                    channel.close()
                except OSError:
                    pass
            if thread.is_alive():
                thread.join(timeout=3)
        client = self.module.client
        if client is not None and hasattr(client, "close"):
            client.close()
        self.api_key = ""
        self.access_token = ""
