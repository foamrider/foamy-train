// Inline settings schema for foamy.train (mirrors manifest.json barWidget.schema).
// Validation and saving live in kit/FoamyPrefs.js. The ordered station pair
// (`route`) is an object and is validated by Model.route() instead.
var schedulePattern = "^$|^(?:[01][0-9]|2[0-3]):[0-5][0-9]-(?:(?:[01][0-9]|2[0-3]):[0-5][0-9]|24:00)$"
var dayKeys = ["scheduleMonday", "scheduleTuesday", "scheduleWednesday", "scheduleThursday", "scheduleFriday", "scheduleSaturday", "scheduleSunday"]
var dayLabels = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

var fields = [
  { key: "lookAheadHours", type: "integer", defaultValue: 24, min: 1, max: 24, step: 1 },
  { key: "showBarMinutes", type: "boolean", defaultValue: true },
  { key: "refreshSeconds", type: "integer", defaultValue: 60, min: 30, max: 900, step: 30 },
  { key: "scheduleEnabled", type: "boolean", defaultValue: false },
  { key: "scheduleOutsideMode", type: "enum", options: ["mute", "hide"], defaultValue: "mute" }
].concat(dayKeys.map(function(key) {
  return { key: key, type: "string", defaultValue: "", maxLength: 11, pattern: schedulePattern }
}))

// Dropdown choices. A value saved outside these (from the CLI) is listed too.
var refreshChoices = [30, 60, 120, 300, 600, 900]
var hourChoices = [1, 2, 3, 4, 6, 8, 12, 24]

if (typeof module !== "undefined") module.exports = { fields: fields, dayKeys: dayKeys, dayLabels: dayLabels, refreshChoices: refreshChoices, hourChoices: hourChoices, schedulePattern: schedulePattern }
