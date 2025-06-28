def classFactory(iface):
    from .geojson_viewer import GeoJsonViewer
    return GeoJsonViewer(iface)