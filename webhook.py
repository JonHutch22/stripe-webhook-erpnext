from flask import Flask, request, jsonify
import stripe
import requests
import os

# === CONFIGURATION ===
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
    try:
        data = res.json().get("data", [])
        if data:
            return data[0]["name"]
    except Exception as e:
        print("Error during ERPNext customer lookup:", e)
        print("Response:", res.text)

    # Create new customer if not found
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
    try:
        return res.json()["data"]["name"]
    except Exception as e:
        print("Error during ERPNext customer creation:", e)
        print("Response:", res.text)
        return None

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

def create_erp_subscription(customer_name, stripe_sub_id, status):
    payload = {
        "customer": customer_name,
        "subscription_status": status,
        "stripe_subscription_id": stripe_sub_id
    }
    return requests.post(
        f"{ERP_BASE_URL}/api/resource/Subscription",
        headers=erp_headers,
        json=payload
    )

def cancel_erp_subscription(stripe_sub_id):
    # Look up ERPNext Subscription by Stripe subscription ID and mark it canceled
    res = requests.get(
        f"{ERP_BASE_URL}/api/resource/Subscription?filters=[[\"Subscription\",\"stripe_subscription_id\",\"=\",\"{stripe_sub_id}\"]]",
        headers=erp_headers
    )
    data = res.json().get("data", [])
    if data:
        sub_name = data[0]["name"]
        update_payload = {"subscription_status": "Cancelled"}
        return requests.put(
            f"{ERP_BASE_URL}/api/resource/Subscription/{sub_name}",
            headers=erp_headers,
            json=update_payload
        )
    return None

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

    event_type = event['type']

if event_type == 'invoice.paid':
    invoice = event['data']['object']
    email = invoice.get('customer_email')
    stripe_invoice_id = invoice['id']
    amount_paid = invoice['amount_paid'] / 100

    print(f"[invoice.paid] Received Stripe invoice: {stripe_invoice_id}")
    print(f"Customer email from Stripe: {email}")

    if not email and 'customer' in invoice:
        customer_id = invoice['customer']
        customer_data = stripe.Customer.retrieve(customer_id)
        email = customer_data.get('email')
        print(f"Retrieved email from customer ID: {email}")

    if email:
        erp_customer = get_or_create_erp_customer(email)
        print(f"ERPNext customer created or found: {erp_customer}")
        create_erp_invoice(erp_customer, amount_paid, stripe_invoice_id)
    else:
        print("[invoice.paid] No email found — skipping ERPNext sync.")

    elif event_type == 'customer.created':
        customer = event['data']['object']
        email = customer.get('email')
        if email:
            get_or_create_erp_customer(email)

    elif event_type == 'customer.subscription.created':
        subscription = event['data']['object']
        stripe_sub_id = subscription['id']
        email = subscription['customer_email'] if 'customer_email' in subscription else None
        status = subscription.get('status', 'active')

        if not email and 'customer' in subscription:
            customer_data = stripe.Customer.retrieve(subscription['customer'])
            email = customer_data.get('email')

        if email:
            erp_customer = get_or_create_erp_customer(email)
            create_erp_subscription(erp_customer, stripe_sub_id, status)

    elif event_type == 'customer.subscription.deleted':
        subscription = event['data']['object']
        stripe_sub_id = subscription['id']
        cancel_erp_subscription(stripe_sub_id)

    elif event_type == 'invoice.payment_failed':
        invoice = event['data']['object']
        email = invoice.get('customer_email')
        stripe_invoice_id = invoice['id']
        print(f"Payment failed for customer {email}, invoice {stripe_invoice_id}")

    return jsonify({"status": "received"}), 200

import os

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)


