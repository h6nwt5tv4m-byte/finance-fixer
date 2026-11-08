// Minimal OOXML workbook: literal text + finite numeric cells, no formulas/macros/external links.
// ZIP uses stored entries (no compression), UTF-8 filenames and CRC-32.
const encoder = new TextEncoder();
const xml = value => String(value).replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\ufffe\uffff]/gu,'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'}[c]));
const crcTable = Array.from({length:256},(_,n)=>{for(let k=0;k<8;k++) n = n&1 ? 0xedb88320^(n>>>1) : n>>>1;return n>>>0;});
function crc32(bytes) {let c=0xffffffff;for(const b of bytes)c=crcTable[(c^b)&255]^(c>>>8);return (c^0xffffffff)>>>0;}
function header(size) {const bytes=new Uint8Array(size);const view=new DataView(bytes.buffer);return {bytes,u16:(p,v)=>view.setUint16(p,v,true),u32:(p,v)=>view.setUint32(p,v,true)};}
function join(chunks) {const out=new Uint8Array(chunks.reduce((n,c)=>n+c.length,0));let offset=0;for(const c of chunks){out.set(c,offset);offset+=c.length;}return out;}
function zip(files) {
  const local=[],central=[];let offset=0,centralSize=0;
  for(const [path,content] of files) {
    const name=encoder.encode(path),data=encoder.encode(content),crc=crc32(data),h=header(30),c=header(46);
    h.u32(0,0x04034b50);h.u16(4,20);h.u16(6,0x0800);h.u16(12,33);h.u32(14,crc);h.u32(18,data.length);h.u32(22,data.length);h.u16(26,name.length);
    c.u32(0,0x02014b50);c.u16(4,20);c.u16(6,20);c.u16(8,0x0800);c.u16(14,33);c.u32(16,crc);c.u32(20,data.length);c.u32(24,data.length);c.u16(28,name.length);c.u32(42,offset);
    local.push(h.bytes,name,data);central.push(c.bytes,name);offset+=30+name.length+data.length;centralSize+=46+name.length;
  }
  const end=header(22);end.u32(0,0x06054b50);end.u16(8,files.length);end.u16(10,files.length);end.u32(12,centralSize);end.u32(16,offset);
  return join([...local,...central,end.bytes]);
}
function column(index) {let s='';for(let n=index+1;n;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s;}
const pre='<?xml version="1.0" encoding="UTF-8" standalone="yes"?>';
const main='http://schemas.openxmlformats.org/spreadsheetml/2006/main';
const rel='http://schemas.openxmlformats.org/officeDocument/2006/relationships';
export function workbookBytes(sheets) {
  const files=[];
  files.push(['[Content_Types].xml',pre+'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'+sheets.map((_,i)=>`<Override PartName="/xl/worksheets/sheet${i+1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`).join('')+'</Types>']);
  files.push(['_rels/.rels',pre+`<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="${rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>`]);
  files.push(['xl/workbook.xml',pre+`<workbook xmlns="${main}" xmlns:r="${rel}"><sheets>`+sheets.map((s,i)=>`<sheet name="${xml(s.name)}" sheetId="${i+1}" r:id="rId${i+1}"/>`).join('')+'</sheets></workbook>']);
  files.push(['xl/_rels/workbook.xml.rels',pre+'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+sheets.map((_,i)=>`<Relationship Id="rId${i+1}" Type="${rel}/worksheet" Target="worksheets/sheet${i+1}.xml"/>`).join('')+'</Relationships>']);
  sheets.forEach((sheet,i)=>{
    const width=Math.max(...sheet.rows.map(r=>r.length));
    const body=sheet.rows.map((row,r)=>`<row r="${r+1}">`+row.map((value,c)=>{
      if(value === null || value === undefined || value === '')return '';
      const ref=column(c)+(r+1);
      if(typeof value === 'number') {if(!Number.isFinite(value))throw new Error('Invalid numeric cell');return `<c r="${ref}"><v>${value}</v></c>`;}
      return `<c r="${ref}" t="inlineStr"><is><t xml:space="preserve">${xml(value)}</t></is></c>`;
    }).join('')+'</row>').join('');
    files.push([`xl/worksheets/sheet${i+1}.xml`,pre+`<worksheet xmlns="${main}"><dimension ref="A1:${column(width-1)}${sheet.rows.length}"/><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><sheetFormatPr defaultRowHeight="18"/><cols><col min="1" max="${width}" width="26" customWidth="1"/></cols><sheetData>${body}</sheetData><autoFilter ref="A1:${column(width-1)}${sheet.rows.length}"/></worksheet>`]);
  });
  return zip(files);
}
