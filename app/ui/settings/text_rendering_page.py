from PySide6 import QtWidgets
from ..dayu_widgets.label import MLabel
from ..dayu_widgets.spin_box import MSpinBox
from ..dayu_widgets.browser import MClickBrowserFileToolButton
from ..dayu_widgets.check_box import MCheckBox

class TextRenderingPage(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QtWidgets.QVBoxLayout(self)

        # Uppercase
        self.uppercase_checkbox = MCheckBox(self.tr("Render Text in UpperCase"))

        # Font section
        font_layout = QtWidgets.QVBoxLayout()
        min_font_layout = QtWidgets.QHBoxLayout()
        max_font_layout = QtWidgets.QHBoxLayout()
        min_font_label = MLabel(self.tr("Minimum Font Size:"))
        max_font_label = MLabel(self.tr("Maximum Font Size:"))

        self.min_font_spinbox = MSpinBox().small()
        self.min_font_spinbox.setFixedWidth(60)
        self.min_font_spinbox.setMaximum(100)
        self.min_font_spinbox.setValue(9)

        self.max_font_spinbox = MSpinBox().small()
        self.max_font_spinbox.setFixedWidth(60)
        self.max_font_spinbox.setMaximum(100)
        self.max_font_spinbox.setValue(40)

        min_font_layout.addWidget(min_font_label)
        min_font_layout.addWidget(self.min_font_spinbox)
        min_font_layout.addStretch()

        max_font_layout.addWidget(max_font_label)
        max_font_layout.addWidget(self.max_font_spinbox)
        max_font_layout.addStretch()

        font_label = MLabel(self.tr("Font:")).h4()

        font_browser_layout = QtWidgets.QHBoxLayout()
        import_font_label = MLabel(self.tr("Import Font:"))
        self.font_browser = MClickBrowserFileToolButton(multiple=True)
        self.font_browser.set_dayu_filters([".ttf", ".ttc", ".otf", ".woff", ".woff2"])
        self.font_browser.setToolTip(self.tr("Import the Font to use for Rendering Text on Images"))

        font_browser_layout.addWidget(import_font_label)
        font_browser_layout.addWidget(self.font_browser)
        font_browser_layout.addStretch()

        font_layout.addWidget(font_label)
        font_layout.addLayout(font_browser_layout)
        
        color_layout = QtWidgets.QHBoxLayout()
        color_label = MLabel(self.tr("Font Color:"))
        self.color_button = QtWidgets.QPushButton()
        self.color_button.setFixedSize(30, 30)
        self.color_button.setStyleSheet("background-color: black; border: none; border-radius: 5px;")
        self.color_button.setProperty("selected_color", "#000000")
        color_layout.addWidget(color_label)
        color_layout.addWidget(self.color_button)
        color_layout.addStretch()
        
        font_layout.addLayout(color_layout)
        font_layout.addLayout(min_font_layout)
        font_layout.addLayout(max_font_layout)

        # Outline section
        outline_label = MLabel(self.tr("Outline:")).h4()
        self.outline_checkbox = MCheckBox(self.tr("Enable Outline by Default"))
        
        outline_props_layout = QtWidgets.QHBoxLayout()
        outline_color_label = MLabel(self.tr("Default Outline Color:"))
        self.outline_color_button = QtWidgets.QPushButton()
        self.outline_color_button.setFixedSize(30, 30)
        self.outline_color_button.setStyleSheet("background-color: white; border: none; border-radius: 5px;")
        self.outline_color_button.setProperty("selected_color", "#ffffff")
        
        outline_width_label = MLabel(self.tr("Default Outline Width:"))
        self.outline_width_spinbox = MSpinBox().small()
        self.outline_width_spinbox.setFixedWidth(60)
        self.outline_width_spinbox.setRange(0.1, 10.0)
        self.outline_width_spinbox.setSingleStep(0.1)
        self.outline_width_spinbox.setValue(1.0)
        
        outline_props_layout.addWidget(outline_color_label)
        outline_props_layout.addWidget(self.outline_color_button)
        outline_props_layout.addSpacing(20)
        outline_props_layout.addWidget(outline_width_label)
        outline_props_layout.addWidget(self.outline_width_spinbox)
        outline_props_layout.addStretch()

        layout.addWidget(self.uppercase_checkbox)
        layout.addSpacing(10)
        layout.addLayout(font_layout)
        layout.addSpacing(20)
        layout.addWidget(outline_label)
        layout.addWidget(self.outline_checkbox)
        layout.addLayout(outline_props_layout)
        layout.addSpacing(10)
        layout.addStretch(1)
