// SHA-256 y SHA-1 en JavaScript puro. El nodo Code de n8n no permite
// require('crypto') salvo que el administrador lo habilite
// (NODE_FUNCTION_ALLOW_BUILTIN), así que no dependemos de él.

function sha256Hex(bytes) {
  const K = new Uint32Array([
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
  ]);
  const H = new Uint32Array([0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]);
  const W = new Uint32Array(64);
  const blocks = padMessage(bytes, false);
  for (let off = 0; off < blocks.length; off += 64) {
    for (let t = 0; t < 16; t++) {
      const j = off + t * 4;
      W[t] = (blocks[j] << 24) | (blocks[j + 1] << 16) | (blocks[j + 2] << 8) | blocks[j + 3];
    }
    for (let t = 16; t < 64; t++) {
      const a = W[t - 15], b = W[t - 2];
      const s0 = ((a >>> 7) | (a << 25)) ^ ((a >>> 18) | (a << 14)) ^ (a >>> 3);
      const s1 = ((b >>> 17) | (b << 15)) ^ ((b >>> 19) | (b << 13)) ^ (b >>> 10);
      W[t] = (W[t - 16] + s0 + W[t - 7] + s1) | 0;
    }
    let a = H[0], b = H[1], c = H[2], d = H[3], e = H[4], f = H[5], g = H[6], h = H[7];
    for (let t = 0; t < 64; t++) {
      const S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7));
      const ch = (e & f) ^ (~e & g);
      const t1 = (h + S1 + ch + K[t] + W[t]) | 0;
      const S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10));
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const t2 = (S0 + maj) | 0;
      h = g; g = f; f = e; e = (d + t1) | 0; d = c; c = b; b = a; a = (t1 + t2) | 0;
    }
    H[0] += a; H[1] += b; H[2] += c; H[3] += d; H[4] += e; H[5] += f; H[6] += g; H[7] += h;
  }
  return wordsHex(H);
}

function sha1Hex(bytes) {
  const H = new Uint32Array([0x67452301, 0xefcdab89, 0x98badcfe, 0x10325476, 0xc3d2e1f0]);
  const W = new Uint32Array(80);
  const blocks = padMessage(bytes, false);
  for (let off = 0; off < blocks.length; off += 64) {
    for (let t = 0; t < 16; t++) {
      const j = off + t * 4;
      W[t] = (blocks[j] << 24) | (blocks[j + 1] << 16) | (blocks[j + 2] << 8) | blocks[j + 3];
    }
    for (let t = 16; t < 80; t++) {
      const x = W[t - 3] ^ W[t - 8] ^ W[t - 14] ^ W[t - 16];
      W[t] = (x << 1) | (x >>> 31);
    }
    let a = H[0], b = H[1], c = H[2], d = H[3], e = H[4];
    for (let t = 0; t < 80; t++) {
      let f, k;
      if (t < 20) { f = (b & c) | (~b & d); k = 0x5a827999; }
      else if (t < 40) { f = b ^ c ^ d; k = 0x6ed9eba1; }
      else if (t < 60) { f = (b & c) | (b & d) | (c & d); k = 0x8f1bbcdc; }
      else { f = b ^ c ^ d; k = 0xca62c1d6; }
      const tmp = (((a << 5) | (a >>> 27)) + f + e + k + W[t]) | 0;
      e = d; d = c; c = (b << 30) | (b >>> 2); b = a; a = tmp;
    }
    H[0] += a; H[1] += b; H[2] += c; H[3] += d; H[4] += e;
  }
  return wordsHex(H);
}

function padMessage(bytes) {
  const len = bytes.length;
  const total = Math.ceil((len + 9) / 64) * 64;
  const out = new Uint8Array(total);
  out.set(bytes);
  out[len] = 0x80;
  // Longitud en bits, big-endian, 64 bits (alcanza con 53 bits de precisión).
  const bits = len * 8;
  const hi = Math.floor(bits / 0x100000000), lo = bits >>> 0;
  out[total - 8] = hi >>> 24; out[total - 7] = (hi >>> 16) & 255; out[total - 6] = (hi >>> 8) & 255; out[total - 5] = hi & 255;
  out[total - 4] = lo >>> 24; out[total - 3] = (lo >>> 16) & 255; out[total - 2] = (lo >>> 8) & 255; out[total - 1] = lo & 255;
  return out;
}

function wordsHex(words) {
  let s = '';
  for (const w of words) s += (w >>> 0).toString(16).padStart(8, '0');
  return s;
}

/** SHA de objeto blob de git: sha1("blob <n>\0" + contenido). Es el que GitHub devuelve al crear el blob. */
function gitBlobSha(bytes) {
  const text = `blob ${bytes.length}\0`; // ASCII: sin TextEncoder (n8n 1.x no lo tiene)
  const head = new Uint8Array(text.length);
  for (let i = 0; i < text.length; i++) head[i] = text.charCodeAt(i);
  const all = new Uint8Array(head.length + bytes.length);
  all.set(head);
  all.set(bytes, head.length);
  return sha1Hex(all);
}

const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';

/** Base64 sin Buffer (el Buffer del nodo Code de n8n 1.x falla con datos creados dentro del nodo). */
function toBase64(bytes) {
  const parts = [];
  let chunk = '';
  for (let i = 0; i < bytes.length; i += 3) {
    const a = bytes[i], b = bytes[i + 1], c = bytes[i + 2];
    const n = (a << 16) | ((b || 0) << 8) | (c || 0);
    chunk += B64[n >> 18] + B64[(n >> 12) & 63] + (i + 1 < bytes.length ? B64[(n >> 6) & 63] : '=') + (i + 2 < bytes.length ? B64[n & 63] : '=');
    if (chunk.length >= 65536) { parts.push(chunk); chunk = ''; }
  }
  parts.push(chunk);
  return parts.join('');
}

// @export
if (typeof module !== 'undefined') module.exports = { sha256Hex, sha1Hex, gitBlobSha, toBase64 };
