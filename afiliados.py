import stripe
import os

# Configuración de tu API key de Stripe
stripe.api_key = "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"

# Clase Afiliado
class Afiliado:
    def __init__(self, nombre, email, cupón):
        self.nombre = nombre
        self.email = email
        self.cupón = cupón  # Código de cupón en Stripe
        self.transacciones = []

    def registrar_transaccion(self, transaccion):
        self.transacciones.append(transaccion)

    def calcular_comision(self, porcentaje_comision):
        total_comision = 0
        for transaccion in self.transacciones:
            total_comision += transaccion['monto'] * porcentaje_comision
        return total_comision

# Función para obtener el uso del cupón desde Stripe
def obtener_uso_cupon(cupon):
    # Busca los pagos asociados al cupón
    pagos = stripe.PaymentIntent.list(limit=100)
    transacciones = []
    for pago in pagos['data']:
        if 'invoice' in pago:
            invoice = stripe.Invoice.retrieve(pago['invoice'])
            if invoice.get('discount') and invoice['discount']['coupon']['id'] == cupon:
                transacciones.append({
                    'monto': invoice['total'] / 100,  # Convierte de centavos a unidades
                    'fecha': invoice['created'],
                })
    return transacciones

# Función para generar el reporte de un afiliado
def generar_reporte_afiliado(afiliado, porcentaje_comision=0.1):
    # Obtener el uso del cupón del afiliado
    transacciones = obtener_uso_cupon(afiliado.cupón)
    for transaccion in transacciones:
        afiliado.registrar_transaccion(transaccion)

    comision = afiliado.calcular_comision(porcentaje_comision)
    print(f"Afiliado: {afiliado.nombre}")
    print(f"Total transacciones: {len(afiliado.transacciones)}")
    print(f"Comisión total: {comision}")

# Ejemplo de uso
if __name__ == "__main__":
    afiliado1 = Afiliado("Juan", "juan@correo.com", "CLSM")
    generar_reporte_afiliado(afiliado1)
