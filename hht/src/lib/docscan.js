// Photo of the customer's manual return document (Option B at the IN gate): resize, read the text on the HHT itself
// (Google ML Kit, offline), then the server matches the pallet numbers with the ledger (and, when IT enables it, an AI
// reading of the photo for handwriting / unusual layouts). Without the server the text is kept and matched at sync.
// Pending photo uploads are kept and retried. Developed by DT
import * as ImageManipulator from 'expo-image-manipulator';
import { apiUpload } from './api';
import { kv } from './db';

let OCR = null;
try { OCR = require('@react-native-ml-kit/text-recognition').default; } catch (e) { OCR = null; }
export const ocrAvailable = () => !!OCR;

/** -> { uri (resized jpeg), text } */
export async function readPhoto(uri) {
  const small = await ImageManipulator.manipulateAsync(uri, [{ resize: { width: 1600 } }], { compress: 0.7, format: ImageManipulator.SaveFormat.JPEG });
  let text = '';
  if (OCR) { try { const r = await OCR.recognize(small.uri); text = (r?.blocks || []).map((b) => b.lines.map((l) => l.text).join('\n')).join('\n') || r?.text || ''; } catch (e) { text = ''; } }
  return { uri: small.uri, text };
}

/** Server matching of one page (photo + its text). Throws {offline} when the server is not reachable. */
export async function matchPage(customer_code, page) {
  return apiUpload('/slips/doc-read', { customer_code, device_text: page.text || '' }, { uri: page.uri, name: 'page.jpg', type: 'image/jpeg' });
}

/** Several pages -> one result (each pallet once). */
export function mergeResults(list) {
  const seen = new Set(); const out = { matched: [], probable: [], other: [], unread: [], read: 0, stated_total: null, ai: false, ai_enabled: false };
  for (const r of list) {
    if (!r) continue;
    for (const k of ['matched', 'probable', 'other']) for (const x of r[k] || []) if (!seen.has(x.pallet_no)) { seen.add(x.pallet_no); out[k].push(x); }
    for (const u of r.unread || []) if (!out.unread.includes(u)) out.unread.push(u);
    out.stated_total = Math.max(out.stated_total || 0, r.stated_total || 0) || null; out.ai = out.ai || !!r.ai; out.ai_enabled = out.ai_enabled || !!r.ai_enabled;
  }
  out.read = out.matched.length + out.probable.length + out.other.length + out.unread.length;
  return out;
}

// ---------------------------------------------------------------- photos kept with the slip on the server
export async function queuePhotos(slip_no, uris) {
  const q = (await kv.get('doc_uploads')) || []; uris.forEach((uri) => q.push({ slip_no, uri, tries: 0 })); await kv.set('doc_uploads', q);
  return sendPhotos();
}
export async function sendPhotos() {
  const q = (await kv.get('doc_uploads')) || []; if (!q.length) return 0;
  const left = []; let sent = 0;
  for (const it of q) {
    try { await apiUpload(`/slips/${encodeURIComponent(it.slip_no)}/doc-photo`, {}, { uri: it.uri, name: 'doc.jpg', type: 'image/jpeg' }); sent++; }
    catch (e) { if (e.status === 404 && it.tries < 20) left.push({ ...it, tries: it.tries + 1 }); else if (e.offline || !e.status) left.push({ ...it, tries: (it.tries || 0) + 1 }); else if (it.tries < 3) left.push({ ...it, tries: it.tries + 1 }); }
  }
  await kv.set('doc_uploads', left);
  return sent;
}
