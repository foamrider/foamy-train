import QtQuick

// Control paths match Foamy's settings and back buttons.

Item {
  id: root
  implicitWidth: 16
  implicitHeight: 16
  property string name: "settings"
  readonly property var paths: ({
                                  "swap": '<path d="M4 7h16m-4-4 4 4-4 4M20 17H4m4-4-4 4 4 4"/>',
                                  "train": '<rect x="5" y="2" width="14" height="17" rx="4"/><path d="M5 10h14M12 2v8M8 19l-2 3m10-3 2 3"/><path d="M8 15h.01M16 15h.01"/>',
                                  "warning":
                                  '<path d="m10.3 3.9-8 14a2 2 0 0 0 1.7 3h16a2 2 0 0 0 1.7-3l-8-14a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4m0 4h.01"/>',
                                  "info": '<path d="M3 11v2a2 2 0 0 0 2 2h3l11 4V5L8 9H5a2 2 0 0 0-2 2Zm4 4 2 6h3l-2-5M8 9v6"/>',
                                  "cancelled": '<circle cx="12" cy="12" r="9"/><path d="m9 9 6 6m0-6-6 6"/>',
                                  "refresh-cw":
                                  "<path d=\"M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8\"></path><path d=\"M21 3v5h-5\"></path><path d=\"M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16\"></path><path d=\"M8 16H3v5\"></path>",
                                  "refresh":
                                  '<path d="M20 7v5h-5M4 17v-5h5"/><path d="M6.1 6.1A8 8 0 0 1 20 12M4 12a8 8 0 0 0 13.9 5.9"/>',
                                  "external-link":
                                  '<path d="M15 3h6v6M10 14 21 3M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5"/>',
                                  "app-window":
                                  '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="M2 8h20M6 4v4"/>',
                                  "check": '<path d="m20 6-11 11-5-5"/>',
                                  "arrow-left": '<path d="m12 19-7-7 7-7M5 12h14"/>',
                                  "chevron-down": '<path d="m6 9 6 6 6-6"/>',
                                  "chevron-right": '<path d="m9 6 6 6-6 6"/>',
                                  "settings":
                                  '<path d="m10 3-.6 2.3-2 .9-2.1-.7-2 3.5 1.6 1.7v2.6L3.3 15l2 3.5 2.1-.7 2 .9L10 21h4l.6-2.3 2-.9 2.1.7 2-3.5-1.6-1.7v-2.6L20.7 9l-2-3.5-2.1.7-2-.9L14 3Z"/><circle cx="12" cy="12" r="3"/>'
                                })
  property color color: "white"
  property real strokeWidth: 1.7
  Image {
    anchors.fill: parent
    sourceSize.width: Math.ceil(width * 2)
    sourceSize.height: Math.ceil(height * 2)
    fillMode: Image.PreserveAspectFit
    // Inline SVG keeps the original stroke geometry and follows the active theme.
    source: "data:image/svg+xml;charset=utf-8," + encodeURIComponent(
              '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="' + root.color.toString(
                ) + '" stroke-width="' + root.strokeWidth + '" stroke-linecap="round" stroke-linejoin="round">' + (
                root.paths[root.name] || root.paths.settings) + '</svg>')
  }
}
