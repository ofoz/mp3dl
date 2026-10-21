/* 浏览器端 ID3v2.3 写入器
 *
 * 用途：MP3 直连下载时，音频字节直接从音源 CDN 进用户浏览器，
 * 服务器只下发歌名/歌手/封面/歌词这些文本，由页面在本地拼出 ID3 头，
 * 这样既省掉服务器带宽，又能保住完整标签和自定义文件名。
 *
 * 只做「在文件头插入标签」，不重新编码任何音频帧，音质与源文件完全一致。
 */
(function (global) {
  'use strict';

  const ID3_HEADER = 10;

  function concat(parts) {
    let len = 0;
    for (let i = 0; i < parts.length; i++) len += parts[i].length;
    const out = new Uint8Array(len);
    let off = 0;
    for (let i = 0; i < parts.length; i++) {
      out.set(parts[i], off);
      off += parts[i].length;
    }
    return out;
  }

  /* v2.3 的帧长度是普通大端 32 位 */
  function be32(n) {
    return new Uint8Array([(n >>> 24) & 0xff, (n >>> 16) & 0xff, (n >>> 8) & 0xff, n & 0xff]);
  }

  /* 标签总长度用 syncsafe（每字节只用低 7 位） */
  function syncsafe(n) {
    return new Uint8Array([
      (n >>> 21) & 0x7f, (n >>> 14) & 0x7f, (n >>> 7) & 0x7f, n & 0x7f,
    ]);
  }

  /* 编码字节 1 = UTF-16 + BOM，兼容性最好 */
  function utf16le(str) {
    const s = String(str == null ? '' : str);
    const out = new Uint8Array(2 + s.length * 2);
    out[0] = 0xff;
    out[1] = 0xfe;
    for (let i = 0; i < s.length; i++) {
      const code = s.charCodeAt(i);
      out[2 + i * 2] = code & 0xff;
      out[3 + i * 2] = (code >>> 8) & 0xff;
    }
    return out;
  }

  function latin1(str) {
    const s = String(str == null ? '' : str);
    const out = new Uint8Array(s.length);
    for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i) & 0xff;
    return out;
  }

  function frame(id, body) {
    if (!body || !body.length) return new Uint8Array(0);
    return concat([latin1(id), be32(body.length), new Uint8Array([0, 0]), body]);
  }

  function textFrame(id, text) {
    if (!text) return new Uint8Array(0);
    return frame(id, concat([new Uint8Array([1]), utf16le(text)]));
  }

  function usltFrame(lyric) {
    if (!lyric) return new Uint8Array(0);
    return frame('USLT', concat([
      new Uint8Array([1]),          // encoding: UTF-16
      latin1('chi'),                // language
      new Uint8Array([0, 0]),       // content descriptor：空串 + 终止符
      utf16le(lyric),
    ]));
  }

  function apicFrame(cover, mime) {
    if (!cover || !cover.length) return new Uint8Array(0);
    return frame('APIC', concat([
      new Uint8Array([1]),                  // encoding: UTF-16
      latin1(mime || 'image/jpeg'),
      new Uint8Array([0]),                  // MIME 终止符
      new Uint8Array([3]),                  // 图片类型：3 = 封面正面
      new Uint8Array([0, 0]),               // 描述：空串 + 终止符
      cover,
    ]));
  }

  function sniffMime(bytes) {
    if (bytes.length > 8 && bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e && bytes[3] === 0x47) {
      return 'image/png';
    }
    return 'image/jpeg';
  }

  /* 剥掉文件里已有的 ID3v2 / ID3v1，避免出现双标签 */
  function stripId3(input) {
    const u8 = input instanceof Uint8Array ? input : new Uint8Array(input);
    let start = 0;
    while (u8.length - start >= ID3_HEADER &&
           u8[start] === 0x49 && u8[start + 1] === 0x44 && u8[start + 2] === 0x33) {
      const ver = u8[start + 3];
      const flags = u8[start + 5];
      const size = (u8[start + 6] & 0x7f) * 0x200000 +
                   (u8[start + 7] & 0x7f) * 0x4000 +
                   (u8[start + 8] & 0x7f) * 0x80 +
                   (u8[start + 9] & 0x7f);
      let total = ID3_HEADER + size;
      if (ver === 4 && (flags & 0x10)) total += ID3_HEADER;   // v2.4 footer
      if (size <= 0 || total > u8.length - start) break;
      start += total;
    }
    let end = u8.length;
    // 结尾 ID3v1：128 字节 "TAG"
    if (end - start >= 128 &&
        u8[end - 128] === 0x54 && u8[end - 127] === 0x41 && u8[end - 126] === 0x47) {
      end -= 128;
    }
    if (start === 0 && end === u8.length) return u8;
    return u8.subarray(start, end);
  }

  function buildTag(tags, cover, mime) {
    const t = tags || {};
    const frames = [
      textFrame('TIT2', t.title),
      textFrame('TPE1', t.artist),
      textFrame('TALB', t.album),
      apicFrame(cover, mime),
      usltFrame(t.lyric),
    ].filter(function (f) { return f.length > 0; });
    if (!frames.length) return new Uint8Array(0);
    const body = concat(frames);
    return concat([
      latin1('ID3'),
      new Uint8Array([3, 0, 0]),      // v2.3.0，无 flag
      syncsafe(body.length),
      body,
    ]);
  }

  /* 音频字节 + 标签 -> 完整文件字节 */
  function attach(audio, tags, cover, mime) {
    const clean = stripId3(audio);
    const tag = buildTag(tags, cover, mime ? mime : sniffMime(cover || new Uint8Array(0)));
    return tag.length ? concat([tag, clean]) : clean;
  }

  global.MP3ID3 = { attach: attach, stripId3: stripId3, buildTag: buildTag, sniffMime: sniffMime };
})(window);
