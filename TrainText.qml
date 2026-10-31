import QtQuick
import "kit"

// Popup text: plain text only (Entur data never renders as markup).
Text {
  color: FoamyPalette.text
  font.family: FoamyStyle.fontFamily
  font.pixelSize: FoamyStyle.font.body
  textFormat: Text.PlainText
  wrapMode: Text.WordWrap
  horizontalAlignment: Text.AlignLeft
}
