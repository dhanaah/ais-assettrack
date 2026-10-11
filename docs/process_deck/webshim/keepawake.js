// screenshot build only. Also: RN-style FormData file parts ({uri,name,type}) -> Blob on web
if (typeof window !== 'undefined' && !window.__fdPatched) {
  window.__fdPatched = true;
  const orig = FormData.prototype.append;
  FormData.prototype.append = function (k, v, n) {
    if (v && typeof v === 'object' && v.uri && !(v instanceof Blob)) {
      const x = new XMLHttpRequest(); x.open('GET', v.uri, false); x.overrideMimeType('text/plain; charset=x-user-defined'); x.send();
      const s = x.responseText; const u = new Uint8Array(s.length); for (let i = 0; i < s.length; i++) u[i] = s.charCodeAt(i) & 0xff;
      return orig.call(this, k, new Blob([u], { type: v.type || 'image/jpeg' }), v.name || 'file.jpg');
    }
    return n === undefined ? orig.call(this, k, v) : orig.call(this, k, v, n);
  };
}
export const useKeepAwake = () => {}; export const activateKeepAwakeAsync = async () => {}; export const deactivateKeepAwake = () => {};
