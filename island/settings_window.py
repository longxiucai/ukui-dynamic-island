"""Settings window: appearance, clock, mail, calendar, quota and toggles."""
from string import Template

from PySide2.QtCore import Qt, QTimer, QUrl
from PySide2.QtGui import QColor, QDesktopServices, QPainter, QPen
from PySide2.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog,
                               QFormLayout, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QScrollArea,
                               QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from island import __version__, blur, quota


def _rgba(color):
    return (f"rgba({color.red()}, {color.green()}, {color.blue()}, "
            f"{color.alpha() / 255:.3f})")


STYLE = Template("""
QDialog { background: $surface; }
QWidget { color: $textPrimary; font-size: 12px; }
QLabel { background: transparent; color: $textSecondary; }
QLabel#section { color: $textTertiary; font-size: 11px; font-weight: 600; }
QLabel#hint { color: $textTertiary; font-size: 10.5px; }
QLabel#status { color: $textSecondary; font-size: 11px; }
QLabel#status[state="ok"] { color: $success; }
QLabel#status[state="error"] { color: $danger; }
QLabel#status[state="warn"] { color: $warning; }
QLabel#preview { background: $fill; border: 1px solid $hairline;
                 border-radius: 10px; color: $textTertiary; font-size: 10.5px; }
QTabWidget::pane { border: 1px solid $hairline; border-radius: 12px;
                   background: $popup; top: -1px; }
QTabBar::tab { background: transparent; color: $textSecondary;
               padding: 6px 14px; margin: 0 4px 6px 0; border-radius: 7px; }
QTabBar::tab:hover { background: $hover; color: $textPrimary; }
QTabBar::tab:selected { background: $fill; color: $textPrimary;
                        font-weight: 600; }
QLineEdit, QComboBox, QSpinBox { background: $input; color: $textPrimary;
    border: 1px solid $controlBorder; border-radius: 7px; padding: 5px 9px;
    min-height: 20px; selection-background-color: $accent;
    selection-color: $onAccent; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: $accent; }
QLineEdit:disabled, QComboBox:disabled { color: $textTertiary;
                                         background: $surface; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox::down-arrow { width: 0; height: 0; }
QSpinBox { padding-right: 24px; }
QComboBox QAbstractItemView { background: $popup; color: $textPrimary;
    border: 1px solid $popupBorder; border-radius: 8px; padding: 4px;
    outline: none; selection-background-color: $fill;
    selection-color: $textPrimary; }
QComboBox QAbstractItemView::item { min-height: 24px; padding: 2px 8px;
                                    border-radius: 5px; }
QCheckBox { background: transparent; color: $textPrimary; spacing: 8px; }
QCheckBox:disabled { color: $textTertiary; }
QCheckBox::indicator { width: 15px; height: 15px;
                       border: 1px solid $controlBorder;
                       border-radius: 4px; background: $input; }
QCheckBox::indicator:hover { border-color: $accent; }
QCheckBox::indicator:checked { background: $accent; border-color: $accent; }
QCheckBox:focus::indicator { border-color: $accent; }
QPushButton { background: $fill; color: $textPrimary;
              border: 1px solid $outline; border-radius: 7px;
              padding: 6px 14px; min-height: 20px; }
QPushButton:hover { background: $hover; }
QPushButton:pressed { background: $pressed; }
QPushButton:disabled { color: $textTertiary; }
QPushButton:focus { border-color: $accent; }
QPushButton#primary { background: $accent; color: $onAccent;
                      border: 1px solid $accent; font-weight: 600; }
QPushButton#primary:hover { background: $accentHover; }
QPushButton#primary:focus { border: 1px solid $textPrimary; }
QPushButton#segment { background: transparent; color: $textSecondary;
                      border: 1px solid $outline; padding: 5px 8px; }
QPushButton#segment:hover { background: $hover; color: $textPrimary; }
QPushButton#segment:checked { background: $accent; color: $onAccent;
                              border-color: $accent; font-weight: 600; }
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: $outline; border-radius: 4px;
                              min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
""")


class Combo(QComboBox):
    """QComboBox that paints its own chevron, so it survives the dark QSS."""

    def __init__(self, *args):
        super().__init__(*args)
        self.arrow_color = QColor("#8E8E99")
        self.popup_color = "#1F1F23"

    def showPopup(self):
        super().showPopup()
        # The popup is its own top-level window with a light native frame.
        self.view().window().setStyleSheet(
            "QComboBoxPrivateContainer { background: %s; border: 0px; }"
            % self.popup_color)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(self.arrow_color, 1.6, Qt.SolidLine,
                            Qt.RoundCap, Qt.RoundJoin))
        x = self.width() - 15
        y = self.height() / 2 - 2
        painter.drawLine(x - 4, y, x, y + 4)
        painter.drawLine(x, y + 4, x + 4, y)


class Spin(QSpinBox):
    """QSpinBox with painted steppers, since the QSS hides the native ones."""

    def __init__(self, *args):
        super().__init__(*args)
        self.setButtonSymbols(QSpinBox.NoButtons)
        self.arrow_color = QColor("#8E8E99")

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(self.arrow_color, 1.4, Qt.SolidLine,
                            Qt.RoundCap, Qt.RoundJoin))
        x = self.width() - 13
        mid = self.height() / 2
        painter.drawLine(x - 3, mid - 2, x, mid - 5)
        painter.drawLine(x, mid - 5, x + 3, mid - 2)
        painter.drawLine(x - 3, mid + 2, x, mid + 5)
        painter.drawLine(x, mid + 5, x + 3, mid + 2)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and event.pos().x() > self.width() - 22:
            if event.pos().y() < self.height() / 2:
                self.stepUp()
            else:
                self.stepDown()
            event.accept()
            return
        super().mousePressEvent(event)


class Check(QCheckBox):
    """QCheckBox with a painted tick; the QSS only fills the box."""

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.tick_color = QColor("#000000")

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.isChecked():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(self.tick_color, 1.6, Qt.SolidLine,
                            Qt.RoundCap, Qt.RoundJoin))
        top = (self.height() - 15) / 2
        painter.drawLine(3.5, top + 7.5, 6.5, top + 10.5)
        painter.drawLine(6.5, top + 10.5, 11.5, top + 4.5)


class SettingsDialog(QDialog):
    PAGE_TABS = {"mail": 2, "calendar": 3, "quota": 4}

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self._watched = {}
        self._workbuddy_login = None
        self._trae_login = None
        self._copilot_login = None
        self._blur_supported = None
        self.setWindowTitle("设置")
        self.setWindowFlags(Qt.Window | Qt.WindowTitleHint
                            | Qt.WindowSystemMenuHint
                            | Qt.WindowMinimizeButtonHint
                            | Qt.WindowCloseButtonHint)
        self.setMinimumSize(520, 480)
        self.resize(560, 600)

        cfg = app.cfg
        self.tabs = QTabWidget()
        self.tabs.addTab(self._scroll(self._appearance(cfg)), "外观")
        self.tabs.addTab(self._scroll(self._clock(cfg)), "时间")
        self.tabs.addTab(self._scroll(self._mail(cfg)), "邮件")
        self.tabs.addTab(self._scroll(self._calendar(cfg)), "日历")
        self.tabs.addTab(self._scroll(self._quota(cfg)), "额度")

        version = QLabel(f"版本 {__version__}")
        version.setObjectName("hint")
        version.setToolTip(
            "配置 ~/.config/ukui-dynamic-island\n日志 ~/.local/state/ukui-dynamic-island")
        close = QPushButton("完成")
        close.setObjectName("primary")
        close.setDefault(True)
        close.clicked.connect(self.accept)

        footer = QHBoxLayout()
        footer.setSpacing(12)
        footer.addWidget(version)
        footer.addStretch(1)
        footer.addWidget(close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 14)
        layout.setSpacing(12)
        layout.addWidget(self.tabs, 1)
        layout.addLayout(footer)
        self._apply_style()

    def select_tab(self, page):
        self.tabs.setCurrentIndex(self.PAGE_TABS.get(page, 0))

    # Layout helpers

    def _scroll(self, page):
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        area.setWidget(page)
        area.viewport().setAutoFillBackground(False)
        return area

    def _page(self):
        page = QWidget()
        page.setAutoFillBackground(False)
        outer = QVBoxLayout(page)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(16)
        return page, outer

    def _group(self, outer, title):
        box = QWidget()
        box.setAutoFillBackground(False)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        if title:
            label = QLabel(title)
            label.setObjectName("section")
            lay.addWidget(label)
        outer.addWidget(box)
        return lay

    def _form(self):
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.DontWrapRows)
        return form

    def _hint(self, text):
        label = QLabel(text)
        label.setObjectName("hint")
        label.setWordWrap(True)
        return label

    def _status(self, text, state=""):
        label = QLabel("")
        label.setObjectName("status")
        label.setWordWrap(True)
        self._set_status(label, text, state)
        return label

    def _set_status(self, label, text, state=""):
        label.setText(text)
        label.setVisible(bool(text))
        label.setProperty("state", state)
        label.style().unpolish(label)
        label.style().polish(label)

    # Theme and preview

    def _theme(self):
        theme_id = self.app.cfg.get("theme")
        return (self.app.themes.get(theme_id)
                or next(iter(self.app.themes.values())))

    def _apply_style(self):
        th = self._theme()
        colors = {name: _rgba(th.color(name)) for name in (
            "hairline", "outline", "fill", "hover", "pressed", "track",
            "popupBorder")}
        for name in ("surface", "popup", "input", "textPrimary",
                     "textSecondary", "textTertiary", "accent", "onAccent",
                     "danger", "warning", "success"):
            colors[name] = th.color(name).name()
        colors["accentHover"] = th.color("accent").lighter(112).name()
        control = QColor(th.color("textSecondary"))
        control.setAlpha(115)
        colors["controlBorder"] = _rgba(control)
        self.setStyleSheet(STYLE.substitute(colors))
        arrow = th.color("textSecondary")
        for widget in self.findChildren(Combo) + self.findChildren(Spin):
            widget.arrow_color = arrow
            if isinstance(widget, Combo):
                widget.popup_color = th.color("popup").name()
            widget.update()
        for check in self.findChildren(Check):
            check.tick_color = th.color("onAccent")
            check.update()

    def _theme_changed(self):
        self.app.set_theme(self.theme.currentData())
        self._apply_style()
        self._sync_material()
        self._refresh_preview()

    def _sync_material(self):
        kind = self._theme().material.get("kind")
        self.material_box.setVisible(kind == "glass")
        if kind != "glass":
            return
        if self._blur_supported is None:
            self._blur_supported = blur.supported()
        self.blur_status.setText(
            "系统模糊可用，岛会随背景透出颜色。" if self._blur_supported
            else "当前窗口管理器未声明模糊，岛会自动回退为半透明。")

    def _refresh_preview(self):
        window = getattr(self.app, "window", None)
        if window is None:
            self.preview.clear()
            self.preview.setText("外观预览")
            return
        pixmap = window.grab()
        if pixmap.isNull():
            return
        width = self.preview.width() - 24
        if width < 200:
            width = max(200, self.width() - 80)
        scale = min(1.0, width / pixmap.width(), 54 / pixmap.height())
        self.preview.setPixmap(pixmap.scaled(
            int(pixmap.width() * scale), int(pixmap.height() * scale),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation))

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_style()
        self._refresh_preview()
        QTimer.singleShot(50, self._refresh_preview)

    # Pages

    def _appearance(self, cfg):
        page, outer = self._page()

        self.preview = QLabel()
        self.preview.setObjectName("preview")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setFixedHeight(74)
        outer.addWidget(self.preview)

        look = self._group(outer, "外观")
        form = self._form()
        self.theme = Combo()
        for theme_id in self.app.theme_ids:
            self.theme.addItem(self.app.themes[theme_id].name, theme_id)
        self.theme.setCurrentIndex(max(0, self.theme.findData(cfg["theme"])))
        self.theme.currentIndexChanged.connect(self._theme_changed)
        form.addRow("皮肤", self.theme)

        holder = QWidget()
        holder.setAutoFillBackground(False)
        shapes = QHBoxLayout(holder)
        shapes.setContentsMargins(0, 0, 0, 0)
        shapes.setSpacing(6)
        group = QButtonGroup(self)
        group.setExclusive(True)
        for style, label in (("notch", "刘海"), ("capsule", "胶囊"),
                             ("line", "指示条")):
            button = QPushButton(label)
            button.setObjectName("segment")
            button.setCheckable(True)
            button.setChecked(cfg["style"] == style)
            button.clicked.connect(
                lambda _checked=False, value=style: self._set_style(value))
            group.addButton(button)
            shapes.addWidget(button, 1)
        form.addRow("形态", holder)
        look.addLayout(form)

        display = self._group(outer, "显示")
        form = self._form()
        self.city = QLineEdit(cfg["weather_city"])
        self.city.setPlaceholderText("城市名，如 长沙")
        self.city.editingFinished.connect(
            lambda: self.app.set_weather_city(self.city.text()))
        form.addRow("天气城市", self.city)
        display.addLayout(form)
        self.weather_on = Check("显示天气")
        self.weather_on.setChecked(cfg["show_weather"])
        self.weather_on.toggled.connect(self._weather_changed)
        self.city.setEnabled(self.weather_on.isChecked())
        self.pet = Check("显示宠物")
        self.pet.setChecked(cfg.get("show_pet", True))
        self.pet.toggled.connect(
            lambda on: self.app.set_option("show_pet", on))
        self.monitor_on = Check("显示资源监控")
        self.monitor_on.setChecked(cfg.get("show_monitor", True))
        self.monitor_on.toggled.connect(
            lambda on: self.app.set_option("show_monitor", on))
        row = QHBoxLayout()
        row.setSpacing(18)
        row.addWidget(self.weather_on)
        row.addWidget(self.pet)
        row.addWidget(self.monitor_on)
        row.addStretch(1)
        display.addLayout(row)

        behaviour = self._group(outer, "启动与行为")
        self.autostart = Check("登录时自动启动")
        self.autostart.setChecked(cfg["autostart"])
        self.autostart.toggled.connect(self.app.set_autostart)
        self.fullscreen = Check("全屏应用时隐藏")
        self.fullscreen.setChecked(cfg.get("hide_fullscreen", True))
        self.fullscreen.toggled.connect(
            lambda on: self.app.set_option("hide_fullscreen", on))
        self.click_through = Check("鼠标穿透")
        self.click_through.setChecked(cfg.get("click_through", False))
        self.click_through.toggled.connect(
            lambda on: self.app.set_option("click_through", on))
        behaviour.addWidget(self.autostart)
        behaviour.addWidget(self.fullscreen)
        behaviour.addWidget(self.click_through)
        behaviour.addWidget(self._hint(
            "开启鼠标穿透后，岛不再响应点击；请从托盘菜单关闭。"))

        self.material_box = QWidget()
        self.material_box.setAutoFillBackground(False)
        material = QVBoxLayout(self.material_box)
        material.setContentsMargins(0, 0, 0, 0)
        material.setSpacing(8)
        title = QLabel("材质")
        title.setObjectName("section")
        material.addWidget(title)
        self.blur_on = Check("毛玻璃皮肤使用系统模糊")
        self.blur_on.setChecked(cfg.get("enable_blur", True))
        self.blur_on.toggled.connect(
            lambda on: self.app.set_option("enable_blur", on))
        material.addWidget(self.blur_on)
        self.blur_status = self._hint("")
        material.addWidget(self.blur_status)
        outer.addWidget(self.material_box)
        outer.addStretch(1)
        self._sync_material()
        return page

    def _set_style(self, style):
        self.app.set_style(style)
        self._refresh_preview()

    def _weather_changed(self, on):
        self.app.set_option("show_weather", on)
        self.city.setEnabled(on)

    def _sync_clock_period(self):
        self.clock_period.setEnabled(bool(self.clock_format.currentData()))

    def _clock(self, cfg):
        page, outer = self._page()

        display = self._group(outer, "时间显示")
        form = self._form()
        self.clock_format = Combo()
        for label, value in (("24 小时", False), ("12 小时", True)):
            self.clock_format.addItem(label, value)
        self.clock_format.setCurrentIndex(
            max(0, self.clock_format.findData(cfg["clock_12h"])))
        self.clock_format.currentIndexChanged.connect(
            lambda: self.app.set_option("clock_12h",
                                        self.clock_format.currentData()))
        self.clock_format.currentIndexChanged.connect(self._sync_clock_period)
        self.clock_period = Combo()
        for label, value in (("不显示", 0), ("上午 / 下午", 1), ("详细时段", 2)):
            self.clock_period.addItem(label, value)
        self.clock_period.setCurrentIndex(
            max(0, self.clock_period.findData(cfg["clock_period"])))
        self.clock_period.currentIndexChanged.connect(
            lambda: self.app.set_option("clock_period",
                                        self.clock_period.currentData()))
        form.addRow("时间制式", self.clock_format)
        form.addRow("时段文字", self.clock_period)
        self._sync_clock_period()
        display.addLayout(form)
        display.addWidget(self._hint(
            "时段文字只在 12 小时制下显示；详细时段：凌晨、上午、中午、"
            "下午、傍晚、晚上。"))
        self.seconds = Check("显示秒数")
        self.seconds.setChecked(cfg["show_seconds"])
        self.seconds.toggled.connect(
            lambda on: self.app.set_option("show_seconds", on))
        self.weekday = Check("时间显示星期")
        self.weekday.setChecked(cfg["show_weekday"])
        self.weekday.toggled.connect(
            lambda on: self.app.set_option("show_weekday", on))
        self.english = Check("英文时段与日期")
        self.english.setChecked(cfg["clock_english"])
        self.english.toggled.connect(
            lambda on: self.app.set_option("clock_english", on))
        checks = QHBoxLayout()
        checks.setSpacing(18)
        checks.addWidget(self.seconds)
        checks.addWidget(self.weekday)
        checks.addWidget(self.english)
        checks.addStretch(1)
        display.addLayout(checks)

        habits = self._group(outer, "专注与喝水")
        form = self._form()
        self.focus_minutes = Spin()
        self.focus_minutes.setRange(1, 180)
        self.focus_minutes.setValue(cfg["focus_minutes"])
        self.focus_minutes.valueChanged.connect(
            lambda value: self.app.set_option("focus_minutes", value))
        self.rest_minutes = Spin()
        self.rest_minutes.setRange(1, 60)
        self.rest_minutes.setValue(cfg["rest_minutes"])
        self.rest_minutes.valueChanged.connect(
            lambda value: self.app.set_option("rest_minutes", value))
        self.water_minutes = Spin()
        self.water_minutes.setRange(5, 180)
        self.water_minutes.setValue(cfg.get("water_minutes", 45))
        self.water_minutes.setSuffix(" 分钟")
        self.water_minutes.valueChanged.connect(
            lambda value: self.app.set_option("water_minutes", value))
        form.addRow("专注分钟", self.focus_minutes)
        form.addRow("休息分钟", self.rest_minutes)
        form.addRow("喝水间隔", self.water_minutes)
        habits.addLayout(form)
        self.focus_remind = Check("番茄结束时在岛上提醒")
        self.focus_remind.setChecked(cfg.get("focus_remind", True))
        self.focus_remind.toggled.connect(
            lambda on: self.app.set_option("focus_remind", on))
        self.water_remind = Check("定时提醒喝水")
        self.water_remind.setChecked(cfg.get("water_remind", True))
        self.water_remind.toggled.connect(
            lambda on: self.app.set_option("water_remind", on))
        row = QHBoxLayout()
        row.setSpacing(18)
        row.addWidget(self.focus_remind)
        row.addWidget(self.water_remind)
        row.addStretch(1)
        habits.addLayout(row)
        habits.addWidget(self._hint(
            "喝水提醒 9:00–22:00 生效；横幅可稍后确认，收起后仍有角标。"))
        outer.addStretch(1)
        return page

    def _mail(self, cfg):
        page, outer = self._page()

        connection = self._group(outer, "连接")
        form = self._form()
        self.mail_host = QLineEdit(cfg["mail_host"])
        self.mail_host.setPlaceholderText("如 imap.qq.com")
        self.mail_port = Spin()
        self.mail_port.setRange(1, 65535)
        self.mail_port.setValue(cfg["mail_port"])
        self.mail_user = QLineEdit(cfg["mail_user"])
        self.mail_password = QLineEdit()
        self.mail_password.setEchoMode(QLineEdit.Password)
        if cfg["mail_password"]:
            self.mail_password.setPlaceholderText("已保存，留空不修改")
        form.addRow("服务器", self.mail_host)
        form.addRow("端口", self.mail_port)
        form.addRow("账号", self.mail_user)
        form.addRow("密码", self.mail_password)
        connection.addLayout(form)
        self.mail_tls = Check("SSL（993）；取消则用明文 IMAP")
        self.mail_tls.setChecked(cfg["mail_tls"])
        connection.addWidget(self.mail_tls)

        behaviour = self._group(outer, "提醒与同步")
        self.mail_remind = Check("新邮件和验证码在岛上提醒")
        self.mail_remind.setChecked(cfg.get("mail_remind", True))
        self.mail_remind.toggled.connect(
            lambda on: self.app.set_option("mail_remind", on))
        self.mail_sync = Check("允许把已读/删除同步到邮箱")
        self.mail_sync.setChecked(cfg.get("mail_sync_operations", False))
        self.mail_sync.toggled.connect(
            lambda on: self.app.set_option("mail_sync_operations", on))
        behaviour.addWidget(self.mail_remind)
        behaviour.addWidget(self.mail_sync)

        save = QPushButton("保存并刷新")
        save.setObjectName("primary")
        save.clicked.connect(self._save_mail)
        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(save)
        outer.addLayout(actions)
        self.mail_status = self._status("")
        outer.addWidget(self.mail_status)
        outer.addWidget(self._hint(
            "QQ/163 服务器：imap.qq.com / imap.163.com。密码填邮箱授权码，"
            "不是登录密码；已保存的密码留空不修改。默认只读，同步删除会移到"
            "回收站。也可用 UKUI_ISLAND_MAIL_PASSWORD 覆盖密码。"))
        outer.addStretch(1)
        return page

    def _save_mail(self):
        values = {
            "mail_host": self.mail_host.text().strip(),
            "mail_port": self.mail_port.value(),
            "mail_user": self.mail_user.text().strip(),
            "mail_tls": self.mail_tls.isChecked(),
        }
        if self.mail_password.text():
            values["mail_password"] = self.mail_password.text()
        self._set_status(self.mail_status, "已保存，正在后台连接…")
        self.app.update_config(values)

    def watch_mail(self, thread):
        self._watch("mail", thread, self._mail_result)

    def _mail_result(self, result):
        result = result or {}
        if result.get("status") == "ok":
            unread = int(result.get("unread") or 0)
            count = f"{unread} 封未读" if unread else "没有未读邮件"
            self._set_status(
                self.mail_status,
                f"已连接 {result.get('at', '')} · {count}", "ok")
        elif result.get("status") == "unconfigured":
            self._set_status(self.mail_status, "未配置邮箱")
        else:
            self._set_status(
                self.mail_status,
                "连接失败：" + str(result.get("error") or "未知错误"), "error")

    def _calendar(self, cfg):
        page, outer = self._page()

        source = self._group(outer, "日历源")
        form = self._form()
        self.calendar_url = QLineEdit(cfg["calendar_url"])
        self.calendar_url.setPlaceholderText(
            ".ics 路径 / https:// 地址 / CalDAV")
        self.calendar_user = QLineEdit(cfg["calendar_user"])
        self.calendar_password = QLineEdit()
        self.calendar_password.setEchoMode(QLineEdit.Password)
        if cfg["calendar_password"]:
            self.calendar_password.setPlaceholderText("已保存，留空不修改")
        form.addRow("地址", self.calendar_url)
        form.addRow("账号", self.calendar_user)
        form.addRow("密码", self.calendar_password)
        source.addLayout(form)

        save = QPushButton("保存并刷新")
        save.setObjectName("primary")
        save.clicked.connect(self._save_calendar)
        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(save)
        outer.addLayout(actions)
        self.calendar_status = self._status("")
        outer.addWidget(self.calendar_status)
        outer.addWidget(self._hint(
            "支持本地 .ics、普通 ICS 链接和 CalDAV。重复日程（RRULE）"
            "只显示首次出现。"))
        outer.addStretch(1)
        return page

    def _save_calendar(self):
        values = {
            "calendar_url": self.calendar_url.text().strip(),
            "calendar_user": self.calendar_user.text().strip(),
        }
        if self.calendar_password.text():
            values["calendar_password"] = self.calendar_password.text()
        self._set_status(self.calendar_status, "已保存，正在重新读取…")
        self.app.update_config(values)

    def watch_calendar(self, thread):
        self._watch("calendar", thread, self._calendar_result)

    def _calendar_result(self, result):
        result = result or {}
        if result.get("status") == "ok":
            count = len(result.get("items") or [])
            upcoming = f"有 {count} 个日程" if count else "没有日程"
            self._set_status(
                self.calendar_status,
                f"已连接 {result.get('at', '')} · 未来 7 天{upcoming}", "ok")
        elif result.get("status") == "unconfigured":
            self._set_status(self.calendar_status, "未配置日历")
        else:
            self._set_status(
                self.calendar_status,
                "读取失败：" + str(result.get("error") or "未知错误"), "error")

    def _watch(self, kind, thread, slot):
        previous = self._watched.get(kind)
        if previous is not None:
            try:
                previous.updated.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._watched[kind] = thread
        thread.updated.connect(slot)

    def _quota(self, cfg):
        page, outer = self._page()

        source = self._group(outer, "额度来源")
        form = self._form()
        self.quota_url = QLineEdit(cfg["quota_url"])
        self.quota_url.setPlaceholderText(
            "New API / One API / Sub2API 或任意 JSON 额度地址（可选）")
        self.quota_token = QLineEdit(cfg.get("quota_token", ""))
        self.quota_token.setEchoMode(QLineEdit.Password)
        self.quota_token.setPlaceholderText("Bearer token（可选）")
        form.addRow("中转/自定义 JSON", self.quota_url)
        form.addRow("中转 Token", self.quota_token)
        source.addLayout(form)

        online = self._group(outer, "在线查询")
        self.codex_online = Check("Codex 用本机登录令牌向官方查询额度")
        self.codex_online.setChecked(bool(cfg.get("codex_online")))
        self.claude_online = Check("Claude 用本机登录令牌向官方查询额度")
        self.claude_online.setChecked(bool(cfg.get("claude_online")))
        self.workbuddy_online = Check("WorkBuddy 用官网账号查询积分")
        self.workbuddy_online.setChecked(bool(cfg.get("workbuddy_online")))
        self.trae_online = Check("Trae CN 用本机登录令牌查询官方额度")
        self.trae_online.setChecked(bool(cfg.get("trae_online")))
        self.copilot_online = Check("Copilot 用编辑器或 CLI 的登录查询额度")
        self.copilot_online.setChecked(bool(cfg.get("copilot_online")))
        self.copilot_connect = QPushButton("连接 Copilot")
        self.copilot_connect.clicked.connect(self._connect_copilot)
        self.copilot_status = self._status(
            "已连接 Copilot 账号" if quota.copilot_session()
            else "未连接：可点“连接 Copilot”走 GitHub 设备码登录")
        self.trae_connect = QPushButton("连接 Trae CN")
        self.trae_connect.clicked.connect(self._connect_trae)
        self.trae_status = self._status(
            "已连接 Trae CN 账号" if quota.trae_session()
            else "未连接：点“连接 Trae CN”打开浏览器登录")
        self.workbuddy_connect = QPushButton("连接 WorkBuddy")
        self.workbuddy_connect.clicked.connect(self._connect_workbuddy)
        self.workbuddy_status = self._status(
            "已连接 WorkBuddy 账号" if quota.workbuddy_session()
            else "未连接：点“连接 WorkBuddy”打开浏览器登录")
        online.addWidget(self.codex_online)
        online.addWidget(self.claude_online)
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(self.workbuddy_online)
        row.addStretch(1)
        row.addWidget(self.workbuddy_connect)
        online.addLayout(row)
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(self.trae_online)
        row.addStretch(1)
        row.addWidget(self.trae_connect)
        online.addLayout(row)
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(self.copilot_online)
        row.addStretch(1)
        row.addWidget(self.copilot_connect)
        online.addLayout(row)
        online.addWidget(self.workbuddy_status)
        online.addWidget(self.trae_status)
        online.addWidget(self.copilot_status)

        save = QPushButton("保存并刷新")
        save.setObjectName("primary")
        save.clicked.connect(self._save_quota)
        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(save)
        outer.addLayout(actions)
        self.quota_status = self._status("")
        outer.addWidget(self.quota_status)
        outer.addWidget(self._hint(
            "默认只读本机记录，失败自动回退。在线查询只把登录令牌发给对应"
            "官方接口，不写日志。Trae CN 与 WorkBuddy 积分需先在官网完成一次"
            "浏览器登录；Copilot 读取 VS Code、Copilot CLI 或 gh 已有的登录。"))
        outer.addStretch(1)
        return page

    def _save_quota(self):
        self._set_status(self.quota_status, "已保存，正在刷新…")
        self.app.update_config({
            "quota_url": self.quota_url.text().strip(),
            "quota_token": self.quota_token.text().strip(),
            "codex_online": self.codex_online.isChecked(),
            "claude_online": self.claude_online.isChecked(),
            "workbuddy_online": self.workbuddy_online.isChecked(),
            "trae_online": self.trae_online.isChecked(),
            "copilot_online": self.copilot_online.isChecked(),
        })

    def watch_quota(self, thread):
        self._watch("quota", thread, self._quota_result)

    def _quota_result(self, result):
        result = result or {}
        providers = result.get("providers") or []
        at = result.get("at") or ""
        ready = [item for item in providers if item.get("status") == "ok"]
        failed = [item for item in providers if item.get("status") == "error"]
        if failed:
            first = failed[0]
            detail = str(first.get("error") or "未知错误")
            self._set_status(
                self.quota_status,
                f"刷新完成 {at} · {first.get('label', '额度')} 失败：{detail}",
                "warn" if ready else "error")
        elif ready:
            labels = "、".join(
                str(item.get("label") or item.get("id") or "") for item in ready)
            self._set_status(self.quota_status, f"已刷新 {at} · {labels}", "ok")
        else:
            self._set_status(
                self.quota_status, "刷新完成，没有可用的额度来源", "warn")

    def _connect_workbuddy(self):
        if (self._workbuddy_login is not None
                and self._workbuddy_login.isRunning()):
            return
        self.workbuddy_connect.setEnabled(False)
        self._set_status(self.workbuddy_status, "正在创建 WorkBuddy 登录请求…")
        worker = quota.WorkBuddyLogin()
        worker.opened.connect(self._open_workbuddy_login)
        worker.authorized.connect(self._workbuddy_authorized)
        worker.failed.connect(self._workbuddy_failed)
        worker.finished.connect(self._workbuddy_finished)
        worker.finished.connect(worker.deleteLater)
        self._workbuddy_login = worker
        worker.start()

    def _open_workbuddy_login(self, url):
        if QDesktopServices.openUrl(QUrl(url)):
            self._set_status(
                self.workbuddy_status,
                "请在浏览器完成登录，完成后会自动返回…")
        else:
            self._set_status(
                self.workbuddy_status,
                "无法打开默认浏览器，请检查系统设置", "error")

    def _workbuddy_authorized(self, result):
        self.workbuddy_online.setChecked(True)
        plan = str(result.get("plan") or "个人版")
        metrics = result.get("metrics") or []
        text = str(metrics[0].get("text") or "") if metrics else ""
        error = str(result.get("error") or "")
        if error:
            self._set_status(
                self.workbuddy_status,
                f"已连接，但积分读取失败：{error}", "warn")
        else:
            self._set_status(
                self.workbuddy_status, f"已连接 {plan} · 剩余 {text}", "ok")
        self.app.update_config({"workbuddy_online": True})

    def _workbuddy_failed(self, message):
        self._set_status(self.workbuddy_status, str(message), "error")

    def _workbuddy_finished(self):
        self.workbuddy_connect.setEnabled(True)
        self._workbuddy_login = None

    def _connect_trae(self):
        if self._trae_login is not None and self._trae_login.isRunning():
            return
        self.trae_connect.setEnabled(False)
        self._set_status(self.trae_status, "正在创建 Trae CN 登录请求…")
        worker = quota.TraeLogin()
        worker.opened.connect(self._open_trae_login)
        worker.authorized.connect(self._trae_authorized)
        worker.failed.connect(self._trae_failed)
        worker.finished.connect(self._trae_finished)
        worker.finished.connect(worker.deleteLater)
        self._trae_login = worker
        worker.start()

    def _open_trae_login(self, url):
        if QDesktopServices.openUrl(QUrl(url)):
            self._set_status(
                self.trae_status,
                "请在浏览器完成 Trae CN 登录，完成后会自动返回…")
        else:
            self._set_status(
                self.trae_status,
                "无法打开默认浏览器，请检查系统设置", "error")

    def _trae_authorized(self, result):
        self.trae_online.setChecked(True)
        plan = str(result.get("plan") or "在线额度")
        metrics = result.get("metrics") or []
        text = str(metrics[0].get("text") or "") if metrics else ""
        error = str(result.get("error") or "")
        if error:
            self._set_status(
                self.trae_status, f"已连接，但额度读取失败：{error}", "warn")
        else:
            self._set_status(
                self.trae_status, f"已连接 {plan} · 剩余 {text}", "ok")

    def _trae_failed(self, message):
        self._set_status(self.trae_status, str(message), "error")

    def _trae_finished(self):
        self.trae_connect.setEnabled(True)
        self._trae_login = None

    def _connect_copilot(self):
        if self._copilot_login is not None and self._copilot_login.isRunning():
            return
        self.copilot_connect.setEnabled(False)
        self._set_status(self.copilot_status, "正在向 GitHub 申请设备码…")
        worker = quota.CopilotLogin()
        worker.opened.connect(self._open_copilot_login)
        worker.authorized.connect(self._copilot_authorized)
        worker.failed.connect(self._copilot_failed)
        worker.finished.connect(self._copilot_finished)
        worker.finished.connect(worker.deleteLater)
        self._copilot_login = worker
        worker.start()

    def _open_copilot_login(self, url, code):
        opened = QDesktopServices.openUrl(QUrl(url))
        text = f"请在浏览器输入设备码 {code} 完成 GitHub 登录，完成后会自动返回"
        self._set_status(self.copilot_status, text,
                         "" if opened else "warn")

    def _copilot_authorized(self, result):
        self.copilot_online.setChecked(True)
        plan = str(result.get("plan") or "在线额度")
        metrics = result.get("metrics") or []
        text = str(metrics[0].get("text") or "") if metrics else ""
        error = str(result.get("error") or "")
        if error:
            self._set_status(
                self.copilot_status, f"已连接，但额度读取失败：{error}",
                "warn")
        else:
            self._set_status(
                self.copilot_status, f"已连接 {plan} · 剩余 {text}", "ok")

    def _copilot_failed(self, message):
        self._set_status(self.copilot_status, str(message), "error")

    def _copilot_finished(self):
        self.copilot_connect.setEnabled(True)
        self._copilot_login = None

    def done(self, result):
        worker = self._workbuddy_login
        if worker is not None and worker.isRunning():
            worker.requestInterruption()
        worker = self._trae_login
        if worker is not None and worker.isRunning():
            worker.requestInterruption()
        worker = self._copilot_login
        if worker is not None and worker.isRunning():
            worker.requestInterruption()
        super().done(result)
