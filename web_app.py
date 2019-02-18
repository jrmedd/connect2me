import datetime
from functools import wraps
import os
from string import Template

from flask import Flask, url_for, render_template, request, redirect, Response, jsonify, session
from bson import ObjectId
from pymongo import MongoClient

import cairosvg

import vobject

import qrcodegen

from passlib.hash import pbkdf2_sha256


MONGO_URL = os.environ.get('MONGO_URL')

CLIENT = MongoClient(MONGO_URL)
DB = CLIENT['landing_contacts']
CONTACTS = DB['contacts']
INTERACTIONS = DB['interactions']
LOGINS = DB['logins']

APP = Flask(__name__)

APP.secret_key = os.environ.get('SECRET_KEY')

def login_required(f):
    @wraps(f)
    def login_check(*args, **kwargs):
        if not session.get('username'):
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return login_check

def create_card(first_name, last_name, role, company_name, email_address, phone_number=None):
    contact = vobject.vCard()
    contact.add('n')
    contact.n.value = vobject.vcard.Name(family=last_name, given=first_name)
    contact.add('fn')
    contact.fn.value = "%s %s" % (first_name, last_name)
    contact.add('title')
    contact.title.value = role
    contact.add('org')
    contact.org.value = [company_name]
    contact.add('email')
    contact.email.value = email_address
    contact.email.type_param = 'INTERNET'
    if phone_number:
        contact.add('tel')
        contact.tel.value = phone_number
        contact.tel.type_param = 'WORK'
    return contact

@APP.route('/')
@login_required
def index():
    print(session)
    all_contacts = list(CONTACTS.find({'org':session.get('org')}).sort('last_name', 1))
    for contact in all_contacts:
        contact.update({'_id':str(contact.get('_id'))})
    return render_template('index.html', contact_list=all_contacts)

@APP.route('/download')
def download():
    download_id = request.args.get('id')
    if download_id and ObjectId.is_valid(download_id):
        found_contact = CONTACTS.find_one({'_id': ObjectId(download_id)})
    else:
        found_contact = None
    if found_contact:
        contact_first_name = found_contact.get('first_name')
        contact_last_name = found_contact.get('last_name')
        contact_role = found_contact.get('role')
        contact_company_name = found_contact.get('company_name')
        contact_email = found_contact.get('email_address')
        contact_phone = found_contact.get('phone_number')
        card_download = create_card(contact_first_name, contact_last_name, contact_role, contact_company_name, contact_email, contact_phone)
        interaction = {'downloaded': download_id}
        interaction.update({'ip': request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)})
        interaction.update({'platform':request.user_agent.platform})
        interaction.update({'browser':request.user_agent.browser})
        interaction.update({'timestamp':datetime.datetime.now()})
        INTERACTIONS.insert_one(interaction)
        return Response(card_download.serialize(), mimetype="text/x-vcard", headers={"Content-Disposition": "attachment;filename=%s_%s.vcf" % (contact_first_name, contact_last_name)})
    else:
        return "Contact does not exist"

@APP.route('/remove/<contact_id>', methods=['DELETE'])
@login_required
def remove(contact_id):
    CONTACTS.delete_one({'_id':ObjectId(contact_id), 'org':session.get('org')})
    return jsonify(deleted=contact_id)

@APP.route('/edit', methods=['GET', 'POST'])
@login_required
def edit():
    editing_contact = CONTACTS.find_one({'email_address': request.args.get('email')})
    if editing_contact:
        editing_contact.update({'_id': str(editing_contact.pop('_id'))})
        qr_code = create_qr_code(url_for('download', _external=True), editing_contact.get('_id'))
    else:
        editing_contact = None
        qr_code = None
    if request.method == "POST":
        contact_form = request.form.to_dict()
        contact_form.update({'org':session.get('org')})
        CONTACTS.replace_one({'_id':ObjectId(contact_form.pop('_id') or None)}, contact_form, upsert=True)
        return redirect(url_for('edit', email=contact_form.get('email_address')))
    return render_template('edit_contact.html', contact_info=editing_contact, qr_code=qr_code)

@APP.route('/login', methods=['GET', 'POST'])
def login(username="", error=None):
    if request.method == 'POST':
        username = request.form.get('username')
        user_info = LOGINS.find_one({'username': username})
        if user_info:
            hash = user_info.get('password')
            allow = pbkdf2_sha256.verify(request.form.get('password'), hash)
            if allow:
                session.update({'username': username, 'org': user_info.get('org')})
                return redirect(request.args.get('next') or url_for('index'))
            else:
                error = "Incorrect password"
        else:
            error = "Unknown user"
    return render_template('login.html', username=username, error=error)

@APP.route('/logout', methods=['GET'])
def logout():
    session.pop('username')
    return redirect(url_for('login'))

@APP.route('/svg')
@login_required
def svg_card_creator():
    download_id = request.args.get('id')
    if download_id and ObjectId.is_valid(download_id):
        found_contact = CONTACTS.find_one({'_id': ObjectId(download_id)})
    else:
        return "No contact"
    full_name = "%s %s" % (found_contact.get('first_name'), found_contact.get('last_name'))
    role = found_contact.get('role')
    company_name = found_contact.get('company_name')
    email_address = found_contact.get('email_address')
    phone_number = found_contact.get('phone_number')
    qr_code = create_qr_code(url_for('download', _external=True), download_id)
    qr_code = qr_code.split('svg11.dtd">\n')[1]
    qr_code = qr_code.replace('viewBox="0 0 33 33"','x="158.9" y="35.4" width="70.9" height="70.9"')
    qr_code = qr_code.replace('<path', '<path transform="scale(2)"')
    with open('static/template.svg', 'r+') as f:
        svg_file = Template(f.read())
    formatted_svg = svg_file.safe_substitute(name=full_name, email=email_address, role=role, company_name=company_name, telephone=phone_number, qr=qr_code)
    formatted_pdf = cairosvg.svg2pdf(bytestring=formatted_svg.encode('utf-8'), scale=1.3333)
    return Response(formatted_pdf, mimetype='application/pdf', headers={"Content-Disposition": "attachment;filename=%s.pdf" % (full_name)})

def create_qr_code(download_url, tenant_id):
    qr_code = qrcodegen.QrCode.encode_text("%s?id=%s" % (download_url, tenant_id), qrcodegen.QrCode.Ecc.MEDIUM)
    return qr_code.to_svg_str(0)


if __name__ == '__main__':
    APP.run(host="0.0.0.0", debug=True)
