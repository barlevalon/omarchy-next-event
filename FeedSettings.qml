import QtQuick
import QtQuick.Controls as QQC
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui

KeyboardPanel {
  id: root
  required property string pluginDir
  property bool revealUrls: false
  property bool helpVisible: false
  property bool pendingRead: false
  property bool feedsLoaded: false
  property string message: ""
  readonly property bool busy: configProcess.running
  signal saved()
  signal refreshRequested()

  contentWidth: fittedContentWidth(Style.space(460))
  contentHeight: fittedContentHeight(form.implicitHeight + actions.implicitHeight + Style.space(10), Style.space(680))
  focusTarget: content

  property ListModel feedModel: ListModel { id: feeds }

  function show() {
    revealUrls = false
    helpVisible = false
    message = ""
    feeds.clear()
    feedsLoaded = false
    open = true
    if (busy) pendingRead = true
    else request("read")
  }

  function dismiss() {
    open = false
    feedsLoaded = false
    revealUrls = false
    feeds.clear()
    message = ""
    pendingRead = false
  }

  function urls() {
    var values = []
    for (var i = 0; i < feeds.count; i++) values.push(feeds.get(i).url)
    return values
  }

  function addFeed() {
    feeds.append({ url: "", feedback: "", connected: false })
    message = ""
    Qt.callLater(function() {
      var row = feedRows.itemAt(feeds.count - 1)
      if (root.open && row) row.input.forceActiveFocus()
    })
  }

  function ensureVisible(item) {
    var top = item.mapToItem(form, 0, 0).y
    var bottom = top + item.height
    if (top < viewport.contentY) viewport.contentY = Math.max(0, top)
    else if (bottom > viewport.contentY + viewport.height) {
      viewport.contentY = Math.max(0, Math.min(bottom - viewport.height, viewport.contentHeight - viewport.height))
    }
  }

  function updateFeed(index, value) {
    feeds.setProperty(index, "url", value)
    feeds.setProperty(index, "feedback", "")
    feeds.setProperty(index, "connected", false)
    message = ""
  }

  function request(action) {
    if (busy) return
    if (action === "save" && !feedsLoaded) {
      message = "Load saved feeds successfully before saving changes."
      return
    }
    if (action === "read") feedsLoaded = false
    message = action === "read" ? "Loading feeds…" : (action === "test" ? "Testing connections…" : "Saving feeds…")
    configProcess.action = action
    configProcess.payload = action === "read" ? "" : JSON.stringify({ urls: urls() })
    configProcess.command = [pluginDir + "/next_event.py", "--feeds-" + action]
    configProcess.running = true
  }

  function applyResult(output, action) {
    try {
      var result = JSON.parse(String(output || "{}"))
      if (action === "save" && result.status === "ok") {
        saved()
        if (!pendingRead) dismiss()
        return
      }
      if (!open || pendingRead) return
      if (result.status !== "ok") {
        message = String(result.error || "Calendar settings request failed.")
        return
      }
      if (action === "read") {
        var values = result.urls
        if (!Array.isArray(values) || values.some(function(value) { return typeof value !== "string" })) {
          throw new Error("Invalid feed settings")
        }
        feeds.clear()
        for (var i = 0; i < values.length; i++) feeds.append({ url: values[i], feedback: "", connected: false })
        feedsLoaded = true
        message = ""
        if (feeds.count === 0) addFeed()
      } else if (action === "test") {
        var results = result.results || []
        var connected = 0
        for (var j = 0; j < Math.min(results.length, feeds.count); j++) {
          var ok = results[j].ok === true
          feeds.setProperty(j, "connected", ok)
          feeds.setProperty(j, "feedback", ok ? "Connected · valid calendar" : String(results[j].error || "Connection failed."))
          if (ok) connected++
        }
        message = connected + " of " + feeds.count + " feeds connected. Testing does not save changes."
      }
    } catch (error) {
      if (open) message = "Calendar settings response was invalid."
    }
  }

  property Process helperProcess: Process {
    id: configProcess
    property string action: ""
    property string payload: ""
    stdinEnabled: true
    onStarted: {
      if (action !== "read") write(payload + "\n")
      payload = ""
    }
    onExited: function(exitCode) {
      if (exitCode !== 0 && root.open) root.message = "Calendar helper failed. Check system Python and reinstall the plugin if files are missing."
      if (root.pendingRead && root.open) Qt.callLater(function() {
        if (root.pendingRead && root.open && !root.busy) {
          root.pendingRead = false
          root.request("read")
        }
      })
    }
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.applyResult(text, configProcess.action)
    }
    // Dependency and network errors must never surface raw secret-bearing stderr.
    stderr: StdioCollector { waitForEnd: true }
  }

  Column {
    id: content
    anchors.fill: parent
    spacing: Style.space(10)
    Keys.onEscapePressed: root.dismiss()

    Flickable {
      id: viewport
      width: parent.width
      height: Math.max(0, content.height - actions.implicitHeight - content.spacing)
      contentWidth: width
      contentHeight: form.implicitHeight
      clip: true
      boundsBehavior: Flickable.StopAtBounds
      QQC.ScrollBar.vertical: QQC.ScrollBar {}

      Column {
        id: form
        width: viewport.width
        spacing: Style.space(10)
        onPositioningComplete: {
          for (var i = 0; i < feedRows.count; i++) {
            var row = feedRows.itemAt(i)
            if (row && row.input.activeFocus) root.ensureVisible(row)
          }
        }

        Text {
          textFormat: Text.PlainText
          text: "Calendar feeds"
          color: Commons.Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.subtitle
          font.bold: true
        }

        Text {
          textFormat: Text.PlainText
          text: "Read-only ICS subscription links. Secret links grant calendar read access; treat them as passwords. Saved locally with owner-only permissions."
          color: Commons.Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
          width: parent.width
          wrapMode: Text.WordWrap
        }

        Button {
          id: helpButton
          onActiveFocusChanged: if (activeFocus) root.ensureVisible(helpButton)
          text: root.helpVisible ? "Hide setup help" : "Where do I get a link?"
          focusable: true
          onClicked: root.helpVisible = !root.helpVisible
        }

        Text {
          visible: root.helpVisible
          textFormat: Text.PlainText
          text: "Google Calendar (web): Settings · choose calendar · Integrate calendar · copy Secret address in iCal format.\n\nOutlook (web): Settings · Calendar · Shared calendars · Publish a calendar · choose permissions · copy the ICS link. Publishing exposes selected details to anyone with that link.\n\nWorkplace policies may disable these options. Paste a subscription link, not an HTML page or downloaded .ics file."
          color: Commons.Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
          width: parent.width
          wrapMode: Text.WordWrap
        }

        Repeater {
          id: feedRows
          model: feeds

          Column {
            id: feedRow
            required property int index
            required property string url
            required property string feedback
            required property bool connected
            property alias input: urlInput
            width: form.width
            spacing: Style.space(4)

            Text {
              textFormat: Text.PlainText
              text: "Feed " + (feedRow.index + 1)
              color: Commons.Color.foreground
              font.family: Style.font.family
              font.pixelSize: Style.font.bodySmall
            }

            Row {
              width: parent.width
              spacing: Style.space(6)

              TextField {
                id: urlInput
                width: Math.max(80, parent.width - removeButton.implicitWidth - parent.spacing)
                text: feedRow.url
                placeholderText: "Paste HTTPS ICS URL"
                password: !root.revealUrls
                enabled: !root.busy && root.feedsLoaded
                inputMethodHints: Qt.ImhSensitiveData | Qt.ImhNoPredictiveText
                Accessible.name: "Calendar feed " + (feedRow.index + 1)
                onTextEdited: root.updateFeed(feedRow.index, text)
                onActiveFocusChanged: if (activeFocus) root.ensureVisible(feedRow)
              }

              Button {
                id: removeButton
                text: "Remove"
                focusable: true
                onActiveFocusChanged: if (activeFocus) root.ensureVisible(feedRow)
                enabled: !root.busy && root.feedsLoaded
                onClicked: {
                  feeds.remove(feedRow.index)
                  root.message = ""
                }
              }
            }

            Text {
              textFormat: Text.PlainText
              text: feedRow.feedback
              visible: text !== ""
              color: feedRow.connected ? Commons.Color.accent : Commons.Color.urgent
              font.family: Style.font.family
              font.pixelSize: Style.font.bodySmall
              width: parent.width
              wrapMode: Text.WordWrap
            }
          }
        }

        Flow {
          width: parent.width
          spacing: Style.space(6)

          Button {
            id: addButton
            text: "Add feed"
            focusable: true
            onActiveFocusChanged: if (activeFocus) root.ensureVisible(addButton)
            enabled: !root.busy && root.feedsLoaded && feeds.count < 32
            onClicked: root.addFeed()
          }

          Button {
            id: revealButton
            text: root.revealUrls ? "Hide URLs" : "Show URLs"
            focusable: true
            onActiveFocusChanged: if (activeFocus) root.ensureVisible(revealButton)
            onClicked: root.revealUrls = !root.revealUrls
          }

          Button {
            id: refreshButton
            text: "Refresh calendar"
            focusable: true
            onActiveFocusChanged: if (activeFocus) root.ensureVisible(refreshButton)
            enabled: !root.busy
            onClicked: root.refreshRequested()
          }

          Button {
            id: retryButton
            text: "Retry load"
            visible: !root.feedsLoaded && !root.busy
            focusable: true
            onActiveFocusChanged: if (activeFocus) root.ensureVisible(retryButton)
            onClicked: root.request("read")
          }
        }

        Text {
          textFormat: Text.PlainText
          text: root.message
          visible: text !== ""
          color: Commons.Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
          width: parent.width
          wrapMode: Text.WordWrap
        }
      }
    }

    Flow {
      id: actions
      width: parent.width
      spacing: Style.space(6)

      Button {
        text: "Test connection"
        focusable: true
        enabled: !root.busy && root.feedsLoaded && feeds.count > 0
        onClicked: root.request("test")
      }

      Button {
        text: "Save & refresh"
        bordered: true
        focusable: true
        enabled: !root.busy && root.feedsLoaded
        onClicked: root.request("save")
      }

      Button {
        text: "Cancel"
        focusable: true
        onClicked: root.dismiss()
      }
    }
  }
}
