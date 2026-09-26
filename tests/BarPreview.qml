import QtQuick
import Quickshell
import qs.Commons
import "plugin" as Train
import "plugin/tests/Fixtures.js" as Fixtures
Scope {
  FloatingWindow {
    visible:true;implicitWidth:640;implicitHeight:400;color:Color.popups.background
    Rectangle {
      id:surface;width:640;height:420;color:Color.popups.background
      Column {
        x:24;y:22;width:592;spacing:14
        Train.TrainText {text:"Minutes shown";font.pixelSize:16}
        Repeater {
          model:[{label:"On time",mode:"normal"},{label:"Delayed 3 minutes",mode:"delay"},{label:"Incident",mode:"incident"},{label:"Delay + incident",mode:"both"},{label:"Information",mode:"info"},{label:"Cancellation",mode:"cancelled"},{label:"Outside schedule",mode:"schedule"},{label:"Minutes hidden · incident",mode:"hidden"}]
          Row {
            required property var modelData
            width:parent.width;height:26;spacing:14
            Train.TrainText {width:280;anchors.verticalCenter:parent.verticalCenter;text:parent.modelData.label}
            Rectangle {
              width:240;height:28;radius:6;color:Qt.alpha(Color.popups.text,0.05)
              Train.TrainBar {
                anchors.left:parent.left;anchors.leftMargin:12;anchors.verticalCenter:parent.verticalCenter
                readonly property string mode:parent.parent.modelData.mode
                readonly property var sample:{var r=Fixtures.report("normal");if(mode==="delay"||mode==="both")r.departures[0]=Fixtures.departure("a",13,"R10",3);if(mode==="incident"||mode==="both"||mode==="hidden")r.departures[0].notices=[Fixtures.notice("x","Signal fault","warning")];if(mode==="info")r.departures[0].notices=[Fixtures.notice("x","Shorter train","info")];if(mode==="cancelled")r.departures[1].cancelled=true;return r}
                next:sample.departures[0];departures:sample.departures;nowEpoch:Fixtures.now
                withinSchedule:mode!=="schedule";showMinutes:mode!=="hidden";opacity:withinSchedule?1:0.45
              }
            }
          }
        }
      }
    }
    Timer {interval:600;running:true;onTriggered:{Color.popups.background="#171b1b";Color.popups.text="#ced2ce";Color.foreground="#ced2ce";Color.accent="#88a8d8";Color.urgent="#e08a8a";capture.start()}}
    Timer {id:capture;interval:150;onTriggered:surface.grabToImage(function(result){result.saveToFile(Quickshell.env("TRAIN_PREVIEW_DIR")+"/bar-states.png");console.log("PREVIEW COMPLETE");Qt.quit()})}
  }
}
