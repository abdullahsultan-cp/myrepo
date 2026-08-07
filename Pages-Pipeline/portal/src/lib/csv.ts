/** Download whatever is on screen as a row-per-item CSV, so a filtered view can be
 *  checked in Excel rather than only in the browser. */
const cell = (v: unknown) => {
  const s = v == null ? '' : String(v)
  return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s
}

export function downloadCsv(name: string, headers: string[], rows: unknown[][]) {
  const body = [headers, ...rows].map(r => r.map(cell).join(',')).join('\r\n')
  // BOM, or Excel opens the accented names in the corpus as mojibake
  const blob = new Blob(['﻿' + body], { type: 'text/csv;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 1000)
}
