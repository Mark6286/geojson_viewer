from qgis.core import QgsVectorLayer, QgsProject, QgsWkbTypes, QgsEditorWidgetSetup
from qgis.PyQt.QtWidgets import (
    QAction, QLineEdit, QDialog, QFormLayout, QPushButton, QSpinBox,
    QMessageBox, QListWidget, QMenu, QTextEdit, QCheckBox
)
from qgis.PyQt.QtCore import QTimer, QSettings, Qt, QVariant, QDate, QThreadPool, QRunnable, pyqtSignal, QObject
from qgis.utils import iface
import json
import requests
import tempfile
import hashlib
import numbers

class SyncSignals(QObject):
    finished = pyqtSignal(str, str)


class SyncWorker(QRunnable):
    def __init__(self, layer, url, token, edited_features, added_features, deleted_ids):
        super().__init__()
        self.layer = layer
        self.url = url
        self.token = token
        self.edited_features = edited_features
        self.added_features = added_features
        self.deleted_ids = deleted_ids
        self.signals = SyncSignals()

    def run(self):
        try:
            changed_ids = self.edited_features | set(self.added_features.keys())
            if not changed_ids:
                self.signals.finished.emit("info", "No changes to sync.")
                return

            features = []
            for fid in self.edited_features:
                feat = self.layer.getFeature(fid)
                feature = self._serialize_feature(feat)
                feature["__mode"] = "update"
                features.append(feature)

            for fid, feat in self.added_features.items():
                feature = self._serialize_feature(feat)
                feature["__mode"] = "add"
                features.append(feature)

            payload = {"type": "FeatureCollection", "features": features}
            headers = {'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'}
            response = requests.post(self.url, headers=headers, data=json.dumps(payload))

            if response.status_code == 200:
                msg = response.json().get("message", "Synced successfully.")
                self.signals.finished.emit("success", msg)
            else:
                self.signals.finished.emit("error", f"Sync failed: {response.status_code}")
        except Exception as e:
            self.signals.finished.emit("error", f"Sync error: {str(e)}")

    def _serialize_feature(self, feat):
        geometry = feat.geometry()
        props = feat.attributes()
        properties = {
            self.layer.fields().at(i).name(): self.convert_variant(props[i])
            for i in range(len(props))
        }
        return {
            "type": "Feature",
            "geometry": json.loads(geometry.asJson()),
            "properties": properties
        }

    def convert_variant(self, val):
        if isinstance(val, QVariant): val = val.value()
        if hasattr(val, 'toPyObject'): val = val.toPyObject()
        if isinstance(val, QDate): return val.toString("yyyy-MM-dd")
        if isinstance(val, (str, numbers.Number, bool)) or val is None: return val
        try: return str(val)
        except Exception: return None


class GeoJsonViewer:
    def __init__(self, iface):
        self.iface = iface
        self.layers = {}
        self.layer_hashes = {}
        self.settings = QSettings("GeoJsonViewer", "Plugin")
        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh_layers)
        self._edited_features = set()
        self._added_features = {}
        self._deleted_ids = set()
        self.thread_pool = QThreadPool()
        self.init_project_signals()
        self.auth_token = self.settings.value("auth_token", "")

    def initGui(self):
        self.token_action = QAction("Set Auth Token", self.iface.mainWindow())
        self.token_action.triggered.connect(self.show_token_dialog)
        self.add_layer_action = QAction("Load Real-Time HTTPS GeoJSON", self.iface.mainWindow())
        self.add_layer_action.triggered.connect(self.run)

        self.iface.addPluginToMenu("&GeoJSON Viewer", self.token_action)
        self.iface.addPluginToMenu("&GeoJSON Viewer", self.add_layer_action)

    def unload(self):
        self.iface.removePluginMenu("&GeoJSON Viewer", self.token_action)
        self.iface.removePluginMenu("&GeoJSON Viewer", self.add_layer_action)
        self.timer.stop()

    def show_token_dialog(self):
        dialog = QDialog()
        dialog.setWindowTitle("Authorization Token")
        layout = QFormLayout(dialog)

        token_edit = QTextEdit()
        token_edit.setPlainText(self.auth_token)
        remember_box = QCheckBox("Remember this token")

        layout.addRow("Bearer Token:", token_edit)
        layout.addRow("", remember_box)

        save_btn = QPushButton("Save")
        layout.addWidget(save_btn)

        def on_save():
            token = token_edit.toPlainText().strip()
            self.auth_token = token
            if remember_box.isChecked():
                self.settings.setValue("auth_token", token)
            dialog.accept()

        save_btn.clicked.connect(on_save)
        dialog.exec_()

    def run(self):
        dialog = QDialog()
        dialog.setWindowTitle("Add Real-Time GeoJSON Layer")

        layout = QFormLayout(dialog)
        url_input = QLineEdit()
        name_input = QLineEdit()
        token_input = QLineEdit()
        token_input.setPlaceholderText("Optional Bearer Token")
        refresh_input = QSpinBox()
        refresh_input.setRange(10, 3600)
        refresh_input.setValue(30)

        layout.addRow("GeoJSON URL:", url_input)
        layout.addRow("Layer Name:", name_input)
        layout.addRow("Auth Token:", token_input)
        layout.addRow("Refresh Interval (seconds):", refresh_input)

        add_button = QPushButton("Add Layer")
        layout.addWidget(add_button)

        bookmarks = QListWidget()
        bookmarks.setSelectionMode(QListWidget.MultiSelection)
        layout.addRow("Saved Bookmarks:", bookmarks)

        reload_button = QPushButton("Reload Selected")
        layout.addWidget(reload_button)

        for name, config in self.layers.items():
            bookmarks.addItem(f"{name} → {config['url']}")

        def on_add():
            url = url_input.text().strip()
            name = name_input.text().strip() or "RealtimeLayer"
            token = token_input.text().strip()
            interval = refresh_input.value() * 1000

            if not url:
                QMessageBox.warning(dialog, "Input Error", "Please provide a GeoJSON URL.")
                return
            if not url.lower().startswith("https://"):
                QMessageBox.warning(dialog, "Invalid URL", "Only HTTPS URLs are allowed.")
                return
            if name in self.layers:
                QMessageBox.warning(dialog, "Duplicate Layer", f"Layer '{name}' already exists.")
                return

            hash_val, content = self.get_geojson_hash(url, token)
            if hash_val is None:
                QMessageBox.critical(dialog, "GeoJSON Viewer", "Failed to download or parse layer.")
                return

            layer = self.create_layer_from_content(content, name)
            if layer and layer.isValid():
                QgsProject.instance().addMapLayer(layer)
                self.connect_sync_signal(layer, url, token)
                self.layers[name] = {"url": url, "token": token}
                self.layer_hashes[name] = hash_val
                self.save_bookmarks()
                self.timer.start(interval)
                bookmarks.addItem(f"{name} → {url}")
                iface.messageBar().pushInfo("GeoJSON Viewer", f"Layer '{name}' added successfully.")
            else:
                iface.messageBar().pushCritical("GeoJSON Viewer", "Failed to load layer from content.")

        def reload_selected():
            for item in bookmarks.selectedItems():
                name, _ = item.text().split(" → ")
                config = self.layers.get(name, {})
                self.reload_layer(name, config.get("url", ""), config.get("token", ""))

        def context_menu(pos):
            item = bookmarks.itemAt(pos)
            if item:
                menu = QMenu()
                load_action = menu.addAction("Load Layer")
                delete_action = menu.addAction("Delete Bookmark")
                action = menu.exec_(bookmarks.mapToGlobal(pos))
                name, _ = item.text().split(" → ")
                config = self.layers.get(name, {})
                if action == load_action:
                    self.reload_layer(name, config.get("url", ""), config.get("token", ""))
                elif action == delete_action:
                    self.delete_bookmark(name)
                    bookmarks.takeItem(bookmarks.row(item))

        bookmarks.setContextMenuPolicy(Qt.CustomContextMenu)
        bookmarks.customContextMenuRequested.connect(context_menu)

        add_button.clicked.connect(on_add)
        reload_button.clicked.connect(reload_selected)
        dialog.setLayout(layout)
        dialog.exec_()

    def reload_layer(self, name, url, token=""):
        hash_val, content = self.get_geojson_hash(url, token)
        if hash_val is None:
            iface.messageBar().pushCritical("GeoJSON Viewer", f"Failed to check updates for layer '{name}'.")
            return

        layer_present = any(lyr.name() == name for lyr in QgsProject.instance().mapLayers().values())
        if layer_present and self.layer_hashes.get(name) == hash_val:
            iface.messageBar().pushInfo("GeoJSON Viewer", f"Layer '{name}' no changes found.")
            return

        layer = self.create_layer_from_content(content, name)
        if layer and layer.isValid():
            if layer_present:
                for lyr in QgsProject.instance().mapLayers().values():
                    if lyr.name() == name:
                        QgsProject.instance().removeMapLayer(lyr.id())
                        break
            QgsProject.instance().addMapLayer(layer)
            self.connect_sync_signal(layer, url, token)
            self.layer_hashes[name] = hash_val
            iface.messageBar().pushInfo("GeoJSON Viewer", f"Layer '{name}' updated.")
        else:
            iface.messageBar().pushCritical("GeoJSON Viewer", f"Failed to reload layer '{name}'.")

    def connect_sync_signal(self, layer, url, token):
        layer.featureAdded.connect(lambda fid: self._added_features.update({fid: layer.getFeature(fid)}))
        layer.featureDeleted.connect(lambda fid: self._deleted_ids.add(fid))
        layer.geometryChanged.connect(lambda fid, geom: self._edited_features.add(fid))
        layer.attributeValueChanged.connect(lambda fid, idx, val: self._edited_features.add(fid))
        layer.editingStopped.connect(lambda: self.sync_layer_to_server(layer, url, token))

    def get_geojson_hash(self, url, token=""):
        try:
            headers = {'Authorization': f'Bearer {token}'} if token else {}
            response = requests.get(url, headers=headers)
            if response.status_code != 200:
                return None, None
            return hashlib.md5(response.content).hexdigest(), response.content
        except Exception:
            return None, None

    def create_layer_from_content(self, content: bytes, name: str) -> QgsVectorLayer | None:
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".geojson") as tmp_file:
                tmp_file.write(content)
                tmp_file.flush()
                layer_path = tmp_file.name

            layer = QgsVectorLayer(layer_path, name, "ogr")
            if not layer.isValid():
                iface.messageBar().pushCritical("GeoJSON Viewer", f"Layer '{name}' failed to load from temporary file.")
                return None

            hidden_fields = []
            form_config = layer.editFormConfig()

            for field_name in ['id', 'fid']:
                index = layer.fields().indexOf(field_name)
                if index != -1:
                    layer.setEditorWidgetSetup(index, QgsEditorWidgetSetup('Hidden', {}))
                    form_config.setReadOnly(index, True)
                    hidden_fields.append(field_name)
            if hidden_fields:
                layer.setCustomProperty("attributeTable/hiddenFields", hidden_fields)

            return layer

        except Exception as e:
            iface.messageBar().pushCritical("GeoJSON Viewer", f"Error creating layer from content: {e}")
            return None

    def convert_variant(self, val):
        if isinstance(val, QVariant): val = val.value()
        if hasattr(val, 'toPyObject'): val = val.toPyObject()
        if isinstance(val, QDate): return val.toString("yyyy-MM-dd")
        if isinstance(val, (str, numbers.Number, bool)) or val is None: return val
        try: return str(val)
        except Exception: return None

    def sync_layer_to_server(self, layer, url, token=""):
        try:
            changed_ids = self._edited_features | set(self._added_features.keys())
            if not changed_ids:
                iface.messageBar().pushInfo("GeoJSON Viewer", "No changes to sync.")
                return

            features = []
            for fid in self._edited_features:
                feat = layer.getFeature(fid)
                feature = self._serialize_feature(layer, feat)
                feature["__mode"] = "update"
                features.append(feature)

            for fid, feat in self._added_features.items():
                feature = self._serialize_feature(layer, feat)
                feature["__mode"] = "add"
                features.append(feature)

            payload = {"type": "FeatureCollection", "features": features}
            headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
            response = requests.post(url, headers=headers, data=json.dumps(payload))

            if response.status_code == 200:
                self._edited_features.clear()
                self._added_features.clear()
                self._deleted_ids.clear()
                msg = response.json().get("message", "Synced successfully.")
                iface.messageBar().pushSuccess("GeoJSON Viewer", msg)
            else:
                iface.messageBar().pushCritical("GeoJSON Viewer", f"Sync failed: {response.status_code}")

        except Exception as e:
            iface.messageBar().pushCritical("GeoJSON Viewer", f"Sync error: {str(e)}")

    def _serialize_feature(self, layer, feat):
        geometry = feat.geometry()
        props = feat.attributes()
        geom_type = QgsWkbTypes.displayString(geometry.wkbType())
        properties = {
            layer.fields().at(i).name(): self.convert_variant(props[i])
            for i in range(len(props))
        }
        return {
            "type": geom_type,
            "geometry": json.loads(geometry.asJson()),
            "properties": properties
        }

    def delete_bookmark(self, name):
        if name in self.layers:
            del self.layers[name]
            self.layer_hashes.pop(name, None)
            self.save_bookmarks()
            iface.messageBar().pushInfo("GeoJSON Viewer", f"Bookmark '{name}' deleted.")

    def refresh_layers(self):
        for name, config in self.layers.items():
            self.reload_layer(name, config.get("url", ""), config.get("token", ""))

    def save_bookmarks(self):
        project_path = QgsProject.instance().fileName()
        if not project_path:
            return
        self.settings.setValue(f"bookmarks/{project_path}", json.dumps(self.layers))

    def load_bookmarks(self):
        project_path = QgsProject.instance().fileName()
        if not project_path:
            return
        stored = self.settings.value(f"bookmarks/{project_path}", "{}")
        try:
            self.layers = json.loads(stored)
            for name, config in self.layers.items():
                url = config.get("url", "")
                token = config.get("token", "")
                hash_val, content = self.get_geojson_hash(url, token)
                if hash_val and content:
                    self.layer_hashes[name] = hash_val
                    layer = self.create_layer_from_content(content, name)
                    if layer and layer.isValid():
                        QgsProject.instance().addMapLayer(layer)
                        self.connect_sync_signal(layer, url, token)
        except Exception as e:
            iface.messageBar().pushCritical("GeoJSON Viewer", f"Failed to load bookmarks: {e}")
            self.layers = {}

    def init_project_signals(self):
        QgsProject.instance().readProject.connect(self.on_project_loaded)
        QgsProject.instance().cleared.connect(self.on_project_closed)

    def on_project_loaded(self):
        self.load_bookmarks()

    def on_project_closed(self):
        self.layers.clear()
        self.layer_hashes.clear()
        self.timer.stop()
