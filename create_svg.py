import qrcodegen
from string import Template

qr_code = qrcodegen.QrCode.encode_text("Test", qrcodegen.QrCode.Ecc.MEDIUM).to_svg_str(0)
qr_code = qr_code.split('svg11.dtd">\n')[1]
qr_code = qr_code.replace('viewBox="0 0 21 21"','x="158.9" y="35.4" width="70.9" height="70.9"')
qr_code = qr_code.replace('<path', '<path transform="scale(3.37)"')

with open('test.svg', 'r+') as f:
    svg_file = Template(f.read())


with open("new.svg", 'w') as new_f:
    new_f.write(svg_file.safe_substitute(name="Darren O'Brien", email="darren.obrien@barclays.com", qr=qr_code))
