import os
import subprocess
import time
import requests

# Configura tu clave secreta de API de Stripe
STRIPE_API_KEY = 'sk_test_51Pr14b2K3oWETT3EMYe9NiKElssrbGmCHpxdUefcuaXLRkKyya5neMrK4jDzd2qh7GUhYZRQT8wqDaiGB2qtg2Md00fbj6TZqF'
WEBHOOK_ID = 'we_1PsJtp2K3oWETT3E6yKXO8BB'  # ID del webhook en Stripe que deseas actualizar

def get_tunnel_url():
    # Inicia localtunnel y captura la URL generada
    process = subprocess.Popen(['lt', '--port', '5000'], stdout=subprocess.PIPE)
    for line in process.stdout:
        if b'your url is' in line:
            return line.decode('utf-8').strip().split(' ')[-1]

def update_stripe_webhook(url):
    # Realiza la solicitud PATCH para actualizar la URL del webhook en Stripe
    response = requests.post(
        f'https://api.stripe.com/v1/webhook_endpoints/{WEBHOOK_ID}',
        headers={
            'Authorization': f'Bearer {STRIPE_API_KEY}'
        },
        data={
            'url': f'{url}/webhook'
        }
    )
    if response.status_code == 200:
        print('Webhook de Stripe actualizado con éxito:', url)
    else:
        print('Error al actualizar el webhook de Stripe:', response.json())

def main():
    while True:
        url = get_tunnel_url()
        if url:
            print('URL de localtunnel obtenida:', url)
            update_stripe_webhook(url)
            break
        else:
            print('No se pudo obtener la URL de localtunnel. Reintentando en 5 segundos...')
            time.sleep(5)

if __name__ == '__main__':
    main()
