import base64
import os
import sys
from typing import Any, List, Dict, Tuple
from pathlib import Path
from collections import namedtuple
from json import loads as j_loads, dumps as j_dumps

import yaml
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QHBoxLayout,
    QScrollArea,
    QPushButton,
    QFrame,
    QTextEdit,
    QFileDialog,
    QMessageBox,
)
from PyQt6.QtCore import Qt


ConfEnt = namedtuple("ConfEnt", ["id", "desc", "default"])

MENIFEST_PATH = "menifest.yaml"


class FormatMap:
    def __init__(self, data: dict = None):
        self.data = data or {}

    def __getitem__(self, key):
        return self.data.get(key, "")

    def __setitem__(self, key, value):
        self.data[key] = value

    def update(self, other: dict):
        self.data.update(other)

    def to_dict(self):
        return dict(self.data)


class Configs:
    def __init__(self, title: str, version: str, base: str):
        self.title = title
        self.version = version
        self.base = Path(base)
        self.targets: List[Path] = []
        self.configs: List[ConfEnt] = []
        self.contents: Dict[str, str] = {}

    def init_targets(self):
        print("Parsing all the target files ...")
        for p in self.base.rglob("*"):
            if p.is_file():
                self.targets.append(p)
        print(f"We got {len(self.targets)} files in all")

    def append(self, conf_id: str, desc: str, default: str):
        self.configs.append(ConfEnt(conf_id, desc, default))

    def export_as_map(self) -> Dict[str, str]:
        output = {}
        for conf in self.configs:
            output[conf.id] = conf.default
        for k, v in self.contents.items():
            output[k] = v
        return output

    def export_as_json(self) -> str:
        o = j_dumps(self.contents)
        print("Exported json config:", o)
        encoded = base64.b64encode(o.encode("utf-8")).decode("utf-8")
        return encoded

    def load_from_json(self, content: str):
        o = base64.b64decode(content).decode("utf-8")
        print("Loaded json config:", o)
        data = j_loads(o)
        self.contents.clear()
        for k, v in data.items():
            self.contents[k] = v

    def export_as_config(
        self, target_base: Path | None = None
    ) -> List[Tuple[Path, str]]:
        output = []
        data = self.export_as_map()

        for p in self.targets:
            raw_text = p.read_text()
            text = raw_text.format_map(data)

            rel = p.relative_to(self.base)
            if target_base is not None:
                real = target_base / rel
            else:
                real = "fake_root" / rel

            output.append((real, text))

        return output


def parse(configs: Configs, prefix: List[str], o: dict):
    if "ident" in o:
        prefix = prefix + [o["ident"]]
    if "description" in o:
        configs.append("|".join(prefix), o["description"], o["default"])
    for sub in o.get("subs", []):
        parse(configs, prefix, sub)


class SeparatorWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.HLine)
        self.setFrameShadow(QFrame.Shadow.Sunken)


class ConfigEntryWidget(QWidget):
    def __init__(self, conf: ConfEnt, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout()

        row1 = QHBoxLayout()
        desc_label = QLabel(conf.desc)
        id_label = QLabel(conf.id)
        id_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        row1.addWidget(desc_label)
        row1.addWidget(id_label)
        layout.addLayout(row1)

        self.line_edit = QLineEdit()
        self.line_edit.setPlaceholderText(str(conf.default))
        layout.addWidget(self.line_edit)
        self.setLayout(layout)


class MainWindow(QWidget):
    def __init__(self, configs: Configs):
        self.configs = configs

        super().__init__()
        self.setWindowTitle(f"{configs.title} v{configs.version}")
        self.setMinimumSize(600, 800)

        self.main_layout = QVBoxLayout()

        self.button_layout = QHBoxLayout()
        self.save_button = QPushButton("保存配置")
        self.load_button = QPushButton("加载配置")
        self.export_button = QPushButton("导出配置")
        self.preview_button = QPushButton("预览配置")
        for btn in [
            self.save_button,
            self.load_button,
            self.export_button,
            self.preview_button,
        ]:
            self.button_layout.addWidget(btn)
        self.main_layout.addLayout(self.button_layout)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.content_widget = QWidget()
        self.conent_layout = QVBoxLayout(self.content_widget)

        self.hint_label = QLabel("留空则使用默认配置！", self)
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.conent_layout.addWidget(self.hint_label)

        self.conent_layout.addWidget(SeparatorWidget(self))
        self.entry_widgets = []
        for conf in configs.configs:
            entry_widget = ConfigEntryWidget(conf)
            entry_widget.line_edit.textEdited.connect(
                self.mk_on_conf_edited(conf.id, entry_widget.line_edit)
            )
            self.conent_layout.addWidget(entry_widget)
            self.conent_layout.addWidget(SeparatorWidget(self))
            self.entry_widgets.append(entry_widget)

        self.scroll_area.setWidget(self.content_widget)
        self.main_layout.addWidget(self.scroll_area)

        self.save_button.clicked.connect(self.on_save_config)
        self.load_button.clicked.connect(self.on_load_config)
        self.export_button.clicked.connect(self.on_export_config)
        self.preview_button.clicked.connect(self.on_preview_config)

        self.setLayout(self.main_layout)

    def mk_on_conf_edited(self, key: str, lineedit: QLineEdit):
        def inner():
            text = lineedit.text()
            if text:
                self.configs.contents[key] = text
            else:
                del self.configs.contents[key]

        return inner

    def on_save_config(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "选择保存配置的文件", "", "All Files (*)"
        )
        if not file_path:
            return
        try:
            jstr = self.configs.export_as_json()
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(jstr)
            QMessageBox.information(self, "保存成功", f"配置已保存到: {file_path}")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"保存配置时出错:\n{e}")

    def on_load_config(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择要加载的配置文件", "", "All Files (*)"
        )
        if not file_path:
            return
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                jstr = f.read()
            self.configs.load_from_json(jstr)
            # 更新界面
            for conf, entry_widget in zip(self.configs.configs, self.entry_widgets):
                value = str(self.configs.contents.get(conf.id, conf.default))
                if value == conf.default:
                    entry_widget.line_edit.setText("")
                else:
                    entry_widget.line_edit.setText(value)
            QMessageBox.information(self, "加载成功", f"配置已从: {file_path} 加载")
        except Exception as e:
            QMessageBox.critical(self, "加载失败", f"加载配置时出错:\n{e}")

    def on_export_config(self):
        folder_path = QFileDialog.getExistingDirectory(
            self, "选择导出文件夹（项目根目录）", ""
        )
        if not folder_path:
            return
        try:
            folder_path = Path(folder_path) / "EPP-Configuration"
            reply = QMessageBox.question(
                self,
                "确认导出",
                f"确定要导出配置到: {folder_path} 吗？此操作将会覆盖其中的内容！",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            os.makedirs(folder_path, exist_ok=True)

            data = self.configs.export_as_config(folder_path)

            for path, content in data:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
                print(f"File {path} written!")

            QMessageBox.information(self, "导出成功", f"配置已导出到: {folder_path}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"导出配置时出错:\n{e}")

    def on_preview_config(self):
        data = self.configs.export_as_config()
        msg = ""
        for path, content in data:
            msg += f"=====> {path} <=====\n{content}\n\n"

        preview_widget = QWidget(self, flags=Qt.WindowType.Window)
        preview_widget.setWindowTitle("配置预览")
        preview_widget.setMinimumSize(600, 400)
        layout = QVBoxLayout(preview_widget)
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setText(msg)
        font = text_edit.font()
        font.setFamily("Courier New")
        font.setStyleHint(font.StyleHint.Monospace)
        text_edit.setFont(font)
        layout.addWidget(text_edit)
        preview_widget.setWindowModality(Qt.WindowModality.ApplicationModal)
        preview_widget.show()


def launch_gui(configs: Configs):
    app = QApplication(sys.argv)
    window = MainWindow(configs)
    window.show()
    return app.exec()


if __name__ == "__main__":
    menifest = yaml.load(open(MENIFEST_PATH, "r"), yaml.SafeLoader)
    configs = Configs(
        menifest["meta"]["title"],
        menifest["meta"]["version"],
        menifest["target"]["base"],
    )
    print(f"Welcome to {configs.title} Ver {configs.version}.")

    print("Parsing all the config items ...")
    parse(configs, list(), menifest["config"])
    print(f"We got {len(configs.configs)} config entries in all.")

    configs.init_targets()

    r = launch_gui(configs)

    print("Exit with return value:", r)
