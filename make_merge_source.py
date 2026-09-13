# -*- coding: utf-8 -*-
"""
从 deyuYS250526T箱单 250319.xlsm 的 Packing List 表提取数据，
生成表头在第1行的最小 xlsx，作为 Word 邮件合并数据源。
"""
import zipfile, sys, io, re
import xml.etree.ElementTree as ET

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SRC = r"D:\ai\deepseek-harness\workspace\yishan\deyuYS250526T箱单 250319.xlsm"
DST = r"D:\ai\deepseek-harness\workspace\yishan\YS250526T标签数据.xlsx"

NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
HEADER_ROW = 15   # 表头行
DATA_FROM = 16    # 数据起始行

z = zipfile.ZipFile(SRC)
shared = []
if 'xl/sharedStrings.xml' in z.namelist():
    root = ET.fromstring(z.read('xl/sharedStrings.xml'))
    shared = [''.join(t.text or '' for t in si.findall('.//m:t', NS)) for si in root.findall('m:si', NS)]

sroot = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
rows = sroot.find('m:sheetData', NS).findall('m:row', NS)

def parse_row(row):
    """返回 {col_letter: value_string}，数值保持数值形式"""
    out = {}
    for c in row.findall('m:c', NS):
        ref = c.get('r') or ''
        m = re.match(r'([A-Z]+)(\d+)', ref)
        col, rn = m.group(1), int(m.group(2))
        t = c.get('t')
        v = c.find('m:v', NS)
        if t == 's' and v is not None:
            idx = int(v.text)
            if idx >= len(shared):
                print(f"WARN: {ref} shared idx {idx} out of range, treat as str")
                val = v.text
            else:
                val = shared[idx]
        elif t == 'inlineStr':
            is_node = c.find('m:is', NS)
            val = ''.join(x.text or '' for x in is_node.findall('.//m:t', NS)) if is_node is not None else ''
        elif v is not None:
            val = v.text
        else:
            val = ''
        if val != '':
            out[col] = val
    return out

def col_num(c):
    n = 0
    for ch in c:
        n = n * 26 + ord(ch) - 64
    return n

def num_to_col(n):
    s = ''
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s

# 收集 A-Y 列（1-25），表头 + 数据
table = {}  # rownum -> {colnum: value}
for row in rows:
    rn = int(row.get('r'))
    if rn < HEADER_ROW:
        continue
    vals = parse_row(row)
    if rn >= DATA_FROM and (not vals or not vals.get('F')):
        continue  # 只保留含卷号(F列)的卷数据行，跳过空行和汇总行
    table[rn] = {col_num(c): v for c, v in vals.items() if col_num(c) <= 25}

header_rn = HEADER_ROW
data_rns = sorted(r for r in table if r >= DATA_FROM)
max_col = 25
print(f"表头行: {header_rn}, 数据行数: {len(data_rns)}")

def esc(s):
    return (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
             .replace('"', '&quot;'))

def cell_xml(col, rn, val):
    ref = f"{num_to_col_col(col)}{rn}" if False else f"{num_to_col(col)}{rn}"
    if val is None or val == '':
        return f'<c r="{ref}"/>'
    # 数值判断
    try:
        f = float(val)
        if val.strip() not in ('', ) and not val.strip().startswith('0') or val.strip() == '0':
            return f'<c r="{ref}"><v>{repr(f) if f != int(f) else str(int(f))}</v></c>'
    except (ValueError, OverflowError):
        pass
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{esc(str(val))}</t></is></c>'

# 构建最小 xlsx
rows_xml = []
seq = 1
out_rn = 1
for rn in [header_rn] + data_rns:
    vals = table.get(rn, {})
    cells = ''.join(cell_xml(c, out_rn, vals.get(c, '')) for c in range(1, max_col + 1))
    rows_xml.append(f'<row r="{out_rn}">{cells}</row>')
    out_rn += 1

sheet_xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             f'<dimension ref="A1:{num_to_col(max_col)}{out_rn-1}"/>'
             '<sheetData>' + ''.join(rows_xml) + '</sheetData></worksheet>')

workbook_xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
    '<sheets><sheet name="Packing List" sheetId="1" r:id="rId1"/></sheets></workbook>')

workbook_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
    '</Relationships>')

root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
    '</Relationships>')

content_types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
    '</Types>')

with zipfile.ZipFile(DST, 'w', zipfile.ZIP_DEFLATED) as out:
    out.writestr('[Content_Types].xml', content_types)
    out.writestr('_rels/.rels', root_rels)
    out.writestr('xl/workbook.xml', workbook_xml)
    out.writestr('xl/_rels/workbook.xml.rels', workbook_rels)
    out.writestr('xl/worksheets/sheet1.xml', sheet_xml)

print("已生成:", DST)

# 验证：重新读取前3行
z2 = zipfile.ZipFile(DST)
r2 = ET.fromstring(z2.read('xl/worksheets/sheet1.xml'))
def read_cell(c):
    t = c.get('t')
    if t == 'inlineStr':
        n = c.find('.//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t')
        return n.text if n is not None else ''
    v = c.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v')
    return v.text if v is not None else ''
out_rows = r2.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheetData')
all_rows = out_rows.findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row')
print(f"验证: 共 {len(all_rows)} 行 (1表头+{len(all_rows)-1}数据)")
print("表头:", [read_cell(c) for c in all_rows[0][:10]])
print("首行数据:", [read_cell(c) for c in all_rows[1][:15]])
