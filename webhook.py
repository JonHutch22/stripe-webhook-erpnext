
from flask import Flask, request, jsonify
import stripe
import requests

# === CONFIGURATION ===
import os
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
stripe_webhook_secret = os.getenv('STRIPE_WEBHOOK_SECRET')

ERP_BASE_URL = os.getenv('ERP_BASE_URL')
ERP_API_KEY = os.getenv('ERP_API_KEY')
ERP_API_SECRET = os.getenv('ERP_API_SECRET')

app = Flask(__name__)

erp_headers = {
    "Authorization": f"token {ERP_API_KEY}:{ERP_API_SECRET}",
    "Content-Type": "application/json"
}

def get_or_create_erp_customer(email):
    res = requests.get(
        f"{ERP_BASE_URL}/api/resource/Customer?filters=[[\"Customer\",\"email_id\",\"=\",\"{email}\"]]",
        headers=erp_headers
    )
    data = res.json().get("data", [])
    if data:
        return data[0]["name"]

    payload = {
        "customer_name": email,
        "customer_type": "Individual",
        "email_id": email
    }
    res = requests.post(
        f"{ERP_BASE_URL}/api/resource/Customer",
        headers=erp_headers,
        json=payload
    )
    return res.json()["data"]["name"]

def create_erp_invoice(customer_name, amount, stripe_invoice_id):
    payload = {
        "customer": customer_name,
        "items": [{
            "item_name": "Stripe Subscription",
            "qty": 1,
            "rate": amount
        }],
        "is_paid": 1,
        "remarks": f"Stripe Invoice ID: {stripe_invoice_id}"
    }
    return requests.post(
        f"{ERP_BASE_URL}/api/resource/Sales Invoice",
        headers=erp_headers,
        json=payload
    )

@app.route('/webhook', methods=['POST'])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, stripe_webhook_secret
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    if event['type'] == 'invoice.paid':
        invoice = event['data']['object']
        email = invoice.get('customer_email')
        amount_paid = invoice['amount_paid'] / 100
        stripe_invoice_id = invoice['id']

        if email:
            erp_customer = get_or_create_erp_customer(email)
            create_erp_invoice(erp_customer, amount_paid, stripe_invoice_id)

    return jsonify({"status": "received"}), 200

if __name__ == '__main__':
    app.run(port=5000)
