// tesla.control — decoding and formatting helpers for the Tesla status cache.

const ICON = {
  car: String.fromCharCode(0xf1b9),        // nf-fa-car
  bolt: String.fromCharCode(0xf0c34),      // nf-md-lightning
  lock: String.fromCharCode(0xf023),       // nf-fa-lock
  unlock: String.fromCharCode(0xf13e),     // nf-fa-lock_open
  battery: [0xf244, 0xf243, 0xf242, 0xf241, 0xf240]  // empty→full
    .map(function(c) { return String.fromCharCode(c) }),
  sun: String.fromCharCode(0xf185),        // nf-fa-sun
  snow: String.fromCharCode(0xf2dc),       // nf-fa-snowflake
  thermo: String.fromCharCode(0xf2c9),     // nf-fa-thermo_half
  power: String.fromCharCode(0xf014d),     // nf-md-power
  plug: String.fromCharCode(0xf1e6),       // nf-fa-plug
  bolt2: String.fromCharCode(0xf0e7),      // nf-fa-bolt
  horn: String.fromCharCode(0xf0a1),       // nf-fa-bullhorn
  winClose: String.fromCharCode(0xf2d2),   // nf-fa-window_restore
  winVent: String.fromCharCode(0xf2d0),    // nf-fa-window_maximize
  arrowUp: String.fromCharCode(0xf01ad),   // nf-md-arrow_up
  arrowDown: String.fromCharCode(0xf0243), // nf-md-arrow_down
  shield: String.fromCharCode(0xf132),     // nf-fa-shield
  key: String.fromCharCode(0xf084),        // nf-fa-key
  plus: String.fromCharCode(0xf067),       // nf-fa-plus
  minus: String.fromCharCode(0xf068),      // nf-fa-minus
  check: String.fromCharCode(0xf00c),      // nf-fa-check
  xmark: String.fromCharCode(0xf00d)       // nf-fa-times
}

function parseStatus(raw) {
  try {
    var data = JSON.parse(String(raw || ""))
    if (!data || data.ok !== true) return null
    return data
  } catch (e) {
    return null
  }
}

function compiled(v) {
  return v && v.ok && v.vehicle ? v.vehicle : null
}

function units(v) {
  var c = compiled(v)
  return c ? String(c.temp_units || "C").toUpperCase() : "C"
}

function batteryIcon(soc) {
  var n = parseFloat(String(soc))
  if (isNaN(n)) return ICON.battery[2]
  if (n <= 12) return ICON.battery[0]
  if (n <= 25) return ICON.battery[1]
  if (n <= 50) return ICON.battery[2]
  if (n <= 75) return ICON.battery[3]
  return ICON.battery[4]
}

function chargeLimit(v) {
  var c = compiled(v)
  if (!c || c.charge_limit_soc === undefined || c.charge_limit_soc === null) return 80
  return Math.round(Number(c.charge_limit_soc))
}

function isCharging(v) {
  var c = compiled(v)
  return !!(c && String(c.charging_state || "").toLowerCase() === "charging")
}

function barLabel(v) {
  if (!v || !v.ok) return ""
  var c = v.vehicle
  var pct = c.battery_level === undefined || c.battery_level === null ? "--" : String(Math.round(Number(c.battery_level)))
  var label = batteryIcon(c.battery_level) + " " + pct + "%"
  if (isCharging(v)) label += " " + ICON.bolt
  return label
}

function pctText(v) {
  var c = compiled(v)
  if (!c || c.battery_level === undefined || c.battery_level === null) return "--"
  return Math.round(Number(c.battery_level)) + "%"
}

function chargingText(v) {
  var c = compiled(v)
  if (!c || !c.charging_state) return "Offline"
  var s = String(c.charging_state)
  if (s === "Charging") return "Charging"
  if (s === "Complete") return "Charged"
  if (s === "Disconnected") return "Not plugged in"
  if (s === "Stopped") return "Charge stopped"
  return s
}

function rangeUnits(v) {
  var c = compiled(v)
  if (c && String(c.range_units || "").toLowerCase() === "km") return "km"
  if (c && String(c.range_units || "").toLowerCase() === "mi") return "mi"
  return speedUnits(v) === "km" ? "km" : "mi"
}

function speedUnits(v) {
  var c = compiled(v)
  return c && String(c.speed_units || "").indexOf("km") !== -1 ? "km" : "mi"
}

function rangeText(v) {
  var c = compiled(v)
  if (!c) return ""
  var mi = c.battery_range_miles
  if (mi === undefined || mi === null) return ""
  var unit = rangeUnits(v)
  var val = unit === "km" ? Number(mi) * 1.60934 : Number(mi)
  return Math.round(val) + " " + unit
}

function tempDisplay(celsius, unit) {
  if (celsius === undefined || celsius === null) return "--"
  var c = Number(celsius)
  if (unit === "F") return Math.round(c * 9 / 5 + 32) + "°F"
  return Math.round(c * 2) / 2 + "°C"
}

function insideTemp(v) {
  var c = compiled(v)
  if (!c) return "--"
  return tempDisplay(c.inside_temp_c, units(v))
}

function outsideTemp(v) {
  var c = compiled(v)
  if (!c) return "--"
  return tempDisplay(c.outside_temp_c, units(v))
}

function targetTemp(v) {
  var c = compiled(v)
  if (!c) return 21
  var t = c.driver_temp_setting_c
  return (t === undefined || t === null) ? 21 : Number(t)
}

function climateIcon(v) {
  var c = compiled(v)
  if (!c) return ICON.thermo
  if (!c.is_climate_on) return ICON.snow
  var inT = Number(c.inside_temp_c)
  var outT = Number(c.outside_temp_c)
  if (isNaN(inT) || isNaN(outT)) return ICON.snow
  return outT > inT ? ICON.snow : ICON.sun
}

function isLocked(v) {
  var c = compiled(v)
  return !!(c && c.locked)
}

function isSentry(v) {
  var c = compiled(v)
  return !!(c && c.sentry_mode)
}

function isChargePortOpen(v) {
  var c = compiled(v)
  return !!(c && c.charge_port_open)
}

function windowsOpen(v) {
  var c = compiled(v)
  return !!(c && c.windows_open)
}

function roundedMiles(v) {
  var c = compiled(v)
  if (!c || c.odometer_miles === undefined || c.odometer_miles === null) return ""
  var unit = speedUnits(v)
  var val = unit === "km" ? Number(c.odometer_miles) * 1.60934 : Number(c.odometer_miles)
  return Math.round(val).toLocaleString() + " " + unit
}

function fmtActionResult(ok, detail) {
  var d = String(detail || "").trim()
  if (ok) return "Command sent"
  return d || "Command failed"
}

function vinYear(code) {
  var l = String(code || "").toUpperCase()
  var idx = "ABCDEFGHJKLMNPRSTVWXY".indexOf(l)
  if (idx !== -1) {
    var y = 1980 + idx
    return y < 2000 ? y + 30 : y
  }
  idx = "123456789".indexOf(l)
  if (idx !== -1) return 2001 + idx
  return null
}

function vinInfo(v) {
  var c = compiled(v)
  if (!c || !c.vin) return ""
  var vin = String(c.vin).toUpperCase()
  var make = /^(7SA|5YJ|SFY|LRW|XP7)/.test(vin) ? "Tesla" : ""
  var model = ""
  if (/^(7SAY|5YJY)/.test(vin)) model = "Model Y"
  else if (/^(5YJ3|LRW3|SFY3)/.test(vin)) model = "Model 3"
  else if (/^5YJSA/.test(vin)) model = "Model S"
  else if (/^5YJXC/.test(vin)) model = "Model X"
  else if (/^SFY/.test(vin)) model = "Model Y"
  else if (/^LRW/.test(vin)) model = "Model 3"
  var year = vinYear(vin.charAt(9))
  var parts = []
  if (year) parts.push(year)
  if (make) parts.push(make)
  if (model) parts.push(model)
  return parts.join(" ")
}

if (typeof module !== "undefined") {
  module.exports = {
    ICON: ICON,
    parseStatus: parseStatus,
    compiled: compiled,
    units: units,
    batteryIcon: batteryIcon,
    isCharging: isCharging,
    chargeLimit: chargeLimit,
    barLabel: barLabel,
    pctText: pctText,
    chargingText: chargingText,
    rangeText: rangeText,
    rangeUnits: rangeUnits,
    speedUnits: speedUnits,
    tempDisplay: tempDisplay,
    insideTemp: insideTemp,
    outsideTemp: outsideTemp,
    targetTemp: targetTemp,
    climateIcon: climateIcon,
    isLocked: isLocked,
    isSentry: isSentry,
    isChargePortOpen: isChargePortOpen,
    windowsOpen: windowsOpen,
    roundedMiles: roundedMiles,
    vinInfo: vinInfo,
    fmtActionResult: fmtActionResult
  }
}