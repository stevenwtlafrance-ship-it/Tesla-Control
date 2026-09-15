import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

Panel {
  id: root
  moduleName: "tesla.control"
  ipcTarget: "tesla.control"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  readonly property var barIdentity: hostWidget || root
  property var carStatus: hostWidget ? hostWidget.carStatus : null

  property bool openedFromHotkey: false
  property bool busy: false
  property bool refreshing: false
  property string statusText: ""
  property string lastError: ""

  readonly property string ctlPath: Quickshell.env("HOME") + "/.local/bin/tesla-ctl"
  readonly property color fg: root.barForeground
  readonly property string fam: root.bar ? root.bar.fontFamily : Style.font.family

  property var actionRows: []

  function open() {
    statusText = ""
    root.controller.show()
    root.refresh()
  }

  function openFromHotkey() {
    root.openedFromHotkey = true
    root.open()
  }

  function close() {
    root.controller.hide()
  }

  function toggle() {
    root.opened ? root.close() : root.openFromHotkey()
  }

  function buildActions() {
    var c = Model.compiled(root.carStatus)
    var locked = c ? Model.isLocked(root.carStatus) : false
    var sentry = c ? Model.isSentry(root.carStatus) : false
    var portOpen = c ? Model.isChargePortOpen(root.carStatus) : false
    var charging = c ? Model.isCharging(root.carStatus) : false
    var S = Model.ICON

    root.actionRows = [
      [
        { act: locked ? "unlock" : "lock", icon: locked ? S.unlock : S.lock, label: locked ? "Unlock" : "Lock" },
        { act: sentry ? "sentry-off" : "sentry-on", icon: S.shield, label: sentry ? "Sentry: On" : "Sentry: Off" }
      ],
      [
        { act: "flash", icon: S.bolt2, label: "Flash lights" },
        { act: "honk", icon: S.horn, label: "Honk" }
      ],
      [
        { act: "vent", icon: S.winVent, label: "Vent windows" },
        { act: "close-windows", icon: S.winClose, label: "Close windows" }
      ],
      [
        { act: portOpen ? "charge-port-close" : "charge-port-open", icon: S.plug, label: portOpen ? "Port: Close" : "Port: Open" },
        { act: charging ? "charge-stop" : "charge-start", icon: S.bolt, label: charging ? "Stop charging" : "Start charging" }
      ],
      [
        { act: "trunk-open", icon: S.arrowDown, label: "Trunk" },
        { act: "frunk-open", icon: S.arrowUp, label: "Frunk" }
      ],
      [
        { act: "wake", icon: S.power, label: "Wake car" },
        { act: "remote-start", icon: S.key, label: "Remote start" }
      ]
    ]
  }

  onCarStatusChanged: root.buildActions()

  function send(command, args) {
    if (root.busy) return
    root.busy = true
    root.lastError = ""
    root.statusText = "Sending " + String(command).replace(/-/g, " ") + "…"
    cmdProc.command = [root.ctlPath, "command", command].concat((args || []).map(String))
    cmdProc.running = true
  }

  function refresh() {
    if (root.refreshing) return
    root.refreshing = true
    statusProc.running = true
  }

  function actionResultLabel(resultText) {
    return root.lastError !== "" ? "Failed — " + root.lastError : "Sent ✓"
  }

  // -------------------------------------------------------------- refresher

  Process {
    id: statusProc
    command: [root.ctlPath, "status"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        if (hostWidget && hostWidget.reloadState) hostWidget.reloadState()
      }
    }
    stderr: StdioCollector {
      id: statusErr
      waitForEnd: true
      onStreamFinished: {
        var msg = String(statusErr.text || "").trim()
        if (msg !== "") root.statusText = msg.split("\n")[0]
      }
    }
    onExited: function(exitCode) {
      root.refreshing = false
    }
  }

  // -------------------------------------------------------------- commands

  Process {
    id: cmdProc
    stdout: StdioCollector {
      waitForEnd: true
    }
    stderr: StdioCollector {
      id: cmdErr
      waitForEnd: true
      onStreamFinished: root.lastError = String(cmdErr.text || "").trim().replace(/^tesla-ctl:\s*/, "")
    }
    onExited: function(exitCode) {
      root.busy = false
      if (exitCode !== 0) {
        root.statusText = root.lastError !== "" ? "Failed — " + root.lastError : "Command failed"
        return
      }
      root.statusText = "Sent ✓"
      afterCommand.restart()
    }
  }

  Timer {
    id: afterCommand
    interval: 1600
    onTriggered: root.refresh()
  }

  Timer {
    id: autoRefresh
    interval: 300000
    running: true
    repeat: true
    onTriggered: root.refresh()
  }

  Component.onCompleted: root.buildActions()

  // ---------------------------------------------------------------- surface

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(478))
    contentHeight: panel.fittedContentHeight(contentColumn.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTextKey: function(t) {
        if (t === "r") root.refresh()
        else if (t === "c") root.close()
      }

      Column {
        id: contentColumn
        width: parent.width
        spacing: Style.spacing.panelGap

        // ---- not-configured hint
        Rectangle {
          visible: !Model.compiled(root.carStatus)
          width: parent.width
          height: hintText.implicitHeight + Style.space(16)
          radius: Style.cornerRadius
          color: Style.normalFillFor(root.fg, Color.accent)

          Text {
            id: hintText
            textFormat: Text.PlainText
            anchors.centerIn: parent
            width: parent.width - Style.space(32)
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: "No Tesla status yet.\n\nSet up the backend with:\n  tesla-ctl doctor\nand follow ~/.config/tesla-ctl/SETUP.md"
            color: Qt.darker(root.fg, 1.4)
            font.family: root.fam
            font.pixelSize: Style.font.bodySmall
          }
        }

        // ---- hero: car glyph + charge summary
        Rectangle {
          width: parent.width
          height: Style.space(104)
          radius: Style.cornerRadius
          color: Style.normalFillFor(root.fg, Color.accent)

          Item {
            id: heroRow
            anchors.fill: parent

            Item {
              id: carIconBlock
              width: Style.space(80)
              height: Style.space(64)
              anchors.left: parent.left
              anchors.leftMargin: Style.space(10)
              anchors.verticalCenter: parent.verticalCenter
              Text {
                textFormat: Text.PlainText
                anchors.centerIn: parent
                text: Model.ICON.car
                color: root.fg
                font.family: root.fam
                font.pixelSize: Style.font.displayLarge
              }
            }

            Column {
              width: Style.space(130)
              anchors.left: carIconBlock.right
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(2)

              Text {
                textFormat: Text.PlainText
                text: Model.pctText(root.carStatus)
                color: root.fg
                font.family: root.fam
                font.pixelSize: Style.font.heading
                font.bold: true
              }
              Text {
                textFormat: Text.PlainText
                text: Model.chargingText(root.carStatus)
                color: Qt.darker(root.fg, 1.4)
                font.family: root.fam
                font.pixelSize: Style.font.bodySmall
              }
              Text {
                textFormat: Text.PlainText
                visible: Model.rangeText(root.carStatus) !== ""
                text: Model.rangeText(root.carStatus)
                color: Qt.darker(root.fg, 1.4)
                font.family: root.fam
                font.pixelSize: Style.font.bodySmall
              }
              Text {
                textFormat: Text.PlainText
                visible: Model.roundedMiles(root.carStatus) !== ""
                text: Model.roundedMiles(root.carStatus) + " total"
                color: Qt.darker(root.fg, 1.4)
                font.family: root.fam
                font.pixelSize: Style.font.bodySmall
              }
            }

            Column {
              anchors.right: parent.right
              anchors.rightMargin: Style.space(18)
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(2)

              Text {
                textFormat: Text.PlainText
                text: {
                  var c = Model.compiled(root.carStatus)
                  return c && c.name ? c.name : "Tesla"
                }
                color: root.fg
                font.family: root.fam
                font.pixelSize: Style.font.bodySmall
              }
              Text {
                textFormat: Text.PlainText
                visible: Model.vinInfo(root.carStatus) !== ""
                text: Model.vinInfo(root.carStatus)
                color: Qt.darker(root.fg, 1.4)
                font.family: root.fam
                font.pixelSize: Style.font.bodySmall
              }
              Text {
                textFormat: Text.PlainText
                text: (Model.isLocked(root.carStatus) ? "Locked" : "Unlocked") + " · " +
                      Model.insideTemp(root.carStatus) + " in"
                color: Qt.darker(root.fg, 1.4)
                font.family: root.fam
                font.pixelSize: Style.font.bodySmall
              }
              Text {
                textFormat: Text.PlainText
                text: Model.outsideTemp(root.carStatus) + " out · " + Model.roundedMiles(root.carStatus)
                color: Qt.darker(root.fg, 1.4)
                font.family: root.fam
                font.pixelSize: Style.font.bodySmall
              }
            }
          }
        }

        PanelSectionHeader {
          text: "CHARGING"
          foreground: root.fg
          fontFamily: root.fam
        }

        // ---- charge limit slider
        Row {
          width: parent.width
          spacing: Style.spacing.lg
          height: Style.spacing.controlHeight

          Text {
            textFormat: Text.PlainText
            width: Style.space(120)
            height: parent.height
            verticalAlignment: Text.AlignVCenter
            text: Model.ICON.bolt + "  Limit"
            color: root.fg
            font.family: root.fam
            font.pixelSize: Style.font.bodySmall
          }

          PanelSlider {
            id: chargeSlider
            bar: root.bar
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width - Style.space(120) - Style.space(96) - Style.spacing.lg * 2
            minimum: 50
            maximum: 100
            integer: true
            step: 1
            tickCount: 11
            value: Model.chargeLimit(root.carStatus)
            onReleased: function(v) {
              var target = Math.round(v)
              var current = Model.chargeLimit(root.carStatus)
              if (target !== current && !root.busy) root.send("charge-limit", [String(target)])
            }
          }

          Text {
            textFormat: Text.PlainText
            width: Style.space(96)
            height: parent.height
            verticalAlignment: Text.AlignVCenter
            horizontalAlignment: Text.AlignRight
            text: (chargeSlider.dragging ? Math.round(chargeSlider.liveValue) : Model.chargeLimit(root.carStatus)) + "%"
            color: root.fg
            font.family: root.fam
            font.pixelSize: Style.font.body
          }
        }

        PanelSectionHeader {
          text: "CLIMATE"
          foreground: root.fg
          fontFamily: root.fam
        }

        // ---- climate: on/off + temp stepper
        Row {
          width: parent.width
          spacing: Style.spacing.lg
          height: Style.spacing.controlHeight

          Button {
            id: climateBtn
            width: (parent.width - Style.spacing.lg) * 0.5
            height: Style.spacing.controlHeight
            iconText: Model.climateIcon(root.carStatus)
            text: Model.compiled(root.carStatus) && Model.compiled(root.carStatus).is_climate_on ? "Climate: On" : "Climate: Off"
            fontFamily: root.fam
            foreground: root.fg
            enabled: !root.busy
            onClicked: root.send(Model.compiled(root.carStatus) && Model.compiled(root.carStatus).is_climate_on ? "climate-off" : "climate-on")
          }

          Item {
            width: (parent.width - Style.spacing.lg) * 0.5
            height: Style.spacing.controlHeight

            Button {
              id: tempDown
              width: Style.space(40)
              height: parent.height
              iconText: Model.ICON.minus
              fontFamily: root.fam
              foreground: root.fg
              enabled: !root.busy
              onClicked: root.adjustTemp(-0.5)
            }

            Text {
              textFormat: Text.PlainText
              anchors.centerIn: parent
              text: Model.tempDisplay(Model.targetTemp(root.carStatus), Model.units(root.carStatus))
              color: root.fg
              font.family: root.fam
              font.pixelSize: Style.font.body
            }

            Button {
              id: tempUp
              anchors.right: parent.right
              width: Style.space(40)
              height: parent.height
              iconText: Model.ICON.plus
              fontFamily: root.fam
              foreground: root.fg
              enabled: !root.busy
              onClicked: root.adjustTemp(0.5)
            }
          }
        }

        PanelSectionHeader {
          text: "CONTROLS"
          foreground: root.fg
          fontFamily: root.fam
        }

        // ---- action grid (two buttons per row)
        Repeater {
          model: root.actionRows

          delegate: Row {
            required property var modelData
            width: contentColumn.width
            spacing: Style.spacing.lg
            height: Style.spacing.controlHeight

            Repeater {
              model: modelData

              delegate: Button {
                required property var modelData
                width: (contentColumn.width - Style.spacing.lg) / 2
                height: Style.spacing.controlHeight
                iconText: modelData.icon
                text: modelData.label
                iconSize: Style.font.icon
                fontSize: Style.font.bodySmall
                fontFamily: root.fam
                foreground: root.fg
                bordered: true
                enabled: !root.busy
                onClicked: root.send(modelData.act, modelData.args || [])
              }
            }
          }
        }

        // ---- footer status
        Row {
          width: parent.width
          spacing: Style.spacing.sm
          visible: root.statusText !== "" || root.busy || root.refreshing

          Text {
            textFormat: Text.PlainText
            visible: root.busy || root.refreshing
            text: "󰦖"
            color: Qt.darker(root.fg, 1.4)
            font.family: root.fam
            font.pixelSize: Style.font.bodySmall

            RotationAnimator on rotation {
              running: root.busy || root.refreshing
              from: 0; to: 360
              duration: 800
              loops: Animation.Infinite
            }
          }

          Text {
            textFormat: Text.PlainText
            text: root.statusText
            color: Qt.darker(root.fg, 1.4)
            font.family: root.fam
            font.pixelSize: Style.font.bodySmall
          }
        }

        // ---- VIN
        Row {
          width: parent.width
          spacing: Style.spacing.sm
          visible: Model.compiled(root.carStatus) && Model.compiled(root.carStatus).vin

          Text {
            textFormat: Text.PlainText
            text: "VIN  " + Model.compiled(root.carStatus).vin
            color: Qt.darker(root.fg, 1.4)
            font.family: root.fam
            font.pixelSize: Style.font.bodySmall
          }
        }
      }
    }
  }

  function adjustTemp(deltaC) {
    if (root.busy) return
    var target = Model.targetTemp(root.carStatus) + deltaC
    target = Math.max(14, Math.min(33, Math.round(target * 2) / 2))
    root.send("temps", [String(target), String(target)])
  }
}