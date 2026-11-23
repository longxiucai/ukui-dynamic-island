"""Settings window: appearance, clock, mail, calendar, quota and toggles."""
from string import Template

from PySide2.QtCore import Qt, QTimer, QUrl
from PySide2.QtGui import QColor, QDesktopServices, QPainter, QPen
from PySide2.QtWidgets import (QAbstractScrollArea, QApplication,
                               QButtonGroup, QCheckBox, QComboBox, QDialog,
                               QFormLayout, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QScrollArea,
                               QSlider, QSpinBox, QTabWidget, QVBoxLayout,
                               QWidget)

from island import __version__, blur, quota, stock, theme, weather
from island.window import IslandWindow


def _rgba(color):
    return (f"rgba({color.red()}, {color.green()}, {color.blue()}, "
            f"{color.alpha() / 255:.3f})")


def _blend(base, overlay):
    """overlay 压在 base 上的结果色，用来预演半透明叠加。"""
    ratio = overlay.alpha() / 255.0
    channels = ((base.red(), overlay.red()), (base.green(), overlay.green()),
                (base.blue(), overlay.blue()))
    return QColor(*[round(low + (high - low) * ratio)
                    for low, high in channels])


def _ink_on(accent, ink):
    """12px 粗体按 WCAG 要 4.5:1；皮肤的 onAccent 压不住 accent 时往深色推。"""
    best = ink
    if theme.contrast(ink, accent) >= 4.5:
        return best
    light = ink.lightness() >= 128
    target = QColor(255, 255, 255) if light else QColor(0, 0, 0)
    for step in range(1, 9):
        cand = _blend(ink, QColor(target.red(), target.green(), target.blue(),
                                  step * 32))
        if theme.contrast(cand, accent) >= 4.5:
            return cand
    return QColor(target.red(), target.green(), target.blue())


def _body_color(th):
    """岛面实际会画出来的颜色（玻璃/悬浮云是带透明度的 tint）。"""
    kind = th.material.get("kind", "opaque")
    if kind == "opaque":
        return th.color("surface")
    body = QColor(th.material.get("tint", "#FFFFFF"))
    body.setAlphaF(float(th.material.get("alpha", 0.6)))
    return body


def _preview_stage(th):
    """预览底色：岛面是半透明的，$fill 压不出对比就会融进背景，
    所以按实际会画出来的颜色往反方向推，直到对比到 1.6:1。"""
    body = _body_color(th)
    flat = QColor(body.red(), body.green(), body.blue())
    target = (QColor(0, 0, 0) if flat.lightness() > 128
              else QColor(255, 255, 255))
    best = flat
    best_ratio = theme.contrast(flat, _blend(flat, body))
    for step in range(1, 17):
        shade = QColor(target.red(), target.green(), target.blue(), step * 14)
        stage = _blend(flat, shade)
        ratio = theme.contrast(stage, _blend(stage, body))
        if ratio >= 1.6:
            return stage.name()
        if ratio > best_ratio:
            best, best_ratio = stage, ratio
    # 透明度很低时岛本来就快看不见了，取能拉开的最大对比
    return best.name()


def _hand_off_wheel(widget, event):
    """滚轮掠过数字框/下拉框时翻页，而不是顺手改掉一个配置值。"""
    area = widget.parentWidget()
    while area is not None and not isinstance(area, QAbstractScrollArea):
        area = area.parentWidget()
    if area is None:
        event.ignore()
        return
    QApplication.sendEvent(area.viewport(), event)


# 注意：QSS 不认非整数 px（10.5px 整条被丢弃，回落到 QWidget 的 12px），
# 阶梯只能用整数；也不要在这里写注释，Qt 的解析器会吞掉后面的规则。
STYLE = Template("""
QDialog { background: $surface; }
QWidget { color: $textPrimary; font-size: 12px; }
QLabel { background: transparent; color: $textSecondary; }
QLabel#section { color: $textTertiary; font-size: 11px; font-weight: 600; }
QLabel#hint { color: $textTertiary; font-size: 11px; }
QLabel#status { color: $textSecondary; font-size: 11px; }
QLabel#status[state="ok"] { color: $success; }
QLabel#status[state="error"] { color: $danger; }
QLabel#status[state="warn"] { color: $warning; }
QLabel#preview { background: $previewStage; border: 1px solid $hairline;
                 border-radius: 10px; color: $textTertiary; font-size: 11px; }
QFrame#card { background: $input; border: 1px solid $hairline;
              border-radius: 10px; }
QLabel#cardTitle { color: $textPrimary; font-size: 13px; font-weight: 600; }
QLabel#cardState { color: $textTertiary; font-size: 11px; }
QLabel#cardState[state="ok"] { color: $success; }
QLabel#cardState[state="warn"] { color: $warning; }
QLabel#cardState[state="error"] { color: $danger; }
QFrame#weatherHero { background: $fill; border: 1px solid $hairline;
                     border-radius: 12px; }
QLabel#weatherTemp { color: $textPrimary; font-size: 32px;
                     font-weight: 600; }
QLabel#weatherPlace { color: $textPrimary; font-size: 13px;
                      font-weight: 600; }
QLabel#weatherText { color: $textSecondary; font-size: 12px; }
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
QPushButton#cityRow { text-align: left; padding: 6px 12px;
                      background: $input; }
QPushButton#cityRow:hover { background: $hover; }
QPushButton#cityRow:checked { background: $accentSoft;
                              border-color: $accentLine; font-weight: 600; }
QPushButton#cityRow:focus { border-color: $accent; }
QPushButton#cityRemove { background: transparent; border: 0; padding: 0;
                         min-width: 26px; max-width: 26px;
                         color: $textTertiary; font-size: 14px; }
QPushButton#cityRemove:hover { background: $hover; color: $danger; }
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: $outline; border-radius: 4px;
                              min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QSlider { background: transparent; min-height: 18px; }
QSlider::groove:horizontal { height: 4px; border-radius: 2px;
                             background: $track; }
QSlider::sub-page:horizontal { height: 4px; border-radius: 2px;
                               background: $accent; }
QSlider::handle:horizontal { background: $popup; width: 12px; height: 12px;
                             margin: -5px 0; border-radius: 7px;
                             border: 1px solid $controlBorder; }
QSlider::handle:horizontal:hover,
QSlider::handle:horizontal:pressed { border-color: $accent; }
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

    def wheelEvent(self, event):
        _hand_off_wheel(self, event)

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

    def wheelEvent(self, event):
        _hand_off_wheel(self, event)


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


class Slider(QSlider):
    """滑块；滚轮仍然翻页，不能顺手改掉数值。"""

    def wheelEvent(self, event):
        _hand_off_wheel(self, event)


class Form(QFormLayout):
    """标签列定宽：切 tab 时字段左边缘一致。"""

    LABEL_W = 60

    def _label(self, label):
        if not isinstance(label, str):
            return label
        widget = QLabel(label)
        widget.setMinimumWidth(self.LABEL_W)
        return widget

    def addRow(self, label, field=None):
        super().addRow(self._label(label), field)


class SettingsDialog(QDialog):
    PAGE_TABS = {"weather": 2, "mail": 3, "calendar": 4, "quota": 5}

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self._watched = {}
        self._workbuddy_login = None
        self._trae_login = None
        self._copilot_login = None
        self._city_search_worker = None
        self._blur_supported = None
        self._sample = None
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
        self.tabs.addTab(self._scroll(self._weather(cfg)), "天气")
        self.tabs.addTab(self._scroll(self._mail(cfg)), "邮件")
        self.tabs.addTab(self._scroll(self._calendar(cfg)), "日历")
        self.tabs.addTab(self._scroll(self._quota(cfg)), "AI 额度")

        version = QLabel(f"版本 {__version__}")
        version.setObjectName("hint")
        version.setToolTip(
            "配置 ~/.config/ukui-dynamic-island\n日志 ~/.local/state/ukui-dynamic-island")
        close = QPushButton("关闭")
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
        form = Form()
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
        current = getattr(self.app, "active_theme", None)
        if current is not None:
            return current
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
        colors["onAccent"] = _ink_on(th.color("accent"),
                                     th.color("onAccent")).name()
        colors["accentHover"] = th.color("accent").lighter(112).name()
        accent = th.color("accent")
        colors["accentSoft"] = _rgba(QColor(accent.red(), accent.green(),
                                            accent.blue(), 40))
        colors["accentLine"] = _rgba(QColor(accent.red(), accent.green(),
                                            accent.blue(), 110))
        control = QColor(th.color("textSecondary"))
        control.setAlpha(115)
        colors["controlBorder"] = _rgba(control)
        colors["previewStage"] = _preview_stage(th)
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
        self._sync_glass_alpha()

    def _sync_glass_alpha(self):
        """把滑块对准当前生效值，不能触发一次新的保存。"""
        raw = self.app.cfg.get("glass_alpha")
        value = self._theme().default_alpha() if raw is None else int(raw)
        self.glass_alpha.blockSignals(True)
        self.glass_alpha.setValue(max(20, min(100, value)))
        self.glass_alpha.blockSignals(False)
        self._show_glass_alpha(value)
        self.glass_reset.setEnabled(raw is not None)

    def _show_glass_alpha(self, value):
        self.glass_alpha_value.setText(f"{int(value)}%")

    def _on_glass_alpha(self, value):
        """拖动时只改标签，落盘和重绘等一会儿，免得每像素写一次配置。"""
        self._show_glass_alpha(value)
        self._alpha_timer.start()

    def _flush_glass_alpha(self):
        self._alpha_timer.stop()
        self._set_glass_alpha(self.glass_alpha.value())

    def _set_glass_alpha(self, value):
        self.app.set_option("glass_alpha", value)
        self._apply_style()
        self._sync_glass_alpha()
        self._refresh_preview()

    def _reset_glass_alpha(self):
        self._alpha_timer.stop()
        self._set_glass_alpha(None)

    def _grab_preview(self):
        sample = self._sample
        if sample is None:
            self.preview.clear()
            self.preview.setText("外观预览")
            return
        pixmap = sample.grab()
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

    def _refresh_preview(self):
        """预览画的是固定样例岛：开关一拨立刻重画，不等后台线程回信号，
        也不依赖当前有没有真实行情或本机会话。"""
        if self._sample is None:
            self._sample = self._sample_window()
        else:
            self._sample.apply(dict(self.app.cfg, stock_hide_closed=False),
                               self._theme())
            self._seed_sample(self._sample)
        self._grab_preview()

    def _sample_window(self):
        """隐藏的样例岛：只用来给预览出图，绝不 show，也不碰真岛。"""
        sample = IslandWindow(dict(self.app.cfg, stock_hide_closed=False),
                              self._theme())
        sample.setAttribute(Qt.WA_DontShowOnScreen, True)
        sample._apply_blur = lambda: None
        self._seed_sample(sample)
        return sample

    def _seed_sample(self, sample):
        """固定读数：预览要快、要每次一致，所以不读真实数据。"""
        sample.productivity.todos.clear()
        sample.set_data({"battery": 0.82, "charging": False, "volume": 0.5,
                         "memory": 0.42, "cpu": 0.31, "disk": 0.6,
                         "temperature": None, "gpu": None, "net_down": None,
                         "net_up": None, "online": True,
                         "weather": {"place": "长沙", "text": "多云",
                                     "temp": 21}})
        sample.set_stock({"status": "ok",
                          "code": sample.cfg.get("stock_code", "sh000001"),
                          "name": "上证指数", "price": 3587.83,
                          "prev_close": 3550.0, "change": 37.83,
                          "change_pct": 1.07, "high": 3596.55,
                          "low": 3548.1, "date": "20260105", "at": "10:00",
                          "points": []})
        sample.set_activity({"provider": "Codex", "state": "working",
                             "label": "正在执行", "detail": "", "active": True,
                             "at": 0.0})
        for timer in (sample.clock, sample._hover, sample._desk,
                      sample._beat, sample._frame, sample._page_beat):
            timer.stop()
        sample._apply_geometry()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_saved_text()
        self._sync_material()
        self._apply_style()
        self._refresh_preview()

    def _sync_saved_text(self):
        """行情代码是即时保存的：输入框里的半成品不代表已生效的值。"""
        code = str(self.app.cfg.get("stock_code", ""))
        if self.stock_code.text() != code:
            self.stock_code.setText(code)
        self._set_status(self.stock_status, "")

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

        display = self._group(outer, "收起状态显示")
        self.monitor_on = Check("资源监控")
        self.pet = Check("宠物")
        self.weather_on = Check("天气与温度")
        self.stock_on = Check("股票涨跌幅")
        self.activity_on = Check("AI 执行状态")
        self.battery_on = Check("电池电量")
        rows = (("show_monitor", self.monitor_on, ""),
                ("show_pet", self.pet, ""),
                ("show_weather", self.weather_on, ""),
                ("show_stock", self.stock_on, ""),
                ("show_activity", self.activity_on,
                 "关闭后不再读取本机会话记录"),
                ("show_battery", self.battery_on, ""))
        for key, widget, note in rows:
            widget.setChecked(bool(cfg.get(key, True)))
            widget.toggled.connect(
                lambda on, name=key: self.app.set_option(name, on))
            widget.toggled.connect(self._refresh_preview)
            if note:
                widget.setToolTip(note)
            display.addWidget(widget)

        market = self._group(outer, "股票")
        form = self._form()
        self.stock_code = QLineEdit(cfg.get("stock_code", "sh000001"))
        self.stock_code.setPlaceholderText(
            "sh000001（上证指数）/ 600519 / hk00700 / usAAPL")
        self.stock_code.editingFinished.connect(self._save_stock_code)
        self.stock_code.setToolTip(
            "6 位数字按首位补 sh/sz/bj，5 位补 hk，纯字母按美股。")
        form.addRow("行情代码", self.stock_code)
        self.stock_grace_minutes = Spin()
        self.stock_grace_minutes.setRange(0, 180)
        self.stock_grace_minutes.setValue(cfg.get("stock_grace_minutes", 15))
        self.stock_grace_minutes.setSuffix(" 分钟")
        self.stock_grace_minutes.valueChanged.connect(
            lambda value: self.app.set_option("stock_grace_minutes", value))
        self.stock_grace_minutes.setToolTip("收盘后再多显示几分钟，0 即收盘就隐藏。")
        form.addRow("收盘宽限", self.stock_grace_minutes)
        market.addLayout(form)
        self.stock_hide_closed = Check("休市/收盘后隐藏收起态涨跌")
        self.stock_hide_closed.setChecked(cfg.get("stock_hide_closed", True))
        self.stock_hide_closed.toggled.connect(
            lambda on: self.app.set_option("stock_hide_closed", on))
        self.stock_hide_closed.toggled.connect(
            self.stock_grace_minutes.setEnabled)
        self.stock_grace_minutes.setEnabled(cfg.get("stock_hide_closed", True))
        self.stock_hide_closed.setToolTip(
            "交易时段：沪深 09:30–15:00、港股 09:30–16:00、"
            "美股 09:30–16:00（美东时间），周末自动隐藏；行情页不受影响。")
        market.addWidget(self.stock_hide_closed)
        self.stock_status = self._status("")
        market.addWidget(self.stock_status)

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
        # 开启后岛点不动，只靠 tooltip 提醒会让人以为程序坏了，所以开着才显示。
        self.click_through_warn = self._status("")
        self.click_through.toggled.connect(self._sync_click_through)
        behaviour.addWidget(self.autostart)
        behaviour.addWidget(self.fullscreen)
        behaviour.addWidget(self.click_through)
        behaviour.addWidget(self.click_through_warn)
        self._sync_click_through(self.click_through.isChecked())
        self.meeting_detect = Check("复制会议邀请时询问是否创建待办")
        self.meeting_detect.setChecked(cfg.get("meeting_detect", True))
        self.meeting_detect.toggled.connect(
            lambda on: self.app.set_option("meeting_detect", on))
        self.meeting_detect.setToolTip(
            "腾讯/飞书/企微的邀请复制后问一次，确认才写进待办。")
        behaviour.addWidget(self.meeting_detect)

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
        self.glass_alpha = Slider(Qt.Horizontal)
        self.glass_alpha.setRange(20, 100)
        self.glass_alpha.setPageStep(5)
        self.glass_alpha.valueChanged.connect(self._on_glass_alpha)
        self.glass_alpha.sliderReleased.connect(self._flush_glass_alpha)
        self.glass_alpha_value = QLabel("")
        self.glass_alpha_value.setObjectName("status")
        self.glass_alpha_value.setAlignment(Qt.AlignRight
                                             | Qt.AlignVCenter)
        self.glass_alpha_value.setMinimumWidth(36)
        self.glass_reset = QPushButton("恢复皮肤默认")
        self.glass_reset.clicked.connect(self._reset_glass_alpha)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.glass_alpha, 1)
        row.addWidget(self.glass_alpha_value)
        row.addWidget(self.glass_reset)
        material.addLayout(row)
        self.glass_alpha.setToolTip("数值越小越透，越能透出桌面颜色。")
        self._alpha_timer = QTimer(self)
        self._alpha_timer.setSingleShot(True)
        self._alpha_timer.setInterval(140)
        self._alpha_timer.timeout.connect(self._flush_glass_alpha)
        outer.addWidget(self.material_box)
        outer.addStretch(1)
        self._sync_material()
        return page

    def _set_style(self, style):
        self.app.set_style(style)
        self._refresh_preview()

    def _weather(self, cfg):
        page, outer = self._page()

        hero = QFrame()
        hero.setObjectName("weatherHero")
        lay = QVBoxLayout(hero)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(8)
        self.weather_place = QLabel("天气")
        self.weather_place.setObjectName("weatherPlace")
        self.weather_state = QLabel("等待刷新")
        self.weather_state.setObjectName("cardState")
        head.addWidget(self.weather_place)
        head.addStretch(1)
        head.addWidget(self.weather_state)
        lay.addLayout(head)
        body = QHBoxLayout()
        body.setSpacing(12)
        self.weather_temp = QLabel("--°")
        self.weather_temp.setObjectName("weatherTemp")
        self.weather_text = QLabel("尚无天气数据")
        self.weather_text.setObjectName("weatherText")
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self._refresh_weather)
        refresh.setToolTip("每 15 分钟自动更新；离线时保留上次天气并标灰。\n"
                           "数据来自 Open-Meteo，自动定位用 wttr.in。")
        body.addWidget(self.weather_temp)
        body.addWidget(self.weather_text, 1)
        body.addWidget(refresh)
        lay.addLayout(body)
        self.weather_note = self._status("")
        lay.addWidget(self.weather_note)
        outer.addWidget(hero)

        city = self._group(outer, "城市")
        self.city_rows = QVBoxLayout()
        self.city_rows.setSpacing(6)
        city.addLayout(self.city_rows)
        self._rebuild_city_rows()
        self.weather_status = self._status("")
        city.addWidget(self.weather_status)

        add = self._group(outer, "添加城市")
        self.city_search = QLineEdit()
        self.city_search.setPlaceholderText("输入城市名搜索，如 长沙 / Tokyo")
        self.city_search.textEdited.connect(self._queue_city_search)
        add.addWidget(self.city_search)
        self.city_results = Combo()
        self.city_results.currentIndexChanged.connect(self._city_pick_changed)
        self.city_add = QPushButton("添加")
        self.city_add.setEnabled(False)
        self.city_add.clicked.connect(self._add_picked_city)
        self.city_search_status = self._status("")
        add.addWidget(self.city_search_status)
        result = QWidget()
        result.setAutoFillBackground(False)
        layout = QHBoxLayout(result)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.city_results, 1)
        layout.addWidget(self.city_add)
        result.setVisible(False)
        self.city_result_row = result
        add.addWidget(result)

        outer.addStretch(1)
        data = getattr(getattr(self.app, "window", None), "data", {}) or {}
        self._weather_result(data.get("weather"))
        return page

    def watch_weather(self, thread):
        self._watch("weather", thread, self._weather_result)

    def _saved_cities(self):
        return [item for item in (self.app.cfg.get("weather_saved") or [])
                if isinstance(item, dict)]

    @staticmethod
    def _same_place(left, right):
        try:
            return (abs(float(left["lat"]) - float(right["lat"])) < 1e-4
                    and abs(float(left["lon"]) - float(right["lon"])) < 1e-4)
        except (KeyError, TypeError, ValueError):
            return False

    def _current_place(self):
        if self.app.cfg.get("weather_auto"):
            return None
        lat = self.app.cfg.get("weather_lat")
        lon = self.app.cfg.get("weather_lon")
        if lat is None or lon is None:
            return None
        return {"lat": lat, "lon": lon}

    def _rebuild_city_rows(self):
        while self.city_rows.count():
            item = self.city_rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        current = self._current_place()
        self.city_rows.addWidget(self._city_row(
            "自动定位", "按当前网络出口识别城市",
            bool(self.app.cfg.get("weather_auto")), self._select_auto_city))
        for place in self._saved_cities():
            name = str(place.get("name") or "")
            region = str(place.get("region") or "")
            title = f"{name} · {region}" if region and region != name else name
            self.city_rows.addWidget(self._city_row(
                title or "未命名城市", title,
                current is not None and self._same_place(current, place),
                lambda place=place: self._select_city(place),
                lambda place=place: self._remove_city(place)))

    def _city_row(self, title, tooltip, checked, pick, remove=None):
        row = QWidget()
        row.setAutoFillBackground(False)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        button = QPushButton(title)
        button.setObjectName("cityRow")
        button.setCheckable(True)
        button.setChecked(checked)
        button.setToolTip(tooltip)
        button.clicked.connect(lambda _checked=False: pick())
        lay.addWidget(button, 1)
        if remove is not None:
            drop = QPushButton("×")
            drop.setObjectName("cityRemove")
            drop.setToolTip("删除这个城市")
            drop.clicked.connect(lambda _checked=False: remove())
            lay.addWidget(drop)
        return row

    def _select_auto_city(self):
        self.app.set_weather_auto()
        self._set_status(self.weather_status, "已切换自动定位，正在刷新…")
        self._refresh_weather()
        self._rebuild_city_rows()

    def _select_city(self, place):
        name = str(place.get("name") or "").strip()
        try:
            lat, lon = float(place["lat"]), float(place["lon"])
        except (KeyError, TypeError, ValueError):
            self._set_status(self.weather_status, "城市坐标无效", "error")
            return
        self.app.set_weather_city(name, lat, lon)
        self._set_status(self.weather_status, f"已切换到 {name}，正在刷新…")
        self._refresh_weather()
        self._rebuild_city_rows()

    def _remove_city(self, place):
        saved = [item for item in self._saved_cities()
                 if not self._same_place(item, place)]
        self.app.update_config({"weather_saved": saved})
        current = self._current_place()
        if current is not None and self._same_place(current, place):
            self.app.set_weather_auto()
            self._refresh_weather()
        self._set_status(self.weather_status, "已删除城市")
        self._rebuild_city_rows()

    def _queue_city_search(self, _text):
        if not hasattr(self, "_city_timer"):
            self._city_timer = QTimer(self)
            self._city_timer.setSingleShot(True)
            self._city_timer.timeout.connect(self._search_cities)
        self._city_timer.start(400)

    def _search_cities(self):
        text = self.city_search.text().strip()
        if not text:
            self.city_results.clear()
            self.city_result_row.setVisible(False)
            self.city_add.setEnabled(False)
            self._set_status(self.city_search_status, "")
            return
        self.city_result_row.setVisible(False)
        self.city_add.setEnabled(False)
        worker = self._city_search_worker
        if worker is not None and worker.isRunning():
            worker.requestInterruption()
        worker = weather.CitySearch(text, self)
        worker.found.connect(self._city_found)
        worker.finished.connect(self._city_search_finished)
        worker.finished.connect(worker.deleteLater)
        self._city_search_worker = worker
        self._set_status(self.city_search_status, "正在搜索城市…")
        worker.start()

    def _city_search_finished(self):
        if self._city_search_worker is self.sender():
            self._city_search_worker = None

    def _city_found(self, query, results):
        if query != self.city_search.text().strip():
            return
        self.city_results.clear()
        for place in results[:8]:
            name = str(place.get("name") or "")
            region = str(place.get("region") or "")
            label = f"{name} · {region}" if region and region != name else name
            self.city_results.addItem(label, place)
        self.city_result_row.setVisible(bool(results))
        self.city_add.setEnabled(bool(results))
        self._set_status(
            self.city_search_status,
            f"找到 {len(results)} 个城市" if results else "没有匹配的城市",
            "" if results else "warn")

    def _city_pick_changed(self, _index):
        self.city_add.setEnabled(
            isinstance(self.city_results.currentData(), dict))

    def _add_picked_city(self):
        place = self.city_results.currentData()
        if not isinstance(place, dict):
            return
        name = str(place.get("name") or "")
        saved = self._saved_cities()
        if any(self._same_place(item, place) for item in saved):
            self._set_status(
                self.city_search_status, "这个城市已经在列表里", "warn")
            return
        if len(saved) >= 5:
            self._set_status(
                self.city_search_status, "最多保存 5 个城市，先删除一个", "warn")
            return
        self.app.update_config({"weather_saved": saved + [place]})
        self._select_city(place)
        self.city_search.clear()
        self.city_results.clear()
        self.city_result_row.setVisible(False)
        self.city_add.setEnabled(False)
        self._set_status(self.city_search_status, f"已添加 {name}", "ok")

    def _refresh_weather(self):
        thread = self._watched.get("weather")
        trigger = getattr(thread, "refresh", None)
        if callable(trigger):
            trigger()
            self._set_status(self.weather_state, "正在刷新…")
        else:
            self._set_status(self.weather_state, "暂无天气线程", "warn")

    def _weather_result(self, result):
        result = result or {}
        temp = result.get("temp")
        try:
            temp_text = f"{float(temp):.0f}°"
        except (TypeError, ValueError):
            temp_text = "--°"
        fallback = ("当前位置" if self.app.cfg.get("weather_auto")
                    else str(self.app.cfg.get("weather_city") or "天气"))
        place = str(result.get("place") or fallback)
        region = str(result.get("region") or "")
        self.weather_place.setText(
            f"{place} · {region}" if region and region != place else place)
        self.weather_temp.setText(temp_text)
        self.weather_text.setText(str(result.get("text") or "尚无天气数据"))
        error = str(result.get("error") or result.get("cache_error") or "")
        if error:
            self._set_status(self.weather_note, f"⚠ {error}", "warn")
        else:
            self._set_status(self.weather_note, "")
        if not result:
            self._set_status(self.weather_state, "等待刷新")
        elif result.get("stale"):
            self._set_status(
                self.weather_state,
                "离线 · 上次数据" if temp_text != "--°" else "读取失败",
                "warn")
        else:
            self._set_status(self.weather_state, "已更新", "ok")

    def _save_stock_code(self):
        code = stock.normalize_code(self.stock_code.text())
        if not code:
            self._set_status(
                self.stock_status, "代码格式无法识别，未保存", "error")
            return
        self.stock_code.setText(code)
        self.app.set_stock_code(code)
        self._set_status(self.stock_status, f"已保存 {code}", "ok")

    def _sync_clock_period(self):
        self.clock_period.setEnabled(bool(self.clock_format.currentData()))

    def _sync_click_through(self, on):
        """只在穿透开启时警告一次：这时岛点不动，托盘是唯一出口。"""
        self._set_status(self.click_through_warn,
                         "岛已不响应点击，请从托盘菜单关闭。" if on else "",
                         "warn")

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
        self.clock_period.setToolTip(
            "详细时段分：凌晨、上午、中午、下午、傍晚、晚上。\n只在 12 小时制下可选。")
        form.addRow("时间制式", self.clock_format)
        form.addRow("时段文字", self.clock_period)
        self._sync_clock_period()
        display.addLayout(form)
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
        self.seconds.setToolTip("更占宽度，收起态可能挤掉其他信息。")
        self.english.setToolTip("实际显示如 Tue 2:05 PM。")
        for widget in (self.seconds, self.weekday, self.english):
            display.addWidget(widget)

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
        self.water_remind.setToolTip("9:00–22:00 之间按上面的间隔提醒。")
        habits.addWidget(self.focus_remind)
        habits.addWidget(self.water_remind)
        outer.addStretch(1)
        return page

    def _mail(self, cfg):
        page, outer = self._page()

        connection = self._group(outer, "连接")
        form = self._form()
        self.mail_host = QLineEdit(cfg["mail_host"])
        self.mail_host.setPlaceholderText("如 imap.qq.com")
        self.mail_host.setToolTip("QQ 用 imap.qq.com，163 用 imap.163.com。")
        self.mail_port = Spin()
        self.mail_port.setRange(1, 65535)
        self.mail_port.setValue(cfg["mail_port"])
        self.mail_port.setToolTip("SSL 常用 993，明文常用 143。")
        self.mail_user = QLineEdit(cfg["mail_user"])
        self.mail_user.setPlaceholderText("完整邮箱地址，如 me@qq.com")
        self.mail_password = QLineEdit()
        self.mail_password.setEchoMode(QLineEdit.Password)
        if cfg["mail_password"]:
            self.mail_password.setPlaceholderText("已保存，留空不修改")
        else:
            self.mail_password.setPlaceholderText("邮箱授权码，不是登录密码")
        self.mail_password.setToolTip(
            "QQ/163 填授权码。也可用环境变量 UKUI_ISLAND_MAIL_PASSWORD "
            "覆盖已保存的密码。")
        form.addRow("服务器", self.mail_host)
        form.addRow("端口", self.mail_port)
        form.addRow("账号", self.mail_user)
        form.addRow("密码", self.mail_password)
        connection.addLayout(form)
        self.mail_tls = Check("用 SSL 加密")
        self.mail_tls.setChecked(cfg["mail_tls"])
        self.mail_tls.setToolTip("取消则用明文 IMAP，密码会明文发送。")
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
        self.mail_sync.setToolTip("开启后删除会移到邮箱回收站。")
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
        self.calendar_user.setPlaceholderText("CalDAV 账号，本地 .ics 留空")
        self.calendar_password = QLineEdit()
        self.calendar_password.setEchoMode(QLineEdit.Password)
        if cfg["calendar_password"]:
            self.calendar_password.setPlaceholderText("已保存，留空不修改")
        else:
            self.calendar_password.setPlaceholderText("CalDAV 密码，本地 .ics 留空")
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
        self.calendar_url.setToolTip("重复日程（RRULE）只显示首次出现。")
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
        self._quota_cards = {}
        reading = getattr(self.app, "quota_thread", None) is not None
        self._quota_reading = reading

        bar = QHBoxLayout()
        bar.setSpacing(8)
        refresh = QPushButton("刷新额度")
        refresh.clicked.connect(self._refresh_quota)
        bar.addWidget(refresh)
        bar.addStretch(1)
        outer.addLayout(bar)
        self.quota_status = self._status("正在读取本机额度…" if reading else "")
        outer.addWidget(self.quota_status)

        sources = self._group(outer, "账号与来源")
        lay = self._quota_card(
            sources, "codex", "Codex",
            "本机用量与配额快照；开启后向官方查询最新周期。")
        self.codex_online = Check("同时向官方查询")
        self.codex_online.setChecked(bool(cfg.get("codex_online")))
        lay.addWidget(self.codex_online)

        lay = self._quota_card(
            sources, "claude", "Claude",
            "只读桌面版本地用量记录；开启后向官方查询周期。")
        self.claude_online = Check("向官方查询")
        self.claude_online.setChecked(bool(cfg.get("claude_online")))
        lay.addWidget(self.claude_online)

        lay = self._quota_card(
            sources, "workbuddy", "WorkBuddy",
            "本机 trace 统计；登录官网后可读取剩余积分。")
        row = QHBoxLayout()
        row.setSpacing(10)
        self.workbuddy_online = Check("读取官网积分")
        self.workbuddy_online.setChecked(bool(cfg.get("workbuddy_online")))
        row.addWidget(self.workbuddy_online)
        row.addStretch(1)
        self.workbuddy_connect = QPushButton("连接 WorkBuddy")
        self.workbuddy_connect.clicked.connect(self._connect_workbuddy)
        row.addWidget(self.workbuddy_connect)
        lay.addLayout(row)
        self.workbuddy_status = self._status(
            "已连接 WorkBuddy 账号" if quota.workbuddy_session()
            else "未连接：点“连接 WorkBuddy”打开浏览器登录")
        lay.addWidget(self.workbuddy_status)

        lay = self._quota_card(
            sources, "trae", "Trae CN",
            "用本机登录令牌查询官方额度。")
        row = QHBoxLayout()
        row.setSpacing(10)
        self.trae_online = Check("读取官方额度")
        self.trae_online.setChecked(bool(cfg.get("trae_online")))
        row.addWidget(self.trae_online)
        row.addStretch(1)
        self.trae_connect = QPushButton("连接 Trae CN")
        self.trae_connect.clicked.connect(self._connect_trae)
        row.addWidget(self.trae_connect)
        lay.addLayout(row)
        self.trae_status = self._status(
            "已连接 Trae CN 账号" if quota.trae_session()
            else "未连接：点“连接 Trae CN”打开浏览器登录")
        lay.addWidget(self.trae_status)

        lay = self._quota_card(
            sources, "copilot", "Copilot",
            "读取 VS Code、Copilot CLI 或 gh 已有的登录。")
        row = QHBoxLayout()
        row.setSpacing(10)
        self.copilot_online = Check("读取官方额度")
        self.copilot_online.setChecked(bool(cfg.get("copilot_online")))
        row.addWidget(self.copilot_online)
        row.addStretch(1)
        self.copilot_connect = QPushButton("连接 Copilot")
        self.copilot_connect.clicked.connect(self._connect_copilot)
        row.addWidget(self.copilot_connect)
        lay.addLayout(row)
        self.copilot_status = self._status(
            "已连接 Copilot 账号" if quota.copilot_session()
            else "未连接：可点“连接 Copilot”走 GitHub 设备码登录")
        lay.addWidget(self.copilot_status)

        lay = self._quota_card(
            sources, "remote", "中转 / 自定义 JSON",
            "New API、One API、Sub2API 或任意返回额度的 JSON 地址。")
        form = self._form()
        self.quota_url = QLineEdit(cfg["quota_url"])
        self.quota_url.setPlaceholderText("https://你的站点地址（可含子目录）")
        self.quota_token = QLineEdit(cfg.get("quota_token", ""))
        self.quota_token.setEchoMode(QLineEdit.Password)
        self.quota_token.setPlaceholderText("Bearer token（可选）")
        form.addRow("地址", self.quota_url)
        form.addRow("Token", self.quota_token)
        lay.addLayout(form)
        row = QHBoxLayout()
        row.addStretch(1)
        remove = QPushButton("移除")
        remove.clicked.connect(self._remove_quota_remote)
        row.addWidget(remove)
        lay.addLayout(row)

        save = QPushButton("保存并刷新")
        save.setObjectName("primary")
        save.clicked.connect(self._save_quota)
        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(save)
        outer.addLayout(actions)
        outer.addWidget(self._hint(
            "在线查询只把登录令牌发给对应官方接口，不写日志。"))
        outer.addStretch(1)
        return page

    def _quota_card(self, outer, key, title, subtitle):
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(8)
        name = QLabel(title)
        name.setObjectName("cardTitle")
        state = QLabel("读取中…" if getattr(self, "_quota_reading", False)
                       else "等待刷新")
        state.setObjectName("cardState")
        head.addWidget(name)
        head.addStretch(1)
        head.addWidget(state)
        lay.addLayout(head)
        hint = QLabel(subtitle)
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        outer.addWidget(card)
        self._quota_cards[key] = state
        return lay

    def _refresh_quota(self):
        thread = self._watched.get("quota")
        trigger = getattr(thread, "refresh", None)
        if callable(trigger):
            trigger()
            self._set_status(self.quota_status, "正在刷新额度…")
        else:
            self._set_status(self.quota_status, "暂无额度线程", "warn")

    def _remove_quota_remote(self):
        self.quota_url.clear()
        self.quota_token.clear()
        self.app.update_config({"quota_url": "", "quota_token": ""})
        self._set_status(self.quota_status, "已移除中转来源", "ok")

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
        self._show_quota(providers)
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

    def _show_quota(self, providers):
        labels = {"Codex": "codex", "Claude": "claude",
                  "WorkBuddy": "workbuddy", "Trae CN": "trae",
                  "Copilot": "copilot", "中转": "remote"}
        seen = {}
        for item in providers:
            key = str(item.get("id") or "").lower()
            key = key or labels.get(str(item.get("label") or ""), "")
            if key:
                seen[key] = item
        for key, state in self._quota_cards.items():
            item = seen.get(key)
            if item is None:
                self._set_status(
                    state, "未配置" if key == "remote" else "未开启")
                continue
            if item.get("status") == "error":
                self._set_status(
                    state, self._short(
                        f"读取失败：{item.get('error') or '未知错误'}"),
                    "error")
                continue
            parts = [f"{metric.get('label')} {metric.get('text')}"
                     for metric in (item.get("metrics") or [])[:2]
                     if isinstance(metric, dict)]
            self._set_status(
                state, self._short(" · ".join(parts) or "已连接"), "ok")

    @staticmethod
    def _short(text, limit=30):
        return text if len(text) <= limit else text[:limit - 1] + "…"

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
        self.app.update_config({"trae_online": True})

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
        self.app.update_config({"copilot_online": True})

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
        worker = self._city_search_worker
        if worker is not None and worker.isRunning():
            worker.requestInterruption()
        super().done(result)
