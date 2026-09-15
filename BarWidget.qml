import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

BarWidget {
  id: root
  moduleName: "tesla.control"

  property var carStatus: null
  readonly property int iconPx: 12

  function tooltipText() {
    return root.carStatus
      ? ("Tesla — " + Model.pctText(root.carStatus) + " · " + Model.chargingText(root.carStatus))
      : "Tesla — not configured"
  }

  function injectPanel() {
    var target = panelLoader.item
    if (!target) return
    if ("bar" in target) target.bar = root.bar
    if ("settings" in target) target.settings = root.settings
    if ("anchorItem" in target) target.anchorItem = button
    if ("hostWidget" in target) target.hostWidget = root
  }

  function refresh() {
    if (panelLoader.item && panelLoader.item.refresh) panelLoader.item.refresh()
  }

  function togglePanel() {
    if (panelLoader.item && panelLoader.item.toggle) panelLoader.item.toggle()
  }

  function reloadState() {
    statusFile.reload()
  }

  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false

  function open() {
    if (panelLoader.item) panelLoader.item.open()
  }

  function close() {
    if (panelLoader.item) panelLoader.item.close()
  }

  readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing === true : false

  function closeForPopoutSwitch() {
    if (panelLoader.item) panelLoader.item.closeForPopoutSwitch()
  }

  visible: true
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  FileView {
    id: statusFile
    path: Quickshell.env("HOME") + "/.local/state/tesla-ctl/status.json"
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: root.carStatus = Model.parseStatus(text())
    onLoadFailed: root.carStatus = null
  }

  onBarChanged: injectPanel()
  onSettingsChanged: injectPanel()

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  Item {
    id: button
    anchors.centerIn: parent
    implicitWidth: Style.bar.iconSlot
    implicitHeight: root.bar ? root.bar.barSize : Style.bar.sizeHorizontal
    width: implicitWidth
    height: implicitHeight

    Row {
      id: pillRow
      anchors.centerIn: parent
      spacing: Style.space(1)

      Item {
        id: carBox
        width: root.iconPx + 3
        height: root.iconPx
        implicitWidth: root.iconPx + 3
        implicitHeight: root.iconPx
        anchors.verticalCenter: parent.verticalCenter

        Image {
          id: carImg
          width: root.iconPx + 3
          height: root.iconPx
          source: Qt.resolvedUrl("icons/car-grayblue.png")
          sourceSize: Qt.size((root.iconPx + 3) * 4, root.iconPx * 4)
          fillMode: Image.Stretch
          smooth: true
          visible: root.carStatus !== null
        }
      }
    }

    MouseArea {
      anchors.fill: parent
      acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onEntered: if (root.bar) root.bar.showTooltip(button, root.tooltipText())
      onExited: if (root.bar) root.bar.hideTooltip(button)
      onClicked: function(mouse) {
        if (!root.bar) return
        if (mouse.button === Qt.RightButton)
          root.bar.run("omarchy-notification-send \"$(tesla-ctl status 2>/dev/null | head -c 600)\"")
        else if (mouse.button === Qt.MiddleButton)
          root.refresh()
        else
          root.togglePanel()
      }
    }
  }
}