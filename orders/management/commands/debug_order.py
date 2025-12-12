# Save as: orders/management/commands/fix_addresses.py
# Run with: python manage.py fix_addresses

from django.core.management.base import BaseCommand
from customers.models import Address, Customer

class Command(BaseCommand):
    help = 'Fix address types for order creation'

    def handle(self, *args, **options):
        print("\n=== FIXING ADDRESS TYPES ===\n")
        
        try:
            # Get the customer
            customer = Customer.objects.first()
            
            if not customer:
                print("✗ No customer found!")
                return
            
            print(f"✓ Working with customer: {customer.id}\n")
            
            # Get all addresses for this customer
            addresses = Address.objects.filter(customer=customer)
            print(f"Found {addresses.count()} address(es):\n")
            
            for addr in addresses:
                print(f"  ID: {addr.id}")
                print(f"  Type: {addr.address_type}")
                print(f"  Address: {addr.street_address}, {addr.city}")
                print(f"  Default: {addr.is_default}\n")
            
            # Option 1: Create a duplicate address for billing if only shipping exists
            shipping_addr = addresses.filter(address_type='shipping').first()
            billing_addr = addresses.filter(address_type='billing').first()
            
            if shipping_addr and not billing_addr:
                print("Creating billing address from shipping address...")
                
                billing_addr = Address.objects.create(
                    customer=customer,
                    address_type='billing',
                    street_address=shipping_addr.street_address,
                    apartment=shipping_addr.apartment,
                    city=shipping_addr.city,
                    state=shipping_addr.state,
                    postal_code=shipping_addr.postal_code,
                    country=shipping_addr.country,
                    is_default=True
                )
                print(f"✓ Created billing address with ID: {billing_addr.id}\n")
            
            elif not shipping_addr and not billing_addr:
                print("✗ No addresses found! Please create addresses first.\n")
                return
            
            # Show final status
            print("=== FINAL ADDRESS STATUS ===\n")
            
            billing = Address.objects.filter(
                customer=customer,
                address_type='billing'
            ).first()
            
            shipping = Address.objects.filter(
                customer=customer,
                address_type='shipping'
            ).first()
            
            if billing:
                print(f"✓ Billing Address (ID: {billing.id})")
                print(f"  {billing.street_address}, {billing.city}\n")
            
            if shipping:
                print(f"✓ Shipping Address (ID: {shipping.id})")
                print(f"  {shipping.street_address}, {shipping.city}\n")
            
            print("=== FIX COMPLETE ===\n")
            
        except Exception as e:
            print(f"\n✗ ERROR: {str(e)}\n")
            import traceback
            traceback.print_exc()