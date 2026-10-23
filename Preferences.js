// All user settings, including the ordered station pair, belong to the shell.json widget entry.
var fields = [
  {
    "key": "lookAheadHours",
    "type": "integer",
    "label": "Next (hours)",
    "defaultValue": 24,
    "min": 1,
    "max": 24,
    "step": 1
  },
  {
    "key": "showBarMinutes",
    "type": "boolean",
    "label": "Show minutes in bar",
    "defaultValue": true
  },
  {
    "key": "refreshSeconds",
    "type": "integer",
    "label": "Refresh interval (seconds)",
    "defaultValue": 60,
    "min": 30,
    "max": 900,
    "step": 30
  },
  {
    "key": "scheduleEnabled",
    "type": "boolean",
    "label": "Use a weekly schedule",
    "defaultValue": false
  },
  {
    "key": "scheduleOutsideMode",
    "type": "enum",
    "label": "Outside the schedule",
    "defaultValue": "mute",
    "options": [
      "mute",
      "hide"
    ]
  },
  {
    "key": "scheduleMonday",
    "type": "string",
    "label": "Monday",
    "defaultValue": ""
  },
  {
    "key": "scheduleTuesday",
    "type": "string",
    "label": "Tuesday",
    "defaultValue": ""
  },
  {
    "key": "scheduleWednesday",
    "type": "string",
    "label": "Wednesday",
    "defaultValue": ""
  },
  {
    "key": "scheduleThursday",
    "type": "string",
    "label": "Thursday",
    "defaultValue": ""
  },
  {
    "key": "scheduleFriday",
    "type": "string",
    "label": "Friday",
    "defaultValue": ""
  },
  {
    "key": "scheduleSaturday",
    "type": "string",
    "label": "Saturday",
    "defaultValue": ""
  },
  {
    "key": "scheduleSunday",
    "type": "string",
    "label": "Sunday",
    "defaultValue": ""
  }
]

function field(key) {
  for (var i=0;i<fields.length;i++) if (fields[i].key === key) return fields[i]
  return null
}
function valid(key,value) {
  var f=field(key)
  if (!f) return false
  if (f.type === "boolean") return typeof value === "boolean"
  if (f.type === "enum") return f.options.indexOf(value) >= 0
  if (f.type === "string") return typeof value === "string" && (value === "" || /^(?:[01][0-9]|2[0-3]):[0-5][0-9]-(?:(?:[01][0-9]|2[0-3]):[0-5][0-9]|24:00)$/.test(value))
  return typeof value === "number" && isFinite(value) && Math.floor(value) === value && value >= f.min && value <= f.max
}
function value(settings,key) { var f=field(key); return f ? settings && valid(key,settings[key]) ? settings[key] : f.defaultValue : undefined }

function optionLabel(value) { return {mute:"Dim",hide:"Hide"}[value] || value }
if(typeof module!=="undefined")module.exports={fields:fields,field:field,valid:valid,value:value,optionLabel:optionLabel}

function updatedText(updatedAt, now, tr) {
  tr = tr || function(text) { return text }
  if (!updatedAt) return ""
  var minutes = Math.max(0, Math.floor((now - updatedAt) / 60))
  return tr(minutes === 0 ? "Updated just now" : minutes === 1 ? "Updated 1 minute ago" : "Updated %1 minutes ago").replace("%1", minutes)
}
