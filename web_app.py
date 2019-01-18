from flask import Flask, flash, url_for, render_template, request, redirect, make_response, Response, jsonify, session
from bson import ObjectId
from functools import wraps
import datetime
from string import Template
from pymongo import MongoClient

import datetime

import vobject

import qrcodegen

import os

from passlib.hash import pbkdf2_sha256
import logging

logging.basicConfig(filename='errors.log',level=logging.DEBUG)


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

def create_card(first_name, last_name, email_address, phone_number=None):
    contact = vobject.vCard()
    contact.add('n')
    contact.n.value = vobject.vcard.Name(family=last_name, given=first_name)
    contact.add('fn') 
    contact.fn.value = "%s %s" % (first_name, last_name)
    contact.add('email')
    contact.email.value = email_address
    contact.email.type_param = 'INTERNET'
    if phone_number:
        contact.add('tel')
        contact.tel.value = phone_number
        contact.tel.type_param = 'WORK'
    return contact

@APP.route('/')
def index():
    return request.url

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
        contact_email = found_contact.get('email_address')
        contact_phone = found_contact.get('phone_number')
        card_download = create_card(contact_first_name, contact_last_name, contact_email, contact_phone)
        print(request.remote_addr)
        print(request.user_agent)
        return Response(card_download.serialize(), mimetype="text/x-vcard", headers={"Content-Disposition": "attachment;filename=%s_%s.vcf" % (contact_first_name, contact_last_name)})
    else:
        return "Contact does not exist"


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
        CONTACTS.replace_one({'_id':ObjectId(contact_form.pop('_id') or None)}, contact_form, upsert=True)
        return redirect(url_for('edit', email=contact_form.get('email_address')))
    return render_template('edit_contact.html', contact_info=editing_contact, qr_code=qr_code)

@APP.route('/contacts')
@login_required
def view():
    all_contacts = list(CONTACTS.find())
    return "all"

@APP.route('/login', methods=['GET', 'POST'])
def login(username=""):
    if request.method == 'POST':
        username = request.form.get('username')
        user_info = LOGINS.find_one({'username': username}, {'password': 1})
        if user_info:
            hash = user_info.get('password')
            allow = pbkdf2_sha256.verify(request.form.get('password'), hash)
            if allow:
                session.update({'username': username})
                return redirect(request.args.get('next') or url_for('index'))
    return render_template('login.html', username=username)

@APP.route('/svg')
@login_required
def svg_card_creator():
    download_id = request.args.get('id')
    if download_id and ObjectId.is_valid(download_id):
        found_contact = CONTACTS.find_one({'_id': ObjectId(download_id)})
    else:
        return "No contact"
    full_name = "%s %s" % (found_contact.get('first_name'), found_contact.get('last_name'))
    email_address = found_contact.get('email_address')
    phone_number = found_contact.get('phone_number')
    qr_code = create_qr_code(url_for('download', _external=True), download_id)
    qr_code = qr_code.split('svg11.dtd">\n')[1]
    qr_code = qr_code.replace('viewBox="0 0 33 33"','x="158.9" y="35.4" width="70.9" height="70.9"')
    qr_code = qr_code.replace('<path', '<path transform="scale(2)"')
    with open('static/template.svg', 'r+') as f:
        svg_file = Template(f.read())
    return Response(svg_file.safe_substitute(name=full_name, email=email_address, telephone=phone_number, qr=qr_code), mimetype='image/svg+xml', headers={"Content-Disposition": "attachment;filename=%s.svg" % (full_name)})


def create_qr_code(download_url, tenant_id):
    qr_code = qrcodegen.QrCode.encode_text("%s/?id=%s" % (download_url, tenant_id), qrcodegen.QrCode.Ecc.MEDIUM)
    return qr_code.to_svg_str(0)


if __name__ == '__main__':
    APP.run(host="0.0.0.0", debug=True)
