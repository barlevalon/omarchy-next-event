import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "alon.next-event"

  readonly property string configDir: Quickshell.env("XDG_CONFIG_HOME") || Quickshell.env("HOME") + "/.config"
  readonly property string pluginDir: configDir + "/omarchy/plugins/alon.next-event"
  readonly property string notificationCommand: Quickshell.env("OMARCHY_PATH") + "/bin/omarchy-notification-send"
  property var eventData: null
  property var eventsData: []
  property bool popupOpen: false
  property string selectedKey: ""
  readonly property var selectedEvent: overlapEvents.find(function(event) { return eventKey(event) === selectedKey }) || null
  property var notified: ({})
  property string status: "loading"
  property string errorText: ""
  property bool refreshPending: false
  readonly property bool privacyMode: setting("privacyMode", true) !== false
  readonly property string privacyHint: "Right-click: turn privacy " + (privacyMode ? "off" : "on") + "\nMiddle-click: calendar feeds"

  onPrivacyModeChanged: if (bar) bar.hideTooltip(button)

  function eventTitle(event) {
    return privacyMode ? "Private event" : String(event.title || "Untitled")
  }

  function eventChoiceTitle(event, index) {
    return eventTitle(event) + (privacyMode ? " " + (index + 1) : "")
  }

  function eventTiming(event) {
    return Qt.formatTime(new Date(event.start), "HH:mm") + "–"
      + Qt.formatTime(new Date(event.end), "HH:mm")
      + " · " + (event.ongoing ? "now" : "upcoming")
  }

  readonly property var overlapEvents: {
    if (status !== "ok" || !eventData) return []
    var start = new Date(eventData.start).getTime()
    var end = new Date(eventData.end).getTime()
    var primaryKey = eventKey(eventData)
    var events = eventsData.length ? eventsData : [eventData]
    return events.filter(function(event) {
      if (eventKey(event) === primaryKey) return true
      var otherStart = new Date(event.start).getTime()
      var otherEnd = new Date(event.end).getTime()
      return start < end && otherStart < otherEnd && otherStart < end && start < otherEnd
    })
  }

  onOverlapEventsChanged: if (overlapEvents.length < 2) closePicker()
  onPopupOpenChanged: if (popupOpen) Qt.callLater(function() { pickerColumn.forceActiveFocus() })

  function closePicker() {
    popupOpen = false
    selectedKey = ""
  }

  function close() {
    closePicker()
    feedSettings.dismiss()
  }

  function openFeedSettings() {
    closePicker()
    feedSettings.show()
  }

  function joinEvent(event) {
    if (!event || !event.meetingUrl || openProcess.running) return
    openProcess.command = ["xdg-open", event.meetingUrl]
    openProcess.running = true
    close()
  }

  function togglePrivacy() {
    if (!bar || !bar.shell) return
    var next = Object.assign({}, settings, { privacyMode: !privacyMode })
    bar.shell.updateEntryInline(moduleName, next)
  }

  readonly property string label: {
    if (status === "setup") return "\uf133  setup"
    if (status === "error") return "\uf071  calendar"
    if (!eventData) return "\uf133"
    var title = (privacyMode ? "\uf023  " : "") + eventTitle(eventData)
    if (title.length > 36) title = title.slice(0, 35) + "…"
    var overlaps = overlapEvents.length - 1
    return (eventData.ongoing ? "now" : Qt.formatTime(new Date(eventData.start), "HH:mm")) + " · " + title
      + (overlaps > 0 ? " · +" + overlaps + " overlap" + (overlaps > 1 ? "s" : "") : "")
  }

  readonly property string details: {
    if (status === "setup") return "Calendar setup required\nLeft-click: add calendar feeds\n" + privacyHint
    if (errorText !== "") return (privacyMode ? "Calendar unavailable" : errorText) + "\n" + privacyHint
    if (!eventData) return "No more timed events today\nLeft-click: calendar feeds\n" + privacyHint
    if (overlapEvents.length > 1) {
      return overlapEvents.map(function(event, index) {
        return eventChoiceTitle(event, index) + "\n" + eventTiming(event)
      }).join("\n\n") + "\nLeft-click: choose event\n" + privacyHint
    }
    return eventTitle(eventData) + "\n" + eventTiming(eventData)
      + (eventData.meetingUrl ? "\nLeft-click: join" : "")
      + "\n" + privacyHint
  }

  visible: label !== ""
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  function refresh() {
    if (fetchProcess.running) {
      refreshPending = true
    } else if (pluginDir !== "") {
      fetchProcess.running = true
    }
  }

  function applyResult(output) {
    try {
      var result = JSON.parse(String(output || "{}"))
      status = String(result.status || "error")
      errorText = String(result.error || "")
      if (status === "ok") {
        eventData = result.event || null
        eventsData = result.events || (eventData ? [eventData] : [])
      } else {
        eventsData = []
      }
    } catch (error) {
      status = "error"
      errorText = "Calendar response was invalid"
      eventsData = []
    }
    checkNotifications()
  }

  function eventKey(event) {
    return [event.start, event.end, event.title, event.meetingUrl].join("\n")
  }

  function sendNotification(event, starting) {
    var start = new Date(event.start)
    var minutes = Math.max(1, Math.ceil((start.getTime() - Date.now()) / 60000))
    var headline = starting ? "Event starting now" : "Event in " + minutes + " minutes"
    var body = eventTitle(event) + " · " + Qt.formatTime(start, "HH:mm")
    var command = [notificationCommand, "--app-name", "Calendar", "-u", "normal", "-g", "\uf133", headline, body]
    if (!privacyMode && event.meetingUrl) command = command.concat(["--exec", "xdg-open", String(event.meetingUrl)])
    Quickshell.execDetached(command)
  }

  function checkNotifications() {
    notificationTimer.stop()
    var now = Date.now()
    var nextAt = Infinity

    for (var i = 0; i < eventsData.length; i++) {
      var event = eventsData[i]
      var startAt = new Date(event.start).getTime()
      var key = eventKey(event)
      var soonKey = key + "\nsoon"
      var startKey = key + "\nstart"
      var soonAt = startAt - 15 * 60 * 1000

      if (!notified[soonKey]) {
        if (now >= soonAt) {
          if (now < startAt) sendNotification(event, false)
          notified[soonKey] = true
        } else {
          nextAt = Math.min(nextAt, soonAt)
        }
      }

      if (!notified[startKey]) {
        if (now >= startAt) {
          if (now < startAt + 5 * 60 * 1000) sendNotification(event, true)
          notified[startKey] = true
        } else {
          nextAt = Math.min(nextAt, startAt)
        }
      }
    }

    if (nextAt < Infinity) {
      notificationTimer.interval = Math.max(1, nextAt - Date.now())
      notificationTimer.start()
    }
  }

  Process {
    id: fetchProcess
    command: [root.pluginDir + "/next_event.py"]
    onExited: function(exitCode) {
      if (exitCode !== 0) {
        root.status = "error"
        root.errorText = "Calendar refresh failed"
      }
      if (root.refreshPending) Qt.callLater(function() {
        root.refreshPending = false
        root.refresh()
      })
    }

    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.applyResult(text)
    }
  }

  Process {
    id: openProcess
  }

  Timer {
    id: notificationTimer
    repeat: false
    onTriggered: root.checkNotifications()
  }

  Timer {
    interval: 300000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }

  FeedSettings {
    id: feedSettings
    anchorItem: button
    bar: root.bar
    owner: root
    pluginDir: root.pluginDir
    onSaved: root.broadcast("refresh")
    onRefreshRequested: root.broadcast("refresh")
  }

  PopupCard {
    id: picker
    anchorItem: button
    bar: root.bar
    owner: root
    open: root.popupOpen
    contentWidth: picker.fittedContentWidth(Style.space(360))
    contentHeight: picker.fittedContentHeight(pickerHeading.implicitHeight + eventList.implicitHeight
      + pickerActions.implicitHeight + pickerColumn.spacing * 2, Style.space(480))

    Column {
      id: pickerColumn
      anchors.fill: parent
      spacing: Style.space(10)
      Keys.onEscapePressed: root.close()

      Column {
        id: pickerHeading
        width: parent.width
        spacing: Style.space(4)

        Text {
          textFormat: Text.PlainText
          text: "Overlapping events"
          color: Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.subtitle
          font.bold: true
        }

        Text {
          textFormat: Text.PlainText
          text: "Choose an event, then join." + (root.privacyMode ? " Titles hidden." : "")
          color: Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
          width: parent.width
          wrapMode: Text.WordWrap
        }
      }

      Flickable {
        id: eventViewport
        width: parent.width
        height: Math.max(0, pickerColumn.height - pickerHeading.implicitHeight
          - pickerActions.implicitHeight - pickerColumn.spacing * 2)
        contentWidth: width
        contentHeight: eventList.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        Column {
          id: eventList
          width: eventViewport.width
          spacing: Style.space(4)

          Repeater {
            model: root.overlapEvents

            Button {
              id: eventRow
              required property var modelData
              required property int index
              width: eventList.width
              implicitHeight: rowContent.implicitHeight + Style.space(16)
              selected: root.selectedKey === root.eventKey(modelData)
              focusable: true
              Accessible.role: Accessible.RadioButton
              Accessible.name: root.eventChoiceTitle(modelData, index) + " " + root.eventTiming(modelData)
              Accessible.checked: selected
              Accessible.onPressAction: root.selectedKey = root.eventKey(modelData)
              onClicked: root.selectedKey = root.eventKey(modelData)
              onActiveFocusChanged: if (activeFocus) {
                eventViewport.contentY = Math.max(0, Math.min(y, eventViewport.contentHeight - eventViewport.height))
              }

              Column {
                id: rowContent
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: eventRow.contentLeftInset
                anchors.rightMargin: eventRow.contentRightInset
                anchors.verticalCenter: parent.verticalCenter
                spacing: Style.space(3)

                Text {
                  textFormat: Text.PlainText
                  text: root.eventChoiceTitle(eventRow.modelData, eventRow.index)
                  color: eventRow.selected ? Color.accent : Color.foreground
                  font.family: Style.font.family
                  font.pixelSize: Style.font.body
                  font.bold: eventRow.selected
                  width: parent.width
                  elide: Text.ElideRight
                }

                Text {
                  textFormat: Text.PlainText
                  text: root.eventTiming(eventRow.modelData) + (eventRow.modelData.meetingUrl ? "" : " · no meeting link")
                  color: Color.foreground
                  font.family: Style.font.family
                  font.pixelSize: Style.font.bodySmall
                  width: parent.width
                  elide: Text.ElideRight
                }
              }
            }
          }
        }
      }

      Row {
        id: pickerActions
        spacing: Style.space(8)

        Button {
          text: "Join meeting"
          bordered: true
          focusable: true
          enabled: root.selectedEvent !== null && !!root.selectedEvent.meetingUrl && !openProcess.running
          opacity: enabled ? 1 : 0.45
          onClicked: root.joinEvent(root.selectedEvent)
        }

        Button {
          text: "Cancel"
          focusable: true
          onClicked: root.close()
        }
      }
    }
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.label
    labelVisible: true
    tooltipText: root.details
    onPressed: function(button) {
      if (button === Qt.RightButton) {
        root.togglePrivacy()
      } else if (button === Qt.MiddleButton || (button === Qt.LeftButton && (root.status === "setup" || root.status === "error" || !root.eventData))) {
        root.openFeedSettings()
      } else if (button === Qt.LeftButton && root.status === "ok" && root.overlapEvents.length > 1) {
        feedSettings.dismiss()
        root.selectedKey = ""
        root.popupOpen = !root.popupOpen
      } else if (button === Qt.LeftButton && root.status === "ok" && root.eventData && root.eventData.meetingUrl) {
        root.joinEvent(root.eventData)
      } else {
        root.refresh()
      }
    }
  }
}
