// Dates for display: dd-mmm-yy (e.g. 09-Oct-26) and local time - server UTC timestamps without a zone are read as UTC.
// Developed by DT
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const p2 = (n) => String(n).padStart(2, '0');
function toDate(v) {
  if (!v) return null;
  if (v instanceof Date) return v;
  let s = String(v).trim();
  if (/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(s)) s = s.replace(' ', 'T') + 'Z';
  const d = new Date(s);
  return isNaN(d) ? null : d;
}
export const fDate = (v) => { const d = toDate(v); return d ? `${p2(d.getDate())}-${MON[d.getMonth()]}-${String(d.getFullYear()).slice(2)}` : ''; };
export const fTime = (v) => { const d = toDate(v); return d ? `${p2(d.getHours())}:${p2(d.getMinutes())}` : ''; };
export const fTimeS = (v) => { const d = toDate(v); return d ? `${p2(d.getHours())}:${p2(d.getMinutes())}:${p2(d.getSeconds())}` : ''; };
export const fDT = (v) => { const d = toDate(v); return d ? `${fDate(d)} ${fTime(d)}` : ''; };
