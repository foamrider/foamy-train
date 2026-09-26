// All user settings, including the ordered station pair, belong to the shell.json widget entry.
var fields = [
  {
    "key": "language",
    "type": "enum",
    "label": "Language",
    "defaultValue": "system",
    "options": [
      "system",
      "en",
      "nb"
    ]
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
var norwegian = {
  "Select both stations from search results.": "Velg begge stasjonene fra søkeresultatene.",
  "Invalid station name.": "Ugyldig stasjonsnavn.",
  "Invalid route or unavailable local cache. Select the stations again.": "Ugyldig strekning eller utilgjengelig hurtigbuffer. Velg stasjonene på nytt.",
  "Show minutes in bar":"Vis minutter i linjen",
  "Dim":"Ton ned", "Hide":"Skjul",
  "Updated just now":"Oppdatert nå", "Updated 1 minute ago":"Oppdatert for 1 minutt siden",
  "Updated %1 minutes ago":"Oppdatert for %1 minutter siden",
  "Last known to":"Sist kjent til",
  "All upcoming trains are cancelled.":"Alle kommende tog er innstilt.",
  "Trains": "Tog",
  "Next to": "Neste til",
  "Platform": "Spor",
  "Arrival": "Ankomst",
  "Journey": "Reisetid",
  "Following departures": "Neste avganger",
  "Other departures": "Andre avganger",
  "Route notices": "Meldinger om strekningen",
  "On time": "I rute",
  "Scheduled": "Rutetid",
  "Cancelled": "Innstilt",
  "min late": "min forsinket",
  "Last known departures": "Sist kjente avganger",
  "Updated": "Oppdatert",
  "Refresh": "Oppdater",
  "Refreshing…": "Oppdaterer…",
  "Settings": "Innstillinger",
  "Back": "Tilbake",
  "Switch direction": "Bytt retning",
  "Choose your stations": "Velg stasjoner",
  "Choose two stations to see direct trains.": "Velg to stasjoner for å se direkte tog.",
  "Choose stations": "Velg stasjoner",
  "Loading departures…": "Henter avganger…",
  "No direct trains found.": "Fant ingen direkte tog.",
  "No departures available.": "Ingen avganger tilgjengelig.",
  "Outside your schedule": "Utenfor tidsplanen",
  "Refresh to check departures now.": "Oppdater for å sjekke avganger nå.",
  "Offline": "Frakoblet",
  "Cached times; live predictions unavailable.": "Lagrede tider; sanntid er utilgjengelig.",
  "Language": "Språk",
  "System": "System",
  "From": "Fra",
  "To": "Til",
  "Search stations…": "Søk etter stasjoner…",
  "Searching…": "Søker…",
  "No stations found.": "Fant ingen stasjoner.",
  "Select a station from the results.": "Velg en stasjon fra resultatene.",
  "Apply route": "Bruk strekning",
  "Swap stations": "Bytt stasjoner",
  "Saving…": "Lagrer…",
  "Refresh interval (seconds)": "Oppdateringsintervall (sekunder)",
  "Use a weekly schedule": "Bruk ukentlig tidsplan",
  "Outside the schedule": "Utenfor tidsplanen",
  "Dim the widget": "Ton ned modulen",
  "Hide the widget": "Skjul modulen",
  "Monday": "Mandag",
  "Tuesday": "Tirsdag",
  "Wednesday": "Onsdag",
  "Thursday": "Torsdag",
  "Friday": "Fredag",
  "Saturday": "Lørdag",
  "Sunday": "Søndag",
  "Off": "Av",
  "Local time. Leave a day empty for off. Overnight ranges are supported.": "Lokal tid. Tomt felt betyr av. Tidsrom over midnatt støttes.",
  "Invalid setting.": "Ugyldig innstilling.",
  "Could not save settings.": "Kunne ikke lagre innstillingene.",
  "Cannot reach Entur. Check your connection and try Refresh.": "Kan ikke nå Entur. Sjekk nettverket og prøv Oppdater.",
  "Offline. Showing the last available update.": "Frakoblet. Viser siste tilgjengelige oppdatering.",
  "Entur is unavailable. Try Refresh.": "Entur er utilgjengelig. Prøv Oppdater.",
  "Entur returned an invalid response. Try Refresh.": "Entur returnerte et ugyldig svar. Prøv Oppdater.",
  "Could not save the local cache.": "Kunne ikke lagre hurtigbufferen.",
  "Route settings are invalid. Select the stations again.": "Ugyldige stasjonsinnstillinger. Velg stasjonene på nytt.",
  "Saved direction is invalid. Select the stations again.": "Lagret retning er ugyldig. Bruk strekningen på nytt.",
  "Cannot read or save local train settings. Select the stations again.": "Kan ikke lese eller lagre toginnstillinger. Bruk strekningen på nytt.",
  "Choose two different stations.": "Velg to forskjellige stasjoner.",
  "Train request failed. Try Refresh.": "Togforespørselen mislyktes. Prøv Oppdater.",
  "Invalid train response.": "Ugyldig togsvar.",
  "Direct trains only · Times in Norway": "Kun direkte tog · Norske klokkeslett",
  "Station search failed. Try again.": "Stasjonssøket mislyktes. Prøv igjen.",
  "Station search returned an invalid response.": "Stasjonssøket returnerte et ugyldig svar.",
  "Entur could not find departures. Try Refresh.": "Entur fant ikke avganger. Prøv Oppdater."
}
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
function language(mode,locale) { return mode === "en" || mode === "nb" ? mode : /^(nb|nn|no)(_|-|$)/i.test(locale || "") ? "nb" : "en" }
function text(label,lang) { return lang === "nb" ? norwegian[label] || label : label }
function optionLabel(value) { return {system:"System",en:"English",nb:"Norsk bokmål",mute:"Dim",hide:"Hide"}[value] || value }
if(typeof module!=="undefined")module.exports={fields:fields,field:field,valid:valid,value:value,language:language,text:text,optionLabel:optionLabel}

function updatedText(updatedAt, now, lang) {
  if (!updatedAt) return ""
  var minutes = Math.max(0, Math.floor((now - updatedAt) / 60))
  return text(minutes === 0 ? "Updated just now" : minutes === 1 ? "Updated 1 minute ago" : "Updated %1 minutes ago", lang).replace("%1", minutes)
}
