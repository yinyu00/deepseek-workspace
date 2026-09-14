# -*- coding: utf-8 -*-
"""
纯Python邮件合并：克隆模板表格87份，替换MERGEFIELD为数据值，
生成可直接打印的 YS250526T箱单标签-合并87张.docx
"""
import zipfile, sys, io, re, copy, shutil
import xml.etree.ElementTree as ET

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
XML_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'

TPL = r"D:\ai\deepseek-harness\workspace\yishan\deyu箱单标签打印模版-横向.docx"
SRC = r"D:\ai\deepseek-harness\workspace\yishan\deyuYS250526T箱单 250319.xlsm"
DST = r"D:\ai\deepseek-harness\workspace\yishan\YS250526T箱单标签-合并76张.docx"

# ============ 打印纸张设置（单位：厘米）============
# None = 沿用模板自带尺寸(10.24 x 8.0cm 横向)；改成数字即自定义纸张
PAGE_W_CM = None   # 例如 10.0
PAGE_H_CM = None   # 例如 8.0
ORIENT = 'landscape'  # 'landscape' 横向 / 'portrait' 纵向
# 页边距（厘米）；None = 沿用模板
MARGIN_CM = {'top': None, 'bottom': None, 'left': None, 'right': None}

def cm_to_twips(cm):
    return str(round(cm * 566.929))

NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
HEADER_ROW, DATA_FROM = 15, 16

# ============ 1) 读 Excel 数据 ============
z = zipfile.ZipFile(SRC)
shared = []
if 'xl/sharedStrings.xml' in z.namelist():
    sroot = ET.fromstring(z.read('xl/sharedStrings.xml'))
    shared = [''.join(t.text or '' for t in si.findall('.//m:t', NS))
              for si in sroot.findall('m:si', NS)]

sroot = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
rows = sroot.find('m:sheetData', NS).findall('m:row', NS)

def parse_row(row):
    out = {}
    for c in row.findall('m:c', NS):
        ref = c.get('r') or ''
        m = re.match(r'([A-Z]+)(\d+)', ref)
        if not m:
            continue
        col = m.group(1)
        t = c.get('t')
        v = c.find('m:v', NS)
        if t == 's' and v is not None:
            val = shared[int(v.text)]
        elif v is not None:
            val = v.text
        else:
            val = ''
        if val != '':
            out[col] = val
    return out

header = parse_row(next(r for r in rows if int(r.get('r')) == HEADER_ROW))
col_by_header = {v.strip(): k for k, v in header.items()}
# 默认填充：主文件Y列(条形码HU CODE/成分)为空时使用（取自同款号旧标签文件）
DEFAULT_COMPOSITION = '100%TENCEL'

records = []
for row in rows:
    rn = int(row.get('r'))
    if rn < DATA_FROM:
        continue
    vals = parse_row(row)
    if vals and vals.get('F'):  # 只有含卷号(F列)的行才是卷数据
        if not vals.get('Y'):
            vals['Y'] = DEFAULT_COMPOSITION
        records.append(vals)
print(f"数据: {len(records)} 行")

# ============ 2) MERGEFIELD -> 列 映射 ============
FIELD_MAP = {
    '客户款号Item code': '客户款号Item code',
    '供应商款号supplier item code': '供应商款号supplier item code',
    '条形码HU CODE': '条形码HU CODE',
    '缸号 Batch NO#': '缸号 Batch NO.',
    '出货数量QTY(pcs)': '出货数量QTY(pcs)',
    '卷号ROLLS NO#': '卷号',
    '颜色Colour': '颜色Colour',
    '毛重G#WT (KGS)': '毛重G.WT                          (KGS)',
    '净重N#WT (KGS)': '净重N.WT         (KGS)',
    'PO NO#': 'PO NO.',
}
# 宽松匹配表头（去除所有空白后比较）
def find_col(fname):
    cand = FIELD_MAP.get(fname, fname)
    if cand in col_by_header:
        return col_by_header[cand]
    if fname in col_by_header:
        return col_by_header[fname]
    key = re.sub(r'\s+', '', cand.replace('#', '.'))
    for h, c in col_by_header.items():
        if re.sub(r'\s+', '', h) == key:
            return c
    return None

field2col = {}
for f in FIELD_MAP:
    col = find_col(f)
    field2col[f] = col
    print(f"  字段 {f!r} -> 列 {col}")
    if col is None:
        print("    !! 未找到对应列")

# ============ 3) 解析模板 ============
zt = zipfile.ZipFile(TPL)
doc_bytes = zt.read('word/document.xml')
root = ET.fromstring(doc_bytes)
body = root.find(W + 'body')
template_tbl = body.find(W + 'tbl')
assert template_tbl is not None

def substitute(tbl, rec):
    """把表格中所有 MERGEFIELD 替换为记录值，返回新表格元素"""
    tbl = copy.deepcopy(tbl)
    for p in tbl.iter(W + 'p'):
        runs = p.findall(W + 'r')
        if not runs or p.find(f'.//{W}instrText') is None:
            continue
        new_children = []
        i = 0
        children = list(p)
        # 重建段落内容：保留非run元素，处理字段组
        field_val_run_rpr = None
        pending = []
        for el in children:
            if el.tag == W + 'r':
                instr = el.find(W + 'instrText')
                fld = el.find(W + 'fldChar')
                if fld is not None:
                    ftype = fld.get(W + 'fldCharType')
                    if ftype == 'begin':
                        pending = ['FIELD']
                    elif ftype == 'end':
                        if pending and pending[0] == 'FIELD':
                            # 输出替换 run
                            fname = pending[1] if len(pending) > 1 else None
                            rpr = pending[2] if len(pending) > 2 else None
                            new_r = ET.Element(W + 'r')
                            if rpr is not None:
                                new_r.append(copy.deepcopy(rpr))
                            t = ET.SubElement(new_r, W + 't')
                            t.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
                            col = field2col.get(fname, None) if fname else None
                            t.text = str(rec.get(col, '')) if col else ''
                            new_children.append(new_r)
                        pending = []
                    # separate / begin 丢弃
                    continue
                if instr is not None and pending and pending[0] == 'FIELD':
                    m = re.search(r'MERGEFIELD\s+"?([^"]+?)"?\s*$', (instr.text or '').strip())
                    pending.append(m.group(1) if m else (instr.text or '').strip())
                    continue
                # 字段结果 run（在 separate 之后）——记住 rPr 供替换用
                if pending and pending[0] == 'FIELD':
                    pending.append(el.find(W + 'rPr'))
                    continue
            new_children.append(el)
        for el in list(p):
            p.remove(el)
        for el in new_children:
            p.append(el)
    return tbl

def pagebreak_p():
    p = ET.Element(W + 'p')
    r = ET.SubElement(p, W + 'r')
    br = ET.SubElement(r, W + 'br')
    br.set(W + 'type', 'page')
    return p

# ============ 4) 组装 ============
sectPr = body.find(W + 'sectPr')

# 应用自定义纸张大小/方向/页边距
if PAGE_W_CM and PAGE_H_CM:
    pgsz = sectPr.find(W + 'pgSz')
    if pgsz is None:
        pgsz = ET.SubElement(sectPr, W + 'pgSz')
    w_tw, h_tw = cm_to_twips(PAGE_W_CM), cm_to_twips(PAGE_H_CM)
    if ORIENT == 'landscape':
        pgsz.set(W + 'w', max(w_tw, h_tw)); pgsz.set(W + 'h', min(w_tw, h_tw))
        pgsz.set(W + 'orient', 'landscape')
    else:
        pgsz.set(W + 'w', min(w_tw, h_tw)); pgsz.set(W + 'h', max(w_tw, h_tw))
        if W + 'orient' in pgsz.attrib:
            del pgsz.attrib[W + 'orient']
    print(f"纸张: {PAGE_W_CM} x {PAGE_H_CM} cm ({ORIENT})")
if any(v for v in MARGIN_CM.values()):
    pgmar = sectPr.find(W + 'pgMar')
    for key, cm in MARGIN_CM.items():
        if cm is not None:
            pgmar.set(W + key, cm_to_twips(cm))
    print("页边距:", {k: v for k, v in MARGIN_CM.items() if v is not None})
for el in list(body):
    body.remove(el)

n = len(records)
for i, rec in enumerate(records):
    tbl = substitute(template_tbl, rec)
    body.append(tbl)
    if i < n - 1:
        body.append(pagebreak_p())
body.append(sectPr)

# 注册命名空间前缀
for (prefix, uri) in [('w', XML_NS)]:
    ET.register_namespace(prefix, uri)
# 保留其它前缀
import re as _re
for m in set(_re.findall(rb'xmlns:(\w+)="([^"]+)"', doc_bytes[:3000])):
    pass

new_doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
           + ET.tostring(root, encoding='unicode'))

# ============ 5) 写出新 docx ============
with zipfile.ZipFile(DST, 'w', zipfile.ZIP_DEFLATED) as out:
    for item in zt.infolist():
        if item.filename == 'word/document.xml':
            out.writestr(item, new_doc)
        elif item.filename.endswith('/'):
            continue
        else:
            out.writestr(item, zt.read(item.filename))

print("已生成:", DST, f"({n} 张标签)")

# ============ 6) 验证 ============
zv = zipfile.ZipFile(DST)
rv = ET.fromstring(zv.read('word/document.xml'))
bv = rv.find(W + 'body')
tbls = bv.findall(W + 'tbl')
print(f"验证: {len(tbls)} 个标签表格")
def tbl_text(tbl):
    return [' | '.join(''.join(t.text or '' for t in tc.iter(W+'t')) for tc in tr.findall(W+'tc'))
            for tr in tbl.findall(W+'tr')[:4]]
for idx in (0, n - 1):
    print(f"--- 标签 {idx+1} ---")
    for line in tbl_text(tbls[idx]):
        print("   ", line)
