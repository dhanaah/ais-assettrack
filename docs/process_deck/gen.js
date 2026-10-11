// AIS AssetTrack - process walkthrough deck. Process slides show each step as a small screen; the arrow on a step
// (or the picture itself) jumps to the full-size picture slide; "Back" returns to the process slide.
const fs = require('fs'), path = require('path');
const pptxgen = require('pptxgenjs');
const React = require('react'); const RDS = require('react-dom/server'); const sharp = require('sharp');
const fa = require('react-icons/fa');
const { applyTheme } = require('/root/.claude/skills/synced/b8bc3863-276a-4a6f-b885-c653ba7813e9_8aaf08c8-bbf0-4fbc-add9-615d5a72c955/pptx/scripts/apply_theme.js');
const SPEC = require('./spec.js');
const DIR = __dirname, IMG = path.join(DIR, 'img'), TH = path.join(DIR, 'th');
const STATIC = '/home/claude/ais-assettrack/server/app/static';

const THEME = { name: 'AIS AssetTrack', headFontFace: 'Calibri', bodyFontFace: 'Calibri',
  colors: { dk1: '1B1F2A', lt1: 'FFFFFF', dk2: '1E2A5A', lt2: 'EEF1F7', accent1: '25358C', accent2: 'D32F2F', accent3: '0F766E',
            accent4: 'B45309', accent5: '15803D', accent6: '6D28D9', hlink: '25358C', folHlink: '6D28D9' } };
const HEX = THEME.colors;

async function icon(Comp, color, size = 256) {
  const svg = RDS.renderToStaticMarkup(React.createElement(Comp, { color: '#' + color, size }));
  const buf = await sharp(Buffer.from(svg)).resize(size, size).png().toBuffer();
  return 'image/png;base64,' + buf.toString('base64');
}
async function circleBtn(kind, fill) {        // round button: play / back / prev / next
  const paths = { play: '<path d="M104 78 L184 128 L104 178 Z" fill="#fff"/>', back: '<path d="M150 70 L88 128 L150 186" stroke="#fff" stroke-width="26" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
    next: '<path d="M106 70 L168 128 L106 186" stroke="#fff" stroke-width="26" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
    map: '<rect x="74" y="80" width="108" height="18" rx="9" fill="#fff"/><rect x="74" y="119" width="108" height="18" rx="9" fill="#fff"/><rect x="74" y="158" width="108" height="18" rx="9" fill="#fff"/>' };
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><circle cx="128" cy="128" r="124" fill="#${fill}"/>${paths[kind]}</svg>`;
  return 'image/png;base64,' + (await sharp(Buffer.from(svg)).png().toBuffer()).toString('base64');
}
const dims = (f) => { const b = fs.readFileSync(f); if (b[0] === 0x89) return { w: b.readUInt32BE(16), h: b.readUInt32BE(20) };
  let i = 2; while (i < b.length) { if (b[i] !== 0xFF) { i++; continue; } const m = b[i + 1]; const len = b.readUInt16BE(i + 2);
    if (m >= 0xC0 && m <= 0xC3) return { h: b.readUInt16BE(i + 5), w: b.readUInt16BE(i + 7) }; i += 2 + len; } throw new Error('size ' + f); };
const fit = (d, bw, bh) => { const r = Math.min(bw / d.w, bh / d.h); return { w: d.w * r, h: d.h * r }; };

(async () => {
  const pres = new pptxgen(); pres.layout = 'LAYOUT_WIDE';
  pres.title = 'AIS AssetTrack - Process walkthrough'; pres.author = 'DT'; pres.company = 'Asahi India Glass Ltd.';
  pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
  const C = pres.SchemeColor;
  const FOOT = 'AIS AssetTrack · process walkthrough';
  pres.defineSlideMaster({ title: 'TITLE_DARK', background: { color: HEX.dk2 }, objects: [] });
  pres.defineSlideMaster({ title: 'CONTENT', background: { color: HEX.lt2 },
    objects: [{ text: { text: FOOT, options: { x: 0.5, y: 7.08, w: 6, h: 0.3, fontSize: 10, color: C.text2, margin: 0 } } }],
    slideNumber: { x: 12.3, y: 7.08, w: 0.6, h: 0.3, fontSize: 10, color: C.text2, align: 'right' } });
  pres.defineSlideMaster({ title: 'PICTURE', background: { color: HEX.lt1 },
    objects: [{ text: { text: FOOT, options: { x: 0.5, y: 7.08, w: 6, h: 0.3, fontSize: 10, color: C.text2, margin: 0 } } }],
    slideNumber: { x: 12.3, y: 7.08, w: 0.6, h: 0.3, fontSize: 10, color: C.text2, align: 'right' } });

  // ---------- slide numbering plan
  // 1 title, 2 how-to + process map, then process slides, then key controls, then picture slides
  let n = 2; const procSlides = [];   // [{proc, part, idx}]
  SPEC.forEach((p) => p.slides.forEach((steps, part) => { n++; procSlides.push({ p, part, steps, no: n }); p.firstNo = p.firstNo || n; }));
  const keyNo = ++n;
  const pics = [];
  procSlides.forEach((ps) => ps.steps.forEach((s, i) => { n++; s.picNo = n; s.parentNo = ps.no; s.proc = ps.p; pics.push(s); }));
  SPEC.forEach((p) => { const all = pics.filter((s) => s.proc === p); all.forEach((s, i) => { s.stepIdx = i + 1; s.stepCount = all.length; s.prev = all[i - 1]; s.next = all[i + 1]; }); });
  for (const s of pics) { if (!fs.existsSync(path.join(IMG, s.img + '.jpg'))) throw new Error('missing ' + s.img); }

  const BTN = { play: await circleBtn('play', HEX.accent2), back: await circleBtn('back', HEX.accent1), next: await circleBtn('next', HEX.accent1),
    prevG: await circleBtn('back', '9AA3B5'), nextG: await circleBtn('next', '9AA3B5'), map: await circleBtn('map', HEX.accent1) };
  const ICON = {}; for (const [k, comp, col] of [['stop', fa.FaHandPaper, 'FFFFFF'], ['qr', fa.FaQrcode, 'FFFFFF'], ['cam', fa.FaCamera, 'FFFFFF'],
    ['door', fa.FaDoorOpen, 'FFFFFF'], ['bal', fa.FaBalanceScale, 'FFFFFF'], ['truck', fa.FaTruck, 'FFFFFF'], ['print', fa.FaPrint, 'FFFFFF'], ['hand', fa.FaHandPointer, HEX.accent1]]) ICON[k] = await icon(comp, col);

  // ---------- 1 title
  pres.addSection({ title: 'Introduction' });
  let s = pres.addSlide({ masterName: 'TITLE_DARK', sectionTitle: 'Introduction' });
  s.addImage({ path: path.join(STATIC, 'wordmark-on-dark.png'), x: 0.8, y: 1.0, w: 4.2, h: 4.2 * 169 / 595, objectName: 'AssetTrack wordmark' });
  s.addText('Process walkthrough', { x: 0.8, y: 2.55, w: 8.6, h: 0.9, fontSize: 44, bold: true, color: C.background1, margin: 0, isTextBox: true, objectName: 'Title' });
  s.addText('Every step with the actual HHT screen, web page and printed output - from dispatch to the pallet coming back home', { x: 0.8, y: 3.5, w: 8.6, h: 1.0, fontSize: 20, color: 'C9D3F0', margin: 0, isTextBox: true, objectName: 'Subtitle' });
  s.addText([{ text: 'Server 1.22 · HHT 2.12', options: { breakLine: true } }, { text: 'Asahi India Glass Ltd. · Developed by DT' }], { x: 0.8, y: 5.9, w: 8, h: 0.8, fontSize: 14, color: 'C9D3F0', margin: 0, isTextBox: true, objectName: 'Version' });
  s.addImage({ path: path.join(TH, 'd04_stop_do_pdi.jpg'), x: 10.0, y: 0.8, h: 5.9, w: 5.9 * 335 / 700, rounding: false, objectName: 'Title screen sample',
    shadow: { type: 'outer', color: '000000', opacity: 0.35, blur: 12, offset: 4, angle: 90 } });
  s.addNotes('Title. The deck walks through every process with real screens captured from the running system with sample data (Hyundai delivery FGCHN2627/13050).');

  // ---------- 2 how to use + map
  s = pres.addSlide({ masterName: 'CONTENT', sectionTitle: 'Introduction' });
  s.addText('Process map', { x: 0.5, y: 0.35, w: 9, h: 0.7, fontSize: 34, bold: true, color: C.text2, margin: 0, isTextBox: true, objectName: 'Title' });
  s.addImage({ data: ICON.hand, x: 0.5, y: 1.2, w: 0.38, h: 0.38, objectName: 'Click hint icon' });
  s.addText([{ text: 'In slideshow, click a process to open it. On a step, click ' }, { text: '▶', options: { color: C.accent2, bold: true } },
    { text: ' (or the small screen) to see the actual picture; click ' }, { text: '◀ Back', options: { color: C.accent1, bold: true } }, { text: ' to return.' }],
    { x: 1.0, y: 1.15, w: 11.5, h: 0.5, fontSize: 16, color: C.text1, margin: 0, isTextBox: true, objectName: 'How to use' });
  const tw = 2.33, th = 2.25, gx = 0.17;
  SPEC.forEach((p, i) => {
    const x = 0.5 + (i % 5) * (tw + gx), y = 1.95 + Math.floor(i / 5) * (th + 0.25);
    const link = { slide: p.firstNo, tooltip: 'Open ' + p.title };
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: tw, h: th, rectRadius: 0.12, fill: { color: C.background1 }, line: { color: 'D5DBE8', width: 0.75 },
      shadow: { type: 'outer', color: '1E2A5A', opacity: 0.12, blur: 6, offset: 2, angle: 90 }, objectName: `Map tile ${i + 1}` });
    s.addText(String(i + 1), { x: x + 0.2, y: y + 0.2, w: 0.5, h: 0.5, shape: pres.shapes.OVAL, fill: { color: C[p.color] }, color: C.background1, bold: true, fontSize: 16, align: 'center', valign: 'middle', margin: 0, objectName: `Map number ${i + 1}` });
    s.addText([{ text: p.title, options: { hyperlink: link, bold: true, fontSize: 15, color: C.text2, breakLine: true } },
      { text: p.who, options: { hyperlink: link, fontSize: 11, color: '5C6478' } }],
      { x: x + 0.2, y: y + 0.85, w: tw - 0.4, h: th - 1.0, valign: 'top', margin: 0, isTextBox: true, objectName: `Map text ${i + 1}` });
    s.addImage({ data: BTN.next, x: x + tw - 0.55, y: y + 0.22, w: 0.36, h: 0.36, hyperlink: link, objectName: `Map open ${i + 1}` });
  });
  s.addNotes('How to use the deck: process slides in order; each step links to its full picture. The pictures are at the end of the file and are reached only by clicking.');

  // ---------- process slides
  for (const ps of procSlides) {
    const p = ps.p; const parts = p.slides.length;
    pres.addSection({ title: p.title }) ;
    s = pres.addSlide({ masterName: 'CONTENT', sectionTitle: p.title });
    s.addText(p.title + (parts > 1 ? ` (${ps.part + 1}/${parts})` : ''), { x: 0.5, y: 0.35, w: 10.4, h: 0.7, fontSize: 32, bold: true, color: C.text2, margin: 0, isTextBox: true, objectName: 'Title' });
    s.addText(p.sub, { x: 0.5, y: 1.05, w: 10.6, h: 0.45, fontSize: 15, color: '4A5266', margin: 0, isTextBox: true, objectName: 'Subtitle' });
    s.addText(p.who, { x: 10.9, y: 0.42, w: 1.95, h: 0.5, shape: pres.shapes.ROUNDED_RECTANGLE, rectRadius: 0.1, fill: { color: C[p.color] }, color: C.background1, fontSize: 11, bold: true, align: 'center', valign: 'middle', margin: 3, objectName: 'Who' });
    s.addImage({ data: BTN.map, x: 12.45, y: 1.08, w: 0.36, h: 0.36, hyperlink: { slide: 2, tooltip: 'Process map' }, objectName: 'Back to map' });
    const k = ps.steps.length, gap = 0.28, cw = (12.33 - gap * (k - 1)) / k, cy = 1.75, ch = 5.15;
    ps.steps.forEach((st, i) => {
      const x = 0.5 + i * (cw + gap); const link = { slide: st.picNo, tooltip: 'Open picture: ' + st.t };
      s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: cy, w: cw, h: ch, rectRadius: 0.1, fill: { color: C.background1 }, line: { color: 'D5DBE8', width: 0.75 },
        shadow: { type: 'outer', color: '1E2A5A', opacity: 0.12, blur: 6, offset: 2, angle: 90 }, objectName: `Step card ${i + 1}` });
      const d = dims(path.join(TH, st.img + '.jpg')); const box = fit(d, cw - 0.3, 3.05);
      s.addImage({ path: path.join(TH, st.img + '.jpg'), x: x + (cw - box.w) / 2, y: cy + 0.15 + (3.05 - box.h) / 2, w: box.w, h: box.h, hyperlink: link, objectName: `Step screen ${i + 1}` });
      s.addText(String(st.stepIdx), { x: x + 0.15, y: cy + 3.38, w: 0.38, h: 0.38, shape: pres.shapes.OVAL, fill: { color: C[p.color] }, color: C.background1, bold: true, fontSize: 13, align: 'center', valign: 'middle', margin: 0, objectName: `Step number ${i + 1}` });
      s.addText(st.t, { x: x + 0.6, y: cy + 3.32, w: cw - 0.7, h: 0.5, fontSize: 13, bold: true, color: C.text2, valign: 'middle', margin: 0, fit: 'shrink', isTextBox: true, objectName: `Step title ${i + 1}` });
      s.addText(st.d, { x: x + 0.15, y: cy + 3.9, w: cw - 0.3, h: 0.72, fontSize: 11, color: '4A5266', valign: 'top', margin: 0, isTextBox: true, objectName: `Step text ${i + 1}` });
      s.addImage({ data: BTN.play, x: x + cw - 0.52, y: cy + ch - 0.5, w: 0.36, h: 0.36, hyperlink: link, objectName: `Open step ${i + 1}` });
      if (i < k - 1) s.addText('›', { x: x + cw - 0.02, y: cy + 1.4, w: gap + 0.04, h: 0.5, fontSize: 24, bold: true, color: C[p.color], align: 'center', margin: 0, isTextBox: true, objectName: `Flow arrow ${i + 1}` });
    });
    s.addNotes(p.notes);
  }

  // ---------- key controls (dark)
  pres.addSection({ title: 'Key controls' });
  s = pres.addSlide({ masterName: 'TITLE_DARK', sectionTitle: 'Key controls' });
  s.addText('Controls built into the flow', { x: 0.6, y: 0.45, w: 11, h: 0.8, fontSize: 36, bold: true, color: C.background1, margin: 0, isTextBox: true, objectName: 'Title' });
  const KC = [['stop', 'STOP - do PDI', 'A part card not on the GCS cannot be loaded', 'load'], ['bal', 'Invoice vs loaded qty', 'Checked at Finish loading', 'load'],
    ['qr', 'Signed QR at the gates', 'Forged or altered QR → HOLD VEHICLE', 'out'], ['door', 'Gate inward register', 'Every inward: slip A, slip B, plant challan', 'gate'],
    ['cam', 'Photo proof for Option B', 'Read, matched, kept for the yard', 'gate'], ['bal', 'Yard count + PIN', 'Differences need the supervisor PIN', 'yard'],
    ['truck', 'Other plants: challan only', 'Received home on the same challan', 'inter'], ['print', 'Printers by job', 'GCS + challan: plant printer · slips: BT', 'load']];
  KC.forEach(([ic, t, d, pid], i) => {
    const x = 0.6 + (i % 4) * 3.07, y = 1.6 + Math.floor(i / 4) * 2.55; const link = { slide: SPEC.find((p) => p.id === pid).firstNo, tooltip: 'Open the process' };
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: 2.85, h: 2.3, rectRadius: 0.12, fill: { color: '2B3A78' }, line: { color: '3B4C93', width: 0.75 }, objectName: `Control card ${i + 1}` });
    s.addShape(pres.shapes.OVAL, { x: x + 0.25, y: y + 0.25, w: 0.7, h: 0.7, fill: { color: C.accent2 }, line: { color: HEX.accent2 }, objectName: `Control icon bg ${i + 1}` });
    s.addImage({ data: ICON[ic], x: x + 0.42, y: y + 0.42, w: 0.36, h: 0.36, objectName: `Control icon ${i + 1}` });
    s.addText([{ text: t, options: { hyperlink: link, bold: true, fontSize: 16, color: 'FFFFFF', breakLine: true } }, { text: d, options: { fontSize: 13, color: 'C9D3F0' } }],
      { x: x + 0.25, y: y + 1.1, w: 2.4, h: 1.1, valign: 'top', margin: 0, isTextBox: true, objectName: `Control text ${i + 1}` });
  });
  s.addNotes('The controls that stop wrong material, wrong vehicles and lost pallets. Click a card title to open its process.');

  // ---------- picture slides
  pres.addSection({ title: 'Pictures (opened from the steps)' });
  for (const st of pics) {
    const p = st.proc;
    s = pres.addSlide({ masterName: 'PICTURE', sectionTitle: 'Pictures (opened from the steps)' });
    const f = path.join(IMG, st.img + '.jpg'); const d = dims(f);
    const label = `${p.title.toUpperCase()} · STEP ${st.stepIdx} OF ${st.stepCount}`;
    let tx, ty, tw2, imgBox;
    if (st.kind === 'L') {
      s.addText(label, { x: 0.5, y: 0.3, w: 9, h: 0.3, fontSize: 11, bold: true, color: C[p.color], margin: 0, charSpacing: 1, isTextBox: true, objectName: 'Label' });
      s.addText(st.t, { x: 0.5, y: 0.62, w: 12.3, h: 0.6, fontSize: 28, bold: true, color: C.text2, margin: 0, isTextBox: true, objectName: 'Title' });
      imgBox = { x: 0.5, y: 1.4, w: 8.7, h: 5.45 }; tx = 9.55; ty = 1.4; tw2 = 3.3;
    } else {
      const bw = st.kind === 'T' ? 4.2 : 3.4;
      imgBox = { x: 0.6, y: 0.4, w: bw, h: 6.55 }; tx = 0.6 + bw + 0.6; ty = 0.9; tw2 = 12.8 - tx;
      s.addText(label, { x: tx, y: 0.5, w: tw2, h: 0.3, fontSize: 11, bold: true, color: C[p.color], margin: 0, charSpacing: 1, isTextBox: true, objectName: 'Label' });
      s.addText(st.t, { x: tx, y: 0.85, w: tw2, h: 0.75, fontSize: 32, bold: true, color: C.text2, margin: 0, isTextBox: true, objectName: 'Title' });
      ty = 1.85;
    }
    const sz = fit(d, imgBox.w, imgBox.h);
    s.addImage({ path: f, x: imgBox.x + (st.kind === 'L' ? 0 : (imgBox.w - sz.w) / 2), y: imgBox.y + (st.kind === 'L' ? 0 : (imgBox.h - sz.h) / 2), w: sz.w, h: sz.h, objectName: 'Picture',
      shadow: { type: 'outer', color: '1E2A5A', opacity: 0.25, blur: 10, offset: 3, angle: 90 } });
    s.addText(st.cap.map((c, i) => ({ text: c, options: { bullet: true, breakLine: i < st.cap.length - 1, paraSpaceAfter: 10 } })),
      { x: tx, y: ty, w: tw2, h: st.kind === 'L' ? 4.3 : 3.9, fontSize: st.kind === 'L' ? 14 : 17, color: C.text1, valign: 'top', margin: 0, isTextBox: true, objectName: 'Explanation' });
    // navigation: back to the process slide, previous / next step
    const ny = 6.25;
    s.addImage({ data: BTN.back, x: tx, y: ny, w: 0.46, h: 0.46, hyperlink: { slide: st.parentNo, tooltip: 'Back to ' + p.title }, objectName: 'Back button' });
    s.addText([{ text: 'Back to steps', options: { hyperlink: { slide: st.parentNo, tooltip: 'Back' }, bold: true, color: C.accent1 } }],
      { x: tx + 0.58, y: ny, w: Math.max(1.5, tw2 - 1.9), h: 0.46, fontSize: 13, valign: 'middle', margin: 0, fit: 'shrink', isTextBox: true, objectName: 'Back link' });
    const ax = tx + tw2 - 1.0;
    s.addImage({ data: st.prev ? BTN.back : BTN.prevG, x: ax, y: ny, w: 0.42, h: 0.42, ...(st.prev ? { hyperlink: { slide: st.prev.picNo, tooltip: 'Previous step' } } : {}), objectName: 'Previous step' });
    s.addImage({ data: st.next ? BTN.next : BTN.nextG, x: ax + 0.55, y: ny, w: 0.42, h: 0.42, ...(st.next ? { hyperlink: { slide: st.next.picNo, tooltip: 'Next step' } } : {}), objectName: 'Next step' });
    s.addNotes(`${p.title} - step ${st.stepIdx}: ${st.t}. ${st.cap.join(' ')}`);
  }
  const out = path.join(DIR, 'AIS_AssetTrack_Process_Walkthrough.pptx');
  await pres.writeFile({ fileName: out });
  await applyTheme(out, THEME);
  console.log('written', out, 'slides', n, 'pictures', pics.length);
})().catch((e) => { console.error(e); process.exit(1); });
