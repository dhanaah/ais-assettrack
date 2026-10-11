// HMAC-SHA256 (pure JS, ASCII text) - signs return slips printed by a customer HHT without network, so the AIS gate can
// trust the QR before the slip reaches the server. Same result as Python hmac.new(key, body, sha256). Developed by DT
const K = [0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
  0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
  0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
  0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2];

function sha256(bytes) {
  const l = bytes.length; const withPad = ((l + 9 + 63) >> 6) << 6; const m = new Uint8Array(withPad);
  m.set(bytes); m[l] = 0x80; const bits = l * 8;
  m[withPad - 4] = (bits >>> 24) & 255; m[withPad - 3] = (bits >>> 16) & 255; m[withPad - 2] = (bits >>> 8) & 255; m[withPad - 1] = bits & 255;
  m[withPad - 5] = Math.floor(bits / 2 ** 32) & 255;
  let h = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
  const w = new Array(64);
  for (let i = 0; i < withPad; i += 64) {
    for (let t = 0; t < 16; t++) w[t] = (m[i + 4 * t] << 24) | (m[i + 4 * t + 1] << 16) | (m[i + 4 * t + 2] << 8) | m[i + 4 * t + 3];
    for (let t = 16; t < 64; t++) {
      const a = w[t - 15], b = w[t - 2];
      const s0 = ((a >>> 7) | (a << 25)) ^ ((a >>> 18) | (a << 14)) ^ (a >>> 3); const s1 = ((b >>> 17) | (b << 15)) ^ ((b >>> 19) | (b << 13)) ^ (b >>> 10);
      w[t] = (w[t - 16] + s0 + w[t - 7] + s1) | 0;
    }
    let [a, b, c, d, e, f, g, hh] = h;
    for (let t = 0; t < 64; t++) {
      const S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7)); const ch = (e & f) ^ (~e & g);
      const t1 = (hh + S1 + ch + K[t] + w[t]) | 0;
      const S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10)); const mj = (a & b) ^ (a & c) ^ (b & c);
      const t2 = (S0 + mj) | 0;
      hh = g; g = f; f = e; e = (d + t1) | 0; d = c; c = b; b = a; a = (t1 + t2) | 0;
    }
    h = [h[0] + a, h[1] + b, h[2] + c, h[3] + d, h[4] + e, h[5] + f, h[6] + g, h[7] + hh].map((x) => x | 0);
  }
  const out = new Uint8Array(32); h.forEach((x, i) => { out[4 * i] = (x >>> 24) & 255; out[4 * i + 1] = (x >>> 16) & 255; out[4 * i + 2] = (x >>> 8) & 255; out[4 * i + 3] = x & 255; });
  return out;
}
const ascii = (s) => Uint8Array.from(String(s), (c) => c.charCodeAt(0) & 0xff);
const hex = (u8) => Array.from(u8, (b) => b.toString(16).padStart(2, '0')).join('');

export function hmacSha256Hex(key, msg) {
  let k = ascii(key); if (k.length > 64) k = sha256(k);
  const kp = new Uint8Array(64); kp.set(k);
  const ipad = kp.map((b) => b ^ 0x36), opad = kp.map((b) => b ^ 0x5c);
  const m = ascii(msg); const inner = new Uint8Array(64 + m.length); inner.set(ipad); inner.set(m, 64);
  const ih = sha256(inner); const outer = new Uint8Array(96); outer.set(opad); outer.set(ih, 64);
  return hex(sha256(outer));
}
export const sha256Hex = (s) => hex(sha256(ascii(s)));
