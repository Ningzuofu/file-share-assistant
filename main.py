import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog

from config import load_config, save_config
from server import init_server, run_server, stop_server

server_thread = None
server_running = False
root = None


class Toast:
    COLORS = {
        'success': {'bg': '#E8F8F0', 'fg': '#4A9E7A', 'icon': '✨'},
        'error': {'bg': '#FDE8E6', 'fg': '#D96B63', 'icon': '💦'},
        'warning': {'bg': '#FEF3E2', 'fg': '#D4A84B', 'icon': '🌸'},
        'info': {'bg': '#E3F0FA', 'fg': '#5A9EC7', 'icon': '💡'}
    }

    def __init__(self, parent):
        self.parent = parent
        self.frame = tk.Frame(parent, bg='#E8F8F0', height=40)
        self.frame.pack_propagate(False)

        self.icon_frame = tk.Frame(self.frame, bg='#E8F8F0', width=36)
        self.icon_frame.pack(side=tk.LEFT, fill=tk.Y)
        self.icon_frame.pack_propagate(False)

        self.icon_label = tk.Label(self.icon_frame, text='', font=('Segoe UI Emoji', 14), bg='#E8F8F0', fg='#4A9E7A')
        self.icon_label.pack(expand=True)

        self.msg_label = tk.Label(self.frame, text='', font=('Comic Sans MS', 10),
                                  bg='#E8F8F0', fg='#4A9E7A', anchor=tk.W, padx=8)
        self.msg_label.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._hide()

    def show(self, message, msg_type='info', duration=3000):
        colors = self.COLORS.get(msg_type, self.COLORS['info'])
        bg = colors['bg']
        fg = colors['fg']
        icon = colors['icon']

        for widget in (self.frame, self.icon_frame, self.icon_label, self.msg_label):
            widget.configure(bg=bg)
        self.icon_label.configure(text=icon, fg=fg)
        self.msg_label.configure(text=message, fg=fg)

        self.parent.update_idletasks()
        self.frame.place(x=0, y=0, relwidth=1.0, height=40)
        self.frame.lift()

        if duration > 0:
            self.frame.after(duration, self._hide)

    def _hide(self):
        self.frame.place_forget()




class FileShareApp:
    COLORS = {
        'bg': '#FFF5F7',
        'card_bg': '#FFFFFF',
        'header_bg': '#FFB6C8',
        'primary': '#FF8FAB',
        'primary_dark': '#E8607D',
        'secondary': '#7EC8E3',
        'success': '#7BC8A4',
        'warning': '#F7C873',
        'error': '#E8847D',
        'text': '#5D4E5A',
        'text_light': '#A8949E',
        'border': '#F5E4E8'
    }

    def __init__(self, master):
        global root
        root = master
        self.master = master
        master.title("🌸 文件共享小助手")
        master.geometry("540x620")
        master.resizable(False, False)
        master.configure(bg=self.COLORS['bg'])

        self.config = load_config()

        canvas = tk.Canvas(master, bg=self.COLORS['bg'], highlightthickness=0)
        canvas.pack(fill=tk.BOTH, expand=True)

        self.main_frame = tk.Frame(canvas, bg=self.COLORS['bg'], padx=24, pady=20)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        self._build_header()
        self._build_toast()
        self._build_settings_card()
        self._build_upload_card()
        self._build_buttons()
        self._build_status_bar()

        if server_running:
            self.update_server_status(True)

        master.protocol("WM_DELETE_WINDOW", self.on_close)

    def _card(self, parent, **kwargs):
        frame = tk.Frame(parent, bg=self.COLORS['card_bg'],
                         highlightbackground=self.COLORS['border'],
                         highlightthickness=1, **kwargs)
        return frame

    def _build_header(self):
        header = tk.Frame(self.main_frame, bg=self.COLORS['header_bg'],
                          highlightbackground=self.COLORS['border'],
                          highlightthickness=1)
        header.pack(fill=tk.X, pady=(0, 12))

        inner = tk.Frame(header, bg=self.COLORS['header_bg'], padx=20, pady=14)
        inner.pack(fill=tk.X)

        title_row = tk.Frame(inner, bg=self.COLORS['header_bg'])
        title_row.pack()

        tk.Label(title_row, text="🌸 文件共享小助手 🌸",
                 font=('Comic Sans MS', 17, 'bold'),
                 fg='#FFFFFF', bg=self.COLORS['header_bg']).pack()

        tk.Label(inner, text="✨ 轻轻松松分享你的文件 ✨",
                 font=('Comic Sans MS', 10),
                 fg='#FFFFFF', bg=self.COLORS['header_bg']).pack(pady=(4, 0))

    def _build_toast(self):
        self.toast = Toast(self.main_frame)

    def _build_settings_card(self):
        card = self._card(self.main_frame)
        card.pack(fill=tk.X, pady=(0, 10))

        body = tk.Frame(card, bg=self.COLORS['card_bg'], padx=18, pady=16)
        body.pack(fill=tk.X)

        tk.Label(body, text="🎈 服务设置", font=('Comic Sans MS', 13, 'bold'),
                 fg=self.COLORS['primary_dark'], bg=self.COLORS['card_bg']).pack(anchor=tk.W, pady=(0, 14))

        self._setting_row(body, 'port', '🎀 服务端口:', str(self.config.get('port', 8080)),
                          '端口号范围 1-65535，默认 8080', width=10)

        self._setting_row(body, 'folder', '📂 共享文件夹:', self.config.get('folder', ''),
                          '选择要分享的文件夹路径', width=30, has_browse=True)

        pw_hint = '设置密码后可防止未授权访问，留空不启用'
        if self.config.get('password_hash', ''):
            pw_hint = '⚠️ 当前已有密码保护，留空将清除密码'
        self._setting_row(body, 'password', '🔒 访问密码:', '',
                          pw_hint, width=22, is_password=True)

    def _build_upload_card(self):
        card = self._card(self.main_frame)
        card.pack(fill=tk.X, pady=(0, 10))

        body = tk.Frame(card, bg=self.COLORS['card_bg'], padx=18, pady=16)
        body.pack(fill=tk.X)

        tk.Label(body, text="📦 上传限制", font=('Comic Sans MS', 13, 'bold'),
                 fg=self.COLORS['primary_dark'], bg=self.COLORS['card_bg']).pack(anchor=tk.W, pady=(0, 14))

        row = tk.Frame(body, bg=self.COLORS['card_bg'])
        row.pack(fill=tk.X)

        tk.Label(row, text="📤 单文件大小上限:", font=('Comic Sans MS', 12),
                 fg=self.COLORS['text'], bg=self.COLORS['card_bg']).pack(side=tk.LEFT, padx=(0, 8))

        self.upload_size_var = tk.StringVar(value=str(self.config.get('max_upload_size', 1024)))
        entry = tk.Entry(row, textvariable=self.upload_size_var, font=('Comic Sans MS', 11),
                         relief=tk.GROOVE, bd=1, width=10,
                         highlightbackground=self.COLORS['border'], highlightthickness=1)
        entry.pack(side=tk.LEFT)

        self.upload_unit_var = tk.StringVar(value=self.config.get('max_upload_unit', 'MB'))
        combo = ttk.Combobox(row, textvariable=self.upload_unit_var,
                             values=['KB', 'MB', 'GB'],
                             font=('Comic Sans MS', 11), state='readonly', width=6)
        combo.pack(side=tk.LEFT, padx=(5, 8))

        tk.Label(row, text="范围 1MB ~ 10GB", font=('Comic Sans MS', 9),
                 fg=self.COLORS['text_light'], bg=self.COLORS['card_bg']).pack(side=tk.LEFT)

    def _setting_row(self, parent, key, label, default, hint, width=10, has_browse=False, is_password=False):
        row = tk.Frame(parent, bg=self.COLORS['card_bg'])
        row.pack(fill=tk.X, pady=(0, 10))

        input_frame = tk.Frame(row, bg=self.COLORS['card_bg'])
        input_frame.pack(fill=tk.X)

        tk.Label(input_frame, text=label, font=('Comic Sans MS', 12),
                 fg=self.COLORS['text'], bg=self.COLORS['card_bg']).pack(side=tk.LEFT, padx=(0, 6))

        if has_browse:
            entry_frame = tk.Frame(input_frame, bg=self.COLORS['card_bg'])
            entry_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

            var = tk.StringVar(value=default)
            setattr(self, f'{key}_var', var)
            entry = tk.Entry(entry_frame, textvariable=var, font=('Comic Sans MS', 10),
                             relief=tk.GROOVE, bd=1,
                             highlightbackground=self.COLORS['border'], highlightthickness=1)
            entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))

            browse_btn = tk.Button(entry_frame, text="📂 浏览", command=lambda: self._browse_folder(var),
                                   font=('Comic Sans MS', 10, 'bold'),
                                   bg=self.COLORS['secondary'], fg='white',
                                   relief=tk.FLAT, padx=12, cursor='hand2')
            browse_btn.pack(side=tk.RIGHT)
            self._hover_effect(browse_btn, self.COLORS['secondary'], '#6DB8D3')
        else:
            var = tk.StringVar(value=default)
            setattr(self, f'{key}_var', var)
            show = '*' if is_password else None
            entry = tk.Entry(input_frame, textvariable=var, font=('Comic Sans MS', 11),
                             relief=tk.GROOVE, bd=1, width=width,
                             highlightbackground=self.COLORS['border'], highlightthickness=1,
                             show=show)
            entry.pack(side=tk.LEFT)

        hint_label = tk.Label(row, text=f'💬 {hint}', font=('Comic Sans MS', 9),
                              fg=self.COLORS['text_light'], bg=self.COLORS['card_bg'],
                              anchor=tk.W, justify=tk.LEFT)
        hint_label.pack(fill=tk.X, padx=(0, 0), pady=(3, 0))

        if has_browse:
            setattr(self, f'{key}_entry', entry)
        else:
            setattr(self, f'{key}_entry', entry)

    def _build_buttons(self):
        btn_frame = tk.Frame(self.main_frame, bg=self.COLORS['card_bg'],
                             highlightbackground=self.COLORS['border'],
                             highlightthickness=1)
        btn_frame.pack(fill=tk.X, pady=(0, 10))

        inner = tk.Frame(btn_frame, bg=self.COLORS['card_bg'], padx=16, pady=12)
        inner.pack(fill=tk.X)

        left_frame = tk.Frame(inner, bg=self.COLORS['card_bg'])
        left_frame.pack(side=tk.LEFT)

        self.start_btn = tk.Button(left_frame, text="🚀 启动服务", command=self.start_server,
                                   font=('Comic Sans MS', 12, 'bold'),
                                   bg=self.COLORS['success'], fg='white',
                                   relief=tk.FLAT, padx=22, pady=8, cursor='hand2')
        self.start_btn.pack(side=tk.LEFT, padx=(0, 10))
        self._hover_effect(self.start_btn, self.COLORS['success'], '#6AB894')

        self.stop_btn = tk.Button(left_frame, text="⏹ 停止服务", command=self.stop_server,
                                  font=('Comic Sans MS', 12, 'bold'),
                                  bg=self.COLORS['warning'], fg='white',
                                  relief=tk.FLAT, padx=22, pady=8, state=tk.DISABLED, cursor='hand2')
        self.stop_btn.pack(side=tk.LEFT)
        self._hover_effect(self.stop_btn, self.COLORS['warning'], '#E7B863')

        right_frame = tk.Frame(inner, bg=self.COLORS['card_bg'])
        right_frame.pack(side=tk.RIGHT)

        self.save_btn = tk.Button(right_frame, text="💾 保存设置", command=self.save_settings,
                                  font=('Comic Sans MS', 12, 'bold'),
                                  bg=self.COLORS['primary'], fg='white',
                                  relief=tk.FLAT, padx=22, pady=8, cursor='hand2')
        self.save_btn.pack(side=tk.RIGHT)
        self._hover_effect(self.save_btn, self.COLORS['primary'], self.COLORS['primary_dark'])

    def _hover_effect(self, btn, normal, hover):
        def on_enter(e):
            btn.configure(bg=hover)
        def on_leave(e):
            btn.configure(bg=normal)
        btn.bind('<Enter>', on_enter)
        btn.bind('<Leave>', on_leave)

    def _build_status_bar(self):
        status_card = self._card(self.main_frame)
        status_card.pack(fill=tk.X)

        body = tk.Frame(status_card, bg=self.COLORS['card_bg'], padx=16, pady=14)
        body.pack(fill=tk.X)

        self.status_icon = tk.Label(body, text="😴", font=('Segoe UI Emoji', 22),
                                    bg=self.COLORS['card_bg'], fg=self.COLORS['text_light'])
        self.status_icon.pack(side=tk.LEFT, padx=(4, 14))

        info = tk.Frame(body, bg=self.COLORS['card_bg'])
        info.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.status_label = tk.Label(info, text="服务正在打盹中...",
                                     font=('Comic Sans MS', 11, 'bold'),
                                     fg=self.COLORS['text_light'], bg=self.COLORS['card_bg'],
                                     anchor=tk.W)
        self.status_label.pack(fill=tk.X)

        self.status_detail = tk.Label(info, text="点击「启动服务」让我工作吧~",
                                      font=('Comic Sans MS', 9),
                                      fg='#C8B4BE', bg=self.COLORS['card_bg'],
                                      anchor=tk.W)
        self.status_detail.pack(fill=tk.X, pady=(2, 0))

        self.status_dot = tk.Canvas(body, width=14, height=14,
                                    bg=self.COLORS['card_bg'],
                                    highlightthickness=0)
        self.status_dot.pack(side=tk.RIGHT, padx=(0, 4))
        self.dot_id = self.status_dot.create_oval(2, 2, 12, 12,
                                                   fill='#E0D0D6', outline='')

    def _browse_folder(self, var):
        folder = filedialog.askdirectory(title="💖 选择要分享的文件夹")
        if folder:
            var.set(folder)

    def save_settings(self):
        try:
            port = int(self.port_var.get())
            if port < 1 or port > 65535:
                self.toast.show('端口号需要在 1~65535 之间哦~', 'warning')
                return
        except ValueError:
            self.toast.show('端口号必须是数字啦~', 'warning')
            return

        folder = self.folder_var.get()
        if folder and not os.path.isdir(folder):
            self.toast.show('这个文件夹好像不存在呢~', 'warning')
            return

        try:
            upload_size = int(self.upload_size_var.get())
            upload_unit = self.upload_unit_var.get()
            if upload_size <= 0:
                self.toast.show('上传大小要填正整数哟~', 'warning')
                return

            min_bytes = 1024 * 1024
            max_bytes = 10 * 1024 * 1024 * 1024
            total_bytes = upload_size * (1024 if upload_unit == 'KB' else
                                         1024 * 1024 if upload_unit == 'MB' else
                                         1024 * 1024 * 1024)
            if total_bytes < min_bytes:
                self.toast.show('上传大小不能小于 1MB 哟~', 'warning')
                return
            if total_bytes > max_bytes:
                self.toast.show('上传大小不能超过 10GB 哟~', 'warning')
                return
        except ValueError:
            self.toast.show('上传大小要填有效的数字哟~', 'warning')
            return

        self.config['port'] = port
        self.config['folder'] = folder
        self.config['password'] = self.password_var.get()
        self.config['max_upload_size'] = upload_size
        self.config['max_upload_unit'] = upload_unit
        save_config(self.config)
        self.toast.show('设置已保存成功啦 ✨', 'success')

    def start_server(self):
        try:
            port = int(self.port_var.get())
            if port < 1 or port > 65535:
                self.toast.show('端口号需要在 1~65535 之间哦~', 'warning')
                return
        except ValueError:
            self.toast.show('端口号必须是数字啦~', 'warning')
            return

        folder = self.folder_var.get()
        if not folder or not os.path.isdir(folder):
            self.toast.show('请先选择一个有效的共享文件夹哟~', 'warning')
            return

        try:
            upload_size = int(self.upload_size_var.get())
            upload_unit = self.upload_unit_var.get()
            if upload_size <= 0:
                self.toast.show('上传大小要填正整数哟~', 'warning')
                return

            min_bytes = 1024 * 1024
            max_bytes = 10 * 1024 * 1024 * 1024
            total_bytes = upload_size * (1024 if upload_unit == 'KB' else
                                         1024 * 1024 if upload_unit == 'MB' else
                                         1024 * 1024 * 1024)
            if total_bytes < min_bytes:
                self.toast.show('上传大小不能小于 1MB 哟~', 'warning')
                return
            if total_bytes > max_bytes:
                self.toast.show('上传大小不能超过 10GB 哟~', 'warning')
                return
        except ValueError:
            self.toast.show('上传大小要填有效的数字哟~', 'warning')
            return

        self.config['port'] = port
        self.config['folder'] = folder
        self.config['password'] = self.password_var.get()
        self.config['max_upload_size'] = upload_size
        self.config['max_upload_unit'] = upload_unit
        save_config(self.config)

        self.config = load_config()
        init_server(self.config)

        global server_thread, server_running
        server_running = True
        server_thread = threading.Thread(target=run_server, args=(port,), daemon=True)
        server_thread.start()

        self.update_server_status(True)
        self.toast.show(f'服务已启动！访问地址: http://localhost:{port} 💖', 'success', 5000)

    def stop_server(self):
        global server_running
        server_running = False
        stop_server()
        self.update_server_status(False)
        self.toast.show('服务已安全停止啦~ 下次见 💦', 'info')

    def update_server_status(self, running):
        if running:
            self.status_icon.configure(text='😊')
            self.status_label.configure(text='服务正在努力工作中！', fg=self.COLORS['success'])
            self.status_detail.configure(text=f'端口: {self.config["port"]} | 地址: http://localhost:{self.config["port"]}',
                                         fg='#8CC4A8')
            self.start_btn.configure(state=tk.DISABLED)
            self.stop_btn.configure(state=tk.NORMAL)
            self.status_dot.itemconfigure(self.dot_id, fill=self.COLORS['success'])
            self._pulse_dot()
        else:
            self.status_icon.configure(text='😴')
            self.status_label.configure(text='服务正在打盹中...', fg=self.COLORS['text_light'])
            self.status_detail.configure(text='点击「启动服务」让我工作吧~', fg='#C8B4BE')
            self.start_btn.configure(state=tk.NORMAL)
            self.stop_btn.configure(state=tk.DISABLED)
            self.status_dot.itemconfigure(self.dot_id, fill='#E0D0D6')
            if hasattr(self, '_pulse_id'):
                self.master.after_cancel(self._pulse_id)

    def _pulse_dot(self):
        colors = ['#7BC8A4', '#9FD8BE', '#7BC8A4']
        def step(i=0):
            if server_running:
                c = colors[i % len(colors)]
                self.status_dot.itemconfigure(self.dot_id, fill=c)
                self._pulse_id = self.master.after(800, lambda: step(i + 1))
            else:
                self.status_dot.itemconfigure(self.dot_id, fill='#E0D0D6')
        step()

    def on_close(self):
        global server_running
        server_running = False
        self.master.destroy()


def main():
    global root
    root = tk.Tk()
    app = FileShareApp(root)
    root.mainloop()

if __name__ == '__main__':
    main()
