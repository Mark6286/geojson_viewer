# GeoJSON Viewer for QGIS

**GeoJSON Viewer** is a QGIS plugin that lets users load, bookmark, auto-refresh, and sync GeoJSON layers from secure HTTPS endpoints. It is ideal for real-time spatial data updates and collaborative geospatial workflows.

![GeoJSON Viewer Screenshot](images/geojson-viewer-banner.png)

---

## 🔧 Features

* 📡 Load GeoJSON layers from secure HTTPS URLs
* 🕒 Auto-refresh layers every N seconds
* 🔐 Set and remember Bearer authentication tokens
* 💾 Bookmark layers by name and reload later
* ✍️ Track edits (added, modified, deleted features)
* 🔄 Sync changes back to a remote backend (POST /FeatureCollection)

---

## 🧩 Requirements

* QGIS 3.22+
* Python 3.9+
* Internet access to remote HTTPS GeoJSON endpoints

---

## 🚀 Installation

1. Clone this repository:

   ```bash
   git clone https://github.com/Mark6286/geojson_viewer.git
   ```
2. Move the folder to your QGIS plugin directory:

   ```
   ~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/
   ```
3. Enable the plugin in QGIS via **Plugins → Manage and Install Plugins**.

## or you can download the zip folder

Open  **QGIS → Plugins → Manage and Install Plugins → install from zip**.

---

## 📷 Screenshot

![screenshot](images/screenshot.png)

---

## 🔐 Authentication

Bearer tokens can be optionally set per layer or saved for session reuse. Tokens are included in HTTP headers:

```http
Authorization: Bearer YOUR_TOKEN_HERE
```

---

## 📁 Plugin Metadata

```ini
[general]
name=GeoJSON Viewer
description=View, bookmark, and sync HTTPS GeoJSON layers
qgisMinimumVersion=3.22
author=Rey Mark Balaod
version=1.0
email=reymarkbalaod@gmail.com
```

---

## 📜 License

This plugin is licensed under the **GNU General Public License v2 (GPLv2)**.

---

## 🤝 Acknowledgments

This plugin uses and extends the [QGIS Python API](https://qgis.org/).
Thanks to the QGIS community for supporting open geospatial innovation.
